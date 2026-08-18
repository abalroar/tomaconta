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
    short_definition: str = ""
    long_definition: str = ""
    ifdata_fields: List[str] = field(default_factory=list)
    cosif_accounts: List[str] = field(default_factory=list)
    source_label: str = ""
    observations: str = ""
    tabs: List[str] = field(default_factory=list)
    interpretation: str = ""
    limitation: str = ""
    periodicity: str = "Trimestral"


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
        short_definition=(
            "Capital regulatório total sobre RWA. O app usa componentes do Rel. 5 quando completos "
            "e mantém o índice publicado como fallback identificado."
        ),
        long_definition=(
            "Índice de adequação de capital do conglomerado prudencial. A camada curada reconstrói "
            "(Capital Principal + Capital Complementar + Capital Nível II) ÷ RWA Total quando os "
            "componentes estão completos; na indisponibilidade, pode usar o índice publicado no Rel. 5."
        ),
        ifdata_fields=[
            "Capital Principal",
            "Capital Complementar",
            "Capital Nível II",
            "RWA Total",
            "Índice de Basileia publicado",
        ],
        source_label="BCB IFData Rel.5, visão prudencial",
        observations="A memória de cálculo deve indicar se o valor foi reconstruído ou publicado.",
        tabs=["Snapshot", "Peers (Tabela)", "Evolução", "Rankings", "Scatter Plot", "Glossário"],
        interpretation="Capital regulatório total disponível para absorver riscos ponderados.",
        limitation=(
            "Diferença material entre o índice reconstruído e o publicado bloqueia a leitura até "
            "reconciliação de escala, componentes e perímetro."
        ),
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
        short_definition="Lucro líquido YTD anualizado ÷ média entre o PL atual e o PL de dezembro anterior.",
        long_definition=(
            "ROE acumulado anualizado: (Lucro Líquido YTD × fator do período) ÷ "
            "((PL do período + PL de dezembro do ano anterior) ÷ 2). Fatores: Mar=4, Jun=2, "
            "Set=12/9 e Dez=1."
        ),
        ifdata_fields=["Lucro Líquido Acumulado YTD", "Patrimônio Líquido"],
        source_label="BCB IFData Rel.1, visão prudencial",
        tabs=["Snapshot", "Peers (Tabela)", "Evolução", "Rankings", "Scatter Plot", "Glossário"],
        interpretation="Rentabilidade anualizada do patrimônio com base no resultado acumulado.",
        limitation="Sensível à sazonalidade, ao PL médio aproximado e a eventos patrimoniais pontuais.",
        periodicity="Trimestral/YTD anualizado",
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
    "custo_credito": MetricDefinition(
        key="custo_credito",
        display_name="Custo de Crédito (%)",
        domain="qualidade_carteira",
        formula=(
            "|Resultado com Perda Esperada de Operações de Crédito (f3)| YTD anualizado "
            "/ Carteira de Crédito*"
        ),
        dependencies=[
            "Resultado com Perda Esperada de Operações de Crédito (f3)",
            "Carteira de Crédito*",
        ],
        unit="%",
        internal_scale="decimal_0_1",
        display_format="pct",
        annualization=AnnualizationRule(
            method="period_factor",
            formula="Mar=4, Jun=2, Set=12/9, Dez=1",
            notes=(
                "Aplicado sobre o YTD reconstruído do Relatório 4, que publica Set como "
                "Jul-Set e Dez como Jul-Dez (soma-se Jun). Sem Jun disponível o resultado é NaN."
            ),
        ),
        null_policy=(
            "NaN quando a carteira for zero/ausente, quando f3 não existir (layout anterior a "
            "2025) ou quando o YTD não puder ser reconstruído por ausência de junho"
        ),
        source_tables=["dre", "ativo", "principal", "derived_metrics"],
        short_definition=(
            "Magnitude do Resultado com Perda Esperada de Operações de Crédito (f3) YTD anualizado "
            "÷ Carteira de Crédito*."
        ),
        long_definition=(
            "Numerador: magnitude de f3 no Rel. 4, com YTD reconstruído e anualização "
            "Mar×4, Jun×2, Set×12/9 e Dez×1. Denominador: Carteira de Crédito* do Rel. 2. "
            "Setembro e dezembro exigem junho. TVM, aplicações interfinanceiras, arrendamento e "
            "outras rendas não entram no numerador."
        ),
        ifdata_fields=[
            "Rel.4: Resultado com Perda Esperada de Operações de Crédito (f3)",
            "Rel.2 2025+: Valor Contábil Bruto (e1, f1, g1, h1)",
            "Rel.2 fallback: agregados líquidos (e, f, g, h)",
        ],
        source_label="BCB IFData Rel.4 (DRE) + Rel.2 (Ativo), visão prudencial",
        observations=(
            "Sem de-para COSIF de f3 no app; reversões e recuperações seguem o agregado IFData e "
            "não são desagregadas localmente."
        ),
        tabs=["Rankings", "Peers (Tabela)", "Scatter Plot", "Glossário"],
        interpretation="Fluxo anualizado de perda esperada de crédito em relação ao estoque de crédito.",
        limitation=(
            "Série inicia em Mar/25. Carteira zero/ausente, f3 ausente ou YTD não reconstruível "
            "resultam em N/D. A Carteira* possui quebra metodológica em 2025."
        ),
        periodicity="Trimestral/YTD anualizado",
    ),
    "custo_credito_receita": MetricDefinition(
        key="custo_credito_receita",
        display_name="Custo de Crédito / Receita de Crédito (%)",
        domain="qualidade_carteira",
        formula=(
            "|Resultado com Perda Esperada de Operações de Crédito (f3)| YTD "
            "/ Rendas de Operações de Crédito (c) YTD"
        ),
        dependencies=[
            "Resultado com Perda Esperada de Operações de Crédito (f3)",
            "Rendas de Operações de Crédito (c)",
        ],
        unit="%",
        internal_scale="decimal_0_1",
        display_format="pct",
        annualization=AnnualizationRule(
            method="nao_aplicavel",
            formula="sem fator",
            notes=(
                "Numerador e denominador são fluxos do mesmo período, então qualquer fator de "
                "anualização se cancela na razão. O YTD reconstruído do Relatório 4 continua "
                "obrigatório por comparabilidade (Set = Jul-Set + Jun; Dez = Jul-Dez + Jun); "
                "sem junho publicado o resultado é NaN."
            ),
        ),
        null_policy=(
            "NaN quando a receita de crédito for zero, negativa ou ausente, quando f3 não existir "
            "(layout anterior a 2025) ou quando o YTD não puder ser reconstruído por ausência de junho"
        ),
        source_tables=["dre", "derived_metrics"],
        short_definition=(
            "Magnitude de f3 YTD ÷ Rendas de Operações de Crédito (c) YTD, ambos do Rel. 4."
        ),
        long_definition=(
            "Razão entre a magnitude do Resultado com Perda Esperada de Operações de Crédito (f3) "
            "e Rendas de Operações de Crédito (c), ambos em YTD reconstruído. Não há anualização, "
            "pois numerador e denominador são fluxos da mesma janela."
        ),
        ifdata_fields=[
            "Rel.4: Resultado com Perda Esperada de Operações de Crédito (f3)",
            "Rel.4: Rendas de Operações de Crédito (c)",
        ],
        source_label="BCB IFData Rel.4 (DRE), visão prudencial",
        observations=(
            "O denominador não inclui rendas de arrendamento (d), outras concessões de crédito (e) "
            "nem recuperação de créditos em campo separado."
        ),
        tabs=["Rankings", "Peers (Tabela)", "Scatter Plot", "Glossário"],
        interpretation="Parcela da receita contábil de operações de crédito consumida por f3.",
        limitation=(
            "Receita zero, negativa ou ausente, f3 ausente ou YTD sem junho resultam em N/D. "
            "Série inicia em Mar/25."
        ),
        periodicity="Trimestral/YTD",
    ),
    "ativos_problematicos_carteira_total": MetricDefinition(
        key="ativos_problematicos_carteira_total",
        display_name="Ativos Problemáticos / Carteira Total",
        domain="qualidade_carteira",
        formula="Ativos problemáticos / Total Geral (IFData Relatório 16)",
        dependencies=["Ativos problemáticos", "Total Geral"],
        unit="%",
        internal_scale="decimal_0_1",
        display_format="pct",
        null_policy=(
            "NaN quando a carteira total do Relatório 16 for zero/ausente ou quando a instituição "
            "não publicar o relatório no período"
        ),
        source_tables=["carteira_instrumentos", "derived_metrics", "critical_screens"],
        short_definition="Ativos problemáticos ÷ Total Geral, ambos no IFData Rel. 16.",
        long_definition=(
            "Participação dos ativos problemáticos na carteira de crédito ativa do Rel. 16. "
            "O conceito inclui atraso relevante acima de 90 dias e liquidação integral improvável "
            "sem garantia, conforme o campo prudencial agregado."
        ),
        ifdata_fields=["Rel.16: Ativos problemáticos", "Rel.16: Total Geral"],
        source_label="BCB IFData Rel.16, Res. 4.966, visão prudencial",
        observations="Numerador e denominador usam o mesmo relatório e o mesmo perímetro.",
        tabs=["Rankings", "Peers (Tabela)", "Scatter Plot", "Glossário"],
        interpretation="Peso da carteira classificada como problemática no Rel. 16.",
        limitation=(
            "Não equivale ao Estágio 3 do Cadoc 4060. Instituição sem Rel. 16 ou denominador válido "
            "permanece N/D."
        ),
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
    "carteira_credito": MetricDefinition(
        key="carteira_credito",
        display_name="Carteira de Crédito*",
        domain="qualidade_carteira",
        formula="Até 2024: d1+e1+f; 2025+: e1+f1+g1+h1; fallback líquido e+f+g+h",
        dependencies=["Relatório 2"],
        unit="R$",
        internal_scale="currency_brl",
        display_format="currency",
        null_policy="N/D quando algum componente obrigatório da regra aplicável estiver ausente",
        source_tables=["ativo", "principal", "critical_screens"],
        short_definition=(
            "Estoque de crédito do Rel. 2 com regra histórica explícita; o asterisco sinaliza quebra "
            "metodológica e possível fallback líquido."
        ),
        long_definition=(
            "Até 2024: Operações de Crédito brutas (d1) + Arrendamento a Receber bruto (e1) + "
            "Outros Créditos líquidos de provisão (f). Em 2025+: Valor Contábil Bruto "
            "e1+f1+g1+h1. Na ausência da composição bruta completa, o fallback e+f+g+h é líquido e sinalizado."
        ),
        ifdata_fields=[
            "Rel.2 legado: d1, e1, f",
            "Rel.2 2025+: e1, f1, g1, h1",
            "Rel.2 fallback: e, f, g, h",
        ],
        source_label="BCB IFData Rel.2 (Ativo), visão prudencial",
        observations="TVM, fianças, avais e garantias prestadas não integram a fórmula.",
        tabs=["Snapshot", "Peers (Tabela)", "Evolução", "Rankings", "Scatter Plot", "Glossário"],
        interpretation="Estoque contábil de operações de crédito e categorias correlatas cobertas pela regra local.",
        limitation="A série atravessa uma quebra em 2025; o trecho legado e o fallback não são integralmente brutos.",
    ),
    "receita_credito": MetricDefinition(
        key="receita_credito",
        display_name="Receita de Crédito",
        domain="rentabilidade",
        formula="Rendas de Operações de Crédito (c) YTD",
        dependencies=["Rendas de Operações de Crédito (c)"],
        unit="R$",
        internal_scale="currency_brl",
        display_format="currency",
        source_tables=["dre", "critical_screens"],
        short_definition="Rendas de Operações de Crédito (c), no Rel. 4, em YTD reconstruído.",
        long_definition=(
            "Fluxo contábil da linha Rendas de Operações de Crédito (c). Setembro e dezembro somam "
            "o valor de junho ao fluxo do segundo semestre para formar o YTD."
        ),
        ifdata_fields=["Rel.4: Rendas de Operações de Crédito (c)"],
        source_label="BCB IFData Rel.4 (DRE), visão prudencial",
        observations=(
            "Não inclui rendas de arrendamento (d), outras concessões (e) nem recuperação em campo separado."
        ),
        tabs=["Memória de cálculo de Rankings", "Memória de cálculo de Peers", "Glossário"],
        interpretation="Receita contábil acumulada das operações de crédito cobertas pela linha c.",
        limitation="Não representa toda receita associada a produtos de crédito do conglomerado.",
        periodicity="Trimestral/YTD",
    ),
    "inadimplencia": MetricDefinition(
        key="inadimplencia",
        display_name="Inadimplência",
        domain="qualidade_carteira",
        formula="Linha Inadimplência do IFData Rel.16",
        dependencies=["Inadimplência"],
        unit="R$",
        internal_scale="currency_brl",
        display_format="currency",
        source_tables=["carteira_instrumentos", "critical_screens"],
        short_definition="Operações com alguma parcela vencida há mais de 90 dias, pelo conceito de arrasto do Rel. 16.",
        long_definition=(
            "Estoque de operações a vencer e vencidas que possuem alguma parcela vencida há mais de "
            "90 dias, conforme o conceito de arrasto publicado no Rel. 16."
        ),
        ifdata_fields=["Rel.16: Inadimplência"],
        source_label="BCB IFData Rel.16, Res. 4.966, visão prudencial",
        observations="Conceito distinto de estágio 3, NPL amplo e default regulatório.",
        tabs=["Peers (Tabela)", "Carteira 4.966", "Glossário"],
        interpretation="Estoque de crédito atingido pelo critério de atraso superior a 90 dias por arrasto.",
        limitation="Série disponível conforme publicação do Rel. 16 por instituição e período.",
    ),
    "inadimplencia_carteira_total": MetricDefinition(
        key="inadimplencia_carteira_total",
        display_name="Inadimplência / Carteira Total",
        domain="qualidade_carteira",
        formula="Inadimplência / Total Geral (IFData Relatório 16)",
        dependencies=["Inadimplência", "Total Geral"],
        unit="%",
        internal_scale="decimal_0_1",
        display_format="pct",
        null_policy="N/D quando o Rel. 16 ou o Total Geral estiver ausente/zerado",
        source_tables=["carteira_instrumentos", "critical_screens"],
        short_definition="Inadimplência por arrasto >90 dias ÷ Total Geral, ambos no Rel. 16.",
        long_definition=(
            "Participação das operações com alguma parcela vencida há mais de 90 dias sobre o "
            "Total Geral da carteira de crédito ativa do mesmo Rel. 16."
        ),
        ifdata_fields=["Rel.16: Inadimplência", "Rel.16: Total Geral"],
        source_label="BCB IFData Rel.16, Res. 4.966, visão prudencial",
        observations="Numerador e denominador usam o mesmo relatório e perímetro.",
        tabs=["Peers (Tabela)", "Glossário"],
        interpretation="Percentual da carteira total atingido pelo critério de atraso >90 dias por arrasto.",
        limitation="Instituição sem Rel. 16 ou denominador válido permanece N/D.",
    ),
    "roe_trim_an": MetricDefinition(
        key="roe_trim_an",
        display_name="ROE Trim. Anualizado (%)",
        domain="rentabilidade",
        formula="(Lucro Líquido Trimestral × 4) / ((PL_t + PL_dez_ano_anterior)/2)",
        dependencies=["Lucro Líquido Trimestral", "Patrimônio Líquido"],
        unit="%",
        internal_scale="decimal_0_1",
        display_format="pct",
        source_tables=["principal", "critical_screens"],
        short_definition="Lucro líquido do trimestre ×4 ÷ média entre o PL atual e o PL de dezembro anterior.",
        long_definition=(
            "ROE do trimestre isolado anualizado: (Lucro Líquido Trimestral ×4) ÷ "
            "((PL do período + PL de dezembro do ano anterior) ÷2)."
        ),
        ifdata_fields=["Lucro Líquido Trimestral", "Patrimônio Líquido"],
        source_label="BCB IFData Rel.1, visão prudencial",
        tabs=["Snapshot", "Rankings", "Scatter Plot", "Glossário"],
        interpretation="Rentabilidade anualizada do trimestre corrente sobre PL médio aproximado.",
        limitation="Métrica volátil e sensível a itens não recorrentes e ao PL médio aproximado.",
    ),
}



DERIVED_METRIC_KEYS: List[str] = [
    "desp_pdd_resultado_intermediacao_fin_bruto",
    "desp_captacao_captacao",
    "custo_credito",
    "custo_credito_receita",
    "ativos_problematicos_carteira_total",
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


_METRIC_LABEL_ALIASES: Dict[str, str] = {
    "Índice de Basileia Total (%)": "indice_basileia",
    "Índice de Basileia": "indice_basileia",
    "ROE Acumulado YTD (%)": "roe_ac_ytd_an",
    "ROE YTD Ac. Anualizado (%)": "roe_ac_ytd_an",
    "ROE Trim. Anualizado (%)": "roe_trim_an",
    "ROE trim. anualizado": "roe_trim_an",
    "Carteira de Crédito Bruta": "carteira_credito",
    "Carteira de Crédito* (Peers)": "carteira_credito",
}


def get_metric_definition_by_label(label: str) -> Optional[MetricDefinition]:
    """Resolve uma definição pelo label canônico ou por alias de interface."""
    normalized = str(label or "").strip()
    metric_key = _METRIC_LABEL_ALIASES.get(normalized)
    if metric_key:
        return METRIC_REGISTRY.get(metric_key)
    for metric in METRIC_REGISTRY.values():
        if normalized == metric.display_name:
            return metric
    return None


def get_metric_short_definition(label: str) -> str:
    """Retorna a definição curta canônica para tooltips e rodapés."""
    metric = get_metric_definition_by_label(label)
    if metric is None:
        return ""
    return metric.short_definition or metric.formula


def get_metric_long_definition(label: str) -> str:
    """Retorna a definição longa canônica para ajuda e glossário."""
    metric = get_metric_definition_by_label(label)
    if metric is None:
        return ""
    return metric.long_definition or metric.short_definition or metric.formula


def get_metric_source_note(label: str) -> str:
    """Retorna a fonte e a observação metodológica sem duplicar fórmulas."""
    metric = get_metric_definition_by_label(label)
    if metric is None:
        return ""
    parts = []
    if metric.source_label:
        parts.append(f"Fonte: {metric.source_label}.")
    if metric.observations:
        parts.append(f"Observação: {metric.observations}")
    return " ".join(parts)


def get_metric_ui_text(label: str, *, long: bool = False, include_source: bool = True) -> str:
    """Compõe o texto único consumido por tooltip, popover e mini-glossário."""
    definition = get_metric_long_definition(label) if long else get_metric_short_definition(label)
    if not definition:
        return ""
    source_note = get_metric_source_note(label) if include_source else ""
    return " ".join(part for part in (definition, source_note) if part)


def get_metric_footer(label: str) -> str:
    """Compõe rodapé curto com definição, fonte e política de ausência."""
    metric = get_metric_definition_by_label(label)
    if metric is None:
        return ""
    parts = [get_metric_short_definition(label)]
    if metric.source_label:
        parts.append(f"Fonte: {metric.source_label}.")
    if metric.null_policy:
        parts.append(f"Ausência: {metric.null_policy}.")
    return " ".join(part for part in parts if part)


def get_metric_glossary_row(label: str) -> Dict[str, str]:
    """Converte a definição central no contrato tabular do Glossário."""
    metric = get_metric_definition_by_label(label)
    if metric is None:
        return {}
    fields = list(metric.ifdata_fields)
    fields.extend(f"COSIF {account}" for account in metric.cosif_accounts)
    return {
        "Indicador": metric.display_name,
        "Aba(s)": ", ".join(metric.tabs) or "N/D",
        "Fonte": metric.source_label or "N/D",
        "Campos / contas": "; ".join(fields) or "N/D",
        "Fórmula": metric.formula,
        "Unidade": metric.unit,
        "Interpretação": metric.interpretation or metric.short_definition,
        "Limitação": metric.limitation or metric.null_policy,
        "Periodicidade": metric.periodicity,
    }


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
