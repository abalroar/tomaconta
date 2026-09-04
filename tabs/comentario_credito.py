"""Card de leitura dos dados, um por página de Estatísticas Crédito BC.

Qualquer pessoa edita. A edição vale para a sessão de quem editou; o botão de
download entrega o JSON atualizado, que substitui
``data/comentarios_credito_bc.json`` em um commit e aí passa a valer para
todos. O disco do Streamlit Cloud é efêmero, então gravar em arquivo daria a
impressão de persistência e o texto voltaria ao anterior no próximo restart.
"""

from __future__ import annotations

from datetime import date
from html import escape

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
div[data-testid="stMarkdownContainer"] .titulo-leitura {
  margin: 0;
  padding: 0;
  font-size: 1.42rem;
  font-weight: 600;
  line-height: 1.3;
  color: #1A1715;
}
div[data-testid="stMarkdownContainer"] .leitura-dado {
  background: #FAF8F5;
  border-bottom: 1px solid #E8E2DB;
  padding: 12px 16px 10px;
  margin: 0 0 14px;
}
div[data-testid="stMarkdownContainer"] .leitura-dado p {
  margin: 0 0 8px;
  font-size: 0.95rem;
  line-height: 1.55;
  color: #1A1715;
}
div[data-testid="stMarkdownContainer"] .leitura-dado p:last-child { margin-bottom: 0; }
div[data-testid="stMarkdownContainer"] .leitura-rodape {
  margin-top: 10px;
  font-size: 0.74rem;
  color: #8A8078;
  line-height: 1.45;
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


def render_comentario(
    chave: str, *, data_base_cache: str | None = None, titulo: str | None = None
) -> None:
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

    # Título e lápis na mesma linha, com o box de texto ocupando a largura
    # inteira abaixo. Com o botão ao lado do box, ele comia largura do
    # comentário e desalinhava o card em relação aos gráficos.
    rotulo = titulo or atual.titulo
    coluna_titulo, coluna_editar = st.columns(
        [0.955, 0.045], vertical_alignment="center"
    )
    with coluna_titulo:
        st.markdown(
            f"<div class='titulo-leitura'>{escape(rotulo)}</div>",
            unsafe_allow_html=True,
        )
    with coluna_editar:
        if st.button(
            "✎",
            key=f"_comentario_btn_{chave}",
            help="Editar a leitura dos dados",
            type="tertiary",
        ):
            st.session_state[f"_comentario_edit_{chave}"] = not editando
            st.rerun()

    if editando:
        texto = st.text_area(
            "Leitura dos dados",
            value=atual.texto,
            height=240,
            key=f"_comentario_texto_{chave}",
            help="Linha em branco separa parágrafos.",
        )
        fontes = st.text_input(
            "Fontes",
            value=" · ".join(atual.fontes),
            key=f"_comentario_fontes_{chave}",
            help="Separadas por ·",
        )
        atual = com_texto(
            atual,
            texto,
            tuple(item.strip() for item in fontes.split("·") if item.strip()),
        )
        _edicoes()[chave] = atual
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
                aplicar(documento, _edicoes(), atualizado_em=date.today().isoformat())
            ),
            file_name="comentarios_credito_bc.json",
            mime="application/json",
            key=f"_comentario_download_{chave}",
            help=(
                "Substitua data/comentarios_credito_bc.json por este arquivo em um "
                "commit. Até lá, a edição vale só para esta sessão."
            ),
        )
