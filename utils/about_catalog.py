"""Catálogo da página Sobre, alinhado aos módulos publicados."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Module:
    label: str
    category: str
    description: str


MODULES = (
    Module("Snapshot", "Instituição", "Visão consolidada dos principais indicadores, variações e qualidade dos dados."),
    Module("Rankings", "Comparação", "Ordenação por indicador e período, com filtros e exportação das instituições selecionadas."),
    Module("Peers (Tabela Nova)", "Comparação", "Bancos e períodos lado a lado, variação trimestral ou anual, grupos salvos e cálculo sob clique."),
    Module("Conselho e Diretoria", "Governança", "Composição dos órgãos por conglomerado e instituição participante."),
    Module("Evolução", "Histórico", "Séries e indicadores por instituição, com gráfico e tabela editáveis no mesmo slide."),
    Module("Scatter Plot", "Relações", "Comparação entre dois indicadores, com tamanho de bolha e filtros por instituição."),
    Module("DRE (Ind. e Congl.)", "Resultado", "DRE gerencial, prudencial e individual, respeitando a fonte e o calendário de cada base."),
    Module("Balanço, DRE e DMPL (Ind.)", "Demonstrações", "Demonstrações individuais publicadas no CDSFN: balanço, resultado e mutações do PL."),
    Module("Contas COSIF", "Contabilidade", "Consulta de contas dos documentos 4010, 4060 e 4066, incluindo contribuições FGC/FGCoop."),
    Module("Carteira 4.966", "Risco", "Carteira, ativos problemáticos, inadimplência, provisões e coberturas por instituição."),
    Module("Estatísticas Crédito BC", "Crédito agregado", "SGS e SCR.data: concessões, saldos, inadimplência, renda, regiões, endividamento e spreads."),
    Module("Taxas de Juros por Produto", "Juros", "Taxas PF/PJ por modalidade, instituição e janela de consulta, com exportação de gráficos."),
    Module("Meios de Pagamento (SPB)", "Pagamentos", "Volume, valor e evolução dos instrumentos de pagamento do Banco Central."),
    Module("Glossário", "Referência", "Definições, fórmulas, fontes, unidades, perímetros e limites dos indicadores."),
)

METRIC_GROUPS = (
    ("Estrutura e resultado", (
        "Ativo total, ativos líquidos e títulos e valores mobiliários",
        "Carteira de crédito, depósitos e Core Funding",
        "Patrimônio líquido e lucro acumulado (YTD)",
        "ROE Anualizado (%)",
        "Ativo / PL e carteira / PL (múltiplos)",
    )),
    ("Capital e prudencial", (
        "Capital Principal — CET1 (%)",
        "Capital Nível 1 (%) e Índice de Basileia Total (%)",
        "Capital complementar e capital nível II",
        "RWA de crédito, mercado e operacional",
        "Exposição total e razão de alavancagem",
    )),
    ("Qualidade e custo do crédito", (
        "Custo de crédito e custo / receita de crédito (%)",
        "Inadimplência (NPL) e ativos problemáticos",
        "Estágios 2 e 3 e suas participações na carteira",
        "Perda esperada, PDD e índices de cobertura",
        "Carteira 4.966 e distribuição por classes de risco",
    )),
    ("Crédito agregado, juros e pagamentos", (
        "Concessões e saldo do crédito PF/PJ por modalidade",
        "Inadimplência por renda, região e modalidade",
        "Endividamento e comprometimento de renda das famílias",
        "Taxas de juros, spreads e provisões",
        "Quantidade e valor das transações por instrumento",
    )),
)

OPERATIONS = (
    ("Recortes reproduzíveis", "Instituições, perímetros, competências, indicadores e janelas de consulta definidos na própria análise."),
    ("Grupos e identidade", "Grupos de peers publicados no GitHub com IDs estáveis; nomes conciliados com o cadastro oficial."),
    ("Office editável", "Tabelas nativas de Excel e PowerPoint; gráficos editáveis nas exportações de Evolução, Peers, Crédito BC, Taxas e SPB."),
    ("Downloads por módulo", "CSV e PNG nas consultas que oferecem esses formatos, além dos arquivos Office disponíveis em cada aba."),
    ("Fonte e memória de cálculo", "Fórmulas, períodos de referência e quebras de série identificados; ausência de dado preservada como N/D."),
    ("Atualização e continuidade", "Caches e bases publicadas com manifestos; Atualizar Base oferece execução por etapas, acompanhamento e retomada."),
)

STEPS = (
    ("Escolha o módulo", "Use comparação entre instituições, evolução histórica, demonstrações, crédito agregado ou pagamentos conforme a pergunta."),
    ("Defina o recorte", "Selecione a base individual ou consolidada/prudencial quando disponível, as instituições e os períodos."),
    ("Confira os indicadores", "Consulte o cálculo sob clique, a fonte e o glossário; observe N/D e as notas de quebra de série."),
    ("Compartilhe a consulta", "Gere a exportação da própria aba para conservar o recorte escolhido. Em Peers, salve também o grupo para reutilizá-lo."),
)

STACK = (
    ("Python e Streamlit", "Processamento e interface web"),
    ("Pandas, NumPy e PyArrow", "Cálculos, recortes e armazenamento Parquet"),
    ("Plotly e Matplotlib", "Gráficos interativos e exportações visuais"),
    ("openpyxl e XlsxWriter", "Planilhas e tabelas Excel"),
    ("python-pptx e OOXML", "Slides, tabelas e gráficos editáveis"),
    ("Requests", "Consultas às APIs oficiais e ao GitHub"),
    ("IFData, COSIF e CDSFN", "Dados de instituições e demonstrações do BCB"),
    ("SGS, SCR.data e SPB", "Crédito agregado, juros e meios de pagamento do BCB"),
)
