from streamlit.testing.v1 import AppTest


def test_rankings_labels_retain_choice_reset_on_indicator_change_and_return_without_warning():
    app = AppTest.from_string('''
import streamlit as st
from utils.ui_polish import render_rankings_data_labels_toggle
show = st.checkbox("Mostrar consulta", value=True)
indicator = st.selectbox("Indicador", ["Ativo Total", "ROE"])
if show:
    st.session_state["test_labels_visible"] = render_rankings_data_labels_toggle(indicator)
''').run()
    assert not app.exception and not app.warning
    assert app.toggle[0].value is True
    app.toggle[0].set_value(False).run()
    assert app.toggle[0].value is False
    app.run()
    assert app.toggle[0].value is False
    app.selectbox[0].set_value("ROE").run()
    assert app.toggle[0].value is True
    app.checkbox[0].set_value(False).run()
    app.checkbox[0].set_value(True).run()
    assert app.toggle[0].value is True
    assert not app.exception and not app.warning
