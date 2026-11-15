from datetime import date

from streamlit.testing.v1 import AppTest


def _app(data_min="2020-01-01", data_max="2026-07-31"):
    return AppTest.from_string(f'''
import streamlit as st
from utils.taxas_juros_periodos import selecionar_periodo_taxas
produto = st.selectbox("Produto", ["A", "B"])
st.selectbox("Taxa", ["Mensal", "Anual"])
selecionar_periodo_taxas(chave="mensal", frequencia="M", data_min="{data_min}", data_max="{data_max}", contexto=produto)
selecionar_periodo_taxas(chave="diario", frequencia="D", data_min="{data_min}", data_max="{data_max}", contexto=produto)
''').run()


def test_defaults_follow_latest_available_month_and_sixty_calendar_days():
    app = _app()
    assert not app.exception
    assert app.selectbox(key="mensal_inicio").value == date(2025, 8, 1)
    assert app.selectbox(key="mensal_fim").value == date(2026, 7, 1)
    assert app.date_input(key="diario_inicio").value == date(2026, 6, 2)
    assert app.date_input(key="diario_fim").value == date(2026, 7, 31)
    assert len(app.slider) == len(app.button) == len(app.toggle) == 0


def test_periods_are_independent_and_survive_unrelated_reruns():
    app = _app()
    app.selectbox(key="mensal_inicio").select(date(2024, 1, 1)).run()
    app.selectbox(key="mensal_fim").select(date(2024, 3, 1)).run()
    app.date_input(key="diario_inicio").set_value(date(2023, 2, 1)).run()
    app.date_input(key="diario_fim").set_value(date(2023, 2, 28)).run()
    app.selectbox[1].select("Anual").run()
    assert not app.exception
    assert app.selectbox(key="mensal_inicio").value == date(2024, 1, 1)
    assert app.selectbox(key="mensal_fim").value == date(2024, 3, 1)
    assert app.date_input(key="diario_inicio").value == date(2023, 2, 1)
    assert app.date_input(key="diario_fim").value == date(2023, 2, 28)


def test_crossing_an_endpoint_keeps_the_last_edit_and_a_valid_range():
    app = _app()
    app.selectbox(key="mensal_fim").select(date(2024, 3, 1)).run()
    assert app.selectbox(key="mensal_inicio").value == date(2024, 3, 1)
    app.selectbox(key="mensal_inicio").select(date(2025, 3, 1)).run()
    assert app.selectbox(key="mensal_fim").value == date(2025, 3, 1)
    app.date_input(key="diario_fim").set_value(date(2023, 2, 28)).run()
    assert app.date_input(key="diario_inicio").value == date(2023, 2, 28)
    app.date_input(key="diario_inicio").set_value(date(2024, 2, 29)).run()
    assert app.date_input(key="diario_fim").value == date(2024, 2, 29)
    assert not app.exception


def test_short_history_and_new_product_use_available_defaults():
    app = _app(data_min="2026-07-20")
    assert app.selectbox(key="mensal_inicio").value == date(2026, 7, 1)
    assert app.date_input(key="diario_inicio").value == date(2026, 7, 20)
    app.date_input(key="diario_inicio").set_value(date(2026, 7, 25)).run()
    app.selectbox[0].select("B").run()
    assert app.date_input(key="diario_inicio").value == date(2026, 7, 20)
    assert not app.exception
