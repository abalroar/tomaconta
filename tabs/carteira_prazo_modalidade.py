from __future__ import annotations

from pathlib import Path
import re
import unicodedata

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st


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
    txt = "" if value is None else str(value)
    txt = " ".join(txt.strip().split())
    if not txt:
        return ""
    txt = unicodedata.normalize("NFKD", txt)
    txt = "".join(ch for ch in txt if not unicodedata.combining(ch))
    return txt.lower()


def _coerce_number(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip()
    s = s.replace({"": np.nan, "NI": np.nan, "ni": np.nan, "N/I": np.nan, "n/i": np.nan})
    has_comma = s.str.contains(",", na=False)
    s = s.str.replace(".", "", regex=False)
    s = s.where(~has_comma, s.str.replace(",", ".", regex=False))
    return pd.to_numeric(s, errors="coerce")


def normalize_modalidade_text(value: object) -> str:
    txt = "" if value is None else str(value)
    txt = " ".join(txt.strip().split())
    if not txt:
        return ""

    n = _norm_text(txt)
    if n == "total":
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


def _periodo_to_datetime(periodo: object) -> pd.Timestamp | pd.NaT:
    if periodo is None or (isinstance(periodo, float) and np.isnan(periodo)):
        return pd.NaT
    txt = str(periodo).strip()
    m = re.match(r"^(\d{1,2})\/(\d{4})$", txt)
    if not m:
        return pd.NaT
    p1 = int(m.group(1))
    ano = int(m.group(2))
    if 1 <= p1 <= 4:
        mes = {1: 3, 2: 6, 3: 9, 4: 12}[p1]
    elif 1 <= p1 <= 12:
        mes = p1
    else:
        return pd.NaT
    return pd.Timestamp(year=ano, month=mes, day=1)


def _periodo_exib_to_api(periodo_exib: object) -> str | None:
    if periodo_exib is None:
        return None
    txt = str(periodo_exib).strip()
    m = re.match(r"^(\d{1,2})\/(\d{4})$", txt)
    if not m:
        return None
    p1 = int(m.group(1))
    ano = int(m.group(2))
    if 1 <= p1 <= 4:
        mes = {1: "03", 2: "06", 3: "09", 4: "12"}[p1]
    elif 1 <= p1 <= 12:
        mes = f"{p1:02d}"
    else:
        return None
    return f"{ano}{mes}"


def _periodo_api_to_data(periodo_api: str) -> pd.Timestamp | pd.NaT:
    if not periodo_api or len(periodo_api) != 6:
        return pd.NaT
    try:
        ano = int(periodo_api[:4])
        mes = int(periodo_api[4:])
        return pd.Timestamp(year=ano, month=mes, day=1)
    except Exception:
        return pd.NaT


def _extract_codigo_from_instituicao(series: pd.Series) -> pd.Series:
    return series.astype(str).str.extract(r"\[IF\s*(\d+)\]", expand=False)


def _resolve_meta_col(meta_map: dict[str, str], aliases: list[str]) -> str | None:
    for alias in aliases:
        if alias in meta_map:
            return meta_map[alias]
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def load_carteira_prazo_csv(path: str) -> pd.DataFrame:
    """Parser CSV compatível com header duplo (produto x modalidade).

    Esta função é utilitária (fallback/compat) e não é a fonte principal da aba.
    """
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()

    df_raw = pd.read_csv(
        p,
        sep=";",
        encoding="utf-8-sig",
        header=[0, 1],
        dtype=str,
        low_memory=False,
    )

    h0 = ["" if x is None else str(x) for x in df_raw.columns.get_level_values(0)]
    h1 = ["" if x is None else str(x) for x in df_raw.columns.get_level_values(1)]
    h0 = ["" if x.startswith("Unnamed:") else " ".join(x.strip().split()) for x in h0]
    h1 = ["" if x.startswith("Unnamed:") else " ".join(x.strip().split()) for x in h1]

    matrix_start = 0
    for i, val in enumerate(h1):
        if val:
            matrix_start = i
            break

    meta_idx = list(range(matrix_start))
    matrix_idx = list(range(matrix_start, len(h0)))

    meta_names = [h0[i] or h1[i] or f"meta_{i}" for i in meta_idx]
    df_meta = df_raw.iloc[:, meta_idx].copy()
    df_meta.columns = meta_names

    norm_map = {_norm_text(c): c for c in df_meta.columns}
    col_instituicao = _resolve_meta_col(norm_map, ["instituicao", "instituicao financeira", "if"])
    col_codigo = _resolve_meta_col(norm_map, ["codigo", "cod", "codinst", "codigo da instituicao", "codigo instituicao"])
    col_data = _resolve_meta_col(norm_map, ["data", "mes", "periodo", "período"])

    total_pf_col = _resolve_meta_col(norm_map, ["total da carteira de pessoa fisica"])
    total_pj_col = _resolve_meta_col(norm_map, ["total da carteira de pessoa juridica"])

    segmento = ""
    total_segmento_col = None
    if total_pf_col is not None:
        segmento = "PF"
        total_segmento_col = total_pf_col
    elif total_pj_col is not None:
        segmento = "PJ"
        total_segmento_col = total_pj_col

    produtos = []
    current = ""
    for idx in matrix_idx:
        if h0[idx]:
            current = h0[idx]
        produtos.append(current)

    matrix = {}
    for j, idx in enumerate(matrix_idx):
        produto = produtos[j]
        modalidade = normalize_modalidade_text(h1[idx])
        if not produto or not modalidade:
            continue
        matrix[f"{produto}|||{modalidade}"] = df_raw.iloc[:, idx]

    if not matrix:
        return pd.DataFrame()

    id_df = pd.DataFrame(
        {
            "instituicao": df_meta[col_instituicao] if col_instituicao else np.nan,
            "codigo": df_meta[col_codigo] if col_codigo else np.nan,
            "data": df_meta[col_data] if col_data else np.nan,
            "segmento": segmento,
            "total_segmento": df_meta[total_segmento_col] if total_segmento_col else np.nan,
        }
    )

    wide = pd.concat([id_df, pd.DataFrame(matrix)], axis=1)
    long = wide.melt(
        id_vars=["instituicao", "codigo", "data", "segmento", "total_segmento"],
        value_vars=list(matrix.keys()),
        var_name="produto_modalidade",
        value_name="valor",
    )
    split = long["produto_modalidade"].str.split("|||", n=1, expand=True)
    long["produto"] = split[0]
    long["modalidade"] = split[1].apply(normalize_modalidade_text)
    long.drop(columns=["produto_modalidade"], inplace=True)

    long["data"] = pd.to_datetime("01/" + long["data"].astype(str), format="%d/%m/%Y", errors="coerce")
    long["codigo"] = _coerce_number(long["codigo"])
    long["total_segmento"] = _coerce_number(long["total_segmento"])
    long["valor"] = _coerce_number(long["valor"])
    long["modalidade"] = pd.Categorical(long["modalidade"], categories=CANONICAL_MODALIDADES, ordered=True)
    return long[["instituicao", "codigo", "data", "segmento", "produto", "modalidade", "valor", "total_segmento"]]


def _melt_cache_df(df: pd.DataFrame, segmento: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    lower_cols = {c.lower(): c for c in df.columns}
    col_inst = lower_cols.get("instituição") or lower_cols.get("instituicao")
    col_periodo = lower_cols.get("período") or lower_cols.get("periodo")
    if not col_inst or not col_periodo:
        return pd.DataFrame()

    total_segmento_col = next(
        (
            c
            for c in df.columns
            if "total da carteira de pessoa fisica" in _norm_text(c)
            or "total da carteira de pessoa juridica" in _norm_text(c)
        ),
        None,
    )

    modalidade_source_cols = [c for c in df.columns if normalize_modalidade_text(c) in CANONICAL_MODALIDADES]
    if not modalidade_source_cols:
        return pd.DataFrame()

    base = df[[col_inst, col_periodo] + ([total_segmento_col] if total_segmento_col else []) + modalidade_source_cols].copy()
    base = base.rename(columns={col_inst: "instituicao", col_periodo: "periodo"})
    base["codigo"] = _extract_codigo_from_instituicao(base["instituicao"])
    base["data"] = base["periodo"].apply(_periodo_to_datetime)
    base["segmento"] = segmento
    base["produto"] = "Carteira Total"
    base["total_segmento"] = pd.to_numeric(base[total_segmento_col], errors="coerce") if total_segmento_col else np.nan

    melted = base.melt(
        id_vars=["instituicao", "codigo", "data", "segmento", "produto", "total_segmento"],
        value_vars=modalidade_source_cols,
        var_name="modalidade_source",
        value_name="valor",
    )
    melted["modalidade"] = melted["modalidade_source"].apply(normalize_modalidade_text)
    melted["valor"] = pd.to_numeric(melted["valor"], errors="coerce")

    # Consolida variantes de rótulo da mesma modalidade (ex.: "Dias" vs "dias").
    keys = ["instituicao", "codigo", "data", "segmento", "produto", "total_segmento", "modalidade"]
    out = melted.groupby(keys, as_index=False)["valor"].sum(min_count=1)
    out["modalidade"] = pd.Categorical(out["modalidade"], categories=CANONICAL_MODALIDADES, ordered=True)
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def _load_relatorio_raw_long(periodos_api: tuple[str, ...], relatorio: int, segmento: str) -> pd.DataFrame:
    """Extrai rel. 11/13 bruto da API e preserva dimensão de produto (Grupo)."""
    try:
        from utils.ifdata_cache.extractor import extrair_cadastro, extrair_valores
    except Exception:
        return pd.DataFrame()

    rows = []
    for periodo in periodos_api:
        if not periodo:
            continue
        df_val = extrair_valores(periodo, relatorio)
        if df_val is None or df_val.empty:
            continue

        df_cad = extrair_cadastro(periodo)
        nome_col = None
        if df_cad is not None and not df_cad.empty:
            for cand in ["NomeInstituicao", "NomeInstituição"]:
                if cand in df_cad.columns:
                    nome_col = cand
                    break
        nome_map = (
            df_cad[["CodInst", nome_col]].drop_duplicates().set_index("CodInst")[nome_col].to_dict()
            if nome_col
            else {}
        )

        tmp = df_val.copy()
        tmp["CodInst"] = tmp["CodInst"].astype(str)
        tmp["instituicao"] = tmp["CodInst"].map(nome_map).fillna(tmp["CodInst"].apply(lambda x: f"[IF {x}]"))
        tmp["codigo"] = tmp["CodInst"]
        tmp["data"] = _periodo_api_to_data(periodo)
        tmp["segmento"] = segmento
        tmp["modalidade"] = tmp["NomeColuna"].apply(normalize_modalidade_text)
        tmp["valor"] = pd.to_numeric(tmp.get("Saldo"), errors="coerce")
        tmp["produto"] = tmp["Grupo"].astype(str).str.strip()
        tmp.loc[tmp["Grupo"].isna() | (tmp["produto"] == ""), "produto"] = np.nan

        total_seg_nome = "Total da Carteira de Pessoa Física" if segmento == "PF" else "Total da Carteira de Pessoa Jurídica"
        total_seg = (
            tmp[tmp["NomeColuna"].astype(str).str.strip() == total_seg_nome][["codigo", "data", "valor"]]
            .rename(columns={"valor": "total_segmento"})
            .drop_duplicates(subset=["codigo", "data"])
        )

        # Linhas com produto explícito (Grupo) + modalidade de prazo/total.
        parte_prod = tmp[tmp["produto"].notna() & tmp["modalidade"].isin(CANONICAL_MODALIDADES)][
            ["instituicao", "codigo", "data", "segmento", "produto", "modalidade", "valor"]
        ]

        # Total exterior entra como produto próprio com modalidade Total.
        exterior_label = "Total Exterior Pessoa Física" if segmento == "PF" else "Total Exterior Pessoa Jurídica"
        parte_ext = tmp[tmp["NomeColuna"].astype(str).str.strip() == exterior_label].copy()
        if not parte_ext.empty:
            parte_ext = parte_ext.assign(produto=exterior_label, modalidade="Total")[
                ["instituicao", "codigo", "data", "segmento", "produto", "modalidade", "valor"]
            ]
            parte_prod = pd.concat([parte_prod, parte_ext], ignore_index=True)

        if parte_prod.empty:
            continue

        parte_prod = parte_prod.merge(total_seg, on=["codigo", "data"], how="left")
        rows.append(parte_prod)

    if not rows:
        return pd.DataFrame()

    out = pd.concat(rows, ignore_index=True)
    out = out.groupby(
        ["instituicao", "codigo", "data", "segmento", "produto", "modalidade", "total_segmento"],
        as_index=False,
    )["valor"].sum(min_count=1)
    out["modalidade"] = pd.Categorical(out["modalidade"], categories=CANONICAL_MODALIDADES, ordered=True)
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def load_carteira_prazo_long() -> pd.DataFrame:
    """Carrega Relatórios 11/13 reais do cache do app e normaliza para long."""
    frames = []

    try:
        from utils.ifdata_cache import get_manager

        manager = get_manager()
    except Exception:
        manager = None

    mapping = [("carteira_pf", "PF", 11), ("carteira_pj", "PJ", 13)]
    for tipo_cache, segmento, relatorio in mapping:
        df_raw = pd.DataFrame()

        if manager is not None:
            result = manager.carregar(tipo_cache)
            if result.sucesso and result.dados is not None and not result.dados.empty:
                df_raw = result.dados.copy()

        if df_raw.empty:
            parquet_path = Path(f"data/cache/{tipo_cache}/dados.parquet")
            if parquet_path.exists():
                df_raw = pd.read_parquet(parquet_path)

        periodos_api = tuple(
            sorted(
                {
                    _periodo_exib_to_api(p)
                    for p in (df_raw["Período"].dropna().unique().tolist() if ("Período" in df_raw.columns) else [])
                    if _periodo_exib_to_api(p) is not None
                }
            )
        )

        df_long = _load_relatorio_raw_long(periodos_api, relatorio, segmento) if periodos_api else pd.DataFrame()
        if df_long.empty:
            df_long = _melt_cache_df(df_raw, segmento)
        if not df_long.empty:
            frames.append(df_long)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    cols = ["instituicao", "codigo", "data", "segmento", "produto", "modalidade", "valor", "total_segmento"]
    return df[cols]


def compute_pct_total_produto(df_long: pd.DataFrame) -> pd.DataFrame:
    if df_long.empty:
        return df_long

    keys = ["instituicao", "codigo", "data", "segmento", "produto"]
    total_prod = (
        df_long[df_long["modalidade"].astype(str) == "Total"][keys + ["valor"]]
        .rename(columns={"valor": "total_produto"})
        .drop_duplicates(subset=keys)
    )

    out = df_long.merge(total_prod, on=keys, how="left")
    out["pct_total_produto"] = np.where(
        out["total_produto"].notna() & (out["total_produto"] != 0),
        out["valor"] / out["total_produto"],
        np.nan,
    )
    return out


def compute_prazo_medio(df_long: pd.DataFrame, incluir_vencido: bool = False) -> pd.DataFrame:
    if df_long.empty:
        return pd.DataFrame(columns=["instituicao", "codigo", "data", "segmento", "produto", "prazo_medio_dias"])

    df = df_long.copy()
    df["modalidade"] = df["modalidade"].astype(str)
    df = df[df["modalidade"] != "Total"]
    if not incluir_vencido:
        df = df[df["modalidade"] != "Vencido a Partir de 15 Dias"]

    df["teto_dias"] = df["modalidade"].map(PRAZO_TETO_DIAS)
    df = df[df["valor"].notna() & df["teto_dias"].notna()]

    keys = ["instituicao", "codigo", "data", "segmento", "produto"]
    agg = (
        df.assign(num=df["valor"] * df["teto_dias"], den=df["valor"])
        .groupby(keys, as_index=False)
        .agg(num=("num", "sum"), den=("den", "sum"))
    )
    agg["prazo_medio_dias"] = np.where(agg["den"].notna() & (agg["den"] != 0), agg["num"] / agg["den"], np.nan)
    return agg[keys + ["prazo_medio_dias"]]


def _bank_label(df: pd.DataFrame) -> pd.Series:
    cod = df["codigo"].astype(str).str.strip()
    cod = cod.where(~cod.isin(["", "nan", "None"]), "s/código")
    return cod + " - " + df["instituicao"].astype(str)


def _run_quick_checks(df: pd.DataFrame) -> dict:
    out = {
        "datas_ordenaveis": bool(df["data"].notna().any()),
        "modalidade_total_existe": bool((df["modalidade"].astype(str) == "Total").any()),
        "amostra": {},
    }

    dfv = compute_pct_total_produto(df)
    keys = ["instituicao", "codigo", "data", "segmento", "produto"]
    sample_keys = dfv.dropna(subset=["data"])[keys].drop_duplicates()
    if sample_keys.empty:
        return out

    k = sample_keys.sort_values("data").iloc[-1]
    mask = (
        (dfv["instituicao"] == k["instituicao"])
        & (dfv["codigo"].astype(str) == str(k["codigo"]))
        & (dfv["data"] == k["data"])
        & (dfv["segmento"] == k["segmento"])
        & (dfv["produto"] == k["produto"])
    )
    s = dfv[mask]

    soma_buckets = s[s["modalidade"].astype(str) != "Total"]["valor"].sum(min_count=1)
    total_prod = s[s["modalidade"].astype(str) == "Total"]["valor"].sum(min_count=1)
    soma_pct = s[s["modalidade"].astype(str) != "Total"]["pct_total_produto"].sum(min_count=1)

    out["amostra"] = {
        "instituicao": str(k["instituicao"]),
        "codigo": str(k["codigo"]),
        "data": k["data"].strftime("%Y-%m-%d") if pd.notna(k["data"]) else None,
        "produto": str(k["produto"]),
        "soma_buckets_sem_total": float(soma_buckets) if pd.notna(soma_buckets) else None,
        "total_produto": float(total_prod) if pd.notna(total_prod) else None,
        "soma_pct_sem_total": float(soma_pct) if pd.notna(soma_pct) else None,
    }
    return out


def render_carteira_prazo_modalidade_tab() -> None:
    st.markdown("### Carteira - Prazo e Modalidade")
    st.caption("Baseada nos caches reais: Relatório 11 (carteira_pf) e Relatório 13 (carteira_pj).")

    df_long = load_carteira_prazo_long()
    if df_long.empty:
        st.warning("Sem dados nos caches carteira_pf/carteira_pj.")
        st.caption("Esperado: data/cache/carteira_pf/dados.parquet e data/cache/carteira_pj/dados.parquet")
        return

    df_long = compute_pct_total_produto(df_long)

    col_f1, col_f2, col_f3 = st.columns([1, 2, 2])
    with col_f1:
        segmentos = sorted(df_long["segmento"].dropna().unique().tolist())
        segmento_sel = st.selectbox("Segmento", ["Todos"] + segmentos, index=0)

    df = df_long.copy()
    if segmento_sel != "Todos":
        df = df[df["segmento"] == segmento_sel]

    df["bank_label"] = _bank_label(df)

    with col_f2:
        instituicoes = sorted(df["instituicao"].dropna().astype(str).unique().tolist())
        inst_sel = st.multiselect("Instituição", instituicoes, default=instituicoes[:1])

    with col_f3:
        df_codes_scope = df[df["instituicao"].isin(inst_sel)] if inst_sel else df
        codigos = sorted(
            [
                c
                for c in df_codes_scope["codigo"].astype(str).str.strip().unique().tolist()
                if c and c not in ["nan", "None"]
            ]
        )
        cod_sel = st.multiselect(
            "Código (CodInst IFData)",
            codigos,
            default=[],
            help="Identificador interno CodInst do IFData (não é código COMPE). Deixe vazio para não filtrar por código.",
        )

    if inst_sel:
        df = df[df["instituicao"].isin(inst_sel)]
    if cod_sel:
        df = df[df["codigo"].astype(str).isin(cod_sel)]

    if df.empty:
        st.info("Sem dados para os filtros selecionados.")
        return

    col_p1, col_p2, col_p3 = st.columns([2, 2, 2])
    with col_p1:
        produtos = sorted(df["produto"].dropna().astype(str).unique().tolist())
        produto_sel = st.selectbox("Produto", produtos, index=0)
    df = df[df["produto"] == produto_sel].copy()

    with col_p2:
        mostrar_total = st.checkbox("Mostrar modalidade Total", value=False)

    modalidades_disp = [m for m in CANONICAL_MODALIDADES if m in df["modalidade"].astype(str).unique()]
    modalidades_default = [m for m in modalidades_disp if m != "Total"]
    if mostrar_total and "Total" in modalidades_disp and "Total" not in modalidades_default:
        modalidades_default.append("Total")

    with col_p3:
        modalidades_sel = st.multiselect("Modalidades", modalidades_disp, default=modalidades_default)

    col_m1, col_m2, col_m3 = st.columns([2, 1, 1])
    with col_m1:
        metrica = st.radio("Métrica", ["% do Total do produto", "Valor absoluto"], horizontal=True, index=0)
    with col_m2:
        calcular_prazo = st.checkbox("Calcular prazo médio ponderado", value=True)
    with col_m3:
        incluir_vencido = st.checkbox("Incluir vencido no prazo médio", value=False)

    if not modalidades_sel:
        st.info("Selecione ao menos uma modalidade.")
        return

    df_plot = df[df["modalidade"].astype(str).isin(modalidades_sel)].copy()
    if not mostrar_total:
        df_plot = df_plot[df_plot["modalidade"].astype(str) != "Total"]

    y_col = "pct_total_produto" if metrica == "% do Total do produto" else "valor"
    y_title = "% do total do produto" if metrica == "% do Total do produto" else "Valor"

    modo_g1 = st.radio(
        "Modo gráfico 1",
        ["Comparar bancos juntos", "Um banco por vez"],
        horizontal=True,
        index=0,
    )

    st.markdown("#### Série histórica por modalidade")
    if modo_g1 == "Um banco por vez":
        bancos = sorted(df_plot["bank_label"].dropna().unique().tolist())
        banco_sel = st.selectbox("Banco (gráfico 1)", bancos, index=0)
        g1 = df_plot[df_plot["bank_label"] == banco_sel].copy()
        fig1 = px.line(
            g1.sort_values("data"),
            x="data",
            y=y_col,
            color="modalidade",
            markers=True,
            title=f"{produto_sel} - {banco_sel}",
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
        prazo_df = compute_prazo_medio(df, incluir_vencido=incluir_vencido)
        prazo_df["bank_label"] = _bank_label(prazo_df)
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
        fig2.update_layout(template="plotly_white", yaxis_title="Prazo médio (dias)", legend_title_text="Banco")
        st.plotly_chart(fig2, width="stretch", config={"displayModeBar": False})
        st.caption("Cap por faixa: acima de 5400 dias é truncado para 5400. A modalidade Total é excluída do cálculo.")

    table_df = df_plot.copy()
    if calcular_prazo and not prazo_df.empty:
        table_df = table_df.merge(
            prazo_df[["instituicao", "codigo", "data", "segmento", "produto", "prazo_medio_dias"]],
            on=["instituicao", "codigo", "data", "segmento", "produto"],
            how="left",
        )

    cols = ["data", "instituicao", "codigo", "produto", "modalidade", "valor", "pct_total_produto", "total_produto"]
    if calcular_prazo:
        cols.append("prazo_medio_dias")

    st.markdown("#### Tabela")
    st.dataframe(
        table_df[cols].sort_values(["data", "instituicao", "modalidade"], ascending=[False, True, True]),
        width="stretch",
        hide_index=True,
    )

    with st.expander("Validações rápidas", expanded=False):
        checks = _run_quick_checks(df)
        st.write(checks)
