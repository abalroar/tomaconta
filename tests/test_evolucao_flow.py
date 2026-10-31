from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "app1.py"


def _app_source() -> str:
    return APP_PATH.read_text(encoding="utf-8")


def test_evolucao_expands_calculation_periods_for_semester_ytd_context():
    source = _app_source()
    assert "def _expandir_periodos_evolucao_calculo" in source
    assert "periodo_jun = _rankings_periodo_mesma_representacao(periodo, 2)" in source
    assert "periodo_dez_anterior = _periodo_dez_ano_anterior(periodo)" in source
    assert "periodos_calculo_evolucao = _expandir_periodos_evolucao_calculo(periodos_evolucao)" in source


def test_evolucao_uses_sliced_capital_sources_instead_of_full_history():
    source = _app_source()
    assert "df_capital_idx = _construir_indices_capital_instituicao_slice(" in source
    assert "capital_base = _construir_componentes_capital_instituicao_slice(" in source
    assert "df_capital_idx = _construir_indices_capital_unificados(_cache_version_token(\"capital\")" not in source


def test_evolucao_has_institution_scoped_capital_helper():
    source = _app_source()
    assert "def _construir_componentes_capital_instituicao_slice" in source
    assert "mask_exata = serie_inst.eq(instituicao_str)" in source
    assert "resolver_nomes_instituicoes_capital(" in source


def test_module_level_flow_has_no_undefined_names():
    """Uma extração de bloco não pode deixar para trás nomes usados pelo restante da página."""
    import ast
    import builtins

    tree = ast.parse(_app_source())
    defined = set(dir(builtins)) | {"__file__"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            defined.add(node.id)
        elif isinstance(node, ast.arg):
            defined.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            defined.update((alias.asname or alias.name).split(".")[0] for alias in node.names)

    assert not {
        node.id: node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in defined
    }
