"""Configuração estática da tabela de Peers."""

PEERS_TABELA_LAYOUT = [
    {
        "section": "Balanço",
        "rows": [
            {
                "label": "Ativo Total",
                "data_keys": ["Ativo Total"],
                "format_key": "Ativo Total",
            },
            {
                "label": "Ativos Líquidos",
                "data_keys": [],
                "format_key": "Ativos Líquidos",
            },
            {
                "label": "Carteira de Crédito*",
                "data_keys": [],
                "format_key": "Carteira de Crédito Bruta",
            },
            {
                "label": "Perda Esperada",
                "data_keys": [],
                "format_key": "Perda Esperada",
            },
            {
                "label": "Depósitos Totais",
                "data_keys": [],
                "format_key": "Depósitos Totais",
            },
            {
                "label": "Core Funding*",
                "data_keys": [],
                "format_key": "Core Funding",
            },
            {
                "label": "Patrimônio Líquido (PL)",
                "data_keys": ["Patrimônio Líquido"],
                "format_key": "Patrimônio Líquido",
            },
        ],
    },
    {
        "section": "Custo de Crédito",
        "rows": [
            {
                "label": "Custo de Crédito (%)",
                "data_keys": [],
                "format_key": "Custo de Crédito (%)",
            },
            {
                "label": "Custo de Crédito / Receita de Crédito (%)",
                "data_keys": [],
                "format_key": "Custo de Crédito / Receita de Crédito (%)",
            },
        ],
    },
    {
        "section": "Qualidade Carteira 4.966",
        "rows": [
            {
                "label": "Ativos Problemáticos / Carteira Total",
                "data_keys": [],
                "format_key": "Ativos Problemáticos / Carteira Total",
            },
            {
                "label": "Inadimplência / Carteira Total",
                "data_keys": [],
                "format_key": "Inadimplência / Carteira Total",
            },
        ],
    },
    {
        "section": "Qualidade Carteira 4060",
        "rows": [
            {
                "label": "Ativos Estágio 2",
                "data_keys": [],
                "format_key": "Ativos Estágio 2",
            },
            {
                "label": "Ativos Estágio 3",
                "data_keys": [],
                "format_key": "Ativos Estágio 3",
            },
            {
                "label": "Ativos Estágio 3 / Carteira de Crédito",
                "data_keys": [],
                "format_key": "Ativos Estágio 3 / Carteira de Crédito",
            },
            {
                "label": "Inadimplência",
                "data_keys": [],
                "format_key": "Inadimplência",
            },
            {
                "label": "Inadimplência / Carteira de Crédito",
                "data_keys": [],
                "format_key": "Inadimplência / Carteira de Crédito",
            },
            {
                "label": "Perda Esperada / Estágio 3",
                "data_keys": [],
                "format_key": "Perda Esperada / Estágio 3",
            },
            {
                "label": "Perda Esperada / Est2+3",
                "data_keys": [],
                "format_key": "Perda Esperada / Est2+3",
            },
            {
                "label": "Perda Esperada / Carteira de Crédito*",
                "data_keys": [],
                "format_key": "Perda Esperada / Carteira de Crédito Bruta",
            },
        ],
    },
    {
        "section": "Alavancagem",
        "rows": [
            {
                "label": "Ativo Total / PL",
                "data_keys": ["Ativo/PL", "Ativo / PL"],
                "format_key": "Ativo/PL",
            },
            {
                "label": "Carteira de Crédito* / PL",
                "data_keys": ["Carteira de Crédito Bruta / PL", "Crédito/PL (%)", "Crédito/PL"],
                "format_key": "Carteira de Crédito Bruta / PL",
            },
            {
                "label": "Índice de Capital Principal (CET1)",
                "data_keys": [],
                "format_key": "Índice de Capital Principal",
            },
            {
                "label": "Índice de Basileia Total (%)",
                "data_keys": [],
                "format_key": "Índice de Basileia",
            },
        ],
    },
    {
        "section": "Desempenho",
        "rows": [
            {
                "label": "Lucro Líquido Acumulado",
                "data_keys": ["Lucro Líquido Acumulado YTD"],
                "format_key": "Lucro Líquido Acumulado YTD",
            },
            {
                "label": "ROE Acumulado YTD (%)",
                "data_keys": ["ROE Ac. Anualizado (%)", "ROE Ac. YTD an. (%)"],
                "format_key": "ROE Ac. Anualizado (%)",
            },
        ],
    },
]

PEERS_GLOSSARIO_RESUMIDO = {
    "Ativo Total": "Ativo Total do balanço principal (Rel. 1).",
    "Ativos Líquidos": "Disponibilidades (a) + Aplicações Interfinanceiras de Liquidez (b) + TVM (c) no Rel. 2.",
    "Carteira de Crédito*": "Até 2024: Crédito Bruta + Arrendamento Bruta + Outros Créditos Líquidos de Provisão. 2025+: Valor Contábil Bruto (e1+f1+g1+h1) no Rel. 2; se a regra canônica do período ficar incompleta, o fallback líquido e+f+g+h é marcado explicitamente.",
    "Perda Esperada": "Soma de perdas esperadas e ajustes de valor justo das bases e/f/g/h no Rel. 2.",
    "Depósitos Totais": "Prioriza a linha agregada oficial disponível no Rel. 3; só usa soma a1..a6 quando nenhum agregado oficial estiver preenchido na linha.",
    "Core Funding*": "Até 2024: Captações (e). 2025+: Captações (e) + Instrumentos de Dívida Elegíveis a Capital (h) no Rel. 3, sem tratar componente ausente como zero.",
    "Patrimônio Líquido (PL)": "Patrimônio Líquido do balanço principal (Rel. 1).",
    "Custo de Crédito (%)": (
        "|Resultado com Perda Esperada de Operações de Crédito (f3)| do Rel. 4 (DRE), YTD reconstruído e "
        "anualizado (Mar ×4, Jun ×2, Set ×12/9, Dez ×1), ÷ Carteira de Crédito*. Numerador restrito a "
        "operações de crédito — não inclui TVM nem aplicações interfinanceiras. Série a partir de Mar/25."
    ),
    "Custo de Crédito / Receita de Crédito (%)": (
        "|Resultado com Perda Esperada de Operações de Crédito (f3)| YTD ÷ Rendas de Operações de Crédito (c) YTD, "
        "ambos do Rel. 4 (DRE). Sem anualização: os dois são fluxos do mesmo período e o fator se cancela. "
        "Mede quanto da receita de crédito é consumido por provisão. Receita zero, negativa ou ausente resulta em N/D."
    ),
    "Ativos Problemáticos / Carteira Total": (
        "Ativos problemáticos ÷ Total Geral, ambos publicados no IFData Rel. 16 (carteira de crédito ativa por "
        "carteiras de instrumentos financeiros, Res. 4.966). Escopo estritamente de crédito, sem reconciliação de "
        "perímetro. 'Ativo problemático' segue o art. 24 da Res. CMN 4.557. Não confundir com Estágio 3 do Cadoc 4060."
    ),
    "Inadimplência / Carteira Total": (
        "Inadimplência ÷ Total Geral, ambos do IFData Rel. 16 — mesmo perímetro do indicador de ativos problemáticos, "
        "porém restrito ao atraso relevante, sem os casos de liquidação improvável."
    ),
    "Ativos Estágio 2": "Saldo da conta 3312000001 (Cadoc 4060) no período, quando a fonte mensal publicar o estágio e houver match prudencial confiável.",
    "Ativos Estágio 3": "Saldo da conta 3313000000 (Cadoc 4060) no período, quando a fonte mensal publicar o estágio e houver match prudencial confiável.",
    "Ativos Estágio 3 / Carteira de Crédito": "Ativos Estágio 3 (Cadoc 4060) ÷ Carteira de Crédito*.",
    "Inadimplência": "Inadimplência publicada no IFData Rel. 16 (Carteira de crédito ativa por carteiras de instrumentos financeiros).",
    "Inadimplência / Carteira de Crédito": "Inadimplência do Rel. 16 ÷ Carteira de Crédito*.",
    "Perda Esperada / Estágio 3": "Magnitude da Perda Esperada (Rel. 2) ÷ Ativos Estágio 3 (Cadoc 4060), somente quando numerador e denominador estiverem disponíveis.",
    "Perda Esperada / Est2+3": "Magnitude da Perda Esperada (Rel. 2) ÷ (Ativos Estágio 2 + Ativos Estágio 3) do Cadoc 4060, somente com cobertura prudencial válida.",
    "Perda Esperada / Carteira de Crédito*": "Magnitude da Perda Esperada ÷ Carteira de Crédito*.",
    "Ativo Total / PL": "Ativo Total ÷ Patrimônio Líquido.",
    "Carteira de Crédito* / PL": "Carteira de Crédito* ÷ Patrimônio Líquido.",
    "Índice de Capital Principal (CET1)": "Capital Principal ÷ RWA Total (Rel. 5).",
    "Índice de Basileia Total (%)": "(CET1 + AT1 + T2) ÷ RWA Total (Rel. 5).",
    "Lucro Líquido Acumulado": "Lucro Líquido acumulado no ano (YTD) até o fim do período (Rel. 1).",
    "ROE Acumulado YTD (%)": "(LL YTD × fator de anualização) ÷ PL Médio.",
}

PEERS_PERCENT_DECIMALS = {
    "Perda Esperada / Est2+3": 1,
}

PEERS_RATIO_COMPONENTS = {
    "Ativos Problemáticos / Carteira Total": ("Ativos Problemáticos 4.966", "Carteira Total 4.966"),
    "Inadimplência / Carteira Total": ("Inadimplência 4.966", "Carteira Total 4.966"),
    "Custo de Crédito (%)": (
        "Trace::Custo de Crédito::PDD Crédito Anualizada",
        "Carteira de Crédito Bruta",
    ),
    "Custo de Crédito / Receita de Crédito (%)": (
        "Trace::Custo de Crédito::PDD Crédito YTD",
        "Trace::Custo de Crédito::Receita de Crédito YTD",
    ),
    "Ativos Estágio 3 / Carteira de Crédito": ("Ativos Estágio 3", "Carteira de Crédito Bruta"),
    "Inadimplência / Carteira de Crédito": ("Inadimplência", "Carteira de Crédito Bruta"),
    "Perda Esperada / Carteira de Crédito Bruta": ("Perda Esperada", "Carteira de Crédito Bruta"),
    "Perda Esperada / Carteira de Crédito*": ("Perda Esperada", "Carteira de Crédito Bruta"),
    "Carteira de Créd. Class. C4+C5 / Carteira Classificada": ("Carteira de Créd. Class. C4+C5", "Carteira de Crédito Classificada"),
    "Perda Esperada / (Carteira C4 + C5)": ("Perda Esperada", "Carteira de Créd. Class. C4+C5"),
    "PDD / Estágio 3": ("PDD Total 4060", "Ativos Estágio 3"),
    "Perda Esperada / Estágio 3": ("Perda Esperada", "Ativos Estágio 3"),
}

# Colunas `Trace::` do cache curado que a tabela precisa carregar como pseudo-métricas
# para montar tooltip e memória de cálculo das razões acima. Derivado de
# PEERS_RATIO_COMPONENTS para não sair de sincronia quando uma razão nova for incluída.
PEERS_TRACE_COMPONENTS = tuple(
    sorted(
        {
            componente
            for componentes in PEERS_RATIO_COMPONENTS.values()
            for componente in componentes
            if str(componente).startswith("Trace::")
        }
    )
)

PEERS_ALLOWANCE_RATIO_METRICS = {
    # A PDD do Rel. 4 é publicada com sinal negativo (despesa); as razões de custo de
    # crédito exibem a magnitude, como já faz o indicador equivalente nos Rankings.
    "Custo de Crédito (%)",
    "Custo de Crédito / Receita de Crédito (%)",
    "PDD / Estágio 3",
    "Perda Esperada / Carteira",
    "Perda Esperada / Carteira de Crédito Bruta",
    "Perda Esperada / Carteira de Crédito*",
    "Perda Esperada / (Carteira C4 + C5)",
    "Perda Esperada / Estágio 3",
    "Perda Esperada / Est2+3",
}

PEERS_BASE_CONSOLIDADA_LABEL = "Consolidada / Prudencial"
PEERS_BASE_INDIVIDUAL_LABEL = "Individual"
PEERS_BASE_DRE_OPTIONS = [PEERS_BASE_CONSOLIDADA_LABEL, PEERS_BASE_INDIVIDUAL_LABEL]
