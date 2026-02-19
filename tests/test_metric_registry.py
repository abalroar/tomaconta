import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "utils" / "ifdata_cache" / "metric_registry.py"
spec = importlib.util.spec_from_file_location("metric_registry", MODULE_PATH)
metric_registry = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
import sys
sys.modules["metric_registry"] = metric_registry
spec.loader.exec_module(metric_registry)

METRIC_REGISTRY = metric_registry.METRIC_REGISTRY
DATASET_CONTRACTS = metric_registry.DATASET_CONTRACTS
get_metric_definition = metric_registry.get_metric_definition
validate_dataframe_by_contract_name = metric_registry.validate_dataframe_by_contract_name
get_derived_metric_labels = metric_registry.get_derived_metric_labels
get_derived_metric_formula_map = metric_registry.get_derived_metric_formula_map


class FakeDataFrame:
    def __init__(self, columns, empty=False):
        self.columns = columns
        self.empty = empty


def test_registry_has_core_metrics():
    assert "indice_basileia" in METRIC_REGISTRY
    assert "roe_ac_ytd_an" in METRIC_REGISTRY
    assert "desp_captacao_captacao" in METRIC_REGISTRY


def test_metric_definition_scale_is_decimal_for_pct_metrics():
    metric = get_metric_definition("desp_captacao_captacao")
    assert metric is not None
    assert metric.unit == "%"
    assert metric.internal_scale == "decimal_0_1"


def test_dataset_contract_validation_ok():
    contract = DATASET_CONTRACTS["derived_metrics_long"]
    df = FakeDataFrame(
        columns=["Instituição", "Período", "Métrica", "Valor", "Unidade"],
        empty=False,
    )
    errors = validate_dataframe_by_contract_name(df, contract.name)
    assert errors == []


def test_dataset_contract_validation_missing_column():
    df = FakeDataFrame(columns=["Instituição", "Período", "Valor"], empty=False)
    errors = validate_dataframe_by_contract_name(df, "derived_metrics_long")
    assert any("coluna obrigatória ausente" in e for e in errors)


def test_dataset_contract_validation_invalid_object():
    errors = validate_dataframe_by_contract_name(object(), "derived_metrics_long")
    assert any("interface de dataframe" in e for e in errors)


def test_derived_metric_helpers_are_consistent():
    labels = get_derived_metric_labels()
    formulas = get_derived_metric_formula_map()
    assert "Desp PDD / NIM bruta" in labels
    assert "Desp Captação / Captação" in labels
    assert set(labels).issubset(set(formulas.keys()))
