"""Página Streamlit do Peer de Adquirentes (IF.data, conglomerado prudencial).

O conteúdo de cada seção vem de utils/peer_adquirentes/vistas.py, que também alimenta o Excel e o PowerPoint.
"""
from __future__ import annotations

import datetime as dt
import html

import plotly.graph_objects as go
import streamlit as st

from utils.peer_adquirentes import config as C
from utils.peer_adquirentes import exportar, ifdata, vistas as V
from utils.peer_adquirentes.calculo import rotulo_mes
from utils.peer_adquirentes.mascara import POR_ID

SECOES = ("Comparativo", "Por instituição", "Evolução", "Fontes")
PLOTLY_CONFIG = {"displayModeBar": "hover", "displaylogo": False, "responsive": True}
_RECUO = {"recuo": 1.1, "pct": 1.1}

_CSS = """
<style>
.peer-tab{overflow-x:auto;margin:.25rem 0 .5rem 0}
.peer-tab table{border-collapse:collapse;font-size:.76rem;font-variant-numeric:tabular-nums;white-space:nowrap}
.peer-tab th,.peer-tab td{border:0;padding:.16rem .38rem}
.peer-tab thead th{color:#fff;font-weight:600;text-align:center}
.peer-tab thead tr.col th{background:#3F4350}
.peer-tab td.v{text-align:right}
.peer-tab td.r{text-align:left;position:sticky;left:0;background:var(--peer-bg,#fff)}
.peer-tab tr.grp td{font-weight:700;padding-top:.6rem}
.peer-tab tr.forte td{font-weight:600}
.peer-tab tr.pct td{color:#5B616E;font-size:.72rem}
.peer-tab tr.sep td{height:.35rem;padding:0}
.peer-tab tbody tr:not(.grp):not(.sep):hover td{background:rgba(127,127,127,.08)}
.peer-notas{font-size:.74rem;color:#6C717B;line-height:1.35}
.peer-notas p{margin:.15rem 0}
</style>
"""


# ---------------------------------------------------------------- dados
def _mtime() -> float:
    try:
        return C.BASE_CSV.stat().st_mtime
    except OSError:
        return 0.0


@st.cache_data(show_spinner=False)
def _base(_mtime_base: float):
    return ifdata.carregar_base()


def _dados(modo: str) -> V.Dados:
    return V.Dados(_base(_mtime()), modo)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _proximo_publicado(ultimo: str) -> tuple[str, bool | None]:
    prox = ifdata.proximo(ultimo)
    fim_tri = dt.date(int(prox[:4]), int(prox[4:]), 28)
    if dt.date.today() < fim_tri + dt.timedelta(days=55):     # o IF.data sai entre 75 e 90 dias depois do fechamento
        return prox, False
    return prox, ifdata.publicado(prox)


# ---------------------------------------------------------------- tabela e gráfico
def tabela_html(t: V.Tab) -> str:
    e = html.escape
    cab = ""
    if t.grupos:
        cab += "<tr><th></th>" + "".join(
            f'<th colspan="{n}" style="background:{C.cor(k, "fundo")}">{e(nome)}</th>'
            for (nome, n), k in zip(t.grupos, t.chaves)) + "</tr>"
    cab += f'<tr class="col"><th style="text-align:left">{e(t.canto)}</th>' + "".join(f"<th>{e(c)}</th>" for c in t.colunas) + "</tr>"
    corpo = []
    for l in t.linhas:
        if l.estilo == "sep":
            corpo.append(f'<tr class="sep"><td colspan="{1 + len(t.colunas)}"></td></tr>')
            continue
        recuo = _RECUO.get(l.estilo, 0)
        rot = f'<td class="r" style="padding-left:{0.38 + recuo:.2f}rem">{e(l.rotulo)}</td>'
        vals = "" if l.estilo == "grp" else "".join(f'<td class="v">{e(V.texto(c))}</td>' for c in l.cels)
        if l.estilo == "grp":
            vals = f'<td colspan="{len(t.colunas)}"></td>'
        corpo.append(f'<tr class="{l.estilo}">{rot}{vals}</tr>')
    return f'<div class="peer-tab"><table><thead>{cab}</thead><tbody>{"".join(corpo)}</tbody></table></div>'


def _notas(v: V.Vista) -> None:
    st.markdown('<div class="peer-notas">' + "".join(f"<p>{html.escape(n)}</p>" for n in [v.nota, *v.notas]) + "</div>",
                unsafe_allow_html=True)


def _fmt_eixo(formato: str) -> dict:
    return {"pct1": dict(tickformat=".0%"), "x1": dict(tickformat=".1f", ticksuffix="x"), "mi": dict(tickformat=",.0f")}[formato]


def _afastar_rotulos(g: V.Graf, altura_px: float = 250, min_px: float = 15) -> dict[str, float]:
    """Desloca na vertical (em px) os rótulos de fim de linha que cairiam um sobre o outro."""
    todos = [x for _, v in g.series for x in v if x is not None]
    if not todos:
        return {}
    faixa = (max(todos) - min(todos)) or 1
    fins = sorted((next(x for x in reversed(v) if x is not None) / faixa * altura_px, k)
                  for k, v in g.series if any(x is not None for x in v))
    desl, ultimo = {}, None
    for y, k in fins:
        alvo = y if ultimo is None else max(y, ultimo + min_px)
        desl[k], ultimo = alvo - y, alvo
    meio = sum(desl.values()) / len(desl)          # centra o bloco deslocado em torno das posições reais
    return {k: d - meio for k, d in desl.items()}


def grafico(g: V.Graf) -> go.Figure:
    escuro = getattr(getattr(st.context, "theme", None), "type", None) == "dark"
    fig = go.Figure()
    deslocamento = _afastar_rotulos(g)
    for k, vals in g.series:
        cor = C.cor(k, "escuro" if escuro else "claro")
        fig.add_trace(go.Scatter(x=g.categorias, y=vals, mode="lines+markers", name=C.INSTITUICOES[k]["curto"],
                                 line=dict(color=cor, width=2), marker=dict(size=6, color=cor), connectgaps=False,
                                 hovertemplate="%{x}: %{customdata}<extra>" + C.INSTITUICOES[k]["curto"] + "</extra>",
                                 customdata=[V.fmt(x, g.formato) for x in vals]))
        idx = [i for i, x in enumerate(vals) if x is not None]
        if idx:                                  # nome e último valor no fim da linha
            i = idx[-1]
            fig.add_annotation(x=g.categorias[i], y=vals[i], text=f"<b>{C.INSTITUICOES[k]['curto']} {V.fmt(vals[i], g.formato)}</b>",
                               showarrow=False, xanchor="left", xshift=8, yshift=deslocamento.get(k, 0), font=dict(color=cor, size=11))
    fig.update_layout(title=dict(text=g.titulo, font=dict(size=14)), height=330, margin=dict(l=10, r=110, t=40, b=10),
                      showlegend=False, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                      separators=",.", hovermode="x unified")
    fig.update_xaxes(showgrid=False, type="category")
    fig.update_yaxes(gridcolor="rgba(127,127,127,.2)", zeroline=False, **_fmt_eixo(g.formato))
    return fig


def _downloads(v: V.Vista, chave: str) -> None:
    a, b, _ = st.columns([1, 1, 4])
    a.download_button("Baixar Excel", exportar.para_excel(v), file_name=f"{v.chave}.xlsx",
                      mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"peer_xl_{chave}", width="stretch")
    b.download_button("Baixar PPT", exportar.para_pptx(v), file_name=f"{v.chave}.pptx",
                      mime="application/vnd.openxmlformats-officedocument.presentationml.presentation", key=f"peer_ppt_{chave}", width="stretch")


# ---------------------------------------------------------------- seções
def _comparativo(d: V.Dados) -> None:
    c1, c2 = st.columns([3, 2])
    chaves = c1.multiselect("Instituições", C.ORDEM, default=C.ORDEM, format_func=lambda k: C.INSTITUICOES[k]["nome"],
                            key="peer_comp_inst") or C.ORDEM
    blocos = c2.multiselect("Blocos", list(V.BLOCOS), default=list(V.BLOCOS), format_func=V.BLOCOS.get, key="peer_comp_blocos")
    v = V.comparativo(d, [k for k in C.ORDEM if k in chaves], blocos or None)
    st.markdown(f"**{v.titulo}** · fluxos acumulados no ano, razões anualizadas")
    st.markdown(tabela_html(v.tabela), unsafe_allow_html=True)
    _downloads(v, "comp")
    _notas(v)


def _por_instituicao(d: V.Dados) -> None:
    c1, c2 = st.columns([3, 2])
    chave = c1.segmented_control("Instituição", C.ORDEM, default=C.ORDEM[0], format_func=lambda k: C.INSTITUICOES[k]["nome"],
                                 key="peer_inst") or C.ORDEM[0]
    leitura = c2.segmented_control("Leitura", ["Trimestral", "Acumulado no ano"], default="Trimestral", key="peer_inst_leitura") or "Trimestral"
    v = V.por_instituicao(d, chave, "tri" if leitura == "Trimestral" else "acum")
    st.markdown(f"**{v.titulo}** · {C.INSTITUICOES[chave]['perimetro']}")
    st.markdown(tabela_html(v.tabela), unsafe_allow_html=True)
    _downloads(v, f"inst_{chave}")
    _notas(v)


def _evolucao(d: V.Dados) -> None:
    c1, c2 = st.columns([3, 2])
    ids = c1.multiselect("Indicadores (até 4)", V.INDICADORES_GRAFICO, default=V.PADRAO_GRAFICO, max_selections=4,
                         format_func=lambda i: POR_ID[i].rotulo, key="peer_evo_ind") or V.PADRAO_GRAFICO
    chaves = c2.multiselect("Instituições", C.ORDEM, default=C.ORDEM, format_func=lambda k: C.INSTITUICOES[k]["nome"],
                            key="peer_evo_inst") or C.ORDEM
    v = V.evolucao(d, ids, [k for k in C.ORDEM if k in chaves])
    for i in range(0, len(v.graficos), 2):
        cols = st.columns(2)
        for col, g in zip(cols, v.graficos[i:i + 2]):
            col.plotly_chart(grafico(g), width="stretch", config=PLOTLY_CONFIG, key=f"peer_evo_{g.titulo}")
    _downloads(v, "evo")
    _notas(v)


def _fontes(d: V.Dados) -> None:
    sit = ifdata.ler_situacao()
    prox, saiu = _proximo_publicado(d.ultimo)
    st.markdown(f"**Última data-base na base:** {rotulo_mes(d.ultimo)} · consulta ao BCB em "
                f"{sit.get('consultado_em', '–').replace('T', ' ')}")
    if saiu:
        st.warning(f"O IF.data já publicou {rotulo_mes(prox)}, que ainda não está na base.")
        if st.button("Buscar agora", key="peer_buscar"):
            with st.spinner("Consultando o IF.data…"):
                r = ifdata.atualizar()
                ifdata.gravar_situacao(r)
            _base.clear()
            st.rerun()
    elif saiu is None:
        st.caption(f"Não foi possível consultar o IF.data agora para saber se {rotulo_mes(prox)} já saiu.")
    else:
        st.caption(f"Próxima data-base: {rotulo_mes(prox)} (o IF.data publica entre 75 e 90 dias depois do fechamento).")

    st.markdown("##### Perímetro")
    st.markdown("\n".join(f"- **{v['nome']}** ({v['cod']}): {v['perimetro'].split(': ', 1)[1]}" for v in C.INSTITUICOES.values()))

    st.markdown("##### Conferências")
    conf = d.peer.conferencias()
    import pandas as pd
    df = pd.DataFrame(conf)
    resumo = df.groupby(["conferencia", "status"]).size().unstack(fill_value=0)
    st.dataframe(resumo, width="stretch")
    pend = df[df["status"] == "diferença"].copy()
    if len(pend):
        pend["instituição"] = pend["chave"].map(lambda k: C.INSTITUICOES[k]["nome"])
        pend["data-base"] = pend["periodo"].map(rotulo_mes)
        st.markdown("A conferir (diferença no próprio IF.data):")
        st.dataframe(pend[["instituição", "data-base", "conferencia", "diferenca"]], width="stretch", hide_index=True)
    st.caption("\"sem dado\": a identidade não se aplica porque alguma linha não foi publicada (lacuna da fonte).")

    st.markdown("##### Lacunas da fonte")
    st.markdown("\n".join(f"- {t}" for t in C.LACUNAS.values()) or "Nenhuma.")

    rev = ifdata.revisoes(d.base)
    st.markdown("##### Reapresentações")
    if rev.empty:
        st.caption("Nenhum número reapresentado pelo BCB desde a primeira coleta.")
    else:
        st.dataframe(rev, width="stretch", hide_index=True)


def render_peer_adquirentes() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown("## Peer de Adquirentes")
    st.caption("Stone, PagBank, Mercado Pago, CloudWalk e SumUp pelo IF.data do Banco Central (COSIF, conglomerado prudencial). "
               "Dados regulatórios, não o gerencial de RI.")
    if not C.BASE_CSV.exists():
        st.error("Base do peer ainda não gerada: rode `python -m utils.peer_adquirentes atualizar`.")
        return
    c1, c2 = st.columns([4, 1])
    secao = c1.segmented_control("Seção", SECOES, default=SECOES[0], key="peer_secao", label_visibility="collapsed") or SECOES[0]
    modo = c2.segmented_control("Visão", ["revisada", "original"], default="revisada", key="peer_visao",
                                label_visibility="collapsed", help="revisada: último valor publicado; original: como saiu na primeira vez") or "revisada"
    d = _dados(modo)
    {"Comparativo": _comparativo, "Por instituição": _por_instituicao, "Evolução": _evolucao, "Fontes": _fontes}[secao](d)
