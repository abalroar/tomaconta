"""Vistas: o conteúdo de cada tela descrito uma vez só (tabela + até quatro gráficos de linha).

A mesma descrição alimenta a página (tabs/peer_adquirentes.py), o Excel e o PowerPoint (exportar.py).
Adaptado do gdes-bancos (src/gdes/vistas.py), sem importá-lo.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import config as C
from . import ifdata
from .calculo import Coluna, Peer, colunas_acumuladas, colunas_trimestrais, rotulo_mes
from .mascara import MASCARA, NOTAS, POR_ID

FMT = {"mi": "mi", "pct1": "pct1", "x1": "x1"}
_SOBRESCRITO = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


def fmt(v, formato: str) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "–"
    br = lambda s: s.replace(",", "§").replace(".", ",").replace("§", ".").replace("-", "−")
    if formato == "mi":
        return br(f"{v:,.0f}")
    if formato == "pct1":
        return br(f"{v * 100:.1f}") + "%"
    if formato == "x1":
        return br(f"{v:.1f}") + "x"
    return str(v)


@dataclass
class Cel:
    v: float | str | None
    f: str = "mi"


@dataclass
class Linha:
    rotulo: str
    cels: list[Cel] = field(default_factory=list)
    estilo: str = ""          # "", forte, recuo, pct, grp


@dataclass
class Tab:
    canto: str
    colunas: list[str]
    linhas: list[Linha]
    grupos: list[tuple[str, int]] = field(default_factory=list)   # (nome da instituição, nº de colunas)
    chaves: list[str | None] = field(default_factory=list)        # chave de cada grupo (cor do cabeçalho)
    vazio: str = "–"


@dataclass
class Graf:
    titulo: str
    categorias: list[str]
    series: list[tuple[str, list]]   # (chave da instituição, valores)
    formato: str = "pct1"


@dataclass
class Vista:
    chave: str
    titulo: str
    tabela: Tab | None = None
    graficos: list[Graf] = field(default_factory=list)
    nota: str = ""                                   # fonte e leitura (vai em toda página/slide)
    notas: list[str] = field(default_factory=list)   # notas numeradas "(n) ..." das linhas e lacunas da fonte

    @property
    def nota_completa(self) -> str:
        return " ".join([self.nota, *self.notas])


def texto(c: Cel | None) -> str:
    if c is None or c.v is None:
        return "–"
    if isinstance(c.v, str):
        return c.v
    return fmt(c.v, c.f)


class Dados:
    """Acesso único: base, visão (revisada ou original) e o cálculo da máscara."""

    def __init__(self, base: pd.DataFrame, modo: str = "revisada"):
        self.base = base
        self.modo = modo
        self.peer = Peer(ifdata.visao(base, modo))
        self.ultimo = self.peer.ultimo

    @classmethod
    def carregar(cls, modo: str = "revisada") -> "Dados":
        return cls(ifdata.carregar_base(), modo)


def _notas(ids: list[str]) -> tuple[dict[str, int], list[str]]:
    """Numera as notas na ordem em que as linhas aparecem."""
    num: dict[str, int] = {}
    for i in ids:
        n = POR_ID[i].nota
        if n and n not in num:
            num[n] = len(num) + 1
    return num, [f"({k}) {NOTAS[n]}" for n, k in num.items()]


def _rotulo(it, num: dict[str, int]) -> str:
    return it.rotulo + (f" ({num[it.nota]})" if it.nota else "")


def _linhas(d: Dados, chaves: list[str], colunas: list[Coluna], blocos: list[str] | None) -> tuple[list[Linha], list[str]]:
    itens, bloco_atual = [], None
    for it in MASCARA:
        if it.tipo == "grupo":
            bloco_atual = it.id
        if blocos and bloco_atual not in blocos:
            continue
        itens.append(it)
    num, notas = _notas([i.id for i in itens if i.tipo != "grupo"])
    linhas = []
    for it in itens:
        if it.tipo == "grupo":
            if linhas:
                linhas.append(Linha("", [], "sep"))
            linhas.append(Linha(it.rotulo, [Cel(None, "mi") for _ in chaves for _ in colunas], "grp"))
            continue
        cels = [Cel(d.peer.valor(k, it, c), it.formato) for k in chaves for c in colunas]
        linhas.append(Linha(_rotulo(it, num), cels, it.estilo))
    return linhas, notas


def _fonte(d: Dados) -> str:
    return ("Fonte: IF.data/BCB (API Olinda), conglomerado prudencial, visão " + d.modo + ". Leiaute COSIF antigo até dez/24 e "
            "da Res. 4.966 a partir de mar/25; \"–\" quando a linha não existe no leiaute ou não foi publicada.")


def _lacunas(chaves: list[str], periodos: set[str]) -> list[str]:
    return [t for (k, p), t in C.LACUNAS.items() if k in chaves and any(p <= x for x in periodos)]


BLOCOS = {"g_resultado": "Resultado", "g_rentabilidade": "Rentabilidade", "g_balanco": "Balanço e funding",
          "g_capital": "Capital regulatório", "g_credito": "Crédito"}


def comparativo(d: Dados, chaves: list[str] | None = None, blocos: list[str] | None = None) -> Vista:
    """A aba 1_Peer_Group: instituições lado a lado, dez/24 · dez/25 · último período (fluxos acumulados no ano)."""
    chaves = chaves or list(C.ORDEM)
    cols = colunas_acumuladas(d.ultimo)
    linhas, notas = _linhas(d, chaves, cols, blocos)
    tab = Tab("R$ milhões", [c.rotulo for _ in chaves for c in cols], linhas,
              grupos=[(C.INSTITUICOES[k]["nome"], len(cols)) for k in chaves], chaves=list(chaves))
    nota = "Fluxos acumulados no ano até o mês da coluna; razões com fluxo anualizadas. " + _fonte(d)
    return Vista("peer_adquirentes_comparativo", f"Peer de Adquirentes – {rotulo_mes(d.ultimo)}", tab, [], nota,
                 notas + _lacunas(chaves, {c.periodo for c in cols}))


def por_instituicao(d: Dados, chave: str, modo: str = "tri", blocos: list[str] | None = None) -> Vista:
    """Máscara completa de uma instituição com os períodos nas colunas (trimestres ou acumulado no ano)."""
    cols = colunas_trimestrais(d.ultimo) if modo == "tri" else colunas_acumuladas(d.ultimo)
    linhas, notas = _linhas(d, [chave], cols, blocos)
    nome = C.INSTITUICOES[chave]["nome"]
    tab = Tab("R$ milhões", [c.rotulo for c in cols], linhas, grupos=[(nome, len(cols))], chaves=[chave])
    leitura = "Fluxos do trimestre" if modo == "tri" else "Fluxos acumulados no ano"
    nota = f"{C.INSTITUICOES[chave]['perimetro']}. {leitura}; razões com fluxo anualizadas. " + _fonte(d)
    return Vista(f"peer_adquirentes_{chave}", f"{nome} – {rotulo_mes(d.ultimo)}", tab, [], nota,
                 notas + _lacunas([chave], {c.periodo for c in cols}))


INDICADORES_GRAFICO = ["roe", "eficiencia", "custo_funding", "basileia", "rwasp_rwa", "margem", "cobertura",
                       "custo_credito", "divida_pl", "receita", "lucro", "transacoes"]
PADRAO_GRAFICO = ["roe", "eficiencia", "rwasp_rwa", "basileia"]


def evolucao(d: Dados, ids: list[str] | None = None, chaves: list[str] | None = None, primeiro: str = "202503") -> Vista:
    """Até quatro gráficos de linha por trimestre, uma linha por instituição. Começa em 1T25 (leiaute novo), para que
    nenhuma linha mude de definição no meio do gráfico."""
    ids = (ids or PADRAO_GRAFICO)[:4]
    chaves = chaves or list(C.ORDEM)
    cols = colunas_trimestrais(d.ultimo, primeiro)
    grafs = []
    for i in ids:
        it = POR_ID[i]
        unidade = {"mi": "R$ milhões", "pct1": "%", "x1": "x"}[it.formato]
        titulo = it.rotulo.split(":")[0] + f" ({unidade})"
        series = [(k, [d.peer.valor(k, it, c) for c in cols]) for k in chaves]
        series = [(k, v) for k, v in series if any(x is not None for x in v)]
        grafs.append(Graf(titulo, [c.rotulo for c in cols], series, it.formato))
    num, notas = _notas(ids)
    nota = "Trimestres desde 1T25 (leiaute da Res. 4.966). Razões com fluxo anualizadas pelo trimestre. " + _fonte(d)
    return Vista("peer_adquirentes_evolucao", f"Peer de Adquirentes – evolução até {cols[-1].rotulo}", None, grafs, nota,
                 notas + _lacunas(chaves, {c.periodo for c in cols}))
