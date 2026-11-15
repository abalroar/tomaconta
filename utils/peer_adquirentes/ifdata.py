"""Extração do IF.data (API Olinda do BCB) para as instituições do peer, com base longa e safras.

Determinística: cada número vem de uma linha do IF.data identificada pelo código da conta (`Conta`), que é estável
entre períodos. A base guarda a primeira aparição de cada número e toda reapresentação posterior (uma linha por safra),
o que dá duas visões: *revisada* (o valor mais recente) e *original* (como publicado na primeira vez).

    python -m utils.peer_adquirentes atualizar
"""
from __future__ import annotations

import datetime as dt
import json
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from . import config as C

BASE_URL = "https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata/"
COLUNAS = ["chave", "cod", "periodo", "relatorio", "conta", "nome", "valor", "safra"]
TOLERANCIA = 0.005        # R$ (meio centavo): abaixo disso não é reapresentação


# ---------------------------------------------------------------- períodos
def trimestres(inicio: str, fim: str) -> list[str]:
    """AnoMes de fim de trimestre entre `inicio` e `fim` (inclusive): ['202312', '202403', ...]."""
    a, m = int(inicio[:4]), int(inicio[4:])
    out = []
    while f"{a}{m:02d}" <= fim:
        if m in (3, 6, 9, 12):
            out.append(f"{a}{m:02d}")
        m += 1
        if m > 12:
            a, m = a + 1, 1
    return out


def proximo(periodo: str) -> str:
    a, m = int(periodo[:4]), int(periodo[4:])
    return f"{a + 1}03" if m == 12 else f"{a}{m + 3:02d}"


def anterior(periodo: str) -> str:
    a, m = int(periodo[:4]), int(periodo[4:])
    return f"{a - 1}12" if m == 3 else f"{a}{m - 3:02d}"


# ---------------------------------------------------------------- API
def _url(periodo: str, relatorio: str, cods: list[str]) -> str:
    filtro = " or ".join(f"CodInst eq '{c}'" for c in cods)
    return (BASE_URL + "IfDataValores(AnoMes=@AnoMes,TipoInstituicao=@TipoInstituicao,Relatorio=@Relatorio)"
            f"?@AnoMes={periodo}&@TipoInstituicao=1&@Relatorio='{relatorio}'&$format=json&$top=1000000"
            f"&$filter={urllib.parse.quote(filtro)}")


def baixar(periodo: str, relatorio: str, cods: list[str] | None = None, tentativas: int = 4) -> list[dict] | None:
    """Linhas do relatório no período para os conglomerados pedidos. [] = ainda não publicado; None = falha de rede."""
    import requests

    cods = cods or [v["cod"] for v in C.INSTITUICOES.values()]
    for _ in range(tentativas):
        try:
            r = requests.get(_url(periodo, relatorio, cods), timeout=180)
            r.raise_for_status()
            return r.json().get("value", [])
        except Exception:  # noqa: BLE001 - qualquer falha de rede vira nova tentativa
            continue
    return None


def publicado(periodo: str) -> bool | None:
    """O período já saiu no IF.data? Consulta só o Resumo (relatório 1). None quando a API não responde."""
    linhas = baixar(periodo, "1", tentativas=2)
    return None if linhas is None else bool(linhas)


def _normalizar(linhas: list[dict]) -> tuple[pd.DataFrame, list[dict]]:
    """Uma linha por (instituição, período, relatório, conta). Duplicatas idênticas (a API repete linhas em
    set/25) caem; duplicatas com valores diferentes ficam na primeira ocorrência e são devolvidas como alerta."""
    reg, alertas, vistos = [], [], {}
    for x in linhas:
        cod = x.get("CodInst")
        if cod not in C.POR_COD:
            continue
        chave = (cod, x["AnoMes"], str(x["NumeroRelatorio"]), str(x["Conta"]))
        v = x.get("Saldo")
        if chave in vistos:
            if (vistos[chave] is None) != (v is None) or (v is not None and abs(vistos[chave] - v) > TOLERANCIA):
                alertas.append({"tipo": "duplicata divergente", "cod": cod, "periodo": x["AnoMes"],
                                "relatorio": chave[2], "conta": chave[3], "valores": [vistos[chave], v]})
            continue
        vistos[chave] = v
        reg.append({"chave": C.POR_COD[cod], "cod": cod, "periodo": x["AnoMes"], "relatorio": chave[2],
                    "conta": chave[3], "nome": " ".join(str(x.get("NomeColuna") or "").split()), "valor": v})
    return pd.DataFrame(reg, columns=COLUNAS[:-1]), alertas


# ---------------------------------------------------------------- base
def carregar_base() -> pd.DataFrame:
    if not C.BASE_CSV.exists():
        return pd.DataFrame(columns=COLUNAS)
    return pd.read_csv(C.BASE_CSV, dtype={"cod": str, "periodo": str, "relatorio": str, "conta": str, "safra": str})


def visao(base: pd.DataFrame, modo: str = "revisada") -> pd.DataFrame:
    """Um valor por (instituição, período, conta): o da safra mais recente (revisada) ou o da primeira (original).
    Uma conta que aparece em dois relatórios (Ativo Total no 2 e no 4, Lucro Líquido no 1 e no 4) tem o mesmo valor
    nos dois; a conferência `contas_repetidas` vigia isso."""
    if base.empty:
        return pd.DataFrame(columns=["chave", "periodo", "conta", "valor"])
    b = base.sort_values(["safra"], kind="stable")
    b = b.groupby(["chave", "periodo", "relatorio", "conta"], as_index=False).agg(valor=("valor", "last" if modo == "revisada" else "first"))
    return b.drop_duplicates(["chave", "periodo", "conta"])[["chave", "periodo", "conta", "valor"]]


def revisoes(base: pd.DataFrame) -> pd.DataFrame:
    """Números reapresentados pelo BC entre uma safra e outra."""
    if base.empty:
        return pd.DataFrame()
    g = base.groupby(["chave", "periodo", "relatorio", "conta"])
    n = g["safra"].transform("nunique")
    r = base[n > 1].sort_values(["chave", "periodo", "relatorio", "conta", "safra"])
    return r


def atualizar(hoje: dt.date | None = None, ate: str | None = None, workers: int = 6) -> dict:
    """Baixa todos os períodos desde PRIMEIRO_PERIODO até o último publicado e grava só o que é novo ou reapresentado."""
    hoje = hoje or dt.date.today()
    safra = hoje.isoformat()
    base = carregar_base()
    ultimo_conhecido = base["periodo"].max() if not base.empty else C.ULTIMO_LEIAUTE_ANTIGO
    # o último publicado: anda trimestre a trimestre a partir do último conhecido até o primeiro vazio
    fim = ate or ultimo_conhecido
    if not ate:
        while proximo(fim) <= f"{hoje.year}{hoje.month:02d}":
            ok = publicado(proximo(fim))
            if not ok:
                break
            fim = proximo(fim)
    jobs = [(p, r) for p in trimestres(C.PRIMEIRO_PERIODO, fim) for r in C.RELATORIOS]
    with ThreadPoolExecutor(workers) as ex:
        resultados = list(ex.map(lambda a: (a, baixar(*a)), jobs))
    falhas = [f"{p}/rel.{r}" for (p, r), linhas in resultados if linhas is None]
    todas = [x for _, linhas in resultados if linhas for x in linhas]
    novo, alertas = _normalizar(todas)

    if not base.empty:
        ult = base.sort_values("safra", kind="stable").groupby(["chave", "periodo", "relatorio", "conta"], as_index=False).last()
        m = novo.merge(ult[["chave", "periodo", "relatorio", "conta", "valor"]], on=["chave", "periodo", "relatorio", "conta"],
                       how="left", suffixes=("", "_ant"), indicator=True)
        inedito = m["_merge"] == "left_only"
        mudou = (m["_merge"] == "both") & (
            (m["valor"].isna() != m["valor_ant"].isna())
            | ((m["valor"] - m["valor_ant"]).abs() > TOLERANCIA)
        )
        entra = m[inedito | mudou][COLUNAS[:-1]].copy()
        n_rev = int(mudou.sum())
    else:
        entra, n_rev = novo.copy(), 0
    entra["safra"] = safra
    saida = pd.concat([base, entra], ignore_index=True) if not base.empty else entra
    saida = saida.sort_values(["chave", "periodo", "relatorio", "conta", "safra"], key=_ordem_chave, kind="stable")
    C.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    if len(entra):
        saida[COLUNAS].to_csv(C.BASE_CSV, index=False)
    resumo = {
        "consultado_em": dt.datetime.now().isoformat(timespec="seconds"),
        "ultimo_periodo": fim,
        "linhas_novas": int(len(entra) - n_rev),
        "reapresentadas": n_rev,
        "falhas": falhas,
        "alertas": alertas,
    }
    return resumo


def _ordem_chave(s: pd.Series) -> pd.Series:
    if s.name == "chave":
        return s.map({k: i for i, k in enumerate(C.ORDEM)})
    if s.name == "conta":
        return s.astype(int)
    return s


def gravar_situacao(resumo: dict) -> None:
    C.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    C.SITUACAO_JSON.write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")


def ler_situacao() -> dict:
    try:
        return json.loads(C.SITUACAO_JSON.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
