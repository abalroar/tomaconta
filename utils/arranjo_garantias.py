"""Garantia / Obrigações em arranjos de pagamento, derivado do balancete prudencial (4060).

Nada é gravado: o painel é uma função da base ``bloprudencial`` já versionada. Um mês novo
nessa base aparece aqui sem outra etapa. A fórmula inteira está em ``COMPONENTS``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from utils.ifdata_cache.bloprudencial_cache import load_bloprudencial_parquet_slice

# O arquivo público só abre o quarto nível do COSIF a partir de jan/2025; antes disso
# 4.4.1 e 1.3.6 vêm agregados e não isolam o arranjo.
START = "202501"
DOCUMENT = "4060"
# Abaixo disso a razão explode sem significar cobertura (ex.: R$ 30 mil de obrigação).
MIN_BASE = 1_000_000.0

OBLIGATIONS = "obrigacoes"
COLLATERAL = "garantia"
CLEARING = "camaras"
OTHER = "outros"
MEMO = "controle"
RATIO = "razao"

# Oito primeiros dígitos da conta: o dígito verificador muda de formato entre arquivos.
COMPONENTS = (
    ("44160000", "4.4.1.60", "Transações de pagamento (relações interfinanceiras)", OBLIGATIONS),
    ("49901000", "4.9.9.01", "Obrigações por transações de pagamento", OBLIGATIONS),
    ("49903000", "4.9.9.03", "Obrigações por serviços de instituidores de arranjo", OBLIGATIONS),
    ("13616000", "1.3.6.16", "Títulos dados em garantia em arranjo de pagamento", COLLATERAL),
    ("13620000", "1.3.6.20", "Títulos dados em garantia - outros", OTHER),
    ("13615000", "1.3.6.15", "Títulos dados em garantia em câmaras de liquidação", CLEARING),
    ("30977000", "3.0.9.77", "Garantias em arranjos de pagamento (conta de controle)", MEMO),
)
ROLE_BY_ACCOUNT = {account: role for account, _, _, role in COMPONENTS}
VALUE_COLUMNS = (OBLIGATIONS, COLLATERAL, OTHER, CLEARING, MEMO)


@dataclass(frozen=True)
class Source:
    """Rubrica que pode entrar no numerador, com o nome exibido e a ressalva de leitura."""
    key: str
    label: str
    short: str
    code: str
    account: str
    reading: str


SOURCES = (
    Source(COLLATERAL, "Garantias - Arranjo de Pagamento", "Arranjo", "1.3.6.16", "Títulos dados em garantia em arranjo de pagamento",
           "É a rubrica específica do arranjo. Não identifica a bandeira beneficiária."),
    Source(OTHER, "Garantia - Outros", "Outros", "1.3.6.20", "Títulos dados em garantia - outros",
           "Rubrica residual: reúne garantias que não cabem nas contas específicas e pode incluir, ou não, a do arranjo. "
           "Leia a razão como teto. Quando a instituição preenche a conta de controle 3.0.9.77, ela indica a parcela do arranjo."),
    Source(CLEARING, "Garantia - Câmaras de Liquidação", "Câmaras", "1.3.6.15", "Títulos dados em garantia de operações em câmaras de liquidação e compensação",
           "Usada por quem registrava ali o colateral do arranjo antes de migrar para 1.3.6.16. "
           "Em bancos com operações em bolsa é margem de câmara, sem relação com o arranjo."),
)
SOURCE_BY_KEY = {source.key: source for source in SOURCES}
DEFAULT_SOURCES = (COLLATERAL,)
MEMO_READING = ("Conta de compensação 3.0.9.77, Garantias em arranjos de pagamento: registro de controle, fora do ativo e do passivo, "
                "em que a própria instituição informa o total de garantias prestadas em arranjos. Existe desde fev/2026 e poucas "
                "instituições a preenchem; zero significa sem registro. Não entra na razão.")


def source_label(sources) -> str:
    """Nome do numerador escolhido, na ordem fixa das rubricas."""
    chosen = [source for source in SOURCES if source.key in set(sources)]
    if len(chosen) == 1:
        return chosen[0].label
    return "Garantias - " + " + ".join(source.short for source in chosen)


def months(start: str = START, today: date | None = None) -> list[str]:
    """Competências possíveis até hoje; as que a base não tem simplesmente não retornam linhas."""
    today = today or date.today()
    year, month, out = int(start[:4]), int(start[4:]), []
    while (year, month) <= (today.year, today.month):
        out.append(f"{year}{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def load_accounts(cache, today: date | None = None) -> pd.DataFrame:
    """Só as contas da fórmula, em todos os meses disponíveis desde ``START``."""
    frame = load_bloprudencial_parquet_slice(
        cache, periodos_yyyymm=months(today=today), documentos=[DOCUMENT],
        columns=["DATA_BASE", "DOCUMENTO", "COD_CONGL", "NOME_CONGL", "CONTA", "SALDO"])
    if frame.empty:
        return frame
    frame = frame.assign(
        DATA_BASE=frame.DATA_BASE.astype(str).str.replace(r"\D", "", regex=True).str[:6],
        COD_CONGL=frame.COD_CONGL.astype(str).str.strip(),
        CONTA=frame.CONTA.astype(str).str.replace(r"\D", "", regex=True).str[:8],
        SALDO=pd.to_numeric(frame.SALDO, errors="coerce"))
    return frame[frame.CONTA.isin(ROLE_BY_ACCOUNT)].reset_index(drop=True)


def build_series(accounts: pd.DataFrame, sources=DEFAULT_SOURCES) -> pd.DataFrame:
    """Uma linha por conglomerado e mês: obrigações, garantia e a razão entre elas.

    Conta não publicada soma zero. A razão fica vazia quando as obrigações não chegam a
    ``MIN_BASE``. ``sources`` escolhe as rubricas somadas no numerador.
    """
    unknown = set(sources) - set(SOURCE_BY_KEY)
    if unknown or not sources:
        raise ValueError(f"Fonte de garantia inválida: {sorted(unknown) or 'nenhuma'}")
    columns = ["COD_CONGL", "NOME_CONGL", "DATA_BASE", *VALUE_COLUMNS, "garantia_total", RATIO]
    if accounts is None or accounts.empty:
        return pd.DataFrame(columns=columns)
    # A base preserva duplicidades históricas na chave contábil; somá-las dobraria o saldo.
    frame = accounts.drop_duplicates(["DATA_BASE", "COD_CONGL", "CONTA"], keep="last")
    frame = frame.assign(papel=frame.CONTA.map(ROLE_BY_ACCOUNT))
    wide = frame.pivot_table(index=["COD_CONGL", "DATA_BASE"], columns="papel", values="SALDO", aggfunc="sum")
    wide = wide.reindex(columns=list(VALUE_COLUMNS)).fillna(0.0).reset_index()
    names = frame.sort_values("DATA_BASE").drop_duplicates("COD_CONGL", keep="last").set_index("COD_CONGL").NOME_CONGL
    wide["NOME_CONGL"] = wide.COD_CONGL.map(names)
    wide["garantia_total"] = wide[[source.key for source in SOURCES if source.key in set(sources)]].sum(axis=1)
    wide[RATIO] = (wide.garantia_total / wide[OBLIGATIONS]).where(wide[OBLIGATIONS] >= MIN_BASE)
    return wide[columns].sort_values(["COD_CONGL", "DATA_BASE"]).reset_index(drop=True)


def with_collateral(series: pd.DataFrame, period: str) -> list[str]:
    """Quem tem garantia registrada no mês, da maior obrigação para a menor."""
    month = series[series.DATA_BASE.eq(period) & (series.garantia_total.gt(0) | series[MEMO].gt(0))]
    return month.sort_values(OBLIGATIONS, ascending=False).COD_CONGL.tolist()


def shift_period(period: str, back: int) -> str:
    total = int(period[:4]) * 12 + int(period[4:]) - 1 - back
    return f"{total // 12}{total % 12 + 1:02d}"


def detail_table(accounts: pd.DataFrame, series: pd.DataFrame, code: str) -> pd.DataFrame:
    """Períodos nas colunas, contas nas linhas, em reais; a razão vem na última linha."""
    own = accounts[accounts.COD_CONGL.eq(code)].drop_duplicates(["DATA_BASE", "CONTA"], keep="last")
    bank = series[series.COD_CONGL.eq(code)].set_index("DATA_BASE")
    periods = sorted(bank.index)
    values = own.pivot_table(index="CONTA", columns="DATA_BASE", values="SALDO", aggfunc="sum").reindex(columns=periods)
    rows = {}
    for account, code_label, name, role in COMPONENTS:
        if role == OBLIGATIONS:
            rows[f"{code_label} {name}"] = values.reindex([account]).iloc[0].fillna(0.0)
    rows["Obrigações do arranjo"] = bank[OBLIGATIONS]
    for account, code_label, name, role in COMPONENTS:
        if role != OBLIGATIONS:
            rows[f"{code_label} {name}"] = values.reindex([account]).iloc[0].fillna(0.0)
    rows["Garantia considerada"] = bank.garantia_total
    rows["Garantia / Obrigações"] = bank[RATIO]
    return pd.DataFrame(rows).T.reindex(columns=periods)


EXPORT_COLUMNS = ("Instituição", "Código", "Data-base", "4.4.1.60 Transações de pagamento", "4.9.9.01 Obrigações por transações",
                  "4.9.9.03 Serviços de instituidores", "Obrigações do arranjo", "1.3.6.16 Garantias - Arranjo de Pagamento",
                  "1.3.6.20 Garantia - Outros", "1.3.6.15 Garantia - Câmaras", "3.0.9.77 Garantias (controle)", "Garantia considerada",
                  "Garantia / Obrigações", "Fonte considerada", "Rubricas com saldo")


def export_frame(accounts: pd.DataFrame, series: pd.DataFrame, codes, sources=DEFAULT_SOURCES) -> pd.DataFrame:
    """Tabela simples das obrigações, uma linha por instituição na última data que publicou.

    Valores em R$ milhões; a razão em decimal. ``Rubricas com saldo`` diz onde há garantia
    registrada, qualquer que seja a fonte escolhida.
    """
    label = source_label(sources)
    parts = accounts.drop_duplicates(["DATA_BASE", "COD_CONGL", "CONTA"], keep="last").set_index(["COD_CONGL", "DATA_BASE", "CONTA"]).SALDO
    rows = []
    for code in codes:
        own = series[series.COD_CONGL.eq(code)]
        if own.empty:
            continue
        row = own.loc[own.DATA_BASE.idxmax()]
        part = lambda account: float(parts.get((code, row.DATA_BASE, account), 0.0)) / 1e6
        present = [source.short for source in SOURCES if row[source.key] > 0]
        rows.append((row.NOME_CONGL, code, f"{row.DATA_BASE[4:]}/{row.DATA_BASE[:4]}", part("44160000"), part("49901000"), part("49903000"),
                     row[OBLIGATIONS] / 1e6, row[COLLATERAL] / 1e6, row[OTHER] / 1e6, row[CLEARING] / 1e6, row[MEMO] / 1e6,
                     row.garantia_total / 1e6, None if pd.isna(row[RATIO]) else float(row[RATIO]), label, " + ".join(present) or "Nenhuma"))
    return pd.DataFrame(rows, columns=EXPORT_COLUMNS)


HEADER_FILL = "EC7000"
HEADER_SIZE = 14
BODY_SIZE = 12


def to_excel(frame: pd.DataFrame, sheet: str = "Obrigações do arranjo") -> bytes:
    """Uma tabela nativa do Excel: cabeçalho laranja com texto branco em negrito, linhas sem preenchimento."""
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo

    book = Workbook()
    page = book.active
    page.title = sheet
    page.append(list(frame.columns))
    for values in frame.itertuples(index=False):
        page.append([None if pd.isna(value) else value for value in values])
    text_columns = {"Instituição", "Código", "Data-base", "Fonte considerada", "Rubricas com saldo"}
    for index, name in enumerate(frame.columns, start=1):
        letter = get_column_letter(index)
        head = page.cell(row=1, column=index)
        head.font = Font(name="Calibri", size=HEADER_SIZE, bold=True, color="FFFFFF")
        head.fill = PatternFill("solid", start_color=HEADER_FILL, end_color=HEADER_FILL)
        head.alignment = Alignment(horizontal="left" if name in text_columns else "right", vertical="center", wrap_text=True)
        widest = max([len(str(value)) for value in frame[name]] + [0]) if name in text_columns else 12
        page.column_dimensions[letter].width = min(max(widest * 1.25 + 2, 16), 46)
        for row in range(2, len(frame) + 2):
            cell = page.cell(row=row, column=index)
            cell.font = Font(name="Calibri", size=BODY_SIZE, color="000000")
            if name == "Garantia / Obrigações":
                cell.number_format = "0.0%"
            elif name not in text_columns:
                cell.number_format = "#,##0.0"
    page.row_dimensions[1].height = 58
    page.freeze_panes = "B2"
    table = Table(displayName="ObrigacoesArranjo", ref=f"A1:{get_column_letter(len(frame.columns))}{max(len(frame), 1) + 1}")
    # Estilo claro sem faixas: as linhas ficam sem preenchimento e o filtro do cabeçalho permanece.
    table.tableStyleInfo = TableStyleInfo(name="TableStyleLight1", showRowStripes=False, showColumnStripes=False)
    page.add_table(table)
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()
