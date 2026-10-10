"""Preserva rotas, nomes e estado da navegação no cabeçalho."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from utils.header_navigation import NAVIGATION_GROUPS


def _app_assignments():
    tree = ast.parse(Path("app1.py").read_text())
    return tree, {
        target.id: ast.literal_eval(node.value)
        for node in tree.body if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id in {
            "MENU_PRINCIPAL", "MENU_BCB", "MENU_SECUNDARIO",
        }
    }


def test_header_groups_keep_every_existing_route_and_name_exactly_once():
    _, menus = _app_assignments()
    destinations = [label for _, labels in NAVIGATION_GROUPS for label in labels]
    existing = [label for group in menus.values() for label in group]
    assert len(destinations) == len(set(destinations)) == 16
    assert set(destinations) == set(existing)


@pytest.mark.parametrize("destination", [label for _, labels in NAVIGATION_GROUPS for label in labels])
def test_header_selection_preserves_data_state_and_closes_previous_panel(destination):
    tree, menus = _app_assignments()
    callback = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "_nav_para_menu")
    selected_banks = ["ITAU - PRUDENCIAL", "BRADESCO - PRUDENCIAL"]
    state = {"menu_atual": "Snapshot", "selected_banks": selected_banks,
             "snapshot_base": "Individual", "_header_nav_revision": 3}
    namespace = {"st": SimpleNamespace(session_state=state), **menus}
    exec(compile(ast.Module(body=[callback], type_ignores=[]), "app1.py", "exec"), namespace)
    namespace["_nav_para_menu"](destination)
    assert state["menu_atual"] == destination
    assert state["_user_selected_menu"] is True
    assert state["_header_nav_revision"] == 4
    assert state["selected_banks"] is selected_banks
    assert state["snapshot_base"] == "Individual"
    assert [state[key] for key in ("nav_main", "nav_bcb", "nav_sec")].count(destination) == 1


def test_native_header_widgets_navigate_from_desktop_and_mobile():
    app = AppTest.from_string('''
import streamlit as st
from utils.header_navigation import render_header_navigation
if "menu_atual" not in st.session_state:
    st.session_state.menu_atual = "Snapshot"
def navigate(destination):
    st.session_state.menu_atual = destination
    st.session_state.revision = st.session_state.get("revision", 0) + 1
render_header_navigation(st.session_state.menu_atual, "", navigate,
                         st.session_state.get("revision", 0))
st.write("Página: " + st.session_state.menu_atual)
''').run()
    assert not app.exception
    app.button(key="header_nav_desktop_1_3").click().run()
    assert not app.exception
    assert app.session_state["menu_atual"] == "Carteira 4.966"
    app.button(key="header_nav_mobile_0_2").click().run()
    assert not app.exception
    assert app.session_state["menu_atual"] == "Tabela de Peers"
    assert app.session_state["revision"] == 2
