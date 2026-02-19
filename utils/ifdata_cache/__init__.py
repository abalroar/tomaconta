"""
ifdata_cache - Sistema unificado de cache para dados do IFData/BCB

Arquitetura extensivel que suporta multiplos tipos de cache:
- principal: Dados gerais das instituicoes (Relatório 1) - variáveis selecionadas
- capital: Dados de capital regulatorio (Relatório 5) - variáveis selecionadas
- ativo: Composição do Ativo (Relatório 2) - todas as variáveis
- passivo: Composição do Passivo (Relatório 3) - todas as variáveis
- dre: Demonstração de Resultado (Relatório 4) - todas as variáveis
- carteira_pf: Carteira de Crédito PF (Relatório 11) - todas as variáveis
- carteira_pj: Carteira de Crédito PJ (Relatório 13) - todas as variáveis
- carteira_instrumentos: Carteira - Instrumentos 4.966 (Relatório 16) - todas as variáveis

Uso basico:
    from utils.ifdata_cache import CacheManager

    # Obter gerenciador
    manager = CacheManager()

    # Carregar dados de capital
    resultado = manager.carregar("capital")
    if resultado.sucesso:
        df = resultado.dados

    # Carregar dados principais
    resultado = manager.carregar("principal")

    # Carregar novos relatórios (todas as variáveis)
    resultado = manager.carregar("ativo")
    resultado = manager.carregar("dre")
    resultado = manager.carregar("carteira_pf")

    # Extrair com salvamento parcial
    resultado = manager.extrair_periodos_com_salvamento(
        tipo="ativo",
        periodos=["202303", "202306", "202309", "202312"],
        modo="incremental",  # ou "overwrite"
        intervalo_salvamento=4,
    )

    # Listar caches disponiveis
    print(manager.listar_caches())
    print(manager.get_caches_info())
"""

from .base import (
    CacheConfig,
    CacheResult,
    BaseCache,
)

from .manager import (
    CacheManager,
    CACHES_INFO,
    criar_manager,
    gerar_periodos_trimestrais as gerar_periodos_trimestrais_cache,
)

from .principal import PrincipalCache
from .capital import CapitalCache, CAMPOS_CAPITAL
from .bloprudencial_cache import BloprudencialCache

# Novos caches de relatórios completos
from .relatorios_completos import (
    AtivoCache,
    PassivoCache,
    DRECache,
    CarteiraPFCache,
    CarteiraPJCache,
    CarteiraInstrumentosCache,
    listar_relatorios_completos,
)

# Cache de Taxas de Juros
from .taxas_juros import (
    TaxasJurosCache,
    buscar_modalidades_disponiveis as buscar_modalidades_taxas_juros,
    buscar_instituicoes_disponiveis as buscar_instituicoes_taxas_juros,
    formatar_nome_modalidade,
    MODALIDADES_CONHECIDAS,
)

from .bloprudencial import (
    build_bloprudencial_url,
    download_bloprudencial_zip,
    extract_bloprudencial_csv,
    inspect_bloprudencial_csv,
    load_bloprudencial_df,
    load_bloprudencial_df_cached,
    preload_bloprudencial,
)

from .metric_registry import (
    MetricDefinition,
    DatasetContract,
    AnnualizationRule,
    METRIC_REGISTRY,
    DATASET_CONTRACTS,
    get_metric_registry,
    get_metric_definition,
    list_metrics_by_domain,
    get_dataset_contracts,
    validate_dataset_contract,
    validate_dataframe_by_contract_name,
    DERIVED_METRIC_KEYS,
    get_derived_metric_labels,
    get_derived_metric_format_map,
    get_derived_metric_formula_map,
)

from .derived_metrics import (
    DerivedMetricsCache,
    DERIVED_METRICS,
    DERIVED_METRICS_FORMAT,
    DERIVED_METRICS_FORMULAS,
    build_derived_metrics,
    load_derived_metrics_slice,
)

# Extrator autônomo (novo sistema)
from .extractor import (
    extrair_cadastro,
    extrair_valores,
    extrair_periodo,
    extrair_resumo,
    extrair_capital,
    extrair_relatorio_completo,
    extrair_multiplos_periodos,
    periodo_api_para_exibicao,
    periodo_exibicao_para_api,
    gerar_periodos,
    VARIAVEIS_RESUMO_API as VARIAVEIS_RESUMO,
    CAMPOS_CAPITAL as VARIAVEIS_CAPITAL,
)

# Compatibilidade com unified_extractor (mantido por retrocompatibilidade)
def processar_periodo(*args, **kwargs):
    from .unified_extractor import processar_periodo as _fn

    return _fn(*args, **kwargs)


def processar_multiplos_periodos(*args, **kwargs):
    from .unified_extractor import processar_multiplos_periodos as _fn

    return _fn(*args, **kwargs)


def get_info_relatorio(*args, **kwargs):
    from .unified_extractor import get_info_relatorio as _fn

    return _fn(*args, **kwargs)


def listar_relatorios_disponiveis(*args, **kwargs):
    from .unified_extractor import listar_relatorios_disponiveis as _fn

    return _fn(*args, **kwargs)


from .unified_extractor import RELATORIOS_INFO

# Funcoes de compatibilidade com sistema antigo
from .compat import (
    # Cache Principal
    baixar_cache_inicial,
    carregar_cache,
    salvar_cache,
    get_cache_info,
    # Cache Capital
    baixar_cache_capital_inicial,
    carregar_cache_capital,
    salvar_cache_capital,
    gerar_periodos_capital,
    processar_todos_periodos_capital,
    get_capital_cache_info,
    get_campos_capital_info,
    ler_info_cache_capital,
)

# Instancia global para uso simplificado
_manager = None


def get_manager() -> CacheManager:
    """Retorna instancia global do gerenciador de cache."""
    global _manager
    if _manager is None:
        _manager = CacheManager()
    return _manager


# Funcoes de conveniencia
def carregar(tipo: str) -> CacheResult:
    """Carrega cache do tipo especificado."""
    return get_manager().carregar(tipo)


def salvar(tipo: str, dados, **kwargs) -> CacheResult:
    """Salva dados no cache do tipo especificado."""
    return get_manager().salvar(tipo, dados, **kwargs)


def info(tipo: str = None) -> dict:
    """Retorna informacoes do cache (ou todos se tipo=None)."""
    return get_manager().info(tipo)


def limpar(tipo: str = None) -> CacheResult:
    """Limpa cache do tipo especificado (ou todos se tipo=None)."""
    return get_manager().limpar(tipo)


def gerar_periodos_trimestrais(*args, **kwargs):
    """Compatibilidade: usa gerador de períodos trimestrais do cache."""
    return gerar_periodos_trimestrais_cache(*args, **kwargs)


__all__ = [
    # Classes principais
    "CacheConfig",
    "CacheResult",
    "BaseCache",
    "CacheManager",
    "CACHES_INFO",
    # Implementacoes - principais
    "PrincipalCache",
    "CapitalCache",
    "CAMPOS_CAPITAL",
    "BloprudencialCache",
    # Implementacoes - relatórios completos
    "AtivoCache",
    "PassivoCache",
    "DRECache",
    "CarteiraPFCache",
    "CarteiraPJCache",
    "CarteiraInstrumentosCache",
    "listar_relatorios_completos",
    # Implementacoes - Taxas de Juros
    "TaxasJurosCache",
    "buscar_modalidades_taxas_juros",
    "buscar_instituicoes_taxas_juros",
    "formatar_nome_modalidade",
    "MODALIDADES_CONHECIDAS",
    # Implementacoes - BLOPRUDENCIAL
    "build_bloprudencial_url",
    "download_bloprudencial_zip",
    "extract_bloprudencial_csv",
    "inspect_bloprudencial_csv",
    "load_bloprudencial_df",
    "load_bloprudencial_df_cached",
    "preload_bloprudencial",
    # Derived metrics
    # Metric registry / contracts
    "MetricDefinition",
    "DatasetContract",
    "AnnualizationRule",
    "METRIC_REGISTRY",
    "DATASET_CONTRACTS",
    "get_metric_registry",
    "get_metric_definition",
    "list_metrics_by_domain",
    "get_dataset_contracts",
    "validate_dataset_contract",
    "validate_dataframe_by_contract_name",
    "DERIVED_METRIC_KEYS",
    "get_derived_metric_labels",
    "get_derived_metric_format_map",
    "get_derived_metric_formula_map",
    "DerivedMetricsCache",
    "DERIVED_METRICS",
    "DERIVED_METRICS_FORMAT",
    "DERIVED_METRICS_FORMULAS",
    "build_derived_metrics",
    "load_derived_metrics_slice",
    # Extrator autônomo
    "extrair_cadastro",
    "extrair_valores",
    "extrair_periodo",
    "extrair_resumo",
    "extrair_capital",
    "extrair_relatorio_completo",
    "extrair_multiplos_periodos",
    "periodo_api_para_exibicao",
    "periodo_exibicao_para_api",
    "gerar_periodos",
    "VARIAVEIS_RESUMO",
    "VARIAVEIS_CAPITAL",
    # Extrator unificado (retrocompatibilidade)
    "processar_periodo",
    "processar_multiplos_periodos",
    "gerar_periodos_trimestrais",
    "get_info_relatorio",
    "listar_relatorios_disponiveis",
    "RELATORIOS_INFO",
    # Funcoes de conveniencia
    "get_manager",
    "criar_manager",
    "carregar",
    "salvar",
    "info",
    "limpar",
    "gerar_periodos_trimestrais",
    "gerar_periodos",
    # Compatibilidade - Principal
    "baixar_cache_inicial",
    "carregar_cache",
    "salvar_cache",
    "get_cache_info",
    # Compatibilidade - Capital
    "baixar_cache_capital_inicial",
    "carregar_cache_capital",
    "salvar_cache_capital",
    "gerar_periodos_capital",
    "processar_todos_periodos_capital",
    "get_capital_cache_info",
    "get_campos_capital_info",
    "ler_info_cache_capital",
]
