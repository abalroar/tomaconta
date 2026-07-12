import ast
from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "app1.py"


def _app_tree():
    return ast.parse(APP_PATH.read_text(encoding="utf-8"))


def _app_source() -> str:
    return APP_PATH.read_text(encoding="utf-8")


def _assigned_list_strings(tree: ast.AST, name: str) -> set[str]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        if isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
            return {elt.value for elt in node.value.elts if isinstance(elt, ast.Constant) and isinstance(elt.value, str)}
    return set()


def test_rankings_t1_is_classified_as_percentual_metric():
    strings = _assigned_list_strings(_app_tree(), "VARS_PERCENTUAL")
    assert "Índice de Capital T1 (%)" in strings
    assert "Índice de Capital T1" in strings
    assert "Índice de Capital Nível I" in strings

def test_rankings_delta_history_has_available_periods_alias():
    source = _app_source()
    assert "periodos = ordenar_periodos(_rankings_periodos_raw, reverso=True)" in source
    assert "periodos_disponiveis = periodos" in source
