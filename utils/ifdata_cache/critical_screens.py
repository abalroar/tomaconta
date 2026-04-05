"""Cache curado para Snapshot e Peers."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Sequence

import pandas as pd

from .availability import display_period_to_api, filter_supported_periods
from .base import BaseCache, CacheConfig, CacheResult
from .bloprudencial import load_bloprudencial_df_cached
from .institutions import build_institution_to_conglomerate_map, canonicalize_institution_name, normalize_institution_name

if TYPE_CHECKING:
    from .manager import CacheManager

logger = logging.getLogger("ifdata_cache")


CRITICAL_SCREENS_CONFIG = CacheConfig(
    nome="critical_screens",
    descricao="Métricas curadas para Snapshot e Peers",
    subdir="critical_screens",
    arquivo_dados="dados.parquet",
    arquivo_metadata="metadata.json",
    github_url_base=None,
    max_idade_horas=None,
    colunas_obrigatorias=["Instituição", "Período", "InstituiçãoKey"],
)


CRITICAL_EXTRA_METRICS = [
    "Ativos Líquidos",
    "Depósitos Totais",
    "Core Funding",
    "Core Funding*",
    "Carteira de Crédito Bruta",
    "Carteira de Crédito*",
    "Perda Esperada",
    "Perda Esperada / Carteira de Crédito Bruta",
    "Perda Esperada / Carteira de Crédito*",
    "Carteira de Crédito Classificada",
    "Carteira de Créd. Class. C4+C5",
    "Carteira de Créd. Class. C4+C5 / Carteira Classificada",
    "Perda Esperada / (Carteira C4 + C5)",
    "Saldo PDD Crédito",
    "Saldo PDD Outros Créditos",
    "PDD Total 4060",
    "Carteira Estágio 1",
    "Ativos Estágio 2",
    "Ativos Estágio 3",
    "PDD / Estágio 3",
    "Perda Esperada / Estágio 3",
    "Índice de Capital Principal (CET1)",
    "Índice de Basileia Total (%)",
]


SOURCE_CACHE_TYPES = [
    "principal",
    "capital",
    "ativo",
    "passivo",
    "dre",
    "carteira_pf",
    "carteira_pj",
    "carteira_instrumentos",
]


class CriticalScreensCache(BaseCache):
    """Cache materializado para consumo rápido das telas críticas."""

    def __init__(self, base_dir: Path):
        super().__init__(CRITICAL_SCREENS_CONFIG, base_dir)

    def baixar_remoto(self):
        return CacheResult(
            sucesso=False,
            mensagem="Cache critical_screens não possui fonte remota",
            fonte="nenhum",
        )

    def extrair_periodo(self, periodo: str, **kwargs):
        return CacheResult(
            sucesso=False,
            mensagem="Cache critical_screens não suporta extração por período",
            fonte="nenhum",
        )


def _normalize_period_display(periodo: str | None) -> str:
    return str(periodo or "").strip()


def _api_to_display_period(periodo_api: str) -> str:
    ano = periodo_api[:4]
    mes = periodo_api[4:6]
    trimestre = {"03": "1", "06": "2", "09": "3", "12": "4"}.get(mes)
    if trimestre is not None:
        return f"{trimestre}/{ano}"
    return f"{mes}/{ano}"


def _pick_col(df: Optional[pd.DataFrame], candidates: Sequence[str]) -> Optional[str]:
    if df is None or df.empty:
        return None

    cols = list(df.columns)
    if not cols:
        return None

    normalized = {normalize_institution_name(str(col)): col for col in cols}
    for candidate in candidates:
        key = normalize_institution_name(candidate)
        if key in normalized:
            return normalized[key]

    for candidate in candidates:
        key = normalize_institution_name(candidate)
        for col in cols:
            col_key = normalize_institution_name(col)
            if key and (key in col_key or col_key in key):
                return col
    return None


def _pick_exact_col(df: Optional[pd.DataFrame], candidates: Sequence[str]) -> Optional[str]:
    if df is None or df.empty:
        return None
    normalized = {normalize_institution_name(str(col)): col for col in df.columns}
    for candidate in candidates:
        key = normalize_institution_name(candidate)
        if key in normalized:
            return normalized[key]
    return None


def _coerce_numeric_value(value) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    try:
        coerced = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    except Exception:
        return None
    if pd.isna(coerced):
        return None
    return float(coerced)


def _sum_values(values: Iterable[object]) -> Optional[float]:
    nums = [_coerce_numeric_value(v) for v in values]
    nums = [v for v in nums if v is not None]
    if not nums:
        return None
    return float(sum(nums))


def _calc_ratio(valor_num, valor_den) -> Optional[float]:
    num = _coerce_numeric_value(valor_num)
    den = _coerce_numeric_value(valor_den)
    if num is None or den is None or den == 0:
        return None
    return float(num) / float(den)


def _prepare_frame(
    df: Optional[pd.DataFrame],
    catalog_map: Dict[str, str],
    *,
    canonicalize_names: bool = True,
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if "Instituição" not in out.columns or "Período" not in out.columns:
        return pd.DataFrame()

    if canonicalize_names:
        nomes_brutos = out["Instituição"].astype(str)
        mapa_canonico = {
            nome: canonicalize_institution_name(nome, catalog_map=catalog_map)
            for nome in nomes_brutos.dropna().unique().tolist()
        }
        out["Instituição"] = nomes_brutos.map(mapa_canonico).fillna(nomes_brutos)
    else:
        out["Instituição"] = out["Instituição"].astype(str).str.strip()

    out["Período"] = out["Período"].astype(str).str.strip()
    out["InstituiçãoKey"] = out["Instituição"].map(normalize_institution_name)
    out = out[out["InstituiçãoKey"].astype(bool)].copy()
    out = out.drop_duplicates(subset=["InstituiçãoKey", "Período"], keep="last")
    return out


def _prepare_lookup(df: Optional[pd.DataFrame], columns: Sequence[Optional[str]]) -> Dict[tuple[str, str], dict]:
    if df is None or df.empty:
        return {}
    valid_columns = list(dict.fromkeys([col for col in columns if col and col in df.columns]))
    if not valid_columns:
        return {}
    base = df[["InstituiçãoKey", "Período", *valid_columns]].copy()
    base = base.dropna(subset=["InstituiçãoKey", "Período"])
    if base.empty:
        return {}
    return base.set_index(["InstituiçãoKey", "Período"]).to_dict("index")


def _lk_get(lookup: Dict[tuple[str, str], dict], institution_key: str, periodo: str, coluna: Optional[str]):
    if not lookup or not coluna:
        return None
    row = lookup.get((institution_key, periodo))
    if row is None:
        return None
    return row.get(coluna)


def _list_local_bloprud_periods(base_dir: Path) -> set[str]:
    periodos: set[str] = set()
    cache_dir = base_dir / "data" / "cache" / "bcb_bloprudencial"
    for pattern in ("csv/*BLOPRUDENCIAL*.CSV", "zips/*BLOPRUDENCIAL*.zip"):
        for path in cache_dir.glob(pattern):
            match = re.match(r"(\d{6})BLOPRUDENCIAL", path.name.upper())
            if match:
                periodos.add(match.group(1))
    for path in base_dir.glob("*BLOPRUDENCIAL*.CSV"):
        match = re.match(r"(\d{6})BLOPRUDENCIAL", path.name.upper())
        if match:
            periodos.add(match.group(1))
    return periodos


def _load_bloprud_periods(base_dir: Path, periodos_display: Sequence[str]) -> pd.DataFrame:
    periodos_desejados = sorted(
        {display_period_to_api(periodo) for periodo in periodos_display if display_period_to_api(periodo)}
    )
    periodos_locais = _list_local_bloprud_periods(base_dir)
    if periodos_locais:
        periodos_api = [periodo for periodo in periodos_desejados if periodo in periodos_locais]
        faltantes = sorted(set(periodos_desejados) - set(periodos_api))
        if faltantes:
            logger.info(
                "[CACHE:CRITICAL_SCREENS] BLOPRUDENCIAL indisponível localmente para %d período(s): %s",
                len(faltantes),
                ", ".join(faltantes[:8]),
            )
    else:
        periodos_api = []
    if not periodos_api:
        return pd.DataFrame()

    dfs = []
    for periodo_api in periodos_api:
        try:
            df_periodo = load_bloprudencial_df_cached(
                periodo_api,
                cache_dir=str(base_dir / "data" / "cache" / "bcb_bloprudencial"),
                force_refresh=False,
            )
        except Exception as exc:
            logger.warning("[CACHE:CRITICAL_SCREENS] Falha ao carregar BLOPRUDENCIAL %s: %s", periodo_api, exc)
            continue
        if df_periodo is None or df_periodo.empty:
            continue
        df_periodo = df_periodo.copy()
        df_periodo["Período"] = _api_to_display_period(periodo_api)
        dfs.append(df_periodo)

    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)


def _build_bloprud_lookup(df_bloprudencial: Optional[pd.DataFrame], catalog_map: Dict[str, str]) -> Dict[tuple[str, str, str], float]:
    if df_bloprudencial is None or df_bloprudencial.empty:
        return {}

    df = df_bloprudencial.copy()
    col_nome_inst = _pick_col(df, ["NOME_INSTITUICAO", "Instituição", "Instituicao"])
    col_nome_congl = _pick_col(df, ["NOME_CONGL", "Nome_Congl", "nome_congl"])
    col_conta = _pick_col(df, ["CONTA", "Conta", "codigo_conta", "COD_CONTA"])
    col_saldo = _pick_col(df, ["SALDO", "Saldo", "VALOR", "Valor"])
    col_documento = _pick_col(df, ["DOCUMENTO", "Documento", "doc", "cadoc"])
    if not col_conta or not col_saldo or (not col_nome_inst and not col_nome_congl):
        return {}

    if col_documento:
        docs = pd.to_numeric(df[col_documento], errors="coerce")
        mask_4060 = docs == 4060
        if mask_4060.any():
            df = df.loc[mask_4060].copy()

    col_data_base = _pick_col(df, ["DATA_BASE", "Data_Base", "data_base"])
    if col_data_base:
        df["PeríodoApi"] = df[col_data_base].astype(str).str.replace(r"\D", "", regex=True).str[:6]
    else:
        df["PeríodoApi"] = df["Período"].map(display_period_to_api)

    df["_conta"] = df[col_conta].astype(str).str.replace(r"\D", "", regex=True)
    df["_saldo"] = pd.to_numeric(df[col_saldo], errors="coerce")
    df = df[df["_conta"].isin({"1490000004", "1890000006", "3311000002", "3312000001", "3313000000"})].copy()
    if df.empty:
        return {}

    names = []
    if col_nome_congl:
        names.append(df[col_nome_congl].fillna(""))
    if col_nome_inst:
        names.append(df[col_nome_inst].fillna(""))

    if not names:
        return {}

    df["_instituicao_canonica"] = names[0].astype(str)
    for serie in names[1:]:
        serie = serie.astype(str)
        df["_instituicao_canonica"] = df["_instituicao_canonica"].where(df["_instituicao_canonica"].str.strip().ne(""), serie)

    nomes_canonicos = df["_instituicao_canonica"].astype(str)
    mapa_canonico = {
        nome: canonicalize_institution_name(nome, catalog_map=catalog_map)
        for nome in nomes_canonicos.dropna().unique().tolist()
    }
    df["_instituicao_canonica"] = nomes_canonicos.map(mapa_canonico).fillna(nomes_canonicos)
    df["InstituiçãoKey"] = df["_instituicao_canonica"].map(normalize_institution_name)
    df = df[df["InstituiçãoKey"].astype(bool)].copy()
    if df.empty:
        return {}

    grouped = (
        df.groupby(["PeríodoApi", "InstituiçãoKey", "_conta"], dropna=False)["_saldo"]
        .sum(min_count=1)
        .reset_index()
    )
    out: Dict[tuple[str, str, str], float] = {}
    for row in grouped.itertuples(index=False):
        if pd.isna(row[3]):
            continue
        out[(str(row[0]), str(row[1]), str(row[2]))] = float(row[3])
    return out


def build_critical_screens_dataframe(
    *,
    df_principal: pd.DataFrame,
    df_ativo: Optional[pd.DataFrame],
    df_passivo: Optional[pd.DataFrame],
    df_capital: Optional[pd.DataFrame],
    df_carteira_pf: Optional[pd.DataFrame],
    df_carteira_pj: Optional[pd.DataFrame],
    df_carteira_instrumentos: Optional[pd.DataFrame],
    df_bloprudencial: Optional[pd.DataFrame],
    base_dir: Path | None = None,
) -> pd.DataFrame:
    """Constroi dataset curado das métricas extras das telas críticas."""
    root = Path(base_dir).resolve() if base_dir else Path(__file__).resolve().parents[2]
    catalog_map = build_institution_to_conglomerate_map(root)

    base = _prepare_frame(df_principal, catalog_map, canonicalize_names=True)
    if base.empty:
        return pd.DataFrame(columns=["Instituição", "Período", "InstituiçãoKey", *CRITICAL_EXTRA_METRICS])

    ativo = _prepare_frame(df_ativo, catalog_map)
    passivo = _prepare_frame(df_passivo, catalog_map)
    capital = _prepare_frame(df_capital, catalog_map)
    carteira_pf = _prepare_frame(df_carteira_pf, catalog_map)
    carteira_pj = _prepare_frame(df_carteira_pj, catalog_map)
    carteira_instr = _prepare_frame(df_carteira_instrumentos, catalog_map)
    blop_lookup = _build_bloprud_lookup(df_bloprudencial, catalog_map)

    col_disp_ativo = _pick_col(ativo, ["Disponibilidades (a)", "Disponibilidades", "Disponibilidades (a) ="])
    col_aplic_ativo = _pick_col(
        ativo,
        [
            "Aplicações Interfinanceiras de Liquidez (b)",
            "Aplicacoes Interfinanceiras de Liquidez (b)",
            "Aplicações Interfinanceiras de Liquidez",
        ],
    )
    col_tvm_ativo = _pick_col(
        ativo,
        [
            "Títulos e Valores Mobiliários (c)",
            "Titulos e Valores Mobiliarios (c)",
            "Títulos e Valores Mobiliários e Instrumentos Financeiros Derivativos (c)",
            "Títulos e Valores Mobiliários",
        ],
    )
    col_depositos_passivo = _pick_exact_col(
        passivo,
        [
            "Depósitos (e)",
            "Depositos (e)",
            "Depósitos (a)",
            "Depósitos Totais (a)",
            "Depósito Total (a)",
            "Depositos (a)",
            "Deposito Total (a)",
        ],
    )
    col_dep_a1 = _pick_col(passivo, ["Depósitos à Vista (a1)", "Depositos a Vista (a1)", "Depósitos à Vista", "Depositos a Vista"])
    col_dep_a2 = _pick_col(passivo, ["Depósitos de Poupança (a2)", "Depositos de Poupanca (a2)", "Depósitos de Poupança"])
    col_dep_a3 = _pick_col(passivo, ["Depósitos Interfinanceiros (a3)", "Depositos Interfinanceiros (a3)"])
    col_dep_a4 = _pick_col(passivo, ["Depósitos a Prazo (a4)", "Depositos a Prazo (a4)"])
    col_dep_a5 = _pick_col(
        passivo,
        [
            "Outros Depósitos (a5)",
            "Outros Depositos (a5)",
            "Conta de Pagamento Pré-Paga (a5)",
            "Conta de Pagamento Pre-Paga (a5)",
            "Conta de Pagamento Pre Paga (a5)",
        ],
    )
    col_dep_a6 = _pick_col(passivo, ["Depósitos Outros (a6)", "Depositos Outros (a6)"])
    col_capt_passivo = _pick_col(
        passivo,
        [
            "Captações (e) = (a) + (b) + (c) + (d)",
            "Captações (e)",
            "Captações",
            "Captacoes (e)",
        ],
    )
    col_instr_passivo = _pick_col(
        passivo,
        [
            "Instrumentos de Dívida Elegíveis a Capital (h)",
            "Instrumentos de Divida Elegiveis a Capital (h)",
            "Instrumentos de Dívida Elegíveis a Capital",
            "Instrumentos de Divida Elegiveis a Capital",
        ],
    )

    col_credito_bruta_e1 = _pick_col(ativo, ["Valor Contábil Bruto (e1)", "Valor Contabil Bruto (e1)"])
    col_credito_bruta_f1 = _pick_col(ativo, ["Valor Contábil Bruto (f1)", "Valor Contabil Bruto (f1)"])
    col_credito_bruta_g1 = _pick_col(ativo, ["Valor Contábil Bruto (g1)", "Valor Contabil Bruto (g1)"])
    col_credito_bruta_h1 = _pick_col(ativo, ["Valor Contábil Bruto (h1)", "Valor Contabil Bruto (h1)"])
    col_credito_bruta_d1 = _pick_col(ativo, ["Operações de Crédito (d1)", "Operacoes de Credito (d1)"])
    col_credito_bruta_e1_alt = _pick_col(ativo, ["Arrendamento Mercantil a Receber (e1)", "Arrendamento Mercantil a Receber"])
    col_credito_bruta_f = _pick_col(
        ativo,
        ["Outros Créditos - Líquido de Provisão (f)", "Outros Creditos - Liquido de Provisao (f)", "Outros Créditos - Líquido de Provisão"],
    )
    col_credito_net_e = _pick_col(ativo, ["Operações de Crédito (e)", "Operacoes de Credito (e)"])
    col_credito_net_f = _pick_col(ativo, ["Operações de Arrendamento Financeiro (f)", "Operacoes de Arrendamento Financeiro (f)"])
    col_credito_net_g = _pick_col(
        ativo,
        ["Outras Operações com Características de Concessão de Crédito (g)", "Outras Operacoes com Caracteristicas de Concessao de Credito (g)"],
    )
    col_credito_net_h = _pick_col(
        ativo,
        [
            "Valores a Receber de Transações de Pagamentos - Usuários Finais (Pós-pago) (h)",
            "Valores a Receber de Transacoes de Pagamentos - Usuarios Finais (Pos-pago) (h)",
        ],
    )

    perda_colunas = []
    for coluna in [
        "Perda Esperada (e2)",
        "Hedge de Valor Justo (e3)",
        "Ajuste a Valor Justo (e4)",
        "Perda Esperada (f2)",
        "Hedge de Valor Justo (f3)",
        "Perda Esperada (g2)",
        "Hedge de Valor Justo (g3)",
        "Ajuste a Valor Justo (g4)",
        "Perda Esperada (h2)",
    ]:
        resolvida = _pick_col(ativo, [coluna])
        if resolvida and resolvida not in perda_colunas:
            perda_colunas.append(resolvida)

    col_pf_total = _pick_col(
        carteira_pf,
        ["Total da Carteira PF", "Total da Carteira de Pessoa Física", "Total da Carteira de Pessoa Fisica"],
    )
    col_pj_total = _pick_col(
        carteira_pj,
        ["Total da Carteira PJ", "Total da Carteira de Pessoa Jurídica", "Total da Carteira de Pessoa Juridica"],
    )
    col_c4 = _pick_col(carteira_instr, ["C4"])
    col_c5 = _pick_col(carteira_instr, ["C5"])

    col_cap_principal = _pick_col(capital, ["Capital Principal", "Capital Principal para Comparação com RWA (a)"])
    col_cap_complementar = _pick_col(capital, ["Capital Complementar", "Capital Complementar (b)"])
    col_cap_nivel2 = _pick_col(capital, ["Capital Nível II", "Capital Nível II (d)", "Capital Nivel II"])
    col_rwa_total = _pick_col(
        capital,
        [
            "RWA Total",
            "Ativos Ponderados pelo Risco (RWA) (j) = (f) + (g) + (h) + (i)",
            "Ativos Ponderados pelo Risco (RWA) (j)",
            "Ativos Ponderados pelo Risco (RWA) (i) = (f) + (g) + (h)",
            "Ativos Ponderados pelo Risco (RWA) (i)",
            "RWA",
        ],
    )
    col_indice_cap_principal = _pick_col(
        capital,
        [
            "Índice de Capital Principal",
            "Índice de Capital Principal (l) = (a) / (j)",
            "Índice de Capital Principal (k) = (a) / (i)",
        ],
    )
    col_indice_basileia_precalc = _pick_col(
        capital,
        [
            "Índice de Basileia",
            "Índice de Basileia Capital",
            "Índice de Basileia (n) = (e) / (j)",
            "Índice de Basileia (m) = (e) / (i)",
        ],
    )

    lk_ativo = _prepare_lookup(
        ativo,
        [
            col_credito_bruta_e1,
            col_credito_bruta_f1,
            col_credito_bruta_g1,
            col_credito_bruta_h1,
            col_credito_bruta_d1,
            col_credito_bruta_e1_alt,
            col_credito_bruta_f,
            col_credito_net_e,
            col_credito_net_f,
            col_credito_net_g,
            col_credito_net_h,
            col_disp_ativo,
            col_aplic_ativo,
            col_tvm_ativo,
            *perda_colunas,
        ],
    )
    lk_passivo = _prepare_lookup(
        passivo,
        [col_depositos_passivo, col_dep_a1, col_dep_a2, col_dep_a3, col_dep_a4, col_dep_a5, col_dep_a6, col_capt_passivo, col_instr_passivo],
    )
    lk_capital = _prepare_lookup(
        capital,
        [col_cap_principal, col_cap_complementar, col_cap_nivel2, col_rwa_total, col_indice_cap_principal, col_indice_basileia_precalc],
    )
    lk_pf = _prepare_lookup(carteira_pf, [col_pf_total])
    lk_pj = _prepare_lookup(carteira_pj, [col_pj_total])
    lk_instr = _prepare_lookup(carteira_instr, [col_c4, col_c5])

    base = base.sort_values(["Período", "InstituiçãoKey", "Instituição"]).reset_index(drop=True)
    rows = []
    for item in base.itertuples(index=False):
        instituicao = str(item.Instituição)
        institution_key = str(item.InstituiçãoKey)
        periodo = str(item.Período)
        periodo_api = display_period_to_api(periodo)
        ano_ref = int(periodo_api[:4]) if periodo_api else None

        valor_pf = _lk_get(lk_pf, institution_key, periodo, col_pf_total)
        valor_pj = _lk_get(lk_pj, institution_key, periodo, col_pj_total)
        carteira_classificada = _sum_values([valor_pf, valor_pj])

        if ano_ref is not None and ano_ref <= 2024:
            carteira_bruta = _sum_values(
                [
                    _lk_get(lk_ativo, institution_key, periodo, col_credito_bruta_d1),
                    _lk_get(lk_ativo, institution_key, periodo, col_credito_bruta_e1_alt),
                    _lk_get(lk_ativo, institution_key, periodo, col_credito_bruta_f),
                ]
            )
        else:
            carteira_bruta = _sum_values(
                [
                    _lk_get(lk_ativo, institution_key, periodo, col_credito_bruta_e1),
                    _lk_get(lk_ativo, institution_key, periodo, col_credito_bruta_f1),
                    _lk_get(lk_ativo, institution_key, periodo, col_credito_bruta_g1),
                    _lk_get(lk_ativo, institution_key, periodo, col_credito_bruta_h1),
                ]
            )
        if carteira_bruta is None:
            carteira_bruta = _sum_values(
                [
                    _lk_get(lk_ativo, institution_key, periodo, col_credito_net_e),
                    _lk_get(lk_ativo, institution_key, periodo, col_credito_net_f),
                    _lk_get(lk_ativo, institution_key, periodo, col_credito_net_g),
                    _lk_get(lk_ativo, institution_key, periodo, col_credito_net_h),
                ]
            )

        ativos_liquidos = _sum_values(
            [
                _lk_get(lk_ativo, institution_key, periodo, col_disp_ativo),
                _lk_get(lk_ativo, institution_key, periodo, col_aplic_ativo),
                _lk_get(lk_ativo, institution_key, periodo, col_tvm_ativo),
            ]
        )
        depositos_totais = _lk_get(lk_passivo, institution_key, periodo, col_depositos_passivo)
        if _coerce_numeric_value(depositos_totais) is None:
            depositos_totais = _sum_values(
                [
                    _lk_get(lk_passivo, institution_key, periodo, col_dep_a1),
                    _lk_get(lk_passivo, institution_key, periodo, col_dep_a2),
                    _lk_get(lk_passivo, institution_key, periodo, col_dep_a3),
                    _lk_get(lk_passivo, institution_key, periodo, col_dep_a4),
                    _lk_get(lk_passivo, institution_key, periodo, col_dep_a5),
                    _lk_get(lk_passivo, institution_key, periodo, col_dep_a6),
                ]
            )

        cap_val = _lk_get(lk_passivo, institution_key, periodo, col_capt_passivo)
        if ano_ref is None or ano_ref <= 2024:
            core_funding = _coerce_numeric_value(cap_val)
        else:
            core_funding = _sum_values([cap_val, _lk_get(lk_passivo, institution_key, periodo, col_instr_passivo)])

        perda_esperada = _sum_values(
            [_lk_get(lk_ativo, institution_key, periodo, coluna) for coluna in perda_colunas]
        )
        valor_c4 = _lk_get(lk_instr, institution_key, periodo, col_c4)
        valor_c5 = _lk_get(lk_instr, institution_key, periodo, col_c5)
        carteira_c4_c5 = _sum_values([valor_c4, valor_c5])

        pdd_credito = blop_lookup.get((str(periodo_api), institution_key, "1490000004")) if periodo_api else None
        pdd_outros = blop_lookup.get((str(periodo_api), institution_key, "1890000006")) if periodo_api else None
        estagio1 = blop_lookup.get((str(periodo_api), institution_key, "3311000002")) if periodo_api else None
        estagio2 = blop_lookup.get((str(periodo_api), institution_key, "3312000001")) if periodo_api else None
        estagio3 = blop_lookup.get((str(periodo_api), institution_key, "3313000000")) if periodo_api else None
        pdd_total_4060 = _sum_values([pdd_credito, pdd_outros])

        indice_cap_principal = None
        val_cp = _coerce_numeric_value(_lk_get(lk_capital, institution_key, periodo, col_cap_principal))
        val_rwa = _coerce_numeric_value(_lk_get(lk_capital, institution_key, periodo, col_rwa_total))
        if val_cp is not None and val_rwa is not None and val_rwa != 0:
            indice_cap_principal = val_cp / val_rwa
        if indice_cap_principal is None:
            val_precalc = _coerce_numeric_value(_lk_get(lk_capital, institution_key, periodo, col_indice_cap_principal))
            if val_precalc is not None:
                indice_cap_principal = val_precalc / 100 if abs(val_precalc) > 1 else val_precalc

        indice_basileia = None
        val_cc = _coerce_numeric_value(_lk_get(lk_capital, institution_key, periodo, col_cap_complementar))
        val_n2 = _coerce_numeric_value(_lk_get(lk_capital, institution_key, periodo, col_cap_nivel2))
        if None not in (val_cp, val_cc, val_n2, val_rwa) and val_rwa not in (None, 0):
            indice_basileia = (val_cp + val_cc + val_n2) / val_rwa
        if indice_basileia is None:
            val_precalc = _coerce_numeric_value(_lk_get(lk_capital, institution_key, periodo, col_indice_basileia_precalc))
            if val_precalc is not None:
                indice_basileia = val_precalc / 100 if abs(val_precalc) > 1 else val_precalc

        rows.append(
            {
                "Instituição": instituicao,
                "Período": periodo,
                "InstituiçãoKey": institution_key,
                "Ativos Líquidos": ativos_liquidos,
                "Depósitos Totais": _coerce_numeric_value(depositos_totais),
                "Core Funding": _coerce_numeric_value(core_funding),
                "Core Funding*": _coerce_numeric_value(core_funding),
                "Carteira de Crédito Bruta": carteira_bruta,
                "Carteira de Crédito*": carteira_bruta,
                "Perda Esperada": perda_esperada,
                "Perda Esperada / Carteira de Crédito Bruta": _calc_ratio(perda_esperada, carteira_bruta),
                "Perda Esperada / Carteira de Crédito*": _calc_ratio(perda_esperada, carteira_bruta),
                "Carteira de Crédito Classificada": carteira_classificada,
                "Carteira de Créd. Class. C4+C5": carteira_c4_c5,
                "Carteira de Créd. Class. C4+C5 / Carteira Classificada": _calc_ratio(carteira_c4_c5, carteira_classificada),
                "Perda Esperada / (Carteira C4 + C5)": _calc_ratio(perda_esperada, carteira_c4_c5),
                "Saldo PDD Crédito": pdd_credito,
                "Saldo PDD Outros Créditos": pdd_outros,
                "PDD Total 4060": pdd_total_4060,
                "Carteira Estágio 1": estagio1,
                "Ativos Estágio 2": estagio2,
                "Ativos Estágio 3": estagio3,
                "PDD / Estágio 3": _calc_ratio(pdd_total_4060, estagio3),
                "Perda Esperada / Estágio 3": _calc_ratio(perda_esperada, estagio3),
                "Índice de Capital Principal (CET1)": indice_cap_principal,
                "Índice de Basileia Total (%)": indice_basileia,
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    out["CapitalDisponivel"] = out["Índice de Capital Principal (CET1)"].notna() | out["Índice de Basileia Total (%)"].notna()
    out["BloprudencialDisponivel"] = out["Ativos Estágio 3"].notna() | out["PDD Total 4060"].notna()
    out["QualidadeCarteiraDisponivel"] = out["Perda Esperada"].notna() & (
        out["Perda Esperada / Carteira de Crédito*"].notna() | out["Perda Esperada / Estágio 3"].notna()
    )

    return out.sort_values(["Período", "Instituição"]).reset_index(drop=True)


def _load_source_cache(manager: CacheManager, cache_name: str) -> pd.DataFrame:
    resultado = manager.carregar(cache_name)
    if not resultado.sucesso or resultado.dados is None:
        raise RuntimeError(f"{cache_name}: {resultado.mensagem}")
    return resultado.dados


def materialize_critical_screens_cache(
    *,
    base_dir: Path | None = None,
    manager: "CacheManager" | None = None,
    force: bool = False,
    periodos: Optional[Sequence[str]] = None,
) -> CacheResult:
    """Materializa o cache curado das telas críticas."""
    root = Path(base_dir).resolve() if base_dir else Path(__file__).resolve().parents[2]
    from .manager import CacheManager

    cache_manager = manager or CacheManager(root)
    cache = CriticalScreensCache(root)

    if cache.existe() and not force and not periodos:
        return cache.carregar_local()

    loaded = {cache_name: _load_source_cache(cache_manager, cache_name) for cache_name in SOURCE_CACHE_TYPES}
    principal = loaded["principal"]
    principal_periodos = sorted(principal["Período"].dropna().astype(str).unique().tolist())
    periodos_criticos = list(periodos) if periodos else principal_periodos

    if periodos_criticos:
        for cache_name, df in list(loaded.items()):
            loaded[cache_name] = df[df["Período"].astype(str).isin(periodos_criticos)].copy()

    blop_df = _load_bloprud_periods(root, periodos_criticos)
    curated = build_critical_screens_dataframe(
        df_principal=loaded["principal"],
        df_ativo=loaded["ativo"],
        df_passivo=loaded["passivo"],
        df_capital=loaded["capital"],
        df_carteira_pf=loaded["carteira_pf"],
        df_carteira_pj=loaded["carteira_pj"],
        df_carteira_instrumentos=loaded["carteira_instrumentos"],
        df_bloprudencial=blop_df,
        base_dir=root,
    )

    info_extra = {
        "tipos_origem": SOURCE_CACHE_TYPES,
        "periodos_materializados": sorted(curated["Período"].dropna().astype(str).unique().tolist()) if not curated.empty else [],
        "linhas_bloprudencial": int(len(blop_df)),
        "metricas_extra": CRITICAL_EXTRA_METRICS,
    }
    return cache.salvar_local(curated, fonte="materialized", info_extra=info_extra)


def load_critical_screens_slice(
    *,
    base_dir: Path | None = None,
    periodos: Optional[Sequence[str]] = None,
    instituicoes: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Carrega recorte do cache curado sem abrir todo o dataset em memória."""
    root = Path(base_dir).resolve() if base_dir else Path(__file__).resolve().parents[2]
    cache = CriticalScreensCache(root)
    if not cache.arquivo_dados.exists():
        resultado = cache.carregar_local()
        if not resultado.sucesso or resultado.dados is None or resultado.dados.empty:
            return pd.DataFrame()
        df = resultado.dados
    else:
        try:
            import pyarrow.dataset as ds

            dataset = ds.dataset(cache.arquivo_dados, format="parquet")
            filtros = []
            if periodos:
                filtros.append(ds.field("Período").isin([str(periodo) for periodo in periodos]))
            if instituicoes:
                canonicas = build_institution_to_conglomerate_map(root)
                instituicoes_canonicas = [canonicalize_institution_name(nome, catalog_map=canonicas) for nome in instituicoes]
                filtros.append(ds.field("Instituição").isin([str(inst) for inst in instituicoes_canonicas]))

            if filtros:
                filtro = filtros[0]
                for extra in filtros[1:]:
                    filtro = filtro & extra
                table = dataset.to_table(filter=filtro)
            else:
                table = dataset.to_table()
            df = table.to_pandas()
        except Exception as exc:
            logger.warning("[CACHE:CRITICAL_SCREENS] Falha ao carregar slice filtrado: %s", exc)
            resultado = cache.carregar_local()
            if not resultado.sucesso or resultado.dados is None or resultado.dados.empty:
                return pd.DataFrame()
            df = resultado.dados

    if periodos:
        df = df[df["Período"].astype(str).isin([str(periodo) for periodo in periodos])].copy()
    if instituicoes:
        canonicas = build_institution_to_conglomerate_map(root)
        instituicoes_canonicas = [canonicalize_institution_name(nome, catalog_map=canonicas) for nome in instituicoes]
        df = df[df["Instituição"].astype(str).isin([str(inst) for inst in instituicoes_canonicas])].copy()
    return df.reset_index(drop=True)


def supported_periods_for_cache(cache_name: str, periodos: Sequence[str]) -> List[str]:
    """Retorna apenas períodos suportados para um cache."""
    suportados, _ = filter_supported_periods(cache_name, periodos)
    return suportados
