"""Garantia / Obrigações em arranjos de pagamento, derivado do balancete prudencial (4060).

Nada é gravado: o painel é uma função da base ``bloprudencial`` já versionada. Um mês novo
nessa base aparece aqui sem outra etapa. A fórmula inteira está em ``COMPONENTS``.
"""
from __future__ import annotations

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
MEMO = "controle"
RATIO = "razao"

# Oito primeiros dígitos da conta: o dígito verificador muda de formato entre arquivos.
COMPONENTS = (
    ("44160000", "4.4.1.60", "Transações de pagamento (relações interfinanceiras)", OBLIGATIONS),
    ("49901000", "4.9.9.01", "Obrigações por transações de pagamento", OBLIGATIONS),
    ("49903000", "4.9.9.03", "Obrigações por serviços de instituidores de arranjo", OBLIGATIONS),
    ("13616000", "1.3.6.16", "Títulos dados em garantia em arranjo de pagamento", COLLATERAL),
    ("13615000", "1.3.6.15", "Títulos dados em garantia em câmaras de liquidação", CLEARING),
    ("30977000", "3.0.9.77", "Garantias em arranjos de pagamento (conta de controle)", MEMO),
)
ROLE_BY_ACCOUNT = {account: role for account, _, _, role in COMPONENTS}
VALUE_COLUMNS = (OBLIGATIONS, COLLATERAL, CLEARING, MEMO)


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


def build_series(accounts: pd.DataFrame, include_clearing: bool = False) -> pd.DataFrame:
    """Uma linha por conglomerado e mês: obrigações, garantia e a razão entre elas.

    Conta não publicada soma zero. A razão fica vazia quando as obrigações não chegam a
    ``MIN_BASE``. ``include_clearing`` soma 1.3.6.15, usada por quem registrava ali o
    colateral do arranjo antes de migrar para 1.3.6.16.
    """
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
    wide["garantia_total"] = wide[COLLATERAL] + (wide[CLEARING] if include_clearing else 0.0)
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
