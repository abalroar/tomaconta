from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "app1.py"


def _app_source() -> str:
    return APP_PATH.read_text(encoding="utf-8")


def test_scatter_period_loader_can_skip_derived_metrics():
    source = _app_source()
    assert "incluir_metricas_derivadas: bool = True" in source
    assert "if incluir_metricas_derivadas:" in source
    assert '"skipped": True' in source


def test_scatter_default_path_keeps_t2_on_demand():
    source = _app_source()
    assert 'key="scatter_load_t2"' in source
    assert "if not carregar_scatter_t2:" in source
    assert "elif periodo_inicial == periodo_subseq:" in source


def test_scatter_derived_metrics_are_loaded_only_when_selected():
    source = _app_source()
    assert "def _scatter_usa_metricas_derivadas" in source
    assert "scatter_t1_usa_derivadas = _scatter_usa_metricas_derivadas(var_x, var_y, var_size)" in source
    assert "scatter_t2_usa_derivadas = _scatter_usa_metricas_derivadas(var_x_n2, var_y_n2, var_size_n2)" in source


def test_scatter_default_path_uses_light_principal_slice():
    source = _app_source()
    assert "def _get_scatter_filters_context" in source
    assert 'pd.read_parquet(cache_principal.arquivo_dados, columns=["Instituição", "Período"])' in source
    assert "def _get_scatter_principal_direct_periodo_df" in source
    assert "usar_base_preparada = _scatter_precisa_base_preparada" in source
