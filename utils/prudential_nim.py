"""Métricas gerenciais de margem, acrescentadas à DRE sem alterar as linhas contábeis."""
from __future__ import annotations

from .prudential_analysis import Analysis, col_name

ND = "N/D"
RATIO = "0.00%"
NIM_ROWS = (("nim_gross", "NIM Bruta (anualizada)", "gross"), ("nim_after_pdd", "NIM pós-PDD (anualizada)", "after_pdd"))
ROE_LIMITATION = "ROE: resultado acumulado no ano × 12 / meses do ano / PL médio. PL médio: Patrimônio Líquido na data-base e em dezembro do ano anterior. Sem os dois saldos ou com média não positiva, gera N/D."
LIMITATION = ("NIM: resultado acumulado no ano × 12 / meses do ano / carteira média. Carteira média: Operações de Crédito "
              "Líq. do Balanço na data-base e em dezembro do ano anterior.")


def prior_year_end(period: str) -> str:
    """Base da média: o início do ano do acumulado, isto é, dezembro anterior."""
    return f"{int(period[:4]) - 1}12"


def prior_periods(periods) -> list[str]:
    """Competências anteriores fora da seleção, que precisam ser carregadas."""
    return sorted({prior_year_end(p) for p in periods} - set(periods))


def required_periods(periods) -> list[str]:
    """Tudo o que uma seleção precisa carregar: junho dos acumulados e dezembro das médias."""
    june = {f"{p[:4]}06" for p in periods if int(p[4:]) > 6}
    return sorted(set(periods) | june | set(prior_periods(periods)))


def credit_balances(analysis: Analysis) -> dict[str, float]:
    """Saldo da carteira por competência, para uso como base de outra seleção."""
    sheet, row = analysis.sheets["Balanço"], analysis.rows["Balanço"]["credit"]
    values = {}
    for i, period in enumerate(analysis.periods):
        cell = sheet.cells.get(f"{col_name(3 + 2 * i)}{row}")
        if cell is not None and isinstance(cell.value, (int, float)):
            values[period] = float(cell.value)
    return values


def equity_balances(analysis: Analysis) -> dict[str, float]:
    """Patrimônio por competência, para a média do ROE de outra seleção."""
    sheet, row = analysis.sheets["Balanço"], analysis.rows["Balanço"]["equity"]
    values = {}
    for i, period in enumerate(analysis.periods):
        cell = sheet.cells.get(f"{col_name(3 + 2 * i)}{row}")
        if cell is not None and isinstance(cell.value, (int, float)):
            values[period] = float(cell.value)
    return values


def apply_average_roe(analysis: Analysis, prior_equity: dict[str, float] | None = None) -> None:
    """ROE sobre o PL médio: a mesma regra do Snapshot, da Evolução e da Tabela de Peers."""
    prior_equity = prior_equity or {}
    sheet = analysis.sheets["Balanço"]
    rows = analysis.rows["Balanço"]
    current = equity_balances(analysis)
    for i, period in enumerate(analysis.periods):
        column = col_name(3 + 2 * i)
        cell = sheet.cells.get(f"{column}{rows['roe']}")
        net, equity = sheet.cells.get(f"{column}{rows['net']}"), current.get(period)
        prior = prior_year_end(period)
        if prior in analysis.periods:
            prior_value = current.get(prior)
            prior_ref = f"{col_name(3 + 2 * analysis.periods.index(prior))}{rows['equity']}"
        else:
            prior_value = prior_equity.get(prior)
            prior_ref = repr(prior_value) if prior_value is not None else '"N/D"'
        net_ref, equity_ref = f"{column}{rows['net']}", f"{column}{rows['equity']}"
        factor = 12 / int(period[4:])
        formula = (f'=IF(AND(ISNUMBER({net_ref}),ISNUMBER({equity_ref}),ISNUMBER({prior_ref})),'
                   f'IF({equity_ref}+{prior_ref}>0,{net_ref}/AVERAGE({equity_ref},{prior_ref})*{factor:g},"{ND}"),"{ND}")')
        value = ND
        if isinstance(getattr(net, "value", None), (int, float)) and equity is not None and prior_value is not None and equity + prior_value > 0:
            value = net.value / ((equity + prior_value) / 2) * factor
        sheet.put(f"{column}{rows['roe']}", value, formula, cell.style, cell.fmt)
    analysis.limitations[:] = [ROE_LIMITATION if str(item).startswith("ROE:") else item for item in analysis.limitations]
    # A aba Validações já recebeu as notas ao ser montada e precisa contar a mesma regra.
    for cell in analysis.sheets["Validações"].cells.values():
        if str(cell.value).startswith("ROE:"):
            cell.value = ROE_LIMITATION


def add_nim_rows(analysis: Analysis, prior_credit: dict[str, float] | None = None) -> None:
    """Acrescenta as duas linhas logo abaixo do resultado líquido, com fórmulas auditáveis."""
    prior_credit = prior_credit or {}
    sheet = analysis.sheets["DRE"]
    balance = analysis.sheets["Balanço"]
    credit_row = analysis.rows["Balanço"]["credit"]
    rows = analysis.rows["DRE"]
    first = rows["net"] + 1
    # A nota de rodapé desce para abrir espaço às duas métricas.
    notes = [(address, cell) for address, cell in sheet.cells.items() if cell.style == "note" and address != "B3"]
    for address, _ in notes:
        del sheet.cells[address]
    sheet.merges = [merge for merge in sheet.merges if merge.split(":")[0] not in {address for address, _ in notes}]
    for offset, (ident, label, source) in enumerate(NIM_ROWS):
        row = first + offset
        rows[ident] = row
        sheet.put(f"B{row}", label, style="ratio")
        sheet.heights[row] = 19
        for i, period in enumerate(analysis.periods):
            column = col_name(3 + 2 * i)
            result = sheet.cells.get(f"{column}{rows[source]}")
            credit = balance.cells.get(f"{column}{credit_row}")
            prior = prior_year_end(period)
            if prior in analysis.periods:
                prior_column = col_name(3 + 2 * analysis.periods.index(prior))
                prior_cell = balance.cells.get(f"{prior_column}{credit_row}")
                prior_value = prior_cell.value if prior_cell is not None else None
                prior_ref = f"'Balanço'!{prior_column}{credit_row}"
            else:
                prior_value = prior_credit.get(prior)
                prior_ref = repr(prior_value) if prior_value is not None else '"N/D"'
            result_ref, credit_ref = f"{column}{rows[source]}", f"'Balanço'!{column}{credit_row}"
            months = int(period[4:])
            formula = (f'=IF(AND(ISNUMBER({result_ref}),ISNUMBER({credit_ref}),ISNUMBER({prior_ref})),'
                       f'IF({credit_ref}+{prior_ref}>0,{result_ref}/AVERAGE({credit_ref},{prior_ref})*{12 / months:g},"{ND}"),"{ND}")')
            numbers = [getattr(result, "value", None), getattr(credit, "value", None), prior_value]
            value = ND
            if all(isinstance(n, (int, float)) for n in numbers) and numbers[1] + numbers[2] > 0:
                value = numbers[0] / ((numbers[1] + numbers[2]) / 2) * 12 / months
            sheet.put(f"{column}{row}", value, formula, "ratio", RATIO)
    note_row = first + len(NIM_ROWS) + 1
    for address, cell in notes:
        sheet.cells[f"{address[0]}{note_row}"] = cell
        sheet.heights[note_row] = sheet.heights.get(int(address[1:]), 19)
    end = col_name(2 + 2 * len(analysis.periods))
    sheet.merges.append(f"B{note_row}:{end}{note_row}")
    sheet.last_row = max(sheet.last_row, note_row)
    sheet.print_area = f"B2:{end}{note_row}"
    analysis.limitations.append(LIMITATION)
