"""Máscara do Peer de Adquirentes: cada linha aponta para contas do IF.data (código `Conta`) ou para outras linhas.

`novo` vale do leiaute da Res. 4.966 (mar/25 em diante); `antigo`, do leiaute anterior (até dez/24). Linha sem
fórmula num leiaute sai como "–" naquele período, com a nota explicando. Mudar uma linha é editar esta lista.

Vocabulário das fórmulas: `c<conta>` é uma conta do IF.data (ex.: c141870 = Lucro Líquido); qualquer outro nome é
o `id` de uma linha anterior; operadores + - * /.

Tipos:
- fluxo: DRE, publicada acumulada no semestre (mar = 1T, jun = 1S, set = 3T, dez = 2S); o trimestre e o acumulado
  no ano saem por soma e diferença (calculo.py).
- estoque: saldo no fim do período (balanço e capital).
- razao: `num` / `den`, ambos expressões em ids; `anualizar` anualiza o numerador (fluxo) e `media` usa a média do
  denominador (estoque) entre o início e o fim do período.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    id: str
    rotulo: str
    tipo: str                    # fluxo | estoque | razao | grupo
    novo: str | None = None
    antigo: str | None = None
    formato: str = "mi"          # mi (R$ milhões) | pct1 | x1
    estilo: str = ""             # forte | recuo | pct | grp
    nota: str | None = None      # chave em NOTAS
    num: str | None = None
    den: str | None = None
    anualizar: bool = False
    media: bool = False
    den_positivo: bool = False   # "–" quando o denominador é negativo (alíquota com prejuízo antes de IR)


NOTAS = {
    "transacoes": "Resultado com transações de pagamento: linha criada no leiaute da Res. 4.966 (mar/25). Vem líquido dos custos "
                  "de transação (intercâmbio e bandeiras); no leiaute antigo receitas e custos de transação ficavam brutos em "
                  "Prestação de serviços, Outras receitas e Outras despesas operacionais, sem equivalência linha a linha. Por isso "
                  "\"–\" até dez/24.",
    "receita": "Receita líquida (aproximação regulatória do faturamento líquido): transações de pagamento antes da perda esperada "
               "+ crédito + aplicações e TVM + serviços e tarifas + outras receitas + derivativos e demais resultados financeiros. "
               "Não é o faturamento gerencial do RI. Sem equivalente no leiaute antigo (ver nota de transações).",
    "floating": "Aplicações e TVM: rendas de aplicações interfinanceiras e de títulos (o \"floating\"). No leiaute antigo, rendas "
                "de TVM (a3) + aplicações compulsórias (a6).",
    "servicos": "Serviços e tarifas: no leiaute antigo inclui a receita de MDR, que no novo foi para transações de pagamento.",
    "outras": "Outras receitas e Outras despesas: no leiaute antigo incluem receitas e custos de transação brutos; a partir de "
              "mar/25 esses valores estão líquidos em transações de pagamento.",
    "captacao": "Despesa de captação: no leiaute novo, captações (g) + instrumentos de dívida elegíveis a capital (h); no antigo, "
                "captação (b1) + empréstimos e repasses (b2) + arrendamento (b3). O custo médio de funding pode ficar acima "
                "da taxa de mercado quando a despesa inclui o desconto de recebíveis cedidos, que não ficam no balanço.",
    "perda": "Perda esperada de crédito: no leiaute novo, perda esperada (f) + de outras operações (q); no antigo, provisão para "
             "créditos de difícil liquidação (b5). A perda esperada com transações de pagamento (l2) fica na linha de transações.",
    "ir": "Imposto de renda: valor positivo é crédito tributário reconhecido no período (Stone, 1S26: R$ 1,4 bi de crédito, "
          "lucro de R$ 2,8 bi para resultado antes de IR de R$ 1,5 bi).",
    "anualizado": "Razões com fluxo no numerador são anualizadas (trimestre × 4; acumulado de jun × 2) e usam a média do "
                  "denominador entre o início e o fim do período (trimestre anterior, ou dez do ano anterior no acumulado).",
    "caixa": "Caixa, aplicações e TVM: disponibilidades + aplicações interfinanceiras + títulos e derivativos. Mercado Pago: "
             "TVM cai de R$ 27,1 bi (dez/24) para R$ 4,4 bi (jun/26) com a troca de leiaute, enquanto Outros ativos "
             "realizáveis sobem; o IF.data não abre a reclassificação.",
    "outros_ativos": "Outros ativos realizáveis: concentra os recebíveis de transações de pagamento (valores a receber de emissores "
                     "e bandeiras), base da antecipação ao lojista.",
    "outras_obrig": "Outras obrigações: inclui os valores a pagar a estabelecimentos.",
    "divida": "Dívida bruta: captações exceto conta de pagamento pré-paga (saldo de clientes, sem custo financeiro) + instrumentos "
              "de dívida elegíveis a capital. Corresponde a Bancos CP + LP e FIDCs on-balance da planilha gerencial, no perímetro "
              "regulatório.",
    "prepaga": "Conta de pagamento pré-paga: moeda eletrônica de clientes, que a IP mantém em títulos públicos ou no BC.",
    "carteira": "Carteira de crédito: carteira classificada do Resumo (relatório 1), que inclui cartão e demais operações com "
                "características de crédito. Carteira bruta e perda esperada vêm do Ativo (relatório 2).",
    "rwasp": "RWAsp: parcela do RWA para serviços de pagamento (Res. BCB 200/2022), exigida das instituições de pagamento.",
    "capital_cw": "CloudWalk não informa a abertura do capital (principal, complementar e nível II) até dez/24.",
    "pos_pago": "Valores a receber de transações de pagamento – pós-pago (cartão emitido pela IP): linha criada no leiaute da "
                "Res. 4.966.",
}

MASCARA: list[Item] = [
    # ------------------------------------------------------------ Resultado
    Item("g_resultado", "Resultado (R$ milhões)", "grupo", estilo="grp"),
    Item("transacoes", "Resultado com transações de pagamento", "fluxo", "c141855", None, estilo="forte", nota="transacoes"),
    Item("tp_servicos", "Serviços por transações de pagamento", "fluxo", "c141852", None, estilo="recuo"),
    Item("tp_outros", "Outros resultados com transações de pagamento", "fluxo", "c141854", None, estilo="recuo"),
    Item("tp_perda", "Perda esperada com transações de pagamento", "fluxo", "c141853", None, estilo="recuo"),
    Item("credito", "Rendas de operações de crédito", "fluxo", "c141835 + c141836 + c141837", "c78203 + c78204"),
    Item("floating", "Rendas de aplicações e TVM", "fluxo", "c141825 + c141830", "c78205 + c78231", nota="floating"),
    Item("servicos", "Prestação de serviços e tarifas", "fluxo", "c141856 + c141857", "c78216 + c78217", nota="servicos"),
    Item("outras_rec", "Outras receitas", "fluxo", "c141864", "c78222", nota="outras"),
    Item("derivativos", "Derivativos e demais resultados financeiros", "fluxo", "c141849 + c141850", "c78206 + c78207 + c78212"),
    Item("receita", "Receita líquida", "fluxo",
         "tp_servicos + tp_outros + credito + floating + servicos + outras_rec + derivativos", None, estilo="forte", nota="receita"),
    Item("captacao", "Despesa de captação", "fluxo", "c141847 + c141848", "c78209 + c78210 + c78211", nota="captacao"),
    Item("perda", "Perda esperada de crédito", "fluxo", "c141842 + c141860", "c78213", nota="perda"),
    Item("pessoal", "Despesas de pessoal", "fluxo", "c141858", "c78218"),
    Item("administrativas", "Despesas administrativas", "fluxo", "c141859", "c78219"),
    Item("tributarias", "Despesas tributárias", "fluxo", "c141862", "c78220"),
    Item("outras_desp", "Outras despesas", "fluxo", "c141865", "c78223", nota="outras"),
    Item("participacoes", "Participações em coligadas e não operacional", "fluxo", "c141863", "c78221 + c78227"),
    Item("lair", "Resultado antes de tributação e participações", "fluxo", "c141867", "c78226", estilo="forte"),
    Item("ir", "Imposto de renda e contribuição social", "fluxo", "c141868", "c78228", nota="ir"),
    Item("plr", "Participações nos lucros", "fluxo", "c141869", "c78229"),
    Item("lucro", "Lucro líquido", "fluxo", "c141870", "c78187", estilo="forte"),
    Item("eficiencia", "Eficiência: (pessoal + administrativas) / receita líquida", "razao", formato="pct1", estilo="pct",
         num="-(pessoal + administrativas)", den="receita"),
    Item("captacao_receita", "Despesa de captação / receita líquida", "razao", formato="pct1", estilo="pct",
         num="-captacao", den="receita"),
    Item("aliquota", "Alíquota efetiva de IR", "razao", formato="pct1", estilo="pct", num="-ir", den="lair", nota="ir", den_positivo=True),

    # ------------------------------------------------------------ Rentabilidade
    Item("g_rentabilidade", "Rentabilidade", "grupo", estilo="grp"),
    Item("pl", "Patrimônio líquido (R$ milhões)", "estoque", "c140246", "c78186", estilo="forte"),
    Item("roe", "ROE: lucro líquido / PL médio", "razao", formato="pct1", estilo="pct", num="lucro", den="pl",
         anualizar=True, media=True, nota="anualizado"),
    Item("margem", "Margem líquida: lucro líquido / receita líquida", "razao", formato="pct1", estilo="pct", num="lucro", den="receita"),
    Item("roa", "ROA: lucro líquido / ativo total médio", "razao", formato="pct1", estilo="pct", num="lucro", den="ativo",
         anualizar=True, media=True, nota="anualizado"),

    # ------------------------------------------------------------ Balanço e funding
    Item("g_balanco", "Balanço e funding (R$ milhões)", "grupo", estilo="grp"),
    Item("ativo", "Ativo total", "estoque", "c140220", "c78182", estilo="forte"),
    Item("caixa", "Caixa, aplicações e TVM", "estoque", "c140198 + c140199 + c140200 + c141612", "c78188 + c78189 + c78190", nota="caixa"),
    Item("outros_ativos", "Outros ativos realizáveis", "estoque", "c140218", "c78200", nota="outros_ativos"),
    Item("captacoes", "Captações", "estoque", "c140239", "c78185", estilo="forte"),
    Item("dep_prazo", "Depósitos a prazo", "estoque", "c140225", "c78286", estilo="recuo"),
    Item("dep_interf", "Depósitos interfinanceiros", "estoque", "c140224", "c78284", estilo="recuo"),
    Item("prepaga", "Conta de pagamento pré-paga", "estoque", "c140226", "c110560", estilo="recuo", nota="prepaga"),
    Item("dep_outros", "Demais depósitos", "estoque", "c140222 + c140223 + c140227", "c78282 + c78283 + c78285", estilo="recuo"),
    Item("titulos", "Letras financeiras e demais títulos", "estoque", "c140236", "c78294", estilo="recuo"),
    Item("emprestimos", "Empréstimos e repasses", "estoque", "c140238", "c78295", estilo="recuo"),
    Item("compromissadas", "Operações compromissadas", "estoque", "c140230", "c78288", estilo="recuo"),
    Item("outras_obrig", "Outras obrigações", "estoque", "c140242", "c78297", nota="outras_obrig"),
    Item("divida_bruta", "Dívida bruta", "estoque", "captacoes - prepaga + c140243", "captacoes - prepaga", estilo="forte", nota="divida"),
    Item("divida_liquida", "Dívida líquida (dívida bruta − caixa)", "estoque", "divida_bruta - caixa", "divida_bruta - caixa"),
    Item("custo_funding", "Custo médio de funding: despesa de captação / dívida bruta média", "razao", formato="pct1", estilo="pct",
         num="-captacao", den="divida_bruta", anualizar=True, media=True, nota="anualizado"),
    Item("divida_pl", "Dívida bruta / PL (x)", "razao", formato="x1", estilo="pct", num="divida_bruta", den="pl"),
    Item("alavancagem", "Ativo total / PL (x)", "razao", formato="x1", estilo="pct", num="ativo", den="pl"),

    # ------------------------------------------------------------ Capital
    Item("g_capital", "Capital regulatório (R$ milhões)", "grupo", estilo="grp"),
    Item("pr", "Patrimônio de referência", "estoque", "c79649", "c79649", estilo="forte"),
    Item("capital_principal", "Capital principal", "estoque", "c79645", "c79645", estilo="recuo", nota="capital_cw"),
    Item("capital_compl", "Capital complementar", "estoque", "c79646", "c79646", estilo="recuo"),
    Item("nivel2", "Nível II", "estoque", "c79648", "c79648", estilo="recuo"),
    Item("rwa", "RWA total", "estoque", "c79665", "c79665", estilo="forte"),
    Item("rwa_credito", "RWA de crédito", "estoque", "c138232", "c138232", estilo="recuo"),
    Item("rwa_mercado", "RWA de mercado", "estoque", "c79651", "c79651", estilo="recuo"),
    Item("rwa_operacional", "RWA operacional", "estoque", "c79656", "c79656", estilo="recuo"),
    Item("rwasp", "RWA de serviços de pagamento (RWAsp)", "estoque", "c134461", "c134461", estilo="recuo", nota="rwasp"),
    Item("rwasp_rwa", "RWAsp / RWA", "razao", formato="pct1", estilo="pct", num="rwasp", den="rwa"),
    Item("basileia", "Índice de Basileia", "estoque", "c79664", "c79664", formato="pct1", estilo="pct"),
    Item("indice_cp", "Índice de capital principal", "estoque", "c79659", "c79659", formato="pct1", estilo="pct", nota="capital_cw"),

    # ------------------------------------------------------------ Crédito
    Item("g_credito", "Crédito (R$ milhões)", "grupo", estilo="grp"),
    Item("carteira", "Carteira de crédito", "estoque", "c141873", "c78183", estilo="forte", nota="carteira"),
    Item("carteira_bruta", "Operações de crédito: valor bruto", "estoque", "c140201 + c140207 + c140212", "c78191 + c78194", estilo="recuo"),
    Item("pe_estoque", "Perda esperada (saldo)", "estoque", "c140202 + c140208 + c140213", "c78192 + c78197", estilo="recuo"),
    Item("pos_pago", "Recebíveis de transações – pós-pago", "estoque", "c145833", None, estilo="recuo", nota="pos_pago"),
    Item("cobertura", "Perda esperada / carteira bruta", "razao", formato="pct1", estilo="pct", num="-pe_estoque", den="carteira_bruta"),
    Item("custo_credito", "Custo de crédito: perda esperada / carteira bruta média", "razao", formato="pct1", estilo="pct",
         num="-perda", den="carteira_bruta", anualizar=True, media=True, nota="anualizado"),
]

POR_ID = {i.id: i for i in MASCARA}

# Identidades que precisam fechar (conferir.py): (nome, lado esquerdo, lado direito, leiaute ou None para os dois)
IDENTIDADES = [
    ("DRE: soma das linhas = resultado antes de IR",
     "transacoes + credito + floating + servicos + outras_rec + derivativos + captacao + perda + pessoal + administrativas"
     " + tributarias + outras_desp + participacoes", "lair", "novo"),
    ("DRE: soma das linhas = resultado antes de IR",
     "credito + floating + servicos + outras_rec + derivativos + captacao + perda + pessoal + administrativas"
     " + tributarias + outras_desp + participacoes", "lair", "antigo"),
    ("DRE: resultado antes de IR + IR + participações = lucro", "lair + ir + plr", "lucro", None),
    ("Transações: serviços + outros + perda = total", "tp_servicos + tp_outros + tp_perda", "transacoes", "novo"),
    ("Captações: soma das aberturas = total",
     "dep_prazo + dep_interf + prepaga + dep_outros + titulos + emprestimos + compromissadas", "captacoes", None),
    ("RWA: crédito + mercado + operacional + RWAsp = total", "rwa_credito + rwa_mercado + rwa_operacional + rwasp", "rwa", None),
    ("Capital: principal + complementar + nível II = PR", "capital_principal + capital_compl + nivel2", "pr", None),
]
