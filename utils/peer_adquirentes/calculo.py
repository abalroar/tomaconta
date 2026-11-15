"""Da base longa (ifdata.visao) à máscara: valor de cada linha por instituição e coluna.

Colunas:
- trimestrais ("2T26"): fluxo do trimestre; estoque no fim do trimestre.
- acumuladas ("jun/26"): fluxo acumulado no ano até aquele mês; estoque no fim. É a leitura da planilha de peers
  (dez/24, dez/25, jun/26).

A DRE do IF.data vem acumulada no semestre: mar = 1T, jun = 1S, set = 3T, dez = 2S. Logo
2T = jun − mar, 4T = dez − set; acumulado de set = jun + set, de dez = jun + dez.
"""
from __future__ import annotations

import ast
import operator as op
from dataclasses import dataclass

import pandas as pd

from . import config as C
from .ifdata import anterior
from .mascara import IDENTIDADES, MASCARA, POR_ID, Item

_MES = {"03": "mar", "06": "jun", "09": "set", "12": "dez"}
_OPS = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv}


def avaliar(expr: str, nomes: dict[str, float | None]) -> float | None:
    """Expressão com + - * / e nomes. Qualquer nome ausente ou None devolve None (o "–" da tabela)."""
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.Name):
            v = nomes.get(n.id)
            if v is None or (isinstance(v, float) and v != v):
                raise KeyError(n.id)
            return float(v)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -ev(n.operand)
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Div) and b == 0:
                raise ZeroDivisionError
            return _OPS[type(n.op)](a, b)
        raise ValueError(f"expressão não suportada: {expr}")
    try:
        return ev(ast.parse(expr, mode="eval"))
    except (KeyError, ZeroDivisionError):
        return None


def leiaute(periodo: str) -> str:
    return "antigo" if periodo <= C.ULTIMO_LEIAUTE_ANTIGO else "novo"


# ---------------------------------------------------------------- colunas
@dataclass(frozen=True)
class Coluna:
    rotulo: str
    periodo: str          # AnoMes de fim
    modo: str             # tri | acum

    @property
    def meses(self) -> int:
        m = int(self.periodo[4:])
        return 3 if self.modo == "tri" else m

    @property
    def inicio(self) -> str:
        """Estoque de abertura para médias: trimestre anterior (tri) ou dezembro do ano anterior (acum)."""
        return anterior(self.periodo) if self.modo == "tri" else f"{int(self.periodo[:4]) - 1}12"


def rotulo_tri(periodo: str) -> str:
    return f"{int(periodo[4:]) // 3}T{periodo[2:4]}"


def rotulo_mes(periodo: str) -> str:
    return f"{_MES[periodo[4:]]}/{periodo[2:4]}"


def colunas_trimestrais(ultimo: str, primeiro: str = "202412") -> list[Coluna]:
    from .ifdata import trimestres
    return [Coluna(rotulo_tri(p), p, "tri") for p in trimestres(primeiro, ultimo)]


def colunas_acumuladas(ultimo: str, primeiro_ano: int = 2024) -> list[Coluna]:
    """Dezembros desde `primeiro_ano` e o último período, se não for dezembro (a leitura dez/24 · dez/25 · jun/26)."""
    cols = [Coluna(rotulo_mes(f"{a}12"), f"{a}12", "acum") for a in range(primeiro_ano, int(ultimo[:4]))]
    return cols + [Coluna(rotulo_mes(ultimo), ultimo, "acum")]


# ---------------------------------------------------------------- cálculo
class Peer:
    """Valores da máscara por instituição, a partir da visão (revisada ou original) da base."""

    def __init__(self, visao: pd.DataFrame):
        self.contas: dict[tuple[str, str], dict[str, float | None]] = {}
        for (chave, periodo), g in visao.groupby(["chave", "periodo"]):
            self.contas[(chave, periodo)] = {f"c{c}": (None if pd.isna(v) else float(v)) for c, v in zip(g["conta"], g["valor"])}
        self.periodos = sorted({p for _, p in self.contas})
        self._pontos: dict[tuple[str, str], dict[str, float | None]] = {}

    @property
    def ultimo(self) -> str:
        return self.periodos[-1]

    def ponto(self, chave: str, periodo: str) -> dict[str, float | None]:
        """Linhas fluxo e estoque como publicadas no período (fluxo = acumulado no semestre), no leiaute do período."""
        k = (chave, periodo)
        if k in self._pontos:
            return self._pontos[k]
        nomes = dict(self.contas.get(k, {}))
        out: dict[str, float | None] = {}
        if nomes:
            lay = leiaute(periodo)
            for it in MASCARA:
                if it.tipo in ("fluxo", "estoque"):
                    expr = it.novo if lay == "novo" else it.antigo
                    out[it.id] = avaliar(expr, nomes) if expr else None
                    nomes[it.id] = out[it.id]
        self._pontos[k] = out
        return out

    def _fluxo(self, chave: str, it_id: str, col: Coluna) -> float | None:
        p = col.periodo
        m = p[4:]
        v = self.ponto(chave, p).get(it_id)
        if v is None:
            return None
        if m == "03" or (m == "09" and col.modo == "tri") or (m == "06" and col.modo == "acum"):
            return v
        par = {"06": f"{p[:4]}03", "12": f"{p[:4]}09", "09": f"{p[:4]}06"}[m]
        w = self.ponto(chave, par).get(it_id)
        if w is None:
            return None
        if col.modo == "tri":       # jun − mar, dez − set
            return v - w
        return v + w                # acumulado de set = jun + 3T

    def _acum_dez(self, chave: str, it_id: str, col: Coluna) -> float | None:
        """Acumulado de dez = jun + 2S (a fórmula genérica pega set, por isso este atalho)."""
        a = col.periodo[:4]
        v, w = self.ponto(chave, col.periodo).get(it_id), self.ponto(chave, f"{a}06").get(it_id)
        return None if v is None or w is None else v + w

    def valor_bruto(self, chave: str, it: Item, col: Coluna) -> float | None:
        """Valor na unidade da fonte (R$ ou fração), antes da escala de exibição."""
        if it.tipo == "estoque":
            return self.ponto(chave, col.periodo).get(it.id)
        if it.tipo == "fluxo":
            if col.modo == "acum" and col.periodo[4:] == "12":
                return self._acum_dez(chave, it.id, col)
            return self._fluxo(chave, it.id, col)
        if it.tipo == "razao":
            ids = _nomes(it.num) | _nomes(it.den)
            num_nomes = {i: self.valor_bruto(chave, POR_ID[i], col) for i in ids if i in POR_ID}
            num = avaliar(it.num, num_nomes)
            if num is None:
                return None
            if it.anualizar:
                num *= 12 / col.meses
            if it.media:
                ini = Coluna(col.rotulo, col.inicio, col.modo)
                den_fim = avaliar(it.den, num_nomes)
                den_ini = avaliar(it.den, {i: self.valor_bruto(chave, POR_ID[i], ini) for i in ids if i in POR_ID})
                if den_fim is None or den_ini is None:
                    return None
                den = (den_fim + den_ini) / 2
            else:
                den = avaliar(it.den, num_nomes)
            if den is None or den == 0 or (it.den_positivo and den < 0):
                return None
            return num / den
        return None

    def valor(self, chave: str, it: Item, col: Coluna) -> float | None:
        """Valor de exibição: R$ milhões para 'mi', fração para 'pct1', vezes para 'x1'."""
        v = self.valor_bruto(chave, it, col)
        if v is None:
            return None
        return v / 1e6 if it.formato == "mi" else v

    def tabela(self, chaves: list[str], colunas: list[Coluna]) -> pd.DataFrame:
        """Formato longo: chave, coluna, id, valor (exibição)."""
        reg = []
        for k in chaves:
            for col in colunas:
                for it in MASCARA:
                    if it.tipo == "grupo":
                        continue
                    reg.append({"chave": k, "coluna": col.rotulo, "id": it.id, "valor": self.valor(k, it, col)})
        return pd.DataFrame(reg)

    # ------------------------------------------------------------ conferências
    def conferencias(self, tol_rs: float = 1_000.0, tol_pct: float = 0.0005) -> list[dict]:
        """Identidades da máscara em cada instituição e período, e Basileia = PR / RWA. Diferença acima de R$ 1 mil
        (ou 0,05 p.p. no índice) vira pendência."""
        out = []
        for (chave, periodo) in sorted(self.contas):
            pt = dict(self.contas[(chave, periodo)])
            pt.update(self.ponto(chave, periodo))
            lay = leiaute(periodo)
            for nome, esq, dir_, so in IDENTIDADES:
                if so and so != lay:
                    continue
                a, b = avaliar(esq, pt), avaliar(dir_, pt)
                if a is None or b is None:
                    out.append({"chave": chave, "periodo": periodo, "conferencia": nome, "status": "sem dado", "diferenca": None})
                    continue
                d = a - b
                out.append({"chave": chave, "periodo": periodo, "conferencia": nome,
                            "status": "ok" if abs(d) <= tol_rs else "diferença", "diferenca": d})
            pt_total = "c140247" if lay == "novo" else "c78300"
            a, b = pt.get("ativo"), pt.get(pt_total)
            if a is not None and b is not None:
                out.append({"chave": chave, "periodo": periodo, "conferencia": "Balanço: ativo total = passivo total",
                            "status": "ok" if abs(a - b) <= tol_rs else "diferença", "diferenca": a - b})
            pr, rwa, ib = pt.get("pr"), pt.get("rwa"), pt.get("basileia")
            if None not in (pr, rwa, ib) and rwa:
                d = pr / rwa - ib
                out.append({"chave": chave, "periodo": periodo, "conferencia": "Basileia: PR / RWA = índice informado",
                            "status": "ok" if abs(d) <= tol_pct else "diferença", "diferenca": d})
        return out


def _nomes(expr: str | None) -> set[str]:
    if not expr:
        return set()
    return {n.id for n in ast.walk(ast.parse(expr, mode="eval")) if isinstance(n, ast.Name)}
