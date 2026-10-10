"""Ajuda de leitura compartilhada pelas abas e pelo glossário.

Qualificações locais descrevem o cálculo efetivamente exibido em cada visão.
Este módulo não calcula indicadores nem infere fontes para campos desconhecidos.
"""
from __future__ import annotations

from utils.glossary_catalog import MODULE_GUIDES, SOURCE_BY_KEY, all_terms, normalize_search
from utils.ifdata_cache.metric_registry import get_metric_definition_by_label


PERIOD_HELP = ("Data-base dos valores, que pode ser anterior à atualização do app. "
               "Saldos representam a posição nessa data; resultados dependem da janela indicada.")
PERIMETER_HELP = ("Individual: pessoa jurídica identificada pelo CNPJ. Prudencial: grupo consolidado "
                  "para acompanhar risco e capital, com eliminação das operações internas. "
                  "Mantenha o mesmo recorte ao comparar instituições e períodos.")
COMPARISON_HELP = ("YoY compara com o mesmo trimestre do ano anterior; QoQ, com o trimestre anterior. "
                   "A diferença entre taxas é expressa em pontos percentuais ou bps (100 bps = 1 p.p.), conforme a tela. Resultados acumulados precisam de janelas "
                   "de duração igual; mudanças contábeis em 2025 podem afetar a comparação.")
PEERS_COMPARISON_HELP = ("YoY compara com o mesmo trimestre do ano anterior; QoQ, com o trimestre anterior. "
                         "Taxas de capital, retorno e risco usam bps inteiros; coberturas e custo/receita usam pontos percentuais (p.p.). "
                         "As duas unidades expressam subtração: 100 bps = 1 p.p. Exemplo: 2,18% para 2,25% = +7 bps; cobertura de 193,1% para 193,5% = +0,4 p.p. "
                         "Valores monetários variam em % com base positiva; múltiplos, em x. "
                         "Cada coluna identifica a referência usada. O delta usa valores sem arredondamento. Lucro YTD requer janelas de igual duração.")
COSIF_BASE_HELP = ("4010: balancete individual mensal. 4060: balancete prudencial mensal. "
                   "4066: balanço prudencial semestral, em junho e dezembro. "
                   "Os documentos 4060 e 4066 representam o mesmo grupo e não devem ser somados.")
COSIF_CALCULATION_HELP = ("Saldo usa o valor publicado na data-base. Nas contas de resultado, "
                          "o semestre reinicia em julho; o acumulado no ano recompõe os dois semestres. "
                          "Trimestre isola três meses, quando os componentes estão disponíveis.")
RATE_HELP = ("Mensal (%) e anual (%) indicam a unidade da taxa. A frequência dos pontos é escolhida "
             "separadamente. As taxas são médias das operações na janela oficial; as condições "
             "de uma proposta dependem do cliente, das garantias e dos encargos.")
PAYMENT_FREQUENCY_HELP = ("A base mensal inclui Pix, TED, boletos, DOC, TEC e cheques. "
                          "Cartões e outras aberturas entram na base trimestral. "
                          "As participações usam os instrumentos do recorte selecionado.")

MODULE_CAPTIONS = {
    "Snapshot": "Indicadores na data-base · IFData trimestral · Visão prudencial e instituições independentes.",
    "Rankings": "Posições entre as instituições com dados no recorte · IFData trimestral · Visão prudencial e instituições independentes.",
    "Tabela de Peers": "Comparação por instituição e data-base · IFData trimestral · Fonte e denominador identificados por indicador.",
    "Conselho e Diretoria": "Cadastro e administradores disponíveis no BCB · Consulta atual, sem série histórica completa de mandatos.",
    "Evolução": "Histórico de balanço, resultado e capital · IFData trimestral · Mudanças no grupo e na contabilidade podem alterar a série.",
    "Scatter Plot": "Comparação entre indicadores na mesma data-base · IFData trimestral · Confira a cobertura das variáveis selecionadas.",
    "DRE (Ind. e Congl.)": "Resultado por instituição e perímetro · IFData trimestral · A DRE publicada acumula valores por semestre.",
    "Balanço, DRE e DMPL (Ind.)": "Demonstrações individuais do documento 9011 · Consulta ao BCB · Referências semestrais ou anuais conforme o documento.",
    "Contas COSIF": "Contas por instituição e data-base · 4010 individual mensal; 4060 prudencial mensal; 4066 prudencial semestral.",
    "Carteira 4.966": "Carteiras de instrumentos e qualidade do crédito · IFData trimestral, Relatório 16 · Visão prudencial desde mar/2025.",
    "Estatísticas Crédito BC": "Mercado de crédito e recortes por região e perfil · SGS e SCR.data mensais, com conceitos e calendários próprios.",
    "Taxas de Juros por Produto": "Taxas médias por instituição, produto e janela de contratação · BCB · A visão mensal usa a última observação do mês.",
    "Meios de Pagamento (SPB)": "Transações, cartões, canais e tarifas · BCB · Dados mensais ou trimestrais conforme o instrumento.",
    "Atualizar Base": "Competências disponíveis, extração e publicação das bases · Cada fonte tem calendário e escopo próprios.",
}

_TERM_ALIASES = {
    "Ativo Total": "asset", "Patrimônio Líquido": "equity", "Patrimônio Líquido (PL)": "equity",
    "Carteira de Crédito": "credit_balance", "Carteira de Crédito Bruta": "credit_balance",
    "Core Funding": "funding", "Core Funding*": "funding", "Captações": "funding",
    "Ativos Líquidos": "liquid_assets", "Depósitos Totais": "deposits",
    "Lucro Líquido Acumulado": "net_income", "Lucro Líquido Acumulado YTD": "net_income",
    "Lucro Líquido Acum. YTD": "net_income", "Lucro Líquido Trimestral": "net_income",
    "Resultado intermediação": "intermediation",
    "ROE Ac. Anualizado": "roe_ytd", "ROE trimestral anualizado (%)": "roe_quarter",
    "Índice de Capital Principal": "cet1", "Índice de Capital Principal (CET1)": "cet1",
    "Índice de Capital T1 (%)": "tier1", "Ativo/PL": "leverage", "Ativo Total / PL": "leverage",
    "Carteira de Crédito* / PL": "credit_equity", "Carteira de Crédito Bruta / PL": "credit_equity",
    "Carteira de Crédito/Core Funding (%)": "credit_funding", "Crédito / Captações": "credit_funding",
    "Ativos Estágio 2": "stage2", "Ativos Estágio 3": "stage3",
    "Perda Esperada": "provision", "Perda Esperada / Estágio 3": "coverage",
    "Perda Esperada / Est2+3": "coverage", "Perda Esperada / Carteira": "provision_ratio",
    "Perda Esperada / Carteira de Crédito*": "provision_ratio",
    "Inadimplência / Carteira de Crédito": "default_ratio",
    "Ativos Estágio 3 / Carteira de Crédito": "stage3",
    "Desp. Anualizada Captação / Volume Captação": "funding_cost",
    "Desp. Anualizada Captações / Volume Captações": "funding_cost",
}
_ALIASES = {normalize_search(label): key for label, key in _TERM_ALIASES.items()}

# Fontes específicas das comparações; o catálogo também descreve outras telas.
_REPORTS = {
    "asset": "IFData Rel. 1", "equity": "IFData Rel. 1", "net_income": "IFData Rel. 1",
    "liquid_assets": "IFData Rel. 2", "deposits": "IFData Rel. 3", "funding": "IFData Rel. 3",
    "credit_equity": "IFData Rel. 2 e Rel. 1", "credit_funding": "IFData Rel. 2 e Rel. 3",
    "cet1": "IFData Rel. 5", "tier1": "IFData Rel. 5", "leverage": "IFData Rel. 1",
    "funding_cost": "IFData Rel. 4 e base de captação indicada na memória de cálculo",
    "intermediation": "IFData Rel. 4",
    "default_balance": "IFData Rel. 16",
    "provision": "IFData Rel. 2", "provision_ratio": "IFData Rel. 2",
    "coverage": "IFData Rel. 2 e documento COSIF 4060",
    "coverage_arrasto": "IFData Rel. 2 e Rel. 16",
    "stage2": "Documento COSIF 4060", "stage3": "Documento COSIF 4060",
}


def get_help_text(label: str, *, base: str = "Prudencial", include_source: bool = True,
                  long: bool = False, context: str = "") -> str:
    """Definição e ressalva do glossário, qualificadas pelo indicador e perímetro."""
    terms = all_terms()
    metric = get_metric_definition_by_label(label)
    key = _ALIASES.get(normalize_search(label))
    term = next((t for t in terms if t.key == key), None)
    if term is None and metric:
        term = next((t for t in terms if t.metric_key == metric.key), None)
    if term is None:
        term = next((t for t in terms if normalize_search(label) in
                     {normalize_search(t.title), *(normalize_search(a) for a in t.aliases)}), None)
    if term is None:
        return ""
    definition, caution = term.definition, term.caution
    source = metric.source_label if metric and metric.source_label else _REPORTS.get(term.key, "")
    frequency = "IFData trimestral; 4060 mensal, na data-base selecionada" if term.key in {"stage2", "stage3", "coverage"} else "Trimestral"
    scope = "visão prudencial e instituições independentes"
    if term.key == "net_income" and context != "DRE":
        definition = ("Resultado líquido de janeiro até a data-base (YTD). O app recompõe o segundo semestre "
                      "a partir da base de junho.") if "Trimestral" not in label else "Resultado líquido dos três meses do trimestre, isolado a partir dos valores acumulados."
    if term.key in {"roe_ytd", "roe_quarter"}:
        caution += " A anualização padroniza a taxa e não projeta o lucro futuro."
    if context == "Peers" and term.key in {"credit_loss_cost", "credit_loss_revenue"}:
        denominator = "carteira contábil ampliada" if term.key == "credit_loss_cost" else "receita de crédito acumulada no ano"
        definition = f"Resultado com perdas de crédito da DRE, com sinal invertido, dividido pela {denominator}."
        if term.key == "credit_loss_cost":
            definition += " O resultado é anualizado antes da divisão."
        caution = "Nesta tabela, despesa líquida gera sinal positivo e reversão líquida gera sinal negativo. O denominador precisa estar disponível e ser positivo."
    if label in {"Ativo Total / PL", "Ativo/PL"}:
        definition = "Ativo total dividido pelo patrimônio líquido: quantos reais de balanço são sustentados por cada real de PL."
        caution = "Expresso em vezes. Composição e risco dos ativos afetam a leitura da alavancagem."
    if label.startswith("Perda Esperada"):
        definition = "Agregado de perdas esperadas e ajustes contábeis do Relatório 2, incluindo parcelas de hedge e valor justo."
        caution = "A composição difere da PDD da Carteira 4.966, que usa somente as parcelas de perda esperada."
        if "/" in label:
            denominator = label.split("/", 1)[1].strip()
            definition += f" Nesta razão, seu valor sem o sinal é dividido por {denominator}."
            caution += " O agregado pode abranger ativos fora do denominador; uma queda exige examinar os componentes."
    if context == "Peers" and label in {"Inadimplência", "Inadimplência / Carteira Total"}:
        caution += " Disponível a partir de mar/2025, conforme a publicação do Relatório 16."
    if label == "Inadimplência / Carteira de Crédito":
        definition = "Saldo integral das operações com parcela vencida há mais de 90 dias (Rel. 16) dividido pela carteira contábil do Rel. 2."
        caution = "O denominador difere do Total Geral do Relatório 16 e pode incluir parcelas líquidas de provisão."
        source = "IFData Rel. 16 e Rel. 2"
    if label == "Ativos Estágio 3 / Carteira de Crédito":
        definition = "Saldo contábil em estágio 3 (4060) dividido pela Carteira de Crédito* do Relatório 2."
        caution = "Fontes e composições distintas. Confira os componentes, o vínculo com o conglomerado e a regra da carteira em 2025."
        source = "Documento COSIF 4060 e IFData Rel. 2"
    if base == "Individual":
        scope = "instituição individual"
        if term.key in {"asset", "equity", "net_income", "credit_balance", "funding", "credit_equity", "leverage", "roe_ytd"}:
            source = "IFData Rel. 1"
        if term.key == "roe_ytd":
            definition = "Retorno calculado pelo lucro acumulado no ano, anualizado, dividido pelo PL atual da instituição."
            caution = "Nesta visão, o denominador é o PL da data-base. Na visão prudencial, o app usa a média entre o PL atual e dezembro anterior. Anualização não projeta o lucro futuro."
        elif term.key == "credit_balance":
            definition = "Carteira de crédito publicada no resumo individual do IFData; a carteira classificada é usada quando a principal está ausente."
            caution = "A composição difere da Carteira de Crédito* do Relatório 2 prudencial. Confira a fonte indicada para a célula."
        elif term.key == "funding":
            definition = "Captações publicadas para a pessoa jurídica no resumo individual do IFData."
            caution = "Nesta visão, o app usa as captações do Relatório 1. O Core Funding prudencial tem outra composição, alterada em 2025."
    parts = [definition, caution]
    if include_source:
        source = source or "IFData, conforme o relatório do indicador"
        if not source.startswith("BCB "):
            source = f"BCB {source}"
        parts.append(f"Fonte: {source} · {frequency} · {scope}.")
    return " ".join(part for part in parts if part)


def render_module_help(module: str, *, base: str | None = None, caption: bool = True) -> None:
    """Contexto breve na tela e fontes do mesmo catálogo em ajuda opcional."""
    import streamlit as st

    guide = next(g for g in MODULE_GUIDES if g.name == module)
    if caption:
        st.caption(MODULE_CAPTIONS[module] + (f" Recorte selecionado: {base}." if base else ""))
    with st.popover("Fontes e leitura", help="Periodicidade, escopo e cuidados relevantes para esta aba"):
        st.write(guide.caution)
        for key in guide.sources:
            source = SOURCE_BY_KEY[key]
            st.markdown(f"**{source.name}**")
            st.write(f"{source.frequency}. {source.scope}")
            st.caption(source.caution)
            st.markdown(" · ".join(f"[{title}]({url})" for title, url in source.links))
        st.caption("Confira a competência carregada na tela. A data-base, a consulta ao BCB e a publicação do app podem ocorrer em datas diferentes.")
