"""Cache de Estatísticas de Meios de Pagamento (SPB/Olinda BCB).

Serviço Olinda `MPV_DadosAbertos`: cada uma das 12 entidades é uma
FunctionImport com um único parâmetro de período (`AnoMes` ou `trimestre`)
que filtra de forma CUMULATIVA (`>=`), não exata. Passar um valor-sentinela
antigo (ex. `trimestre='19001'`) devolve o histórico completo da entidade em
uma única chamada HTTP, sem paginação. Por isso a ingestão aqui não usa o
padrão de janelas/checkpoint trimestral de `taxas_juros_historico.py`: cada
dataset precisa de apenas uma chamada para materializar todo o seu histórico,
e a resumibilidade é por-dataset (pular datasets já materializados, a menos
que `overwrite=True`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd
import requests

from .base import BaseCache, CacheConfig, CacheResult
from .release_config import get_release_config
from .taxas_juros_historico import REQUEST_TIMEOUT, _escape_odata_literal, _request_json

BASE_URL = "https://olinda.bcb.gov.br/olinda/servico/MPV_DadosAbertos/versao/v1/odata"

SPB_CACHE_NAME = "spb_meios_pagamento"
_MAIN_KEY = "nucleo_trimestral"


@dataclass(frozen=True)
class _DatasetSpec:
    key: str
    descricao: str
    function_name: str
    param_name: str
    sentinel_value: str
    rename: Dict[str, str]
    decimal_columns: Tuple[str, ...] = ()
    int_columns: Tuple[str, ...] = ()
    period_column: str = "trimestre"

    @property
    def string_columns(self) -> Tuple[str, ...]:
        numeric = set(self.decimal_columns) | set(self.int_columns) | {self.period_column}
        return tuple(col for col in self.rename.values() if col not in numeric)


DATASETS: Tuple[_DatasetSpec, ...] = (
    _DatasetSpec(
        key=_MAIN_KEY,
        descricao="Meios de pagamentos (trimestral)",
        function_name="MeiosdePagamentosTrimestralDA",
        param_name="trimestre",
        sentinel_value="19001",
        rename={
            "datatrimestre": "trimestre",
            "valorPix": "valor_pix",
            "valorTED": "valor_ted",
            "valorTEC": "valor_tec",
            "valorCheque": "valor_cheque",
            "valorBoleto": "valor_boleto",
            "valorDOC": "valor_doc",
            "valorCartaoCredito": "valor_cartao_credito",
            "valorCartaoDebito": "valor_cartao_debito",
            "valorCartaoPrePago": "valor_cartao_pre_pago",
            "valorTransIntrabancaria": "valor_trans_intrabancaria",
            "valorConvenios": "valor_convenios",
            "valorDebitoDireto": "valor_debito_direto",
            "valorSaques": "valor_saques",
            "quantidadePix": "quantidade_pix",
            "quantidadeTED": "quantidade_ted",
            "quantidadeTEC": "quantidade_tec",
            "quantidadeCheque": "quantidade_cheque",
            "quantidadeBoleto": "quantidade_boleto",
            "quantidadeDOC": "quantidade_doc",
            "quantidadeCartaoCredito": "quantidade_cartao_credito",
            "quantidadeCartaoDebito": "quantidade_cartao_debito",
            "quantidadeCartaoPrePago": "quantidade_cartao_pre_pago",
            "quantidadeTransIntrabancaria": "quantidade_trans_intrabancaria",
            "quantidadeConvenios": "quantidade_convenios",
            "quantidadeDebitoDireto": "quantidade_debito_direto",
            "quantidadeSaques": "quantidade_saques",
        },
        decimal_columns=(
            "valor_pix", "valor_ted", "valor_tec", "valor_cheque", "valor_boleto", "valor_doc",
            "valor_cartao_credito", "valor_cartao_debito", "valor_cartao_pre_pago",
            "valor_trans_intrabancaria", "valor_convenios", "valor_debito_direto", "valor_saques",
            "quantidade_pix", "quantidade_ted", "quantidade_tec", "quantidade_cheque",
            "quantidade_boleto", "quantidade_doc", "quantidade_cartao_credito",
            "quantidade_cartao_debito", "quantidade_cartao_pre_pago",
            "quantidade_trans_intrabancaria", "quantidade_convenios", "quantidade_debito_direto",
            "quantidade_saques",
        ),
    ),
    _DatasetSpec(
        key="nucleo_mensal",
        descricao="Meios de pagamentos e transferências (mensal)",
        function_name="MeiosdePagamentosMensalDA",
        param_name="AnoMes",
        sentinel_value="190001",
        rename={
            "AnoMes": "ano_mes",
            "quantidadePix": "quantidade_pix",
            "valorPix": "valor_pix",
            "quantidadeTED": "quantidade_ted",
            "valorTED": "valor_ted",
            "quantidadeTEC": "quantidade_tec",
            "valorTEC": "valor_tec",
            "quantidadeCheque": "quantidade_cheque",
            "valorCheque": "valor_cheque",
            "quantidadeBoleto": "quantidade_boleto",
            "valorBoleto": "valor_boleto",
            "quantidadeDOC": "quantidade_doc",
            "valorDOC": "valor_doc",
        },
        decimal_columns=(
            "quantidade_pix", "valor_pix", "quantidade_ted", "valor_ted", "quantidade_tec",
            "valor_tec", "quantidade_cheque", "valor_cheque", "quantidade_boleto", "valor_boleto",
            "quantidade_doc", "valor_doc",
        ),
        period_column="ano_mes",
    ),
    _DatasetSpec(
        key="cartoes",
        descricao="Quantidade e valor de transações de cartões",
        function_name="Quantidadeetransacoesdecartoes",
        param_name="trimestre",
        sentinel_value="19001",
        rename={
            "trimestre": "trimestre",
            "nomeBandeira": "nome_bandeira",
            "nomeFuncao": "nome_funcao",
            "produto": "produto",
            "modalidade": "modalidade",
            "qtdCartoesEmitidos": "qtd_cartoes_emitidos",
            "qtdCartoesAtivos": "qtd_cartoes_ativos",
            "qtdTransacoesNacionais": "qtd_transacoes_nacionais",
            "valorTransacoesNacionais": "valor_transacoes_nacionais",
            "qtdTransacoesInternacionais": "qtd_transacoes_internacionais",
            "valorTransacoesInternacionais": "valor_transacoes_internacionais",
        },
        decimal_columns=("valor_transacoes_nacionais", "valor_transacoes_internacionais"),
        int_columns=(
            "qtd_cartoes_emitidos", "qtd_cartoes_ativos", "qtd_transacoes_nacionais",
            "qtd_transacoes_internacionais",
        ),
    ),
    _DatasetSpec(
        key="intercambio",
        descricao="Tarifa de intercâmbio por função do cartão",
        function_name="INTERCAMDA",
        param_name="trimestre",
        sentinel_value="19001",
        rename={
            "trimestre": "trimestre",
            "produto": "produto",
            "bandeira": "bandeira",
            "funcaoCartao": "funcao_cartao",
            "formacaptura": "forma_captura",
            "segmento": "segmento",
            "numeroparcelas": "numero_parcelas",
            "valorTransacoes": "valor_transacoes",
            "qtdTransacoes": "qtd_transacoes",
            "tarifaIntercambioPonderada": "tarifa_intercambio_ponderada",
        },
        decimal_columns=("valor_transacoes", "qtd_transacoes", "tarifa_intercambio_ponderada"),
    ),
    _DatasetSpec(
        key="desconto",
        descricao="Taxa de desconto (MDR) por função do cartão",
        function_name="DESCONTODA",
        param_name="trimestre",
        sentinel_value="19001",
        rename={
            "trimestre": "trimestre",
            "bandeira": "bandeira",
            "funcaoCartao": "funcao_cartao",
            "formacaptura": "forma_captura",
            "numeroparcelas": "numero_parcelas",
            "qtdDesconto": "qtd_desconto",
            "valorDesconto": "valor_desconto",
            "txMediaDesconto": "tx_media_desconto",
        },
        decimal_columns=("qtd_desconto", "valor_desconto", "tx_media_desconto"),
    ),
    _DatasetSpec(
        key="portador",
        descricao="Portador / programas de recompensa de cartões",
        function_name="PORTADORDA",
        param_name="trimestre",
        sentinel_value="19001",
        rename={
            "trimestre": "trimestre",
            "funcaoCartao": "funcao_cartao",
            "bandeira": "bandeira",
            "produto": "produto",
            "modalidade": "modalidade",
            "tarifaAnuidadeMedia": "tarifa_anuidade_media",
            "qtdPontosAcumulados": "qtd_pontos_acumulados",
            "qtdPontosAdquiridos": "qtd_pontos_adquiridos",
            "qtdPontosConvertidos": "qtd_pontos_convertidos",
            "qtdPontosExpirados": "qtd_pontos_expirados",
            "valorGastoProgramaRecompra": "valor_gasto_programa_recompra",
        },
        decimal_columns=(
            "tarifa_anuidade_media", "qtd_pontos_acumulados", "qtd_pontos_adquiridos",
            "qtd_pontos_convertidos", "qtd_pontos_expirados", "valor_gasto_programa_recompra",
        ),
    ),
    _DatasetSpec(
        key="atm",
        descricao="Estatísticas de ATMs por função/localização",
        function_name="ESTATATMDA",
        param_name="trimestre",
        sentinel_value="19001",
        rename={
            "trimestre": "trimestre",
            "codFuncaoTerminal": "cod_funcao_terminal",
            "codLocalizacao": "cod_localizacao",
            "codTipoCompartilhamento": "cod_tipo_compartilhamento",
            "UF_Terminal": "uf_terminal",
            "qtdTerminal": "qtd_terminal",
        },
        decimal_columns=("qtd_terminal",),
    ),
    _DatasetSpec(
        key="terminais",
        descricao="Infraestrutura de terminais POS/PDV por UF",
        function_name="INFRTERMDA",
        param_name="trimestre",
        sentinel_value="19001",
        rename={
            "trimestre": "trimestre",
            "UFTerminal": "uf_terminal",
            "qtdTermPOS": "qtd_term_pos",
            "qtdTermPOScompartilhados": "qtd_term_pos_compartilhados",
            "qtdTermPOSchip": "qtd_term_pos_chip",
            "qtdTermPDV": "qtd_term_pdv",
        },
        decimal_columns=("qtd_term_pos", "qtd_term_pos_compartilhados", "qtd_term_pos_chip", "qtd_term_pdv"),
    ),
    _DatasetSpec(
        key="estabelecimentos_credenciados",
        descricao="Estabelecimentos credenciados e ativos por bandeira",
        function_name="EstabCredTransDA",
        param_name="trimestre",
        sentinel_value="19001",
        rename={
            "trimestre": "trimestre",
            "bandeira": "bandeira",
            "funcaoCartao": "funcao_cartao",
            "qtdEstabCredenciados": "qtd_estab_credenciados",
            "qtdEstabAtivos": "qtd_estab_ativos",
        },
        int_columns=("qtd_estab_credenciados", "qtd_estab_ativos"),
    ),
    _DatasetSpec(
        key="infra_estabelecimentos",
        descricao="Infraestrutura de captura por UF do estabelecimento",
        function_name="INFRESTADA",
        param_name="trimestre",
        sentinel_value="19001",
        rename={
            "trimestre": "trimestre",
            "UFEstabelecimento": "uf_estabelecimento",
            "qtdEstabTotal": "qtd_estab_total",
            "qtdEstabCapturaManual": "qtd_estab_captura_manual",
            "qtdEstabCapturaEletronica": "qtd_estab_captura_eletronica",
            "qtdEstabCapturaRemota": "qtd_estab_captura_remota",
        },
        decimal_columns=(
            "qtd_estab_total", "qtd_estab_captura_manual", "qtd_estab_captura_eletronica",
            "qtd_estab_captura_remota",
        ),
    ),
    _DatasetSpec(
        key="canais_servicos",
        descricao="Serviços por canal de acesso",
        function_name="OPEINTRADA",
        param_name="trimestre",
        sentinel_value="19001",
        rename={
            "trimestre": "trimestre",
            "operacao": "operacao",
            "qtdTransacoes": "qtd_transacoes",
            "valorTransacoes": "valor_transacoes",
        },
        decimal_columns=("qtd_transacoes", "valor_transacoes"),
    ),
    _DatasetSpec(
        key="canais_transacoes",
        descricao="Pagamento de conta/tributo, transferência e Pix por canal de acesso",
        function_name="TRANSOPADA",
        param_name="trimestre",
        sentinel_value="19001",
        rename={
            "trimestre": "trimestre",
            "canalAcesso": "canal_acesso",
            "produto": "produto",
            "acessoATM": "acesso_atm",
            "qtdTransacoes": "qtd_transacoes",
            "valorTransacoes": "valor_transacoes",
        },
        decimal_columns=("qtd_transacoes", "valor_transacoes"),
    ),
)

_SPECS_BY_KEY: Dict[str, _DatasetSpec] = {spec.key: spec for spec in DATASETS}


def _spec_by_key(key: str) -> Optional[_DatasetSpec]:
    return _SPECS_BY_KEY.get(key)


def _build_function_url(function_name: str, param_name: str, value: str) -> str:
    escaped = _escape_odata_literal(value)
    return (
        f"{BASE_URL}/{function_name}({param_name}=@{param_name})"
        f"?@{param_name}='{escaped}'&$format=json"
    )


def _normalize_dataset(records: List[Dict[str, Any]], spec: _DatasetSpec) -> pd.DataFrame:
    columns = list(spec.rename.values())
    if not records:
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame.from_records(records)
    df = df.rename(columns=spec.rename)
    df = df[[col for col in columns if col in df.columns]]

    for col in spec.decimal_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Float64")
    for col in spec.int_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in spec.string_columns:
        if col in df.columns:
            df[col] = df[col].astype("string")
    if spec.period_column in df.columns:
        df[spec.period_column] = df[spec.period_column].astype(str).astype("string")

    df = df.drop_duplicates().reset_index(drop=True)
    if spec.period_column in df.columns:
        df = df.sort_values(spec.period_column, kind="stable").reset_index(drop=True)
    return df


def _fetch_dataset_history(
    spec: _DatasetSpec,
    *,
    session: Optional[requests.Session] = None,
    timeout: int = REQUEST_TIMEOUT,
) -> pd.DataFrame:
    url = _build_function_url(spec.function_name, spec.param_name, spec.sentinel_value)
    records: List[Dict[str, Any]] = []
    next_url: Optional[str] = url
    while next_url:
        payload = _request_json(next_url, session=session, timeout=timeout)
        records.extend(payload.get("value") or [])
        next_url = payload.get("@odata.nextLink")
    return _normalize_dataset(records, spec)


SPB_MEIOS_PAGAMENTO_CONFIG = CacheConfig(
    nome=SPB_CACHE_NAME,
    descricao="Estatísticas de Meios de Pagamento (SPB/Olinda BCB)",
    subdir=SPB_CACHE_NAME,
    arquivo_dados=f"{_MAIN_KEY}.parquet",
    arquivo_metadata="metadata.json",
    github_url_base=None,
    max_idade_horas=24.0 * 30,
    colunas_obrigatorias=["trimestre"],
    api_url=BASE_URL,
)


class SPBMeiosPagamentoCache(BaseCache):
    """Cache batch das 12 entidades de Meios de Pagamento (Olinda/BCB).

    O dataset `nucleo_trimestral` é o arquivo "principal" exigido por
    `BaseCache` (`arquivo_dados`); os outros 11 são "extras" publicados via
    `extra_release_assets()`, seguindo o mesmo padrão das dimensões de
    `TaxasJurosHistoricoCache`.
    """

    def __init__(self, base_dir: Path):
        super().__init__(SPB_MEIOS_PAGAMENTO_CONFIG, base_dir)
        release_config = get_release_config()
        self.release_repo = release_config.repo
        self.release_tag = release_config.tag
        self.release_base_url = release_config.release_base_url
        self.github_release_parquet_url = f"{self.release_base_url}/{self.config.nome}_dados.parquet"
        self.github_release_metadata_url = f"{self.release_base_url}/{self.config.nome}_metadata.json"

    @property
    def manifest_path(self) -> Path:
        return self.cache_dir / "spb_manifest.json"

    def dataset_paths(self) -> Dict[str, Path]:
        paths: Dict[str, Path] = {}
        for spec in DATASETS:
            paths[spec.key] = self.arquivo_dados if spec.key == _MAIN_KEY else self.cache_dir / f"{spec.key}.parquet"
        return paths

    def _release_url_for(self, key: str) -> str:
        return f"{self.release_base_url}/{self.config.nome}_{key}.parquet"

    def extra_release_assets(self) -> List[Tuple[Path, str]]:
        extras: List[Tuple[Path, str]] = []
        paths = self.dataset_paths()
        for spec in DATASETS:
            if spec.key == _MAIN_KEY:
                continue
            path = paths[spec.key]
            if path.exists():
                extras.append((path, f"{self.config.nome}_{spec.key}.parquet"))
        if self.manifest_path.exists():
            extras.append((self.manifest_path, f"{self.config.nome}_manifest.json"))
        return extras

    def _log_local(self, nivel: str, mensagem: str, callback: Optional[Callable[[str], None]] = None) -> None:
        if callback:
            callback(mensagem)
        self._log(nivel, mensagem)

    def _save_json(self, path: Path, payload: Dict[str, Any]) -> None:
        import json

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def materialize_history(
        self,
        *,
        datasets: Optional[Sequence[str]] = None,
        overwrite: bool = False,
        timeout: int = REQUEST_TIMEOUT,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> CacheResult:
        self._garantir_diretorio()
        selecionados = [spec for spec in DATASETS if not datasets or spec.key in set(datasets)]
        if not selecionados:
            return CacheResult(sucesso=False, mensagem="Nenhum dataset SPB selecionado.", fonte="nenhum")

        paths = self.dataset_paths()
        total = len(selecionados)
        falhas: List[Dict[str, str]] = []
        resumo: Dict[str, int] = {}

        with requests.Session() as session:
            for idx, spec in enumerate(selecionados, start=1):
                path = paths[spec.key]
                if not overwrite and path.exists():
                    self._log_local("info", f"{spec.key}: já materializado, pulando (overwrite=False).", log_callback)
                    if progress_callback:
                        progress_callback(idx / total, f"{spec.key}: já existe, pulado")
                    continue

                if progress_callback:
                    progress_callback((idx - 1) / total, f"Baixando {spec.key} ({idx}/{total})...")
                self._log_local(
                    "info",
                    f"Baixando histórico completo de {spec.key} ({spec.function_name})...",
                    log_callback,
                )
                try:
                    df = _fetch_dataset_history(spec, session=session, timeout=timeout)
                    if df.empty:
                        raise RuntimeError("API retornou conjunto vazio")

                    if spec.key == _MAIN_KEY:
                        resultado = self.salvar_local(
                            df,
                            fonte="api",
                            info_extra={"dataset": spec.key, "function_name": spec.function_name},
                        )
                        if not resultado.sucesso:
                            raise RuntimeError(resultado.mensagem)
                    else:
                        tmp_path = path.with_suffix(".parquet.tmp")
                        df.to_parquet(tmp_path, index=False)
                        tmp_path.replace(path)

                    resumo[spec.key] = int(len(df))
                    self._log_local("info", f"{spec.key}: {len(df):,} linhas materializadas.", log_callback)
                except Exception as exc:
                    falhas.append({"dataset": spec.key, "erro": str(exc)})
                    self._log_local("error", f"Falha em {spec.key}: {exc}", log_callback)

                if progress_callback:
                    progress_callback(idx / total, f"{spec.key}: concluído")

        if falhas:
            return CacheResult(
                sucesso=False,
                mensagem=f"{len(falhas)} dataset(s) falharam: {', '.join(item['dataset'] for item in falhas)}",
                metadata={"failures": falhas, "summary": resumo},
                fonte="nenhum",
            )

        metadata = {
            "finalized_at": datetime.now().isoformat(),
            "datasets": resumo,
        }
        self._save_json(self.manifest_path, metadata)

        if not resumo:
            return CacheResult(
                sucesso=True,
                mensagem="Nenhum dataset novo processado (todos já materializados).",
                metadata=metadata,
                fonte="cache_local",
            )

        return CacheResult(
            sucesso=True,
            mensagem=(
                f"Histórico SPB consolidado: {sum(resumo.values()):,} linhas em {len(resumo)} dataset(s)."
            ),
            metadata=metadata,
            fonte="api",
        )

    def bootstrap_local_assets(self, *, force: bool = False) -> CacheResult:
        paths = self.dataset_paths()
        if not force and all(path.exists() for path in paths.values()) and self.arquivo_metadata.exists():
            return CacheResult(sucesso=True, mensagem="Assets SPB já disponíveis localmente.", fonte="cache_local")

        self._garantir_diretorio()
        urls: Dict[Path, str] = {self.arquivo_metadata: self.github_release_metadata_url}
        for spec in DATASETS:
            urls[paths[spec.key]] = (
                self.github_release_parquet_url if spec.key == _MAIN_KEY else self._release_url_for(spec.key)
            )

        for local_path, url in urls.items():
            try:
                response = requests.get(url, timeout=120)
            except requests.RequestException as exc:
                if local_path == self.arquivo_dados:
                    return CacheResult(sucesso=False, mensagem=f"Erro de rede: {exc}", fonte="nenhum")
                continue

            if response.status_code == 404:
                if local_path == self.arquivo_dados:
                    return CacheResult(
                        sucesso=False, mensagem="Dataset núcleo trimestral não encontrado nos releases", fonte="nenhum"
                    )
                continue

            if response.status_code != 200:
                if local_path == self.arquivo_dados:
                    return CacheResult(
                        sucesso=False,
                        mensagem=f"Falha ao baixar asset principal ({response.status_code})",
                        fonte="nenhum",
                    )
                continue

            local_path.parent.mkdir(parents=True, exist_ok=True)
            if local_path.suffix == ".json":
                local_path.write_text(response.text, encoding="utf-8")
            else:
                local_path.write_bytes(response.content)

        return CacheResult(sucesso=True, mensagem="Assets SPB baixados dos releases.", fonte="github_releases")

    def baixar_remoto(self) -> CacheResult:
        bootstrap = self.bootstrap_local_assets(force=True)
        if not bootstrap.sucesso:
            return bootstrap
        loaded_df = pd.read_parquet(self.arquivo_dados)
        return CacheResult(
            sucesso=True,
            mensagem=f"Baixado núcleo trimestral remoto: {len(loaded_df)} registros",
            dados=loaded_df,
            fonte="github_releases",
        )

    def carregar(self, forcar_remoto: bool = False) -> CacheResult:
        if not forcar_remoto:
            valido, _ = self.cache_valido()
            if valido:
                resultado = self.carregar_local()
                if resultado.sucesso:
                    return resultado

        resultado = self.baixar_remoto()
        if not resultado.sucesso:
            return resultado
        return self.carregar_local()

    def carregar_dataset(self, key: str, *, forcar_remoto: bool = False) -> CacheResult:
        """Carrega um dos 11 datasets "extras" (fora do `nucleo_trimestral`)."""
        spec = _spec_by_key(key)
        if spec is None:
            return CacheResult(sucesso=False, mensagem=f"Dataset SPB desconhecido: {key}", fonte="nenhum")
        if key == _MAIN_KEY:
            return self.carregar(forcar_remoto=forcar_remoto)

        path = self.dataset_paths()[key]
        if not forcar_remoto and path.exists():
            try:
                return CacheResult(sucesso=True, mensagem=f"{key} carregado do cache local", dados=pd.read_parquet(path), fonte="cache_local")
            except Exception as exc:
                self._log("warning", f"Falha ao ler {key} localmente: {exc}")

        bootstrap = self.bootstrap_local_assets(force=forcar_remoto)
        if not bootstrap.sucesso or not path.exists():
            return CacheResult(sucesso=False, mensagem=f"Dataset {key} indisponível: {bootstrap.mensagem}", fonte="nenhum")
        return CacheResult(sucesso=True, mensagem=f"{key} baixado dos releases", dados=pd.read_parquet(path), fonte="github_releases")

    def extrair_periodo(self, periodo: str, **kwargs) -> CacheResult:
        """Refaz a extração completa de UM dataset (`periodo` = chave do dataset)."""
        spec = _spec_by_key(periodo)
        if spec is None:
            return CacheResult(sucesso=False, mensagem=f"Dataset SPB desconhecido: {periodo}", fonte="nenhum")
        df = _fetch_dataset_history(spec, timeout=int(kwargs.get("timeout", REQUEST_TIMEOUT)))
        return CacheResult(
            sucesso=True,
            mensagem=f"{spec.key}: {len(df)} linhas extraídas",
            dados=df,
            fonte="api",
        )

    def limpar_local(self) -> CacheResult:
        resultado = super().limpar_local()
        extras_removidos: List[str] = []
        paths = self.dataset_paths()
        for spec in DATASETS:
            if spec.key == _MAIN_KEY:
                continue
            path = paths[spec.key]
            if path.exists():
                path.unlink()
                extras_removidos.append(path.name)
        if self.manifest_path.exists():
            self.manifest_path.unlink()
            extras_removidos.append(self.manifest_path.name)
        if extras_removidos:
            return CacheResult(
                sucesso=True,
                mensagem=f"{resultado.mensagem}; extras removidos: {', '.join(extras_removidos)}",
                fonte="nenhum",
            )
        return resultado
