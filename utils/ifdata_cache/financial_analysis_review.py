"""Revisão de contas COSIF a cada publicação: regras fixas, sem interpretação de nomes.

O catálogo é o próprio histórico carregado. Conta nova, conta que sumiu ou salto em
linha-chave com valor material suspendem a promoção até uma decisão registrada.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..prudential_analysis import dre_row_for, dre_row_labels, stem

# A DRE tolera menos: uma conta fora da linha certa muda o subtotal sem alterar o lucro.
REVIEW_MATERIAL_BRL = 100_000_000.0
BALANCE_MATERIAL_BRL = 5_000_000_000.0
# Compensação (3 e 9) e seus totais ficam fora do Balanço e da DRE.
STATEMENT_GROUPS = tuple("124678")
WATCHED_ROWS = ("provision",)
JUMP_FACTOR = 3.0
# As contas de resultado encerram em junho e dezembro: sumir no mês seguinte é esperado.
RESET_MONTHS = ("01", "07")


def _summary(frame):
    if frame.empty:
        return pd.DataFrame(columns=["total", "institutions", "name"])
    # O prefixo contábil identifica a conta: o BCB trocou códigos de 8 por 10 dígitos em 2025.
    frame = frame[frame.CONTA.str[0].isin(STATEMENT_GROUPS)]
    if frame.empty:
        return pd.DataFrame(columns=["total", "institutions", "name", "account"])
    grouped = frame.assign(abs_saldo=frame.SALDO.abs(), prefix=frame.CONTA.map(stem)).groupby("prefix", sort=True)
    return pd.DataFrame({"total": grouped.abs_saldo.sum(), "institutions": grouped.COD_CONGL.nunique(),
                         "name": grouped.NOME_CONTA.agg(lambda names: names.value_counts().index[0]),
                         "account": grouped.CONTA.last()})


def _clean(name):
    return " ".join(str(name).split()).casefold()


def _is_material(row, limit):
    return row.total >= (limit if row.account[0] in "78" else max(limit, BALANCE_MATERIAL_BRL))


def _item(kind, document, row, *, material, overrides=None, previous_name=None):
    account = row["account"]
    result_account = document == "4060" and account[0] in "78"
    line = (overrides or {}).get(account) or (dre_row_for(account) if result_account else None)
    return {"id": f"{kind}:{document}:{account}", "kind": kind, "document": document, "account": account,
            "name": str(row["name"]), "previous_name": previous_name, "total_brl": float(row["total"]),
            "institutions": int(row["institutions"]), "row": line,
            "row_label": dre_row_labels().get(line) if line else None, "result_account": result_account,
            "blocking": material}


def account_changes(cosif, period, *, material=REVIEW_MATERIAL_BRL, overrides=None):
    """Compara a competência com o histórico, por documento, em todo o sistema."""
    items = []
    for document, frame in cosif.groupby("DOCUMENTO"):
        incoming = frame[frame.DATA_BASE.eq(period)]
        history = frame[frame.DATA_BASE.lt(period)]
        if incoming.empty or history.empty:
            continue
        current, known = _summary(incoming), set(history.CONTA.map(stem))
        before = _summary(history[history.DATA_BASE.eq(history.DATA_BASE.max())])
        for prefix, row in current.iterrows():
            if prefix not in known:
                items.append(_item("nova", document, row, material=_is_material(row, material), overrides=overrides))
            elif prefix in before.index and _clean(before.at[prefix, "name"]) != _clean(row["name"]):
                # Mudança de nome pode ser só grafia; fica visível, sem suspender.
                items.append(_item("renomeada", document, row, material=False, overrides=overrides, previous_name=str(before.at[prefix, "name"])))
        for prefix, row in before[~before.index.isin(current.index)].iterrows():
            expected = row.account[0] in "78" and period[4:] in RESET_MONTHS
            items.append(_item("sumiu", document, row, material=_is_material(row, material) and not expected, overrides=overrides))
    return sorted(items, key=lambda item: (not item["blocking"], -item["total_brl"]))


def row_jumps(watched, period):
    """Troca de sinal ou salto acima de três vezes contra a mesma janela do ano anterior."""
    items = []
    for ident, (current, previous) in watched.items():
        if not previous:
            continue
        if (current < 0) != (previous < 0) or not 1 / JUMP_FACTOR <= abs(current / previous) <= JUMP_FACTOR:
            items.append({"id": f"salto:{ident}:{period}", "kind": "salto", "document": "4060", "account": None,
                          "name": dre_row_labels().get(ident, ident), "previous_name": None,
                          "total_brl": current * 1e6, "previous_brl": previous * 1e6, "institutions": None,
                          "row": ident, "row_label": dre_row_labels().get(ident), "result_account": True, "blocking": True})
    return items


def pending_items(items, decisions):
    """Itens que ainda impedem a promoção."""
    answered = set(decisions or ())
    return [item["id"] for item in items if item["blocking"] and item["id"] not in answered]


def new_decisions(decisions, period, run_id):
    """Registro auditável das respostas; só as contas com linha definida alteram a DRE."""
    now = datetime.now(timezone.utc).isoformat()
    labels = dre_row_labels()
    recorded = []
    for item_id, answer in (decisions or {}).items():
        row = (answer or {}).get("row")
        if row and row not in labels:
            raise ValueError(f"Linha da DRE desconhecida: {row}")
        recorded.append({"id": item_id, "account": item_id.split(":")[2] if item_id.count(":") == 2 and not item_id.startswith("salto") else None,
                         "row": row, "period": period, "run_id": run_id, "decided_at": now})
    return recorded
