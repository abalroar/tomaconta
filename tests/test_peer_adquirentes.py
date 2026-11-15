"""Peer de Adquirentes: fórmulas, trimestre a partir do acumulado semestral, identidades na base gravada e exportação."""
from __future__ import annotations

import io

import pandas as pd
import pytest

from utils.peer_adquirentes import config as C
from utils.peer_adquirentes import exportar, ifdata, vistas as V
from utils.peer_adquirentes.calculo import Coluna, Peer, avaliar, colunas_acumuladas, colunas_trimestrais
from utils.peer_adquirentes.mascara import MASCARA, POR_ID


def test_avaliar_propaga_ausente():
    assert avaliar("c1 + c2", {"c1": 1.0, "c2": 2.0}) == 3.0
    assert avaliar("c1 + c2", {"c1": 1.0}) is None
    assert avaliar("-(a + b) / c", {"a": 1.0, "b": 1.0, "c": 4.0}) == -0.5
    assert avaliar("a / b", {"a": 1.0, "b": 0.0}) is None


def test_mascara_referencias_validas():
    """Toda fórmula só usa contas (cNNN) ou ids de linhas anteriores."""
    import ast
    vistos = set()
    for it in MASCARA:
        for expr in (it.novo, it.antigo, it.num, it.den):
            if not expr:
                continue
            for n in ast.walk(ast.parse(expr, mode="eval")):
                if isinstance(n, ast.Name) and not n.id.startswith("c"):
                    assert n.id in POR_ID, (it.id, n.id)
                    if it.tipo != "razao":
                        assert n.id in vistos, f"{it.id} usa {n.id} antes de defini-lo"
        vistos.add(it.id)


def _visao_sintetica():
    """Lucro (c141870, leiaute novo) publicado acumulado no semestre: mar=10, jun=25, set=12, dez=30; PL=100 estável."""
    reg = []
    for p, ll in {"202503": 10, "202506": 25, "202509": 12, "202512": 30}.items():
        reg += [{"chave": "stone", "periodo": p, "conta": "141870", "valor": ll * 1e6},
                {"chave": "stone", "periodo": p, "conta": "140246", "valor": 100e6}]
    reg.append({"chave": "stone", "periodo": "202412", "conta": "78186", "valor": 100e6})
    return pd.DataFrame(reg)


def test_trimestre_e_acumulado_do_semestral():
    p = Peer(_visao_sintetica())
    lucro = POR_ID["lucro"]
    tri = {c.rotulo: p.valor("stone", lucro, c) for c in colunas_trimestrais("202512", "202503")}
    assert tri == {"1T25": 10, "2T25": 15, "3T25": 12, "4T25": 18}
    acum = {c.rotulo: p.valor("stone", lucro, c) for c in colunas_acumuladas("202512", 2025)}
    assert acum == {"dez/25": 55}
    assert p.valor("stone", lucro, Coluna("set/25", "202509", "acum")) == 37
    assert p.valor("stone", lucro, Coluna("jun/25", "202506", "acum")) == 25


def test_roe_anualizado_com_pl_medio():
    p = Peer(_visao_sintetica())
    roe = POR_ID["roe"]
    assert p.valor("stone", roe, Coluna("2T25", "202506", "tri")) == pytest.approx(15 * 4 / 100)
    assert p.valor("stone", roe, Coluna("jun/25", "202506", "acum")) == pytest.approx(25 * 2 / 100)   # PL de dez/24 no leiaute antigo


@pytest.fixture(scope="module")
def dados():
    if not C.BASE_CSV.exists():
        pytest.skip("base do peer não gerada")
    return V.Dados.carregar()


def test_base_tem_as_cinco_instituicoes(dados):
    assert set(dados.base["chave"]) == set(C.ORDEM)
    assert dados.ultimo >= "202606"


def test_identidades_fecham(dados):
    """Só a diferença conhecida da própria fonte (SumUp mar/26, Basileia informada × PR/RWA) pode aparecer."""
    pend = [c for c in dados.peer.conferencias() if c["status"] == "diferença"]
    assert all((c["chave"], c["periodo"], c["conferencia"].split(":")[0]) == ("sumup", "202603", "Basileia") for c in pend), pend


def test_numeros_ancora_jun26(dados):
    """Âncoras conferidas contra o IF.data em jun/26 (R$ milhões)."""
    col = Coluna("jun/26", "202606", "acum")
    v = lambda k, i: dados.peer.valor(k, POR_ID[i], col)
    assert v("stone", "lucro") == pytest.approx(2811.27, abs=0.01)
    assert v("stone", "lair") == pytest.approx(1535.31, abs=0.01)
    assert v("stone", "rwasp") == pytest.approx(11592.76, abs=0.01)
    assert v("mercadopago", "ativo") == pytest.approx(125042.64, abs=0.01)
    assert v("stone", "transacoes") == pytest.approx(5508.18, abs=0.01)
    # leiaute antigo: "–" onde não há equivalência
    assert dados.peer.valor("stone", POR_ID["transacoes"], Coluna("dez/24", "202412", "acum")) is None


def test_exportacoes_abrem(dados):
    from openpyxl import load_workbook
    from pptx import Presentation
    for v in (V.comparativo(dados), V.evolucao(dados), V.por_instituicao(dados, "cloudwalk")):
        wb = load_workbook(io.BytesIO(exportar.para_excel(v)))
        assert wb.sheetnames
        prs = Presentation(io.BytesIO(exportar.para_pptx(v)))
        assert len(prs.slides) >= 1


def test_normalizar_remove_duplicata_identica():
    linha = {"CodInst": "C0084686", "AnoMes": "202509", "NumeroRelatorio": "1", "Conta": "140220",
             "NomeColuna": "Ativo Total", "Saldo": 1.0}
    df, alertas = ifdata._normalizar([linha, dict(linha), dict(linha, Saldo=2.0)])
    assert len(df) == 1 and len(alertas) == 1
