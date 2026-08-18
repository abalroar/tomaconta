from tabs.peers_config import PEERS_GLOSSARIO_RESUMIDO
from utils.ifdata_cache.metric_registry import (
    get_metric_definition_by_label,
    get_metric_footer,
    get_metric_glossary_row,
    get_metric_short_definition,
    get_metric_ui_text,
)


AUDITED_LABELS = [
    "Carteira de Crédito*",
    "Receita de Crédito",
    "Custo de Crédito (%)",
    "Custo de Crédito / Receita de Crédito (%)",
    "Ativos Problemáticos / Carteira Total",
    "Inadimplência",
    "Inadimplência / Carteira Total",
    "Índice de Basileia Total (%)",
    "ROE Acumulado YTD (%)",
    "ROE Trim. Anualizado (%)",
]


def test_audited_metrics_have_complete_central_definitions():
    for label in AUDITED_LABELS:
        metric = get_metric_definition_by_label(label)
        assert metric is not None, label
        assert metric.formula, label
        assert metric.short_definition, label
        assert metric.long_definition, label
        assert metric.ifdata_fields, label
        assert metric.source_label, label
        assert metric.interpretation, label
        assert metric.limitation, label


def test_credit_loss_definition_does_not_infer_cosif_accounts():
    metric = get_metric_definition_by_label("Custo de Crédito (%)")
    assert metric is not None
    assert metric.cosif_accounts == []
    assert "Sem de-para COSIF" in metric.observations
    assert "f3" in metric.ifdata_fields[0]


def test_inadimplencia_definition_is_arrasto_over_90_days():
    text = get_metric_ui_text("Inadimplência", long=True)
    assert "mais de 90 dias" in text
    assert "arrasto" in get_metric_short_definition("Inadimplência")


def test_peers_consumes_the_same_short_definitions():
    for label in [
        "Carteira de Crédito*",
        "Custo de Crédito (%)",
        "Custo de Crédito / Receita de Crédito (%)",
        "Ativos Problemáticos / Carteira Total",
        "Inadimplência / Carteira Total",
        "Inadimplência",
        "Índice de Basileia Total (%)",
        "ROE Acumulado YTD (%)",
    ]:
        assert PEERS_GLOSSARIO_RESUMIDO[label] == get_metric_short_definition(label)


def test_glossary_row_and_footer_expose_source_fields_and_null_policy():
    row = get_metric_glossary_row("Custo de Crédito (%)")
    assert row["Fonte"].startswith("BCB IFData Rel.4")
    assert "Resultado com Perda Esperada" in row["Campos / contas"]
    assert row["Fórmula"]
    assert row["Limitação"]
    footer = get_metric_footer("Ativos Problemáticos / Carteira Total")
    assert "Fonte: BCB IFData Rel.16" in footer
    assert "Ausência:" in footer
