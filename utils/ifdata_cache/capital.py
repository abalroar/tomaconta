"""
capital.py - Cache de dados de capital regulatório (Relatório 5)

Implementa cache para o Relatório 5 do IFData com variáveis de capital.
Produz dados no formato exato que os gráficos do app1.py esperam.
"""

import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

from .base import BaseCache, CacheConfig, CacheResult

logger = logging.getLogger("ifdata_cache")

# Mapeamento de campos do Relatório 5
CAMPOS_CAPITAL = {
    "Capital Principal para Comparação com RWA (a)": "Capital Principal",
    "Capital Complementar (b)": "Capital Complementar",
    "Patrimônio de Referência Nível I para Comparação com RWA (c) = (a) + (b)": "Patrimônio de Referência Nível I",
    "Capital Nível II (d)": "Capital Nível II",
    "RWA para Risco de Crédito (f)": "RWA Crédito",
    "RWA para Risco de Mercado (g) = (g1) + (g2) + (g3) + (g4) + (g5) + (g6)": "RWA Mercado",
    "RWA para Risco de Mercado (g) = (g1) + (g2) + (g3) + (g4)": "RWA Mercado",
    "RWA para Risco Operacional (h)": "RWA Operacional",
    "Ativos Ponderados pelo Risco (RWA) (j) = (f) + (g) + (h) + (i)": "RWA Total",
    "Ativos Ponderados pelo Risco (RWA) (i) = (f) + (g) + (h)": "RWA Total",
    "Exposição Total (k)": "Exposição Total",
    "Índice de Capital Principal (l) = (a) / (j)": "Índice de Capital Principal",
    "Índice de Capital Principal (k) = (a) / (i)": "Índice de Capital Principal",
    "Índice de Capital Nível I (m) = (c) / (j)": "Índice de Capital Nível I",
    "Índice de Basileia (n) = (e) / (j)": "Índice de Basileia",
    "Índice de Basileia (m) = (e) / (i)": "Índice de Basileia",
    "Adicional de Capital Principal": "Adicional de Capital Principal",
    "IRRBB": "IRRBB",
    "Razão de Alavancagem (o) = (c) / (k)": "Razão de Alavancagem",
    "Índice de Imobilização (p)": "Índice de Imobilização",
}

# Configuração do cache de capital
CAPITAL_CONFIG = CacheConfig(
    nome="capital",
    descricao="Dados de capital regulatório (Relatório 5)",
    subdir="capital",
    arquivo_dados="dados.parquet",
    arquivo_metadata="metadata.json",
    github_url_base="https://github.com/abalroar/tomaconta/releases/download/v1.0-cache",
    max_idade_horas=720.0,
    colunas_obrigatorias=["Período"],
    campos_mapeamento=CAMPOS_CAPITAL,
    api_url="https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata",
    relatorio_tipo=5,
)


class CapitalCache(BaseCache):
    """Cache de dados de capital regulatório do IFData.

    Produz dados com:
    - Coluna "Instituição" (nome da instituição)
    - Coluna "Período" no formato "1/2024" (trimestre/ano)
    - Métricas de capital no formato esperado pelos gráficos
    """

    def __init__(self, base_dir: Path, manter_codinst: bool = True):
        super().__init__(CAPITAL_CONFIG, base_dir)
        self.manter_codinst = manter_codinst
        release_repo = os.getenv("TOMACONTA_RELEASE_REPO", "abalroar/tomaconta")
        raw_repo = os.getenv("TOMACONTA_RAW_REPO", "abalroar/tomaconta")
        release_base = f"https://github.com/{release_repo}/releases/download/v1.0-cache"

        # URLs em ordem de prioridade:
        # 1. Parquet do repositório raw (configurável)
        self.github_raw_url = f"https://raw.githubusercontent.com/{raw_repo}/main/data/cache/capital/dados.parquet"
        # 2. Parquet dos releases (prod por padrão)
        self.github_release_parquet_url = f"{release_base}/capital_dados.parquet"
        # 3. Pickle dos releases (compat legado)
        self.github_release_url = f"{release_base}/capital_cache.pkl"

    def baixar_remoto(self) -> CacheResult:
        """Baixa dados do GitHub (tenta múltiplas fontes em ordem de prioridade)."""
        self._log("info", "Tentando baixar do GitHub...")

        # 1. Tentar parquet do repositório raw
        resultado = self._baixar_parquet_repo()
        if resultado.sucesso:
            return resultado

        # 2. Tentar parquet dos releases
        resultado = self._baixar_parquet_release()
        if resultado.sucesso:
            return resultado

        # 3. Fallback: pickle dos releases
        resultado = self._baixar_pickle_releases(self.github_release_url, "releases")
        if resultado.sucesso:
            return resultado

        return CacheResult(
            sucesso=False,
            mensagem="Cache de capital não encontrado no GitHub (tentou repositório raw e releases)",
            fonte="nenhum"
        )

    def _baixar_com_deadline(self, url: str, deadline_s: int = 20) -> Tuple[Optional[bytes], object]:
        """Download com deadline de wall-clock absoluto.

        requests.timeout só reinicia por chunk recebido; um servidor que envia
        dados muito devagar (20 KB/s) nunca dispara o timeout mas leva minutos.
        Aqui abortamos se o total ultrapassar deadline_s segundos.

        Retorna (bytes_conteudo, status_code) em sucesso ou (None, motivo_str) em falha.
        """
        import io
        t0 = time.monotonic()
        buf = io.BytesIO()
        try:
            resp = requests.get(url, stream=True, timeout=(10, 10))
            status = resp.status_code
            if not resp.ok:
                return None, status
            for chunk in resp.iter_content(chunk_size=65536):
                elapsed = time.monotonic() - t0
                if elapsed > deadline_s:
                    resp.close()
                    self._log("warning", f"Deadline {deadline_s}s atingido ({elapsed:.1f}s) para {url}")
                    return None, "DEADLINE"
                if chunk:
                    buf.write(chunk)
            return buf.getvalue(), status
        except requests.RequestException as e:
            return None, str(e)

    def _baixar_parquet_repo(self) -> CacheResult:
        """Baixa parquet do repositório GitHub."""
        import io
        self._log("info", f"Tentando parquet do repositório: {self.github_raw_url}")
        try:
            conteudo, status = self._baixar_com_deadline(self.github_raw_url, deadline_s=20)
            if conteudo is None:
                if status == 404:
                    self._log("warning", "Parquet não encontrado no repositório")
                else:
                    self._log("warning", f"Falha no repositório: {status}")
                return CacheResult(sucesso=False, mensagem=f"Repo: {status}", fonte="nenhum")
            df = pd.read_parquet(io.BytesIO(conteudo))
            self._log("info", f"Baixado parquet do repositório: {len(df)} registros")
            return CacheResult(sucesso=True, mensagem=f"Repo: {len(df)} registros", dados=df, fonte="github_repo")
        except Exception as e:
            self._log("error", f"Erro ao baixar do repositório: {e}")
            return CacheResult(sucesso=False, mensagem=str(e), fonte="nenhum")

    def _baixar_parquet_release(self) -> CacheResult:
        """Baixa parquet do GitHub Releases."""
        import io
        self._log("info", f"Tentando parquet dos releases: {self.github_release_parquet_url}")
        try:
            conteudo, status = self._baixar_com_deadline(self.github_release_parquet_url, deadline_s=20)
            if conteudo is None:
                if status == 404:
                    self._log("warning", "Parquet não encontrado nos releases")
                else:
                    self._log("warning", f"Falha nos releases: {status}")
                return CacheResult(sucesso=False, mensagem=f"Releases: {status}", fonte="nenhum")
            df = pd.read_parquet(io.BytesIO(conteudo))
            self._log("info", f"Baixado parquet dos releases: {len(df)} registros")
            return CacheResult(sucesso=True, mensagem=f"Releases: {len(df)} registros", dados=df, fonte="github_releases")
        except Exception as e:
            self._log("error", f"Erro de rede: {e}")
            return CacheResult(sucesso=False, mensagem=str(e), fonte="nenhum")

    def _baixar_pickle_releases(self, url: str, repo_nome: str = "") -> CacheResult:
        """Baixa pickle do GitHub Releases (formato antigo)."""
        import io, pickle
        self._log("info", f"Tentando pickle dos releases ({repo_nome}): {url}")
        try:
            conteudo, status = self._baixar_com_deadline(url, deadline_s=20)
            if conteudo is None:
                self._log("warning", f"Pickle não encontrado ({repo_nome}): {status}")
                return CacheResult(sucesso=False, mensagem=f"Releases pickle: {status}", fonte="nenhum")

            dados_dict = pickle.load(io.BytesIO(conteudo))

            if isinstance(dados_dict, dict):
                dfs = []
                for periodo, df in dados_dict.items():
                    if isinstance(df, pd.DataFrame) and not df.empty:
                        if "Período" not in df.columns:
                            df = df.copy()
                            df["Período"] = str(periodo)
                        dfs.append(df)
                if not dfs:
                    return CacheResult(sucesso=False, mensagem="Arquivo pickle vazio", fonte="nenhum")
                df_final = pd.concat(dfs, ignore_index=True)
            elif isinstance(dados_dict, pd.DataFrame):
                df_final = dados_dict
            else:
                return CacheResult(sucesso=False, mensagem=f"Formato inesperado: {type(dados_dict)}", fonte="nenhum")

            self._log("info", f"Baixado pickle dos releases ({repo_nome}): {len(df_final)} registros")
            return CacheResult(
                sucesso=True,
                mensagem=f"Pickle releases ({repo_nome}): {len(df_final)} registros",
                dados=df_final,
                fonte=f"github_releases_{repo_nome}"
            )
        except Exception as e:
            self._log("error", f"Erro: {e}")
            return CacheResult(sucesso=False, mensagem=str(e), fonte="nenhum")

    def extrair_periodo(
        self,
        periodo: str,
        dict_aliases: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> CacheResult:
        """Extrai dados de capital de um período da API do BCB.

        Usa o extrator autônomo para produzir dados no formato dos gráficos.

        Args:
            periodo: Período no formato YYYYMM (ex: "202312")
            dict_aliases: Dicionário de aliases para instituições

        Returns:
            CacheResult com DataFrame ou erro
        """
        self._log("info", f"Extraindo período {periodo}...")

        try:
            # Usar extrator autônomo
            from .extractor import extrair_capital

            df = extrair_capital(periodo, dict_aliases, manter_codinst=self.manter_codinst)

            if df is None or df.empty:
                return CacheResult(
                    sucesso=False,
                    mensagem=f"Sem dados de capital para {periodo}",
                    fonte="nenhum"
                )

            self._log("info", f"Período {periodo}: {len(df)} instituições")

            return CacheResult(
                sucesso=True,
                mensagem=f"Extraído {periodo}: {len(df)} registros",
                dados=df,
                metadata={
                    "periodo": periodo,
                    "n_registros": len(df),
                    "colunas": list(df.columns)
                },
                fonte="api"
            )

        except Exception as e:
            self._log("error", f"Erro ao extrair {periodo}: {e}")
            return CacheResult(
                sucesso=False,
                mensagem=f"Erro: {e}",
                fonte="nenhum"
            )

    # =========================================================================
    # COMPATIBILIDADE COM SISTEMA ANTIGO
    # =========================================================================

    def carregar_formato_antigo(self) -> Optional[dict]:
        """Carrega e retorna no formato antigo {periodo: DataFrame}."""
        resultado = self.carregar()
        if not resultado.sucesso or resultado.dados is None:
            return None

        df = resultado.dados
        if "Período" not in df.columns:
            return None

        dados_dict = {}
        for periodo in df["Período"].unique():
            dados_dict[str(periodo)] = df[df["Período"] == periodo].copy()

        return dados_dict

    def salvar_formato_antigo(
        self,
        dados_dict: dict,
        fonte: str = "api",
        info_extra: Optional[dict] = None
    ) -> CacheResult:
        """Salva a partir do formato antigo {periodo: DataFrame}."""
        if not dados_dict:
            return CacheResult(
                sucesso=False,
                mensagem="Dicionário vazio",
                fonte="nenhum"
            )

        dfs = []
        for periodo, df in dados_dict.items():
            if isinstance(df, pd.DataFrame) and not df.empty:
                df_copy = df.copy()
                if "Período" not in df_copy.columns:
                    df_copy["Período"] = str(periodo)
                dfs.append(df_copy)

        if not dfs:
            return CacheResult(
                sucesso=False,
                mensagem="Nenhum DataFrame válido",
                fonte="nenhum"
            )

        df_final = pd.concat(dfs, ignore_index=True)
        return self.salvar_local(df_final, fonte=fonte, info_extra=info_extra)


def gerar_periodos_trimestrais(
    ano_ini: int,
    mes_ini: int,
    ano_fin: int,
    mes_fin: int
) -> List[str]:
    """Gera lista de períodos trimestrais.

    Args:
        ano_ini: Ano inicial
        mes_ini: Mês inicial (3, 6, 9, ou 12)
        ano_fin: Ano final
        mes_fin: Mês final (3, 6, 9, ou 12)

    Returns:
        Lista de períodos no formato YYYYMM
    """
    meses_validos = [3, 6, 9, 12]
    periodos = []

    for ano in range(ano_ini, ano_fin + 1):
        for mes in meses_validos:
            if ano == ano_ini and mes < mes_ini:
                continue
            if ano == ano_fin and mes > mes_fin:
                continue
            periodos.append(f"{ano}{mes:02d}")

    return periodos
