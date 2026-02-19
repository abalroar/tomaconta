"""
metric_registry.py - Registro central de métricas e contratos de dados.

Objetivo:
- Definir um catálogo único com metadados de métricas (fórmula, unidade,
  escala interna, anualização e formatação sugerida para UI).
- Definir contratos mínimos de datasets curados para validação estrutural.

Observação:
- Este módulo é leve e não depende de pandas em runtime.
- Escala interna recomendada para percentuais: decimal (0-1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Literal, Protocol, runtime_checkable, Any


ScaleType = Literal["decimal_0_1", "percent_0_100", "currency_brl", "count", "ratio", "raw"]
DatasetLayer = Literal["raw", "staging", "curated"]


@runtime_checkable
class DataFrameLike(Protocol):
    """Contrato mínimo para validação estrutural sem acoplamento ao pandas."""

    @property
    def empty(self) -> bool:  # pragma: no cover - tipagem estrutural
        ...

    @property
    def columns(self) -> Any:  # pragma: no cover - tipagem estrutural
        ...


@dataclass(frozen=True)
class AnnualizationRule:
    """Regra de anualização informativa para uma métrica."""

    method: str
    formula: str
    notes: Optional[str] = None


@dataclass(frozen=True)
class MetricDefinition:
    """Definição canônica de uma métrica."""

    key: str
    display_name: str
    domain: str
    formula: str
    dependencies: List[str]
    unit: str
    internal_scale: ScaleType
    display_format: str
    annualization: Optional[AnnualizationRule] = None
    null_policy: str = "NaN quando denominador zero/ausente"
    source_tables: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class DatasetContract:
    """Contrato estrutural de dataset em uma camada do pipeline."""

    name: str
    layer: DatasetLayer
    required_columns: List[str]
    key_columns: List[str]
    period_column: str = "Período"
    institution_column: str = "Instituição"


METRIC_REGISTRY: Dict[str, MetricDefinition] = {
    "indice_basileia": MetricDefinition(
        key="indice_basileia",
        display_name="Índice de Basileia",
        domain="capital",
        formula="Patrimônio de Referência / RWA Total",
        dependencies=["Patrimônio de Referência", "RWA Total"],
        unit="%",
        internal_scale="decimal_0_1",
        display_format="pct",
        source_tables=["principal", "capital"],
    ),
    "roe_ac_ytd_an": MetricDefinition(
        key="roe_ac_ytd_an",
        display_name="ROE Ac. Anualizado (%)",
        domain="rentabilidade",
        formula="(LL_YTD × fator_anualização) / ((PL_t + PL_dez_ano_anterior)/2)",
        dependencies=["Lucro Líquido Acumulado YTD", "Patrimônio Líquido"],
        unit="%",
        internal_scale="decimal_0_1",
        display_format="pct",
        annualization=AnnualizationRule(
            method="period_factor",
            formula="Mar=4, Jun=2, Set=12/9, Dez=1",
            notes="Usa PL médio entre período t e dezembro do ano anterior.",
        ),
        source_tables=["principal"],
    ),
    "credito_pl": MetricDefinition(
        key="credito_pl",
        display_name="Crédito/PL (%)",
        domain="alavancagem",
        formula="Carteira de Crédito / Patrimônio Líquido",
        dependencies=["Carteira de Crédito", "Patrimônio Líquido"],
        unit="%",
        internal_scale="decimal_0_1",
        display_format="pct",
        source_tables=["principal"],
    ),
    "desp_pdd_resultado_intermediacao_fin_bruto": MetricDefinition(
        key="desp_pdd_resultado_intermediacao_fin_bruto",
        display_name="Desp PDD / Resultado Intermediação Fin. Bruto",
        domain="qualidade_carteira",
        formula="Desp. PDD / Resultado de Intermediação Financeira Bruto",
        dependencies=[
            "Resultado com Perda Esperada (f)",
            "Rendas de Aplicações Interfinanceiras de Liquidez (a)",
            "Rendas de Títulos e Valores Mobiliários (b)",
            "Rendas de Operações de Crédito (c)",
            "Rendas de Arrendamento Financeiro (d)",
            "Rendas de Outras Operações com Características de Concessão de Crédito (e)",
        ],
        unit="%",
        internal_scale="decimal_0_1",
        display_format="pct",
        source_tables=["dre", "derived_metrics"],
    ),
    "desp_captacao_captacao": MetricDefinition(
        key="desp_captacao_captacao",
        display_name="Desp Captação / Captação",
        domain="custo_funding",
        formula="Desp. Captação anualizada / Captações",
        dependencies=["Despesas de Captações (g)", "Captações"],
        unit="%",
        internal_scale="decimal_0_1",
        display_format="pct",
        annualization=AnnualizationRule(
            method="12_sobre_meses",
            formula="Desp_captacao_anualizada = Desp_captacao * (12 / meses_periodo)",
        ),
        source_tables=["dre", "principal", "derived_metrics"],
    ),
}



DERIVED_METRIC_KEYS: List[str] = [
    "desp_pdd_resultado_intermediacao_fin_bruto",
    "desp_captacao_captacao",
]


def get_derived_metric_labels() -> List[str]:
    """Retorna labels (display_name) das métricas derivadas suportadas."""
    labels: List[str] = []
    for key in DERIVED_METRIC_KEYS:
        m = METRIC_REGISTRY.get(key)
        if m is not None:
            labels.append(m.display_name)
    return labels


def get_derived_metric_format_map() -> Dict[str, str]:
    """Retorna map label -> formato para métricas derivadas."""
    out: Dict[str, str] = {}
    for key in DERIVED_METRIC_KEYS:
        m = METRIC_REGISTRY.get(key)
        if m is not None:
            out[m.display_name] = m.display_format
    return out


def get_derived_metric_formula_map() -> Dict[str, str]:
    """Retorna map label -> fórmula canônica para métricas derivadas."""
    out: Dict[str, str] = {}
    for key in DERIVED_METRIC_KEYS:
        m = METRIC_REGISTRY.get(key)
        if m is not None:
            out[m.display_name] = m.formula
    return out

DATASET_CONTRACTS: Dict[str, DatasetContract] = {
    "principal_curated": DatasetContract(
        name="principal_curated",
        layer="curated",
        required_columns=["Instituição", "Período"],
        key_columns=["Instituição", "Período"],
    ),
    "capital_curated": DatasetContract(
        name="capital_curated",
        layer="curated",
        required_columns=["Instituição", "Período"],
        key_columns=["Instituição", "Período"],
    ),
    "derived_metrics_long": DatasetContract(
        name="derived_metrics_long",
        layer="curated",
        required_columns=["Instituição", "Período", "Métrica", "Valor", "Unidade"],
        key_columns=["Instituição", "Período", "Métrica"],
    ),
}


def get_metric_registry() -> Dict[str, MetricDefinition]:
    """Retorna cópia do registro de métricas."""
    return dict(METRIC_REGISTRY)


def get_metric_definition(metric_key: str) -> Optional[MetricDefinition]:
    """Retorna definição de uma métrica por chave."""
    return METRIC_REGISTRY.get(metric_key)


def list_metrics_by_domain(domain: str) -> List[MetricDefinition]:
    """Lista métricas de um domínio."""
    return [m for m in METRIC_REGISTRY.values() if m.domain == domain]


def get_dataset_contracts() -> Dict[str, DatasetContract]:
    """Retorna cópia dos contratos de datasets."""
    return dict(DATASET_CONTRACTS)


def validate_dataset_contract(df: Optional[DataFrameLike], contract: DatasetContract) -> List[str]:
    """Valida estrutura de dataset (colunas/chaves) contra um contrato."""
    errors: List[str] = []

    if df is None:
        return [f"{contract.name}: dataframe ausente"]

    if not hasattr(df, "empty") or not hasattr(df, "columns"):
        return [f"{contract.name}: objeto sem interface de dataframe (empty/columns)"]

    if bool(df.empty):
        return [f"{contract.name}: dataframe vazio"]

    cols = set(df.columns)
    for col in contract.required_columns:
        if col not in cols:
            errors.append(f"{contract.name}: coluna obrigatória ausente: {col}")

    for col in contract.key_columns:
        if col not in cols:
            errors.append(f"{contract.name}: coluna de chave ausente: {col}")

    return errors


def validate_dataframe_by_contract_name(df: Optional[DataFrameLike], contract_name: str) -> List[str]:
    """Valida dataset usando nome de contrato registrado."""
    contract = DATASET_CONTRACTS.get(contract_name)
    if contract is None:
        return [f"Contrato desconhecido: {contract_name}"]
    return validate_dataset_contract(df, contract)
