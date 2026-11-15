"""Seleção de períodos da interface de Taxas, sem alterar as observações."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def _ajustar_periodo(chave: str, alterado: str) -> None:
    inicio, fim = f"{chave}_inicio", f"{chave}_fim"
    if st.session_state[inicio] and st.session_state[fim] and st.session_state[inicio] > st.session_state[fim]:
        destino, origem = (fim, inicio) if alterado == "inicio" else (inicio, fim)
        st.session_state[destino] = st.session_state[origem]


def selecionar_periodo_taxas(
    *, chave: str, frequencia: str, data_min, data_max, contexto,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Mostra somente início/fim; o último campo editado prevalece ao cruzar limites."""
    minimo, maximo = pd.Timestamp(data_min).normalize(), pd.Timestamp(data_max).normalize()
    if frequencia == "M":
        minimo, maximo = minimo.to_period("M").start_time, maximo.to_period("M").start_time
        inicio_padrao = max(minimo, maximo - pd.DateOffset(months=11))
        opcoes = pd.date_range(minimo, maximo, freq="MS").date.tolist()
    else:
        inicio_padrao = max(minimo, maximo - pd.Timedelta(days=59))

    chave_contexto = f"{chave}_contexto"
    novo_contexto = st.session_state.get(chave_contexto) != contexto
    for limite, padrao in (("inicio", inicio_padrao), ("fim", maximo)):
        widget_key = f"{chave}_{limite}"
        valor = pd.to_datetime(st.session_state.get(widget_key), errors="coerce")
        if novo_contexto or pd.isna(valor):
            valor = padrao
        if frequencia == "M":
            valor = valor.to_period("M").start_time
        st.session_state[widget_key] = min(max(valor, minimo), maximo).date()
    st.session_state[chave_contexto] = contexto
    _ajustar_periodo(chave, "inicio")

    for coluna, limite, rotulo in zip(st.columns(2), ("inicio", "fim"), ("Início", "Fim")):
        with coluna:
            parametros = dict(
                key=f"{chave}_{limite}", on_change=_ajustar_periodo, args=(chave, limite),
            )
            if frequencia == "M":
                st.selectbox(rotulo, opcoes, format_func=lambda data: data.strftime("%m/%Y"), **parametros)
            else:
                st.date_input(
                    rotulo, min_value=minimo.date(), max_value=maximo.date(),
                    format="DD/MM/YYYY", **parametros,
                )
    return (
        pd.Timestamp(st.session_state[f"{chave}_inicio"]),
        pd.Timestamp(st.session_state[f"{chave}_fim"]),
    )
