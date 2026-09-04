"""Card de leitura dos dados, um por página de Estatísticas Crédito BC.

Qualquer pessoa edita. A edição vale para a sessão de quem editou; o botão de
download entrega o JSON atualizado, que substitui
``data/comentarios_credito_bc.json`` em um commit e aí passa a valer para
todos. O disco do Streamlit Cloud é efêmero, então gravar em arquivo daria a
impressão de persistência e o texto voltaria ao anterior no próximo restart.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from utils.comentarios_credito import (
    Comentario,
    aplicar,
    carregar,
    com_texto,
    comentario as buscar_comentario,
    desatualizado,
    serializar,
)
from utils.sgs_credit_analytics import formatar_competencia


_ESTILO = """
<style>
div[data-testid="stMarkdownContainer"] .leitura-dado {
  border-left: 3px solid #EC7000;
  background: #FBFAF8;
  padding: 14px 20px 12px;
  margin: 4px 0 18px;
}
div[data-testid="stMarkdownContainer"] .leitura-dado p {
  margin: 0 0 10px;
  font-size: 0.97rem;
  line-height: 1.58;
  color: #1A1715;
}
div[data-testid="stMarkdownContainer"] .leitura-dado p:last-child { margin-bottom: 0; }
div[data-testid="stMarkdownContainer"] .leitura-rodape {
  margin-top: 12px;
  padding-top: 9px;
  border-top: 1px solid #E0D9D2;
  font-size: 0.76rem;
  color: #6E655F;
  line-height: 1.5;
}
</style>
"""


def _edicoes() -> dict[str, Comentario]:
    return st.session_state.setdefault("_comentarios_credito_edicoes", {})


def _competencia(valor: str) -> str:
    try:
        return formatar_competencia(f"{valor}-01")
    except Exception:
        return valor


def render_comentario(chave: str, *, data_base_cache: str | None = None) -> None:
    """Desenha o card da página ``chave``. Silencioso se não há texto."""
    documento = carregar()
    base = buscar_comentario(chave, documento=documento)
    if base is None:
        return
    atual = _edicoes().get(chave, base)
    editando = st.session_state.get(f"_comentario_edit_{chave}", False)

    if not editando and atual.vazio:
        return

    st.markdown(_ESTILO, unsafe_allow_html=True)
    coluna_texto, coluna_acao = st.columns([0.9, 0.1], vertical_alignment="top")

    with coluna_acao:
        rotulo = "Fechar" if editando else "Editar"
        if st.button(rotulo, key=f"_comentario_btn_{chave}", width="stretch"):
            st.session_state[f"_comentario_edit_{chave}"] = not editando
            st.rerun()

    with coluna_texto:
        if editando:
            texto = st.text_area(
                "Leitura dos dados",
                value=atual.texto,
                height=260,
                key=f"_comentario_texto_{chave}",
                help="Linha em branco separa parágrafos.",
            )
            fontes = st.text_input(
                "Fontes",
                value=" · ".join(atual.fontes),
                key=f"_comentario_fontes_{chave}",
                help="Separadas por ·",
            )
            editado = com_texto(
                atual,
                texto,
                tuple(item.strip() for item in fontes.split("·") if item.strip()),
            )
            _edicoes()[chave] = editado
            atual = editado
        else:
            corpo = "".join(f"<p>{paragrafo}</p>" for paragrafo in atual.paragrafos)
            rodape = []
            if atual.data_base:
                rodape.append(f"escrito sobre {_competencia(atual.data_base)}")
            if atual.fontes:
                rodape.append("fontes: " + " · ".join(atual.fontes))
            st.markdown(
                f'<div class="leitura-dado">{corpo}'
                + (f'<div class="leitura-rodape">{" — ".join(rodape)}</div>' if rodape else "")
                + "</div>",
                unsafe_allow_html=True,
            )

    if desatualizado(atual, data_base_cache):
        st.caption(
            f"⚠︎ O texto foi escrito sobre {_competencia(atual.data_base)} e o cache "
            f"está em {_competencia(str(data_base_cache))}. Revise antes de usar."
        )

    if editando:
        st.download_button(
            "Baixar JSON atualizado",
            data=serializar(
                aplicar(
                    documento,
                    _edicoes(),
                    atualizado_em=date.today().isoformat(),
                )
            ),
            file_name="comentarios_credito_bc.json",
            mime="application/json",
            key=f"_comentario_download_{chave}",
            help=(
                "Substitua data/comentarios_credito_bc.json por este arquivo em um "
                "commit. Até lá, a edição vale só para esta sessão."
            ),
        )
