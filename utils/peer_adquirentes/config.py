"""Instituições do Peer de Adquirentes e cor de cada uma (fonte única para tela, Excel e PowerPoint).

Todas no perímetro **prudencial** (TipoInstituicao = 1 no IF.data). Perímetros não se misturam: o individual
de cada IP não entra na base.
"""
from __future__ import annotations

from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
PASTA_DADOS = RAIZ / "data" / "peer_adquirentes"
BASE_CSV = PASTA_DADOS / "base.csv"
SITUACAO_JSON = PASTA_DADOS / "situacao.json"

# chave -> nome, nome curto, código do conglomerado prudencial e o que ele consolida (cadastro do IF.data, jun/26)
INSTITUICOES: dict[str, dict] = {
    "stone": {"nome": "Stone", "curto": "Stone", "cod": "C0084686",
              "perimetro": "Stone IP – Prudencial: Stone IP, Stone SCD, Stone SCFI, Stone DTVM, Stone Cartões IP e Pagar.me IP"},
    "pagbank": {"nome": "PagBank", "curto": "PagBank", "cod": "C0084813",
                "perimetro": "PagSeguro – Prudencial: PagSeguro Internet IP, BancoSeguro e PagInvest CTVM"},
    "mercadopago": {"nome": "Mercado Pago", "curto": "M. Pago", "cod": "C0084820",
                    "perimetro": "Mercado Pago IP – Prudencial: Mercado Pago IP, Mercado Crédito SCFI e Mercado Pago DTVM"},
    "cloudwalk": {"nome": "CloudWalk", "curto": "CloudWalk", "cod": "C0086581",
                  "perimetro": "CloudWalk IP – Prudencial: CloudWalk IP e CloudWalk Financeira SCFI"},
    "sumup": {"nome": "SumUp", "curto": "SumUp", "cod": "C0085238",
              "perimetro": "SumUp IP – Prudencial: SumUp IP e SumUp SCD"},
}
ORDEM = list(INSTITUICOES)
POR_COD = {v["cod"]: k for k, v in INSTITUICOES.items()}

# Cor só identifica a instituição. claro/escuro: linhas e rótulos em cada tema; fundo: cabeçalho com texto branco.
# Stone: verde da marca. PagBank: o amarelo da marca não sustenta texto branco, por isso o dourado escuro.
# Mercado Pago: azul da marca. CloudWalk: a marca é preta, por isso ardósia (clara no tema escuro).
# SumUp: a marca é preta e azul (azul já tomado), por isso roxo. Toda linha de gráfico termina com o nome da instituição.
CORES: dict[str, dict[str, str]] = {
    "stone": {"claro": "#00A868", "escuro": "#2ECC8F", "fundo": "#00875A"},
    "pagbank": {"claro": "#B08500", "escuro": "#E0B420", "fundo": "#A07800"},
    "mercadopago": {"claro": "#009EE3", "escuro": "#3DB8F0", "fundo": "#007DB8"},
    "cloudwalk": {"claro": "#3D4555", "escuro": "#AAB3C5", "fundo": "#3D4555"},
    "sumup": {"claro": "#7C3AED", "escuro": "#A78BFA", "fundo": "#6D28D9"},
}


def cor(chave: str, uso: str = "claro") -> str:
    c = CORES[chave]
    return c.get(uso) or c["fundo"]


# Períodos (AnoMes) que a base cobre: dez/23 entra só como estoque de abertura (média de PL, dívida e carteira de 2024).
PRIMEIRO_PERIODO = "202312"
# Até dez/24 vale o leiaute antigo do COSIF no IF.data; de mar/25 em diante, o leiaute da Res. 4.966.
ULTIMO_LEIAUTE_ANTIGO = "202412"
RELATORIOS = ("1", "2", "3", "4", "5")

# Lacunas da própria fonte, mostradas na nota da tabela e na página Fontes (não são erro de extração).
LACUNAS = {
    ("sumup", "202512"): "SumUp: o IF.data publica o conglomerado prudencial de dez/25 só com capital (balanço e DRE nulos). "
                         "Ficam \"–\" dez/25, o 4T25, o acumulado de 2025 e as razões que usam o PL de dez/25.",
}
