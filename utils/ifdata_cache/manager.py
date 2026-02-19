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
from datetime import datetime
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
    "derived_metrics": {
        "nome_exibicao": "Métricas Derivadas",
        "descricao": "Indicadores derivados (DRE + Resumo)",
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
        from .principal import PrincipalCache
        from .capital import CapitalCache
        from .relatorios_completos import (
            AtivoCache,
            PassivoCache,
            DRECache,
            CarteiraPFCache,
            CarteiraPJCache,
            CarteiraInstrumentosCache,
        )
        from .taxas_juros import TaxasJurosCache
        from .derived_metrics import DerivedMetricsCache
        from .balancetes import BalancetesCache
        from .bloprudencial_cache import BloprudencialCache

        # Caches principais (variáveis selecionadas)
        self.registrar(PrincipalCache(self.base_dir))
        self.registrar(CapitalCache(self.base_dir))

        # Caches de relatórios completos (todas as variáveis)
        self.registrar(AtivoCache(self.base_dir))
        self.registrar(PassivoCache(self.base_dir))
        self.registrar(DRECache(self.base_dir))
        self.registrar(CarteiraPFCache(self.base_dir))
        self.registrar(CarteiraPJCache(self.base_dir))
        self.registrar(CarteiraInstrumentosCache(self.base_dir))

        # Cache de Taxas de Juros (API BCB diferente)
        self.registrar(TaxasJurosCache(self.base_dir))
        # Cache de métricas derivadas (DRE + Resumo)
        self.registrar(DerivedMetricsCache(self.base_dir))
        # Cache de balancetes COSIF (API REST BCB)
        self.registrar(BalancetesCache(self.base_dir))
        # Cache BLOPRUDENCIAL mensal (arquivo estático BCB)
        self.registrar(BloprudencialCache(self.base_dir))

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
        **kwargs
    ) -> CacheResult:
        """Extrai dados de múltiplos períodos com salvamento parcial.

        Args:
            tipo: Nome do tipo de cache
            periodos: Lista de períodos "YYYYMM"
            modo: "incremental" (merge com existente) ou "overwrite" (substituir)
            intervalo_salvamento: Salvar a cada N períodos (default: 4)
            callback_progresso: Função(i, total, periodo) chamada a cada período
            callback_salvamento: Função(info) chamada a cada salvamento
            dict_aliases: Dicionário de aliases para instituições
            **kwargs: Argumentos extras para extração

        Returns:
            CacheResult com todos os dados
        """
        cache = self._caches.get(tipo)
        if cache is None:
            return CacheResult(
                sucesso=False,
                mensagem=f"Tipo de cache desconhecido: {tipo}. Disponíveis: {self.listar_caches()}",
                fonte="nenhum"
            )

        logger.info(f"[CACHE:{tipo.upper()}] Iniciando extração de {len(periodos)} períodos, modo={modo}")

        # Carregar dados existentes se modo incremental
        dados_existentes = None
        if modo == "incremental" and cache.existe():
            resultado_existente = cache.carregar_local()
            if resultado_existente.sucesso:
                dados_existentes = resultado_existente.dados
                logger.info(f"[CACHE:{tipo.upper()}] Carregados {len(dados_existentes)} registros existentes")

        dados_extraidos = []
        erros = []
        periodos_desde_save = 0

        for i, periodo in enumerate(periodos):
            # Callback de progresso
            if callback_progresso:
                callback_progresso(i, len(periodos), periodo)

            try:
                # Extrair período
                resultado = cache.extrair_periodo(periodo, dict_aliases=dict_aliases, **kwargs)

                if resultado.sucesso and resultado.dados is not None:
                    dados_extraidos.append(resultado.dados)
                    periodos_desde_save += 1

                    # Salvamento parcial
                    if periodos_desde_save >= intervalo_salvamento:
                        self._salvar_parcial(
                            cache=cache,
                            dados_novos=dados_extraidos,
                            dados_existentes=dados_existentes,
                            modo=modo,
                            info=f"Salvamento parcial até {periodo[4:6]}/{periodo[:4]}"
                        )
                        periodos_desde_save = 0

                        if callback_salvamento:
                            callback_salvamento(f"Salvos {len(dados_extraidos)} períodos")
                else:
                    erros.append(f"{periodo}: {resultado.mensagem}")
                    logger.warning(f"[CACHE:{tipo.upper()}] Falha em {periodo}: {resultado.mensagem}")
                    if callback_erro:
                        callback_erro(periodo, resultado.mensagem)

                # Rate limiting
                time.sleep(1.5)

            except Exception as e:
                erros.append(f"{periodo}: {str(e)}")
                logger.error(f"[CACHE:{tipo.upper()}] Erro em {periodo}: {e}")
                if callback_erro:
                    callback_erro(periodo, str(e))

                # Salvamento de emergência
                if dados_extraidos:
                    try:
                        self._salvar_parcial(
                            cache=cache,
                            dados_novos=dados_extraidos,
                            dados_existentes=dados_existentes,
                            modo=modo,
                            info=f"Salvamento emergência após erro em {periodo}"
                        )
                        logger.info(f"[CACHE:{tipo.upper()}] Salvamento de emergência realizado")
                    except Exception as save_error:
                        erros.append(f"Erro no salvamento de emergência: {save_error}")

        # Resultado final
        if not dados_extraidos:
            return CacheResult(
                sucesso=False,
                mensagem=f"Nenhum período extraído com sucesso. Erros: {'; '.join(erros[:3])}",
                metadata={"erros": erros},
                fonte="nenhum"
            )

        # Concatenar todos os dados extraídos
        df_extraido = pd.concat(dados_extraidos, ignore_index=True)

        # Salvamento final
        resultado_save = self._salvar_parcial(
            cache=cache,
            dados_novos=dados_extraidos,
            dados_existentes=dados_existentes,
            modo=modo,
            info=f"Salvamento final: {periodos[0][4:6]}/{periodos[0][:4]} até {periodos[-1][4:6]}/{periodos[-1][:4]}"
        )

        if callback_salvamento:
            callback_salvamento(f"Salvos {len(dados_extraidos)} períodos (final)")

        # Calcular total de registros
        df_final = resultado_save.dados if resultado_save.dados is not None else df_extraido

        logger.info(f"[CACHE:{tipo.upper()}] Extração concluída: {len(dados_extraidos)}/{len(periodos)} períodos, {len(df_final)} registros")

        return CacheResult(
            sucesso=True,
            mensagem=f"Extraídos {len(dados_extraidos)}/{len(periodos)} períodos, {len(df_final)} registros",
            dados=df_final,
            metadata={
                "periodos_extraidos": len(dados_extraidos),
                "periodos_total": len(periodos),
                "total_registros": len(df_final),
                "erros": erros,
                "modo": modo
            },
            fonte="api"
        )

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

        if modo == "incremental" and dados_existentes is not None:
            # Encontrar coluna de período (verificar ambas as grafias)
            col_periodo_novos = "Período" if "Período" in df_novos.columns else "Periodo"
            col_periodo_exist = "Período" if "Período" in dados_existentes.columns else "Periodo"

            # Identificar períodos novos
            periodos_novos = set(df_novos[col_periodo_novos].unique())
            periodos_existentes = set(dados_existentes[col_periodo_exist].unique())

            # Remover períodos que serão substituídos
            df_manter = dados_existentes[~dados_existentes[col_periodo_exist].isin(periodos_novos)]

            # Concatenar
            df_final = pd.concat([df_manter, df_novos], ignore_index=True)
            logger.info(f"[CACHE] Merge: {len(periodos_existentes)} existentes, {len(periodos_novos)} novos/atualizados")
        else:
            df_final = df_novos

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
    periodos = []
    ano_atual = ano_inicial
    mes_atual = mes_inicial

    while True:
        periodo = f"{ano_atual}{mes_atual}"
        periodos.append(periodo)

        if ano_atual == ano_final and mes_atual == mes_final:
            break

        if mes_atual == '03':
            mes_atual = '06'
        elif mes_atual == '06':
            mes_atual = '09'
        elif mes_atual == '09':
            mes_atual = '12'
        elif mes_atual == '12':
            mes_atual = '03'
            ano_atual += 1

    return periodos
