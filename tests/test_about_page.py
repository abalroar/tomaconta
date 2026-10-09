import ast
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tabs.about import format_date, format_hours, weekly_figure
from utils.about_catalog import MODULES
from utils.development_hours import DEFAULT_CONFIG, read_json, valid_snapshot


ROOT = Path(__file__).resolve().parents[1]


def test_catalog_covers_current_menu_routes():
    tree = ast.parse((ROOT / "app1.py").read_text(encoding="utf-8"))
    menus = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("MENU_PRINCIPAL", "MENU_BCB"):
                    menus[target.id] = ast.literal_eval(node.value)
    expected = set(menus["MENU_PRINCIPAL"] + menus["MENU_BCB"] + ["Glossário"])
    labels = [module.label for module in MODULES]
    assert set(labels) == expected
    assert len(labels) == len(expected)


def test_shipped_estimate_is_complete_and_repositories_are_resolved():
    snapshot = read_json(ROOT / "data/dev_hours_cache.json")
    assert valid_snapshot(snapshot)
    assert snapshot["schema_version"] == 2
    assert snapshot["total_commits"] > 776
    assert len(snapshot["fontes"]) == 2
    names = {name for source in snapshot["fontes"] for name in source["nomes_consultados"]}
    assert names == set(DEFAULT_CONFIG["repositorios"])


def test_chart_uses_calendar_weeks_br_labels_and_exact_palette():
    snapshot = read_json(ROOT / "data/dev_hours_cache.json")
    fig = weekly_figure(snapshot)
    assert fig.data[1].marker.color == "#EC7000"
    assert fig.layout.xaxis.type == "date"
    assert "fev" in " ".join(fig.layout.xaxis.ticktext)
    assert sum(fig.data[0].y) + sum(fig.data[1].y) == pytest.approx(snapshot["total_horas"], abs=.1)
    assert "Semana de 19/01/2026" in fig.data[0].customdata[0]
    assert format_date("2026-01-26") == "26/01/2026"
    assert format_hours(1234.56) == "1.234,6 h"


def test_summary_and_weekly_chart_are_mutually_exclusive_without_network():
    script = '''
from tabs.about import render_investment
from utils.development_hours import DEFAULT_CONFIG, EstimateStatus, read_json
from pathlib import Path
class Cache:
    def status(self, *args):
        return EstimateStatus(read_json(Path("data/dev_hours_cache.json")))
render_investment(cache=Cache(), config=DEFAULT_CONFIG)
'''
    app = AppTest.from_string(script).run()
    assert not app.exception
    assert not app.get("plotly_chart")
    assert any("Resumo da estimativa" in element.value for element in app.markdown)
    app.button_group[0].set_value(["Por semana"]).run()
    assert not app.exception
    assert len(app.get("plotly_chart")) == 1
    assert not any("Resumo da estimativa" in element.value for element in app.markdown)
    app.button_group[0].set_value(["Resumo"]).run()
    assert not app.exception
    assert not app.get("plotly_chart")
