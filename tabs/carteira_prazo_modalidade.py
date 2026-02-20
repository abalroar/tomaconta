from __future__ import annotations

from pathlib import Path
import unicodedata

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st


DEFAULT_PF_PATH = "/mnt/data/credito_prazo.csv"
DEFAULT_PJ_PATH = "/mnt/data/carteira_prazo_pj.csv"

CANONICAL_MODALIDADES = [
    "Vencido a Partir de 15 Dias",
    "A Vencer em até 90 Dias",
    "A Vencer Entre 91 a 360 Dias",
    "A Vencer Entre 361 a 1080 Dias",
    "A Vencer Entre 1081 a 1800 Dias",
    "A Vencer Entre 1801 a 5400 Dias",
    "A vencer Acima de 5400 Dias",
    "Total",
]

PRAZO_TETO_DIAS = {
    "Vencido a Partir de 15 Dias": 15,
    "A Vencer em até 90 Dias": 90,
    "A Vencer Entre 91 a 360 Dias": 360,
    "A Vencer Entre 361 a 1080 Dias": 1080,
    "A Vencer Entre 1081 a 1800 Dias": 1800,
    "A Vencer Entre 1801 a 5400 Dias": 5400,
    "A vencer Acima de 5400 Dias": 5400,
}



def _norm_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.strip().split())
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def _coerce_number(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip()
    s = s.replace({"": np.nan, "NI": np.nan, "ni": np.nan, "N/I": np.nan, "n/i": np.nan})
    has_comma = s.str.contains(",", na=False)
    s = s.str.replace(".", "", regex=False)
    s = s.where(~has_comma, s.str.replace(",", ".", regex=False))
    return pd.to_numeric(s, errors="coerce")


def normalize_modalidade_text(value: object) -> str:
    raw = "" if value is None else str(value)
    txt = " ".join(raw.strip().split())
    if not txt:
        return ""

    n = _norm_text(txt)
    if "total" == n:
        return "Total"
    if "vencido" in n and "15" in n:
        return "Vencido a Partir de 15 Dias"
    if "ate 90" in n and "vencer" in n:
        return "A Vencer em até 90 Dias"
    if "91" in n and "360" in n:
        return "A Vencer Entre 91 a 360 Dias"
    if "361" in n and "1080" in n:
        return "A Vencer Entre 361 a 1080 Dias"
    if "1081" in n and "1800" in n:
        return "A Vencer Entre 1081 a 1800 Dias"
    if "1801" in n and "5400" in n:
        return "A Vencer Entre 1801 a 5400 Dias"
    if "acima" in n and "5400" in n:
        return "A vencer Acima de 5400 Dias"

    return txt


def _resolve_meta_col(meta_map: dict[str, str], aliases: list[str]) -> str | None:
    for alias in aliases:
        if alias in meta_map:
            return meta_map[alias]
    return None


def _extract_codigo_from_instituicao(series: pd.Series) -> pd.Series:
    extracted = series.astype(str).str.extract(r"\[IF\s*(\d+)\]", expand=False)
    return extracted


def _df_cache_to_long(df: pd.DataFrame, segmento: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    lower_cols = {c.lower(): c for c in df.columns}
    col_inst = lower_cols.get("instituição") or lower_cols.get("instituicao")
    col_periodo = lower_cols.get("período") or lower_cols.get("periodo")
    col_total_seg = next(
        (
            c for c in df.columns
            if "total da carteira de pessoa fisica" in _norm_text(c)
            or "total da carteira de pessoa juridica" in _norm_text(c)
        ),
        None,
    )
    modalidade_cols = [c for c in df.columns if normalize_modalidade_text(c) in CANONICAL_MODALIDADES]
    if not col_inst or not col_periodo or not modalidade_cols:
        return pd.DataFrame()

    out = df[[col_inst, col_periodo] + ([col_total_seg] if col_total_seg else []) + modalidade_cols].copy()
    out = out.rename(columns={col_inst: "instituicao", col_periodo: "data"})
    out["codigo"] = _extract_codigo_from_instituicao(out["instituicao"])
    out["produto"] = "Carteira Total"
    out["segmento"] = segmento
    out["tcb"] = np.nan
    out["td"] = np.nan
    out["tc"] = np.nan
    out["sr"] = np.nan
    out["cidade"] = np.nan
    out["uf"] = np.nan
    out["total_segmento"] = out[col_total_seg] if col_total_seg else np.nan

    melt = out.melt(
        id_vars=[
            "instituicao",
            "codigo",
            "tcb",
            "td",
            "tc",
            "sr",
            "cidade",
            "uf",
            "data",
            "segmento",
            "total_segmento",
            "produto",
        ],
        value_vars=modalidade_cols,
        var_name="modalidade",
        value_name="valor",
    )
    melt["modalidade"] = melt["modalidade"].apply(normalize_modalidade_text)
    melt["data"] = pd.to_datetime("01/" + melt["data"].astype(str), format="%d/%m/%Y", errors="coerce")
    melt["valor"] = pd.to_numeric(melt["valor"], errors="coerce")
    melt["total_segmento"] = pd.to_numeric(melt["total_segmento"], errors="coerce")
    melt["modalidade"] = pd.Categorical(melt["modalidade"], categories=CANONICAL_MODALIDADES, ordered=True)
    return melt[
        [
            "instituicao",
            "codigo",
            "tcb",
            "td",
            "tc",
            "sr",
            "cidade",
            "uf",
            "data",
            "segmento",
            "total_segmento",
            "produto",
            "modalidade",
            "valor",
        ]
    ]


@st.cache_data(ttl=3600, show_spinner=False)
def load_carteira_prazo_csv(path: str) -> pd.DataFrame:
    csv_path = Path(path)
    if not csv_path.exists():
        return pd.DataFrame()

    df_raw = pd.read_csv(
        csv_path,
        sep=";",
        encoding="utf-8-sig",
        header=[0, 1],
        dtype=str,
        low_memory=False,
    )

    h0 = ["" if x is None else str(x) for x in df_raw.columns.get_level_values(0)]
    h1 = ["" if x is None else str(x) for x in df_raw.columns.get_level_values(1)]
    h0_clean = ["" if x.startswith("Unnamed:") else " ".join(x.strip().split()) for x in h0]
    h1_clean = ["" if x.startswith("Unnamed:") else " ".join(x.strip().split()) for x in h1]

    matrix_start = 0
    for i, val in enumerate(h1_clean):
        if val:
            matrix_start = i
            break

    meta_indices = list(range(matrix_start))
    matrix_indices = list(range(matrix_start, len(h0_clean)))

    meta_names = []
    for idx in meta_indices:
        cand = h0_clean[idx] or h1_clean[idx] or f"meta_{idx}"
        meta_names.append(cand)

    df_meta = df_raw.iloc[:, meta_indices].copy()
    df_meta.columns = meta_names

    norm_map = {_norm_text(c): c for c in df_meta.columns}

    col_instituicao = _resolve_meta_col(norm_map, ["instituicao", "instituicao financeira", "if"])
    col_codigo = _resolve_meta_col(norm_map, ["codigo", "cod", "codinst", "codigo da instituicao", "codigo instituicao"])
    col_tcb = _resolve_meta_col(norm_map, ["tcb"])
    col_td = _resolve_meta_col(norm_map, ["td"])
    col_tc = _resolve_meta_col(norm_map, ["tc"])
    col_sr = _resolve_meta_col(norm_map, ["sr"])
    col_cidade = _resolve_meta_col(norm_map, ["cidade", "municipio"])
    col_uf = _resolve_meta_col(norm_map, ["uf", "estado"])
    col_data = _resolve_meta_col(norm_map, ["data", "mes", "periodo"])

    total_pf_col = _resolve_meta_col(norm_map, ["total da carteira de pessoa fisica"])
    total_pj_col = _resolve_meta_col(norm_map, ["total da carteira de pessoa juridica"])

    segmento = None
    total_segmento_col = None
    if total_pf_col is not None:
        segmento = "PF"
        total_segmento_col = total_pf_col
    elif total_pj_col is not None:
        segmento = "PJ"
        total_segmento_col = total_pj_col

    product_ffill = []
    current = ""
    for idx in matrix_indices:
        if h0_clean[idx]:
            current = h0_clean[idx]
        product_ffill.append(current)

    matrix_data: dict[str, pd.Series] = {}
    for j, idx in enumerate(matrix_indices):
        produto = product_ffill[j]
        modalidade = normalize_modalidade_text(h1_clean[idx])
        if not produto or not modalidade:
            continue
        key = f"{produto}|||{modalidade}"
        matrix_data[key] = df_raw.iloc[:, idx]

    if not matrix_data:
        return pd.DataFrame()

    id_df = pd.DataFrame({
        "instituicao": df_meta[col_instituicao] if col_instituicao else np.nan,
        "codigo": df_meta[col_codigo] if col_codigo else np.nan,
        "tcb": df_meta[col_tcb] if col_tcb else np.nan,
        "td": df_meta[col_td] if col_td else np.nan,
        "tc": df_meta[col_tc] if col_tc else np.nan,
        "sr": df_meta[col_sr] if col_sr else np.nan,
        "cidade": df_meta[col_cidade] if col_cidade else np.nan,
        "uf": df_meta[col_uf] if col_uf else np.nan,
        "data": df_meta[col_data] if col_data else np.nan,
        "total_segmento": df_meta[total_segmento_col] if total_segmento_col else np.nan,
    })

    matrix_df = pd.DataFrame(matrix_data)
    df = pd.concat([id_df, matrix_df], axis=1)

    df_long = df.melt(
        id_vars=[
            "instituicao",
            "codigo",
            "tcb",
            "td",
            "tc",
            "sr",
            "cidade",
            "uf",
            "data",
            "total_segmento",
        ],
        value_vars=list(matrix_df.columns),
        var_name="produto_modalidade",
        value_name="valor",
    )

    split = df_long["produto_modalidade"].str.split("|||", n=1, expand=True)
    df_long["produto"] = split[0]
    df_long["modalidade"] = split[1].apply(normalize_modalidade_text)
    df_long.drop(columns=["produto_modalidade"], inplace=True)

    df_long["data"] = pd.to_datetime(
        "01/" + df_long["data"].astype(str).str.strip(),
        format="%d/%m/%Y",
        errors="coerce",
    )

    for col in ["codigo", "tcb", "td", "tc", "sr"]:
        if col in df_long.columns:
            df_long[col] = _coerce_number(df_long[col])
    df_long["total_segmento"] = _coerce_number(df_long["total_segmento"])
    df_long["valor"] = _coerce_number(df_long["valor"])

    df_long["segmento"] = segmento if segmento is not None else ""
    df_long["modalidade"] = pd.Categorical(
        df_long["modalidade"],
        categories=CANONICAL_MODALIDADES,
        ordered=True,
    )

    cols = [
        "instituicao",
        "codigo",
        "tcb",
        "td",
        "tc",
        "sr",
        "cidade",
        "uf",
        "data",
        "segmento",
        "total_segmento",
        "produto",
        "modalidade",
        "valor",
    ]
    return df_long[cols]


@st.cache_data(ttl=3600, show_spinner=False)
def load_carteira_prazo_parquet_fallback(path: str, segmento: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    return _df_cache_to_long(pd.read_parquet(p).copy(), segmento)


@st.cache_data(ttl=3600, show_spinner=False)
def load_carteira_prazo_cache_segment(segmento: str) -> pd.DataFrame:
    try:
        from utils.ifdata_cache import get_manager
    except Exception:
        return pd.DataFrame()

    manager = get_manager()
    if manager is None:
        return pd.DataFrame()

    tipo_cache = "carteira_pf" if segmento == "PF" else "carteira_pj"
    resultado = manager.carregar(tipo_cache)
    if resultado.sucesso and resultado.dados is not None:
        return _df_cache_to_long(resultado.dados.copy(), segmento)
    return pd.DataFrame()


def compute_pct_total_produto(df_long: pd.DataFrame) -> pd.DataFrame:
    if df_long.empty:
        return df_long

    keys = ["codigo", "instituicao", "data", "segmento", "produto"]
    totals = (
        df_long[df_long["modalidade"].astype(str) == "Total"][keys + ["valor"]]
        .rename(columns={"valor": "total_produto"})
        .drop_duplicates(subset=keys)
    )

    out = df_long.merge(totals, on=keys, how="left")
    out["pct_total_produto"] = np.where(
        out["total_produto"].notna() & (out["total_produto"] != 0),
        out["valor"] / out["total_produto"],
        np.nan,
    )
    return out


def compute_prazo_medio(df_long: pd.DataFrame, incluir_vencido: bool = False) -> pd.DataFrame:
    if df_long.empty:
        return pd.DataFrame(columns=["codigo", "instituicao", "data", "segmento", "produto", "prazo_medio_dias"])

    df = df_long.copy()
    df["modalidade"] = df["modalidade"].astype(str)
    df = df[df["modalidade"] != "Total"]
    if not incluir_vencido:
        df = df[df["modalidade"] != "Vencido a Partir de 15 Dias"]

    df["teto_dias"] = df["modalidade"].map(PRAZO_TETO_DIAS)
    df = df[df["teto_dias"].notna() & df["valor"].notna()]

    keys = ["codigo", "instituicao", "data", "segmento", "produto"]
    grouped = (
        df.assign(_num=df["valor"] * df["teto_dias"], _den=df["valor"])
        .groupby(keys, as_index=False)
        .agg(numerador=("_num", "sum"), denominador=("_den", "sum"))
    )
    grouped["prazo_medio_dias"] = np.where(
        grouped["denominador"].notna() & (grouped["denominador"] != 0),
        grouped["numerador"] / grouped["denominador"],
        np.nan,
    )
    return grouped[keys + ["prazo_medio_dias"]]


@st.cache_data(ttl=3600, show_spinner=False)
def _load_both_segments() -> pd.DataFrame:
    dfs = []
    pairs = ["PF", "PJ"]
    for seg in pairs:
        df = load_carteira_prazo_cache_segment(seg)
        if df.empty:
            parquet_path = "data/cache/carteira_pf/dados.parquet" if seg == "PF" else "data/cache/carteira_pj/dados.parquet"
            df = load_carteira_prazo_parquet_fallback(parquet_path, seg)
        if df.empty:
            continue
        dfs.append(df)
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)


def _build_bank_options(df: pd.DataFrame) -> pd.DataFrame:
    base = df[["codigo", "instituicao"]].copy()
    base["codigo_key"] = (
        base["codigo"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    )
    base = base[~base["codigo_key"].isin(["", "nan", "None"])].drop_duplicates(subset=["codigo_key"], keep="first")
    base["label"] = base["codigo_key"] + " - " + base["instituicao"].astype(str)
    return base.sort_values(["instituicao", "codigo"])


def render_carteira_prazo_modalidade_tab() -> None:
    st.markdown("### Carteira - Prazo e Modalidade")
    st.caption("Fonte padrão: caches persistidos dos relatórios 11 (PF) e 13 (PJ).")

    df_long = _load_both_segments()
    if df_long.empty:
        st.warning("Sem dados nos caches persistidos carteira_pf/carteira_pj.")
        return

    df_long = compute_pct_total_produto(df_long)

    col_f1, col_f2, col_f3 = st.columns([1, 2, 2])
    with col_f1:
        segmentos_disp = sorted([s for s in df_long["segmento"].dropna().unique().tolist() if s])
        segmento_sel = st.selectbox("Segmento", ["Todos"] + segmentos_disp, index=0)

    df_seg = df_long.copy()
    if segmento_sel != "Todos":
        df_seg = df_seg[df_seg["segmento"] == segmento_sel]
    df_seg["_codigo_key"] = (
        df_seg["codigo"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    )

    bank_opts = _build_bank_options(df_seg)
    if bank_opts.empty:
        st.info("Sem bancos disponíveis para os filtros atuais.")
        return

    with col_f2:
        instituicoes = sorted(df_seg["instituicao"].dropna().astype(str).unique().tolist())
        inst_sel = st.multiselect("Instituição", instituicoes, default=instituicoes[:1])

    with col_f3:
        cod_options = bank_opts["codigo_key"].astype(str).tolist()
        cod_sel = st.multiselect("Código", cod_options, default=cod_options[: min(3, len(cod_options))])

    allowed_codes = set(bank_opts["codigo_key"].dropna().astype(str))
    if inst_sel:
        allowed_by_inst = set(
            bank_opts[bank_opts["instituicao"].isin(inst_sel)]["codigo_key"].dropna().astype(str)
        )
        allowed_codes &= allowed_by_inst
    if cod_sel:
        allowed_codes &= set(cod_sel)

    df_f = df_seg[df_seg["_codigo_key"].isin(allowed_codes)].copy()
    if df_f.empty:
        st.info("Sem dados para a combinação de bancos selecionada.")
        return

    col_p1, col_p2, col_p3 = st.columns([2, 2, 2])
    with col_p1:
        produtos = sorted(df_f["produto"].dropna().astype(str).unique().tolist())
        produto_sel = st.selectbox("Produto", produtos, index=0)

    df_f = df_f[df_f["produto"] == produto_sel].copy()

    with col_p2:
        mostrar_total = st.checkbox("Mostrar modalidade Total", value=False)

    modalidades_disp = [m for m in CANONICAL_MODALIDADES if m in df_f["modalidade"].astype(str).unique()]
    modalidades_default = [m for m in modalidades_disp if m != "Total"]
    if mostrar_total and "Total" in modalidades_disp and "Total" not in modalidades_default:
        modalidades_default = modalidades_default + ["Total"]

    with col_p3:
        modalidades_sel = st.multiselect(
            "Modalidades",
            modalidades_disp,
            default=modalidades_default,
        )

    col_m1, col_m2, col_m3 = st.columns([2, 1, 1])
    with col_m1:
        metrica = st.radio(
            "Métrica",
            ["% do Total do produto", "Valor absoluto"],
            horizontal=True,
            index=0,
        )
    with col_m2:
        calcular_prazo = st.checkbox("Calcular prazo médio ponderado", value=True)
    with col_m3:
        incluir_vencido = st.checkbox("Incluir vencido no prazo médio", value=False)

    if not modalidades_sel:
        st.info("Selecione ao menos uma modalidade.")
        return

    df_plot = df_f[df_f["modalidade"].astype(str).isin(modalidades_sel)].copy()
    if not mostrar_total:
        df_plot = df_plot[df_plot["modalidade"].astype(str) != "Total"]

    bank_labels = (
        df_plot[["codigo", "instituicao"]]
        .drop_duplicates()
        .assign(
            bank_label=lambda x: (
                x["codigo"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
                + " - "
                + x["instituicao"].astype(str)
            )
        )
    )
    df_plot = df_plot.merge(bank_labels, on=["codigo", "instituicao"], how="left")

    y_col = "pct_total_produto" if metrica == "% do Total do produto" else "valor"
    y_title = "% do total do produto" if metrica == "% do Total do produto" else "Valor"

    modo_graf1 = st.radio(
        "Modo gráfico 1",
        ["Comparar bancos juntos", "Um banco por vez"],
        horizontal=True,
        index=0,
    )

    st.markdown("#### Série histórica por modalidade")
    if modo_graf1 == "Um banco por vez":
        banks = sorted(df_plot["bank_label"].dropna().unique().tolist())
        bank_one = st.selectbox("Banco (gráfico 1)", banks, index=0)
        df_g1 = df_plot[df_plot["bank_label"] == bank_one].copy()
        fig1 = px.line(
            df_g1.sort_values("data"),
            x="data",
            y=y_col,
            color="modalidade",
            markers=True,
            title=f"{produto_sel} - {bank_one}",
            hover_data=["instituicao", "codigo", "valor", "pct_total_produto", "total_produto"],
        )
    else:
        fig1 = px.line(
            df_plot.sort_values("data"),
            x="data",
            y=y_col,
            color="modalidade",
            line_dash="bank_label",
            markers=True,
            title=f"{produto_sel} - comparação entre bancos",
            hover_data=["instituicao", "codigo", "valor", "pct_total_produto", "total_produto"],
        )

    if metrica == "% do Total do produto":
        fig1.update_yaxes(tickformat=".1%")
    fig1.update_layout(template="plotly_white", yaxis_title=y_title, legend_title_text="Legenda")
    st.plotly_chart(fig1, width="stretch", config={"displayModeBar": False})

    prazo_df = pd.DataFrame()
    if calcular_prazo:
        prazo_df = compute_prazo_medio(df_f, incluir_vencido=incluir_vencido)
        prazo_df = prazo_df.merge(bank_labels, on=["codigo", "instituicao"], how="left")
        st.markdown("#### Série histórica do prazo médio ponderado")
        fig2 = px.line(
            prazo_df.sort_values("data"),
            x="data",
            y="prazo_medio_dias",
            color="bank_label",
            markers=True,
            title="Prazo médio ponderado (dias)",
            hover_data=["instituicao", "codigo", "produto"],
        )
        fig2.update_layout(
            template="plotly_white",
            yaxis_title="Prazo médio (dias)",
            legend_title_text="Banco",
        )
        fig2.update_traces(
            hovertemplate=(
                "Data=%{x|%Y-%m-%d}<br>Banco=%{customdata[0]}<br>Prazo médio=%{y:.1f} dias"
                "<extra></extra>"
            )
        )
        st.plotly_chart(fig2, width="stretch", config={"displayModeBar": False})

        st.caption(
            "Prazo médio usa teto por faixa; para 'Acima de 5400 dias' aplica cap em 5400 dias. "
            "A modalidade 'Total' é excluída do cálculo."
        )

    table_df = df_plot.copy()
    if calcular_prazo and not prazo_df.empty:
        table_df = table_df.merge(
            prazo_df[["codigo", "instituicao", "data", "segmento", "produto", "prazo_medio_dias"]],
            on=["codigo", "instituicao", "data", "segmento", "produto"],
            how="left",
        )

    table_cols = [
        "data",
        "instituicao",
        "codigo",
        "produto",
        "modalidade",
        "valor",
        "pct_total_produto",
        "total_produto",
    ]
    if calcular_prazo:
        table_cols.append("prazo_medio_dias")

    st.markdown("#### Tabela")
    st.dataframe(
        table_df[table_cols].sort_values(["data", "instituicao", "modalidade"], ascending=[False, True, True]),
        width="stretch",
        hide_index=True,
    )

    with st.expander("Validações rápidas", expanded=False):
        val_base = df_f.copy()
        if not val_base.empty:
            amostra = val_base.dropna(subset=["codigo", "data"]).sort_values("data").iloc[-1]
            filtro = (
                (val_base["codigo"] == amostra["codigo"])
                & (val_base["produto"] == amostra["produto"])
                & (val_base["data"] == amostra["data"])
            )
            chk = val_base[filtro]
            soma_modalidades = chk[chk["modalidade"].astype(str) != "Total"]["valor"].sum(min_count=1)
            total_linha = chk[chk["modalidade"].astype(str) == "Total"]["valor"].sum(min_count=1)
            soma_pct = chk[chk["modalidade"].astype(str) != "Total"]["pct_total_produto"].sum(min_count=1)
            st.write(
                {
                    "codigo": str(amostra["codigo"]) if pd.notna(amostra["codigo"]) else None,
                    "data": amostra["data"].strftime("%Y-%m-%d") if pd.notna(amostra["data"]) else None,
                    "produto": amostra["produto"],
                    "soma_modalidades_sem_total": soma_modalidades,
                    "total_modalidade_total": total_linha,
                    "soma_pct_sem_total": soma_pct,
                }
            )
