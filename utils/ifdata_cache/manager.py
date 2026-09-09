"""
manager.py - Gerenciador central de caches

Coordena multiplos tipos de cache e fornece interface unificada.

Caches disponíveis:
- principal: Resumo geral (Relatório 1) - variáveis selecionadas
- capital: Informações de Capital (Relatório 5) - variáveis selecionadas
- ativo: Composição do Ativo (Relatório 2) - todas as variáveis
- passivo: Composição do Passivo (Relatório 3) - todas as variáveis
- dre: Demonstração de Resultado (Relatório 4) - todas as variáveis
- carteira_pf: Carteira de Crédito PF (Relatório 11) - todas as variáveis
- carteira_pj: Carteira de Crédito PJ (Relatório 13) - todas as variáveis
- carteira_instrumentos: Carteira - Instrumentos 4.966 (Relatório 16) - todas as variáveis
"""

import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from .base import BaseCache, CacheResult

logger = logging.getLogger("ifdata_cache")


# Informações dos caches para UI
CACHES_INFO = {
    "principal": {
        "nome_exibicao": "Resumo (Relatório 1)",
        "descricao": "Dados gerais das instituições - variáveis selecionadas",
        "relatorio": 1,
        "todas_variaveis": False,
    },
    "principal_individual": {
        "nome_exibicao": "Resumo Individual (Relatório 1)",
        "descricao": "Dados gerais das instituições individuais - variáveis selecionadas",
        "relatorio": 1,
        "todas_variaveis": False,
    },
    "capital": {
        "nome_exibicao": "Capital Regulatório (Relatório 5)",
        "descricao": "Informações de capital - variáveis selecionadas",
        "relatorio": 5,
        "todas_variaveis": False,
    },
    "ativo": {
        "nome_exibicao": "Ativo (Relatório 2)",
        "descricao": "Composição detalhada do ativo - TODAS as variáveis",
        "relatorio": 2,
        "todas_variaveis": True,
    },
    "passivo": {
        "nome_exibicao": "Passivo (Relatório 3)",
        "descricao": "Composição detalhada do passivo - TODAS as variáveis",
        "relatorio": 3,
        "todas_variaveis": True,
    },
    "dre": {
        "nome_exibicao": "DRE (Relatório 4)",
        "descricao": "Demonstração de Resultado - TODAS as variáveis",
        "relatorio": 4,
        "todas_variaveis": True,
    },
    "dre_individual": {
        "nome_exibicao": "DRE Individual (Relatório 4)",
        "descricao": "Demonstração de Resultado - instituições individuais - TODAS as variáveis",
        "relatorio": 4,
        "todas_variaveis": True,
    },
    "carteira_pf": {
        "nome_exibicao": "Carteira PF (Relatório 11)",
        "descricao": "Carteira de crédito PF - modalidade e prazo",
        "relatorio": 11,
        "todas_variaveis": True,
    },
    "carteira_pj": {
        "nome_exibicao": "Carteira PJ (Relatório 13)",
        "descricao": "Carteira de crédito PJ - modalidade e prazo",
        "relatorio": 13,
        "todas_variaveis": True,
    },
    "carteira_instrumentos": {
        "nome_exibicao": "Carteira (Instrumentos 4.966) (Relatório 16)",
        "descricao": "Carteira de crédito - Instrumentos Financeiros Res. 4.966 (C1-C5)",
        "relatorio": 16,
        "todas_variaveis": True,
    },
    "taxas_juros": {
        "nome_exibicao": "Taxas de Juros (API BCB)",
        "descricao": "Taxas de juros por produto e instituição financeira",
        "relatorio": None,  # API diferente do IFData
        "todas_variaveis": True,
        "periodicidade": "diaria",  # Janelas de 5 dias úteis
    },
    "taxas_juros_historico": {
        "nome_exibicao": "Taxas de Juros Histórico (Batch BCB)",
        "descricao": "Histórico consolidado de taxas por instituição financeira",
        "relatorio": None,
        "todas_variaveis": True,
        "periodicidade": "diaria",
    },
    "derived_metrics": {
        "nome_exibicao": "Métricas Derivadas",
        "descricao": "Indicadores derivados (DRE + Resumo)",
        "relatorio": None,
        "todas_variaveis": False,
    },
    "derived_metrics_individual": {
        "nome_exibicao": "Métricas Derivadas Individual",
        "descricao": "Indicadores derivados (DRE individual + Resumo individual)",
        "relatorio": None,
        "todas_variaveis": False,
    },
    "critical_screens": {
        "nome_exibicao": "Snapshot/Peers Curado",
        "descricao": "Métricas materializadas para Snapshot e Peers",
        "relatorio": None,
        "todas_variaveis": False,
    },
    "bloprudencial": {
        "nome_exibicao": "Conglomerados Prudenciais (BLOPRUDENCIAL)",
        "descricao": "Arquivo mensal estático BLOPRUDENCIAL (BCB)",
        "relatorio": None,
        "todas_variaveis": True,
        "periodicidade": "mensal",
    },
    "balancetes": {
        "nome_exibicao": "Balancetes COSIF (4060, 4066)",
        "descricao": "Demonstrações Contábeis - Balancetes do BCB",
        "relatorio": None,  # API REST diferente do IFData
        "todas_variaveis": True,
        "periodicidade": "trimestral",
    },
    "spb_meios_pagamento": {
        "nome_exibicao": "Meios de Pagamento (SPB/Olinda BCB)",
        "descricao": "Estatísticas de Meios de Pagamento - 12 entidades (MPV_DadosAbertos)",
        "relatorio": None,  # API Olinda diferente do IFData
        "todas_variaveis": True,
        "periodicidade": "trimestral/mensal",
    },
    "scr_data": {
        "nome_exibicao": "SCR.data (Inadimplência/BCB)",
        "descricao": "Carteira, inadimplência e ativo problemático por UF, segmento, porte e produto",
        "relatorio": None,  # ZIPs anuais do PDA, sem API
        "todas_variaveis": True,
        "periodicidade": "mensal",
    },
    "mercado_credito_sgs": {
        "nome_exibicao": "Estatísticas Crédito BC (SGS/BCB)",
        "descricao": "Séries agregadas de concessões, estoques, inadimplência, taxas e famílias",
        "relatorio": None,
        "todas_variaveis": False,
        "periodicidade": "mensal",
    },
}


class CacheManager:
    """Gerenciador central de todos os caches do IFData."""

    def __init__(self, base_dir: Optional[Path] = None):
        """
        Args:
            base_dir: Diretorio base do projeto. Se None, detecta automaticamente.
        """
        if base_dir is None:
            # Detectar diretorio base (3 niveis acima: utils/ifdata_cache/manager.py)
            base_dir = Path(__file__).parent.parent.parent.resolve()

        self.base_dir = base_dir
        self._caches: Dict[str, BaseCache] = {}
        self._registrar_caches_padrao()

    def _registrar_caches_padrao(self):
        """Registra os caches padrao do sistema."""
        # Importar aqui para evitar dependencia circular
        from .principal import PrincipalCache, PrincipalIndividualCache
        from .capital import CapitalCache
        from .relatorios_completos import (
            AtivoCache,
            PassivoCache,
            DRECache,
            DREIndividualCache,
            CarteiraPFCache,
            CarteiraPJCache,
            CarteiraInstrumentosCache,
        )
        from .taxas_juros import TaxasJurosCache
        from .taxas_juros_historico import TaxasJurosHistoricoCache
        from .derived_metrics import DerivedMetricsCache, DerivedMetricsIndividualCache
        from .critical_screens import CriticalScreensCache
        from .balancetes import BalancetesCache
        from .bloprudencial_cache import BloprudencialCache
        from .spb_meios_pagamento import SPBMeiosPagamentoCache
        from .scr_data import SCRDataCache
        from .sgs_credit import SGSCreditCache

        # Caches principais (variáveis selecionadas)
        self.registrar(PrincipalCache(self.base_dir, manter_codinst=True))
        self.registrar(PrincipalIndividualCache(self.base_dir))
        self.registrar(CapitalCache(self.base_dir, manter_codinst=True))

        # Caches de relatórios completos (todas as variáveis)
        self.registrar(AtivoCache(self.base_dir))
        self.registrar(PassivoCache(self.base_dir))
        self.registrar(DRECache(self.base_dir))
        self.registrar(DREIndividualCache(self.base_dir))
        self.registrar(CarteiraPFCache(self.base_dir))
        self.registrar(CarteiraPJCache(self.base_dir))
        self.registrar(CarteiraInstrumentosCache(self.base_dir))

        # Cache de Taxas de Juros (API BCB diferente)
        self.registrar(TaxasJurosCache(self.base_dir))
        self.registrar(TaxasJurosHistoricoCache(self.base_dir))
        # Cache de métricas derivadas (DRE + Resumo)
        self.registrar(DerivedMetricsCache(self.base_dir))
        self.registrar(DerivedMetricsIndividualCache(self.base_dir))
        self.registrar(CriticalScreensCache(self.base_dir))
        # Cache de balancetes COSIF (API REST BCB)
        self.registrar(BalancetesCache(self.base_dir))
        # Cache BLOPRUDENCIAL mensal (arquivo estático BCB)
        self.registrar(BloprudencialCache(self.base_dir))
        # Cache de Meios de Pagamento SPB (API Olinda MPV_DadosAbertos)
        self.registrar(SPBMeiosPagamentoCache(self.base_dir))
        # Cache do SCR.data (ZIPs anuais do PDA/BCB, sem API)
        self.registrar(SCRDataCache(self.base_dir))
        # Cache de estatísticas agregadas de crédito (API BCData/SGS)
        self.registrar(SGSCreditCache(self.base_dir))

    def registrar(self, cache: BaseCache):
        """Registra um novo tipo de cache.

        Args:
            cache: Instancia de cache a registrar
        """
        nome = cache.config.nome
        self._caches[nome] = cache
        logger.debug(f"[CACHE_MANAGER] Registrado: {nome}")

    def listar_caches(self) -> List[str]:
        """Lista nomes de todos os caches registrados."""
        return list(self._caches.keys())

    def get_cache(self, tipo: str) -> Optional[BaseCache]:
        """Retorna instancia de cache pelo tipo."""
        return self._caches.get(tipo)

    def carregar(self, tipo: str, forcar_remoto: bool = False) -> CacheResult:
        """Carrega dados de um tipo de cache.

        Args:
            tipo: Nome do tipo de cache (ex: "principal", "capital")
            forcar_remoto: Se True, ignora cache local

        Returns:
            CacheResult com dados ou erro
        """
        cache = self._caches.get(tipo)
        if cache is None:
            return CacheResult(
                sucesso=False,
                mensagem=f"Tipo de cache desconhecido: {tipo}. Disponiveis: {self.listar_caches()}",
                fonte="nenhum"
            )

        return cache.carregar(forcar_remoto=forcar_remoto)

    def salvar(
        self,
        tipo: str,
        dados,
        fonte: str = "desconhecida",
        **kwargs
    ) -> CacheResult:
        """Salva dados em um tipo de cache.

        Args:
            tipo: Nome do tipo de cache
            dados: DataFrame a salvar
            fonte: Identificador da fonte dos dados
            **kwargs: Argumentos extras passados para salvar_local

        Returns:
            CacheResult
        """
        cache = self._caches.get(tipo)
        if cache is None:
            return CacheResult(
                sucesso=False,
                mensagem=f"Tipo de cache desconhecido: {tipo}",
                fonte="nenhum"
            )

        return cache.salvar_local(dados, fonte=fonte, info_extra=kwargs.get("info_extra"))

    def info(self, tipo: str = None) -> Dict[str, Any]:
        """Retorna informacoes sobre cache(s).

        Args:
            tipo: Nome do tipo de cache. Se None, retorna info de todos.

        Returns:
            Dicionario com informacoes
        """
        if tipo is not None:
            cache = self._caches.get(tipo)
            if cache is None:
                return {"erro": f"Tipo desconhecido: {tipo}"}
            return cache.get_info()

        # Retornar info de todos
        return {nome: cache.get_info() for nome, cache in self._caches.items()}

    def limpar(self, tipo: str = None) -> CacheResult:
        """Limpa cache(s).

        Args:
            tipo: Nome do tipo de cache. Se None, limpa todos.

        Returns:
            CacheResult
        """
        if tipo is not None:
            cache = self._caches.get(tipo)
            if cache is None:
                return CacheResult(
                    sucesso=False,
                    mensagem=f"Tipo desconhecido: {tipo}",
                    fonte="nenhum"
                )
            return cache.limpar_local()

        # Limpar todos
        resultados = []
        for nome, cache in self._caches.items():
            resultado = cache.limpar_local()
            resultados.append(f"{nome}: {resultado.mensagem}")

        return CacheResult(
            sucesso=True,
            mensagem="; ".join(resultados),
            fonte="nenhum"
        )

    def extrair_periodos(
        self,
        tipo: str,
        periodos: List[str],
        callback_progresso=None,
        **kwargs
    ) -> CacheResult:
        """Extrai dados de multiplos periodos da API.

        Args:
            tipo: Nome do tipo de cache
            periodos: Lista de periodos "YYYYMM"
            callback_progresso: Funcao (i, total, periodo) chamada a cada periodo
            **kwargs: Argumentos extras para extracao

        Returns:
            CacheResult com todos os dados
        """
        import pandas as pd

        cache = self._caches.get(tipo)
        if cache is None:
            return CacheResult(
                sucesso=False,
                mensagem=f"Tipo desconhecido: {tipo}",
                fonte="nenhum"
            )

        dados_todos = []
        erros = []

        for i, periodo in enumerate(periodos):
            if callback_progresso:
                callback_progresso(i, len(periodos), periodo)

            resultado = cache.extrair_periodo(periodo, **kwargs)

            if resultado.sucesso and resultado.dados is not None:
                dados_todos.append(resultado.dados)
            else:
                erros.append(f"{periodo}: {resultado.mensagem}")
                logger.warning(f"[CACHE:{tipo.upper()}] Erro em {periodo}: {resultado.mensagem}")

        if not dados_todos:
            return CacheResult(
                sucesso=False,
                mensagem=f"Nenhum periodo extraido. Erros: {'; '.join(erros[:3])}",
                fonte="nenhum"
            )

        # Concatenar todos os periodos
        df_final = pd.concat(dados_todos, ignore_index=True)

        logger.info(f"[CACHE:{tipo.upper()}] Extraidos {len(dados_todos)}/{len(periodos)} periodos, {len(df_final)} registros")

        return CacheResult(
            sucesso=True,
            mensagem=f"Extraidos {len(dados_todos)} periodos, {len(df_final)} registros",
            dados=df_final,
            metadata={"periodos_extraidos": len(dados_todos), "erros": erros},
            fonte="api"
        )

    def existe(self, tipo: str) -> bool:
        """Verifica se cache de um tipo existe."""
        cache = self._caches.get(tipo)
        if cache is None:
            return False
        return cache.existe()

    def cache_valido(self, tipo: str) -> tuple:
        """Verifica se cache de um tipo esta valido."""
        cache = self._caches.get(tipo)
        if cache is None:
            return False, f"Tipo desconhecido: {tipo}"
        return cache.cache_valido()

    # =========================================================================
    # NOVOS METODOS PARA EXTRACAO AVANÇADA
    # =========================================================================

    def get_caches_info(self) -> Dict[str, Dict]:
        """Retorna informações sobre todos os caches disponíveis para UI."""
        return CACHES_INFO.copy()

    def get_cache_info_completa(self, tipo: str) -> Dict[str, Any]:
        """Retorna informações completas sobre um cache específico."""
        info_base = CACHES_INFO.get(tipo, {})
        info_cache = self.info(tipo)

        return {
            **info_base,
            **info_cache,
            "tipo": tipo,
        }

    def extrair_periodos_com_salvamento(
        self,
        tipo: str,
        periodos: List[str],
        modo: str = "incremental",
        intervalo_salvamento: int = 4,
        callback_progresso: Optional[Callable[[int, int, str], None]] = None,
        callback_salvamento: Optional[Callable[[str], None]] = None,
        callback_erro: Optional[Callable[[str, str], None]] = None,
        dict_aliases: Optional[Dict[str, str]] = None,
        callback_checkpoint: Optional[Callable[[Dict[str, Any]], None]] = None,
        execution_periods: Optional[List[str]] = None,
        **kwargs
    ) -> CacheResult:
        """Extrai e confirma apenas períodos validados e efetivamente persistidos.

        ``incremental`` e ``overwrite`` preservam períodos fora da atualização.
        ``rebuild`` reconstrói o dataset. O checkpoint é notificado após a gravação;
        sua falha interrompe a execução e impede uma conclusão bem-sucedida.
        """
        from datetime import datetime

        from .update_state import mutation_lock

        requested = list(dict.fromkeys(str(periodo).strip() for periodo in periodos))
        execution = list(dict.fromkeys(str(p).strip() for p in execution_periods)) if execution_periods is not None else requested
        cache = self._caches.get(tipo)
        validation_error = None
        if cache is None:
            validation_error = f"Tipo de cache desconhecido: {tipo}"
        elif modo not in {"incremental", "overwrite", "rebuild"}:
            validation_error = f"Modo de atualização inválido: {modo}"
        elif not isinstance(intervalo_salvamento, int) or isinstance(intervalo_salvamento, bool) or intervalo_salvamento < 1:
            validation_error = "Intervalo de salvamento deve ser um inteiro positivo"
        elif not requested:
            validation_error = "Nenhum período solicitado"
        elif not set(requested).issubset(execution):
            validation_error = "O lote contém competências fora do plano completo da execução"
        else:
            for periodo in execution:
                try:
                    if len(periodo) != 6 or not periodo.isascii() or not periodo.isdigit():
                        raise ValueError("formato YYYYMM obrigatório")
                    datetime(int(periodo[:4]), int(periodo[4:]), 1)
                    if getattr(cache.config, "relatorio_tipo", None) and periodo[4:] not in {"03", "06", "09", "12"}:
                        raise ValueError("relatório IFData exige competência trimestral")
                except ValueError as exc:
                    validation_error = f"Período inválido {periodo!r}: {exc}"
                    break
        if validation_error:
            return CacheResult(
                sucesso=False, mensagem=validation_error, fonte="nenhum",
                metadata={
                    "requested_periods": requested, "extracted_periods": [],
                    "persisted_periods": [], "failed_periods": {},
                    "pending_periods": requested, "status": "failed",
                    "periodos_extraidos": 0, "periodos_total": len(requested),
                    "total_registros": 0, "erros": [validation_error], "modo": modo,
                },
            )
        with mutation_lock(self.base_dir):
            return self._extrair_periodos_com_salvamento_locked(
                cache, requested, modo, intervalo_salvamento,
                callback_progresso, callback_salvamento, callback_erro,
                callback_checkpoint, execution, **kwargs,
            )

    def _extrair_periodos_com_salvamento_locked(
        self, cache, requested, modo, intervalo_salvamento,
        callback_progresso, callback_salvamento, callback_erro,
        callback_checkpoint, execution_periods, **kwargs,
    ) -> CacheResult:
        from .diagnostics import normalize_period_reference
        from .update_state import load_cache_update_result, write_cache_update_result

        dados_existentes = None
        dados_persistidos = None
        dados_extraidos = []
        extracted = []
        persisted = []
        failed = {}
        erros = []
        operation_errors = {}
        ledger_requested = list(execution_periods)
        ledger_persisted = set()
        ledger_extracted = set()
        ledger_failures = {}

        def metadata():
            complete = len(persisted) == len(requested) and not erros
            return {
                "requested_periods": list(requested),
                "extracted_periods": list(extracted),
                "persisted_periods": list(persisted),
                "failed_periods": dict(failed),
                "pending_periods": [p for p in requested if p not in persisted],
                "status": "saved" if complete else "partial" if persisted else "failed",
                "periodos_extraidos": len(extracted), "periodos_total": len(requested),
                "total_registros": len(dados_persistidos) if dados_persistidos is not None else 0,
                "erros": list(erros), "modo": modo,
                **operation_errors,
            }

        def ledger_metadata(*, ongoing=False):
            info = metadata()
            confirmed = ledger_persisted | set(persisted)
            failures = {**ledger_failures, **failed}
            failures = {period: reason for period, reason in failures.items() if period not in confirmed}
            pending = [period for period in ledger_requested if period not in confirmed]
            complete = not pending and not failures and not erros
            info.update({
                "requested_periods": list(ledger_requested),
                "extracted_periods": [p for p in ledger_requested if p in ledger_extracted or p in extracted],
                "persisted_periods": [p for p in ledger_requested if p in confirmed],
                "failed_periods": failures,
                "pending_periods": pending,
                # Somente finish conclui a operação. Uma interrupção nos callbacks
                # ou na gravação final conserva um marcador que bloqueia publicação.
                "status": "extracting" if ongoing else "saved" if complete else "partial" if confirmed else "failed",
                "periodos_total": len(ledger_requested),
            })
            info["periodos_extraidos"] = len(info["extracted_periods"])
            return info

        def write_ledger(*, ongoing=False):
            try:
                write_cache_update_result(self.base_dir, cache.config.nome, ledger_metadata(ongoing=ongoing))
            except Exception as exc:
                operation_errors["checkpoint_error"] = str(exc)
                erros.append(f"Falha ao registrar resultado persistido da fonte: {exc}")
                return False
            return True

        def finish(message=None, *, record_ledger=True):
            if record_ledger:
                write_ledger()
            info = metadata()
            return CacheResult(
                sucesso=info["status"] == "saved",
                mensagem=message or (
                    f"Persistidos {len(persisted)}/{len(requested)} períodos"
                    + (f". Falhas: {'; '.join(erros[:3])}" if erros else "")
                ),
                dados=dados_persistidos, metadata=info,
                fonte="api" if persisted else "nenhum",
            )

        def fail(periodo, message):
            failed[periodo] = message
            erros.append(f"{periodo}: {message}")
            logger.warning("[CACHE:%s] %s: %s", cache.config.nome, periodo, message)
            if callback_erro:
                callback_erro(periodo, message)

        try:
            previous_ledger = load_cache_update_result(self.base_dir, cache.config.nome)
        except Exception as exc:
            operation_errors["checkpoint_error"] = str(exc)
            erros.append(f"Resultado anterior da fonte ilegível: {exc}")
            return finish(record_ledger=False)
        if previous_ledger and (
            previous_ledger.get("status") != "saved"
            or previous_ledger.get("pending_periods")
            or previous_ledger.get("failed_periods")
            or previous_ledger.get("checkpoint_error")
            or previous_ledger.get("persistence_error")
        ):
            ledger_requested = list(dict.fromkeys([
                *previous_ledger.get("requested_periods", []), *execution_periods,
            ]))
            # Reprocessamento só confirma novamente após escrita real. Rebuild
            # invalida a geração anterior inteira; suas pendências ficam visíveis.
            if modo != "rebuild":
                ledger_persisted = set(previous_ledger.get("persisted_periods", [])) - set(requested)
            ledger_extracted = set(previous_ledger.get("extracted_periods", [])) - set(requested)
            ledger_failures = dict(previous_ledger.get("failed_periods") or {})
        if not write_ledger(ongoing=True):
            return finish(record_ledger=False)

        if modo != "rebuild" and cache.existe_leitura():
            try:
                previous = cache.carregar_local()
            except Exception as exc:
                previous = CacheResult(False, str(exc))
            if not previous.sucesso or previous.dados is None:
                erros.append(f"Base existente ilegível: {previous.mensagem}")
                return finish(erros[-1])
            dados_existentes = previous.dados

        def persist():
            nonlocal dados_persistidos
            unsaved = [p for p in extracted if p not in persisted]
            if not unsaved:
                return True
            try:
                saved = self._salvar_parcial(
                    cache=cache, dados_novos=dados_extraidos,
                    dados_existentes=dados_existentes, modo=modo,
                    info=f"Atualização: {len(extracted)}/{len(requested)} períodos extraídos",
                )
                if not saved.sucesso:
                    raise RuntimeError(saved.mensagem)
            except Exception as exc:
                operation_errors["persistence_error"] = str(exc)
                for periodo in unsaved:
                    fail(periodo, f"Falha ao persistir: {exc}")
                return False
            persisted[:] = extracted
            dados_persistidos = saved.dados
            if not write_ledger(ongoing=True):
                return False
            if callback_checkpoint:
                try:
                    callback_checkpoint(metadata())
                except Exception as exc:
                    operation_errors["checkpoint_error"] = str(exc)
                    erros.append(f"Falha ao registrar checkpoint após persistência: {exc}")
                    return False
            if callback_salvamento:
                callback_salvamento(f"Salvos {len(persisted)} períodos")
            return True

        for i, periodo in enumerate(requested):
            if callback_progresso:
                callback_progresso(i, len(requested), periodo)
            try:
                result = cache.extrair_periodo(periodo, **kwargs)
                if not result.sucesso or result.dados is None:
                    raise ValueError(result.mensagem)
                valid, message = cache._validar_dados(result.dados)
                if not valid:
                    raise ValueError(message)
                period_column = "Período" if "Período" in result.dados.columns else "Periodo"
                references = {normalize_period_reference(value) for value in result.dados[period_column]}
                if references != {periodo}:
                    raise ValueError(f"Competência extraída diverge da solicitada: {sorted(references)}")
                dados_extraidos.append(result.dados)
                extracted.append(periodo)
            except Exception as exc:
                fail(periodo, str(exc))
            if len(extracted) - len(persisted) >= intervalo_salvamento and not persist():
                return finish()
            if i + 1 < len(requested):
                time.sleep(1.5)

        if not persist():
            return finish()
        return finish()

    def _salvar_parcial(
        self,
        cache: BaseCache,
        dados_novos: List[pd.DataFrame],
        dados_existentes: Optional[pd.DataFrame],
        modo: str,
        info: str
    ) -> CacheResult:
        """Salva dados parciais com merge se necessário."""
        if not dados_novos:
            return CacheResult(
                sucesso=False,
                mensagem="Sem dados para salvar",
                fonte="nenhum"
            )

        df_novos = pd.concat(dados_novos, ignore_index=True)

        # "overwrite" substitui os períodos extraídos, não o dataset inteiro. Antes,
        # uma extração de intervalo curto nesse modo descartava todo o histórico e o
        # metadata passava a listar só aqueles períodos — degradação silenciosa que
        # sumia com períodos das abas. Rebuild total só via modo explícito "rebuild".
        if modo != "rebuild" and dados_existentes is not None:
            from .diagnostics import normalize_period_reference

            # Encontrar coluna de período (verificar ambas as grafias)
            col_periodo_novos = "Período" if "Período" in df_novos.columns else "Periodo"
            col_periodo_exist = "Período" if "Período" in dados_existentes.columns else "Periodo"

            # Identificar períodos novos
            periodos_novos = set(df_novos[col_periodo_novos].map(normalize_period_reference))
            periodos_existentes = set(dados_existentes[col_periodo_exist].map(normalize_period_reference))

            # Remover períodos que serão substituídos
            df_manter = dados_existentes[
                ~dados_existentes[col_periodo_exist].map(normalize_period_reference).isin(periodos_novos)
            ]
            if col_periodo_exist != col_periodo_novos:
                df_manter = df_manter.rename(columns={col_periodo_exist: col_periodo_novos})

            # Concatenar
            df_final = pd.concat([df_manter, df_novos], ignore_index=True)
            logger.info(f"[CACHE] Merge: {len(periodos_existentes)} existentes, {len(periodos_novos)} novos/atualizados")
        else:
            df_final = df_novos

        if cache.config.nome == "carteira_instrumentos":
            from .institutions import canonicalize_institution_history

            df_final = canonicalize_institution_history(df_final, base_dir=self.base_dir)
        elif cache.config.nome in {"principal_individual", "dre_individual"}:
            from .diagnostics import count_placeholder_names
            from .institutions import stabilize_institution_names_by_code

            df_final = stabilize_institution_names_by_code(df_final)
            placeholders = count_placeholder_names(df_final)
            if placeholders:
                return CacheResult(
                    sucesso=False,
                    mensagem=f"Extração rejeitada: {placeholders} nome(s) de instituição não resolvido(s)",
                    fonte="nenhum",
                )

        # Salvar
        return cache.salvar_local(df_final, fonte="api", info_extra={"operacao": info})

    def get_dados_para_download(self, tipo: str) -> Optional[dict]:
        """Retorna dados do cache para download, com fallback (parquet/csv/pickle)."""
        cache = self._caches.get(tipo)
        if cache is None:
            return None

        if cache.arquivo_dados.exists():
            return {
                "data": cache.arquivo_dados.read_bytes(),
                "ext": ".parquet",
                "mime": "application/octet-stream",
                "label": "Parquet",
            }

        if cache.arquivo_dados_pickle.exists():
            return {
                "data": cache.arquivo_dados_pickle.read_bytes(),
                "ext": ".pkl",
                "mime": "application/octet-stream",
                "label": "Pickle",
            }

        resultado = cache.carregar()
        if not resultado.sucesso or resultado.dados is None:
            return None

        import io
        buffer = io.BytesIO()
        try:
            resultado.dados.to_parquet(buffer, index=False)
            return {
                "data": buffer.getvalue(),
                "ext": ".parquet",
                "mime": "application/octet-stream",
                "label": "Parquet",
            }
        except Exception:
            try:
                csv_bytes = resultado.dados.to_csv(index=False).encode("utf-8")
                return {
                    "data": csv_bytes,
                    "ext": ".csv",
                    "mime": "text/csv",
                    "label": "CSV",
                }
            except Exception:
                buffer = io.BytesIO()
                resultado.dados.to_pickle(buffer)
                return {
                    "data": buffer.getvalue(),
                    "ext": ".pkl",
                    "mime": "application/octet-stream",
                    "label": "Pickle",
                }

    def get_dados_para_download_csv(self, tipo: str) -> Optional[bytes]:
        """Retorna dados do cache em formato CSV para download."""
        cache = self._caches.get(tipo)
        if cache is None:
            return None

        resultado = cache.carregar_local()
        if not resultado.sucesso or resultado.dados is None:
            return None

        # Converter para CSV
        return resultado.dados.to_csv(index=False).encode('utf-8')


# =============================================================================
# FUNCOES DE CONVENIENCIA (NIVEL DE MODULO)
# =============================================================================

def criar_manager() -> CacheManager:
    """Cria e retorna uma instância do CacheManager."""
    return CacheManager()


def gerar_periodos_trimestrais(
    ano_inicial: int,
    mes_inicial: str,
    ano_final: int,
    mes_final: str
) -> List[str]:
    """Gera lista de períodos trimestrais.

    Args:
        ano_inicial: Ano inicial
        mes_inicial: Mês inicial ('03', '06', '09', '12')
        ano_final: Ano final
        mes_final: Mês final ('03', '06', '09', '12')

    Returns:
        Lista de períodos no formato YYYYMM
    """
    meses = ('03', '06', '09', '12')
    if mes_inicial not in meses or mes_final not in meses:
        raise ValueError("Meses trimestrais devem ser 03, 06, 09 ou 12")
    if not (1 <= ano_inicial <= 9999 and 1 <= ano_final <= 9999):
        raise ValueError("Ano fora do calendário suportado")
    inicio = ano_inicial * 4 + meses.index(mes_inicial)
    fim = ano_final * 4 + meses.index(mes_final)
    return [f"{indice // 4:04d}{meses[indice % 4]}" for indice in range(inicio, fim + 1)]
