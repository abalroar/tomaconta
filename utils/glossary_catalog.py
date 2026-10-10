"""Guia de leitura do app. Fórmulas auditadas permanecem no metric_registry.

Conteúdo editorial sem dependência de Streamlit, pandas ou acesso à rede.
As periodicidades descrevem a fonte, não a atualização da instalação do app.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import re
import unicodedata

from utils.ifdata_cache.metric_registry import get_metric_definition


@dataclass(frozen=True)
class SourceGuide:
    key: str
    name: str
    description: str
    frequency: str
    scope: str
    publication: str
    in_app: str
    caution: str
    links: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class GlossaryTerm:
    key: str
    title: str
    topic: str
    definition: str
    caution: str
    sources: tuple[str, ...] = ()
    modules: tuple[str, ...] = ()
    formula: str = ""
    unit: str = ""
    example: str = ""
    aliases: tuple[str, ...] = ()
    metric_key: str = ""


@dataclass(frozen=True)
class ReadingGuide:
    key: str
    title: str
    explanation: str
    example: str
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModuleGuide:
    name: str
    purpose: str
    sources: tuple[str, ...]
    caution: str


IFDATA_URL = "https://www3.bcb.gov.br/ifdata/index.html"
COSIF_URL = "https://www.bcb.gov.br/estabilidadefinanceira/balancetesbalancospatrimoniais"
SCR_URL = "https://www.bcb.gov.br/pda/desig/metodologia_versao2.pdf"
CREDIT_RULES_URL = "https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo?numero=4966&tipo=RESOLU%C3%87%C3%83O+CMN"
REPORTS = ("Snapshot", "Rankings", "Peers (Tabela Nova)", "Evolução", "Scatter Plot")
DRE = "DRE (Ind. e Congl.)"
STATISTICS = "Estatísticas Crédito BC"
COSIF = "Contas COSIF"
PAYMENTS = "Meios de Pagamento (SPB)"
RATES = "Taxas de Juros por Produto"
PORTFOLIO = "Carteira 4.966"
STATEMENTS = "Balanço, DRE e DMPL (Ind.)"


SOURCES = (
    SourceGuide(
        "ifdata", "IFData: balanço, resultado e capital",
        "Organiza informações das instituições supervisionadas pelo Banco Central. "
        "Balanço e DRE vêm da contabilidade COSIF; as informações de capital vêm do demonstrativo regulatório de limites.",
        "Trimestral", "Individual; prudencial; financeiro, conforme o relatório e a data-base.",
        "O BCB informa até 60 dias após março, junho e setembro; até 90 dias após dezembro. "
        "Substituições posteriores entram no reprocessamento anual informado pelo BCB.",
        "Snapshot e comparações usam bases preparadas pelo app. A DRE gerencial consulta o BCB "
        "para o período e perímetro escolhidos; se a consulta falhar, identifica a recuperação de uma base validada da mesma seleção.",
        "A periodicidade trimestral descreve a data-base. A data de consulta e a versão publicada do app "
        "podem ser diferentes. Relatórios e colunas mudaram com o COSIF de 2025.",
        (("Metodologia e relatórios IFData", IFDATA_URL),),
    ),
    SourceGuide(
        "ifdata_credit", "IFData: carteiras de crédito",
        "Apresenta agregados originados no Sistema de Informações de Créditos (SCR), "
        "com aberturas por produto, tomador e carteira de instrumentos financeiros.",
        "Trimestral", "Financeiro até dez/2024; prudencial a partir de mar/2025, nas carteiras divulgadas pelo IFData.",
        "Segue o calendário trimestral do IFData. O Relatório 16, por carteiras de instrumentos, está disponível a partir de mar/2025.",
        "O Relatório 16 alimenta Carteira 4.966 e os indicadores de inadimplência e ativos problemáticos. "
        "O Total Geral desse relatório pode diferir da carteira contábil do balanço.",
        "A passagem de 2024 para 2025 altera classificação e perímetro. "
        "O antigo relatório por níveis de risco A a H exige leitura histórica separada.",
        (("Relatórios de crédito e formas de consolidação", IFDATA_URL),
         ("Critérios de perdas de crédito: Resolução CMN 4.966", CREDIT_RULES_URL)),
    ),
    SourceGuide(
        "cosif_4010", "COSIF 4010: balancete individual",
        "Mostra saldos por conta contábil e instituição. É a base individual consultada na aba Contas COSIF.",
        "Mensal", "Instituição individual identificada pelo CNPJ-base.",
        "O documento 4010 é mensal. A cobertura efetiva no app depende dos arquivos públicos ingeridos.",
        "Permite consultar contas, comparar instituições e acompanhar valores individuais, incluindo AR e VR do FGC quando publicados.",
        "O nome do grupo no arquivo serve como identificação. O saldo continua individual. "
        "Somar contas sintéticas e suas subcontas duplica valores.",
        (("Balancetes publicados pelo BCB", COSIF_URL),
         ("Leiaute dos documentos 4010 e 4016", "https://www.bcb.gov.br/content/estabilidadefinanceira/cosif_leiautes/Leiaute_4010_xmlV0.pdf")),
    ),
    SourceGuide(
        "cosif_prudential", "COSIF 4060 e 4066: consolidado prudencial",
        "São os documentos contábeis do conglomerado prudencial: balancete analítico (4060) e balanço analítico (4066).",
        "4060 mensal; 4066 semestral", "Conglomerado prudencial, com eliminações das operações internas ao grupo.",
        "4060 refere-se aos meses; 4066, a junho e dezembro. Remessa ao regulador e divulgação pública têm calendários próprios.",
        "A aba Contas COSIF oferece a visão prudencial do BLOPRUDENCIAL. "
        "Os indicadores de estágios usam o 4060 quando há conta publicada e vínculo confiável com a instituição.",
        "4060 e 4066 representam documentos diferentes na mesma data-base. Somá-los duplica a exposição. "
        "Uma conta mensal disponível em Contas COSIF pode estar ausente na competência usada por um indicador trimestral.",
        (("Balancetes e balanços publicados", COSIF_URL),
         ("Periodicidade dos documentos prudenciais", "https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo?numero=210&tipo=Instru%C3%A7%C3%A3o+Normativa+BCB")),
    ),
    SourceGuide(
        "statements", "Documento 9011: demonstrações individuais",
        "Contém demonstrações financeiras enviadas pela instituição, como balanço, DRE, fluxo de caixa e mutações do patrimônio.",
        "Semestral e anual, conforme a demonstração", "Instituição individual; o app consulta o documento 9011.",
        "A disponibilidade depende da remessa e da publicação da instituição para a competência escolhida.",
        "A consulta é feita ao vivo no BCB. A tela exibe os blocos, unidades e referências de período presentes no documento.",
        "Dois documentos podem apresentar aberturas e colunas diferentes. "
        "A ausência de um bloco ou período fica como lacuna. Documentos consolidados em IFRS ou prudenciais têm outros códigos.",
        (("Central de demonstrações financeiras do BCB", "https://www3.bcb.gov.br/informes/"),
         ("Códigos das demonstrações financeiras", "https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo?numero=236&tipo=Instru%C3%A7%C3%A3o+Normativa+BCB")),
    ),
    SourceGuide(
        "scr", "SCR.data: crédito por região e perfil",
        "Divulga saldos e qualidade do crédito por UF, tipo de instituição, produto e perfil do tomador, a partir das operações informadas no SCR.",
        "Mensal", "Agregados de operações no país; sem saldos de dependências e controladas no exterior.",
        "O BCB informa divulgação no último dia útil do mês, com cerca de 30 dias após a data-base. "
        "Os dados mensais são distribuídos em arquivos anuais.",
        "A área de inadimplência nas Estatísticas Crédito BC usa essa base. "
        "A série completa por região tem menos aberturas que a consulta detalhada por UF e segmento.",
        "Permite estudar segmentos e recortes regionais. Não identifica a carteira de um banco específico. "
        "As taxas são calculadas pela soma dos saldos e preservam a mudança de conceito de ativos problemáticos em jan/2025.",
        (("Metodologia SCR.data, versão 2", SCR_URL),
         ("Dados abertos SCR.data", "https://dadosabertos.bcb.gov.br/dataset/scr_data")),
    ),
    SourceGuide(
        "sgs", "SGS: estatísticas do mercado de crédito",
        "Reúne séries do Banco Central sobre saldo, concessões, juros, spread, inadimplência, provisionamento e outros indicadores do mercado.",
        "Mensal nas séries de crédito do app", "Mercado ou segmento indicado no título de cada série; também há séries de contexto macroeconômico.",
        "Cada série tem calendário e período inicial próprios. "
        "A data-base mais recente pode variar entre indicadores da mesma tela.",
        "Alimenta as Estatísticas Crédito BC e referências de contexto, como PIB, inflação e salário mínimo quando usados nas análises.",
        "Confirme a unidade e o conceito da série. Saldo, concessão, juros das novas operações e custo do estoque medem coisas diferentes.",
        (("Sistema Gerenciador de Séries Temporais", "https://www3.bcb.gov.br/sgspub/"),
         ("Estatísticas monetárias e de crédito", "https://www.bcb.gov.br/estatisticas/estatisticasmonetariascredito")),
    ),
    SourceGuide(
        "rates", "Taxas de juros por instituição e produto",
        "Mostra taxas médias de operações contratadas por instituição e modalidade. "
        "As janelas diárias divulgadas pelo BCB reúnem cinco dias úteis e ponderam as taxas pelos valores contratados.",
        "Janelas oficiais diárias ou mensais, conforme a modalidade", "Instituição e produto; operações observadas na janela publicada.",
        "Há defasagem entre contratação e publicação. A janela oficial aparece com início e fim próprios.",
        "A aba Taxas de Juros por Produto oferece série por janela e visão mensal. "
        "Na visão mensal, o app seleciona a última observação disponível de cada mês.",
        "Essa seleção mensal não calcula a média de todas as operações do mês. "
        "A taxa publicada é uma referência observada; o custo de uma proposta individual depende das condições do cliente.",
        (("Taxas de juros divulgadas pelo BCB", "https://www.bcb.gov.br/estatisticas/txjuros"),
         ("Metodologia das taxas por instituição", "https://dadosabertos.bcb.gov.br/dataset/taxas-de-juros-de-operacoes-de-credito")),
    ),
    SourceGuide(
        "payments", "SPB: estatísticas de meios de pagamento",
        "Reúne informações sobre transações, cartões, canais de acesso, infraestrutura de aceitação e tarifas.",
        "Mensal e trimestral, conforme o instrumento", "Mercado brasileiro de pagamentos; cobertura específica de cada conjunto de dados.",
        "O catálogo do BCB informa 17 dias após o mês para os instrumentos mensais "
        "e dois meses após o trimestre para os trimestrais.",
        "A aba Meios de Pagamento separa as visões mensal e trimestral. "
        "Pix, TED, boletos, DOC, TEC e cheques têm base mensal; cartões e outras aberturas usam a base trimestral.",
        "Quantidade e valor financeiro têm unidades distintas. "
        "O conjunto de instrumentos muda entre as visões: a participação mensal e a trimestral podem ter denominadores diferentes.",
        (("Catálogo e periodicidades do SPB", "https://dadosabertos.bcb.gov.br/dataset/estatisticas-meios-pagamentos"),),
    ),
    SourceGuide(
        "registry", "Cadastro e administradores das instituições",
        "Identifica a instituição, seus vínculos cadastrais e os administradores disponibilizados pelo Banco Central.",
        "Atualização cadastral, sem frequência contábil fixa", "Pessoa jurídica e vínculos encontrados na consulta cadastral.",
        "Reflete a informação disponível no cadastro consultado. O app não mantém uma série histórica completa de mandatos.",
        "Orienta a seleção de instituições e a consulta de Conselho e Diretoria.",
        "Um cadastro consultado hoje pode diferir da composição do grupo em uma data-base passada. "
        "Cargo e vínculo cadastral precisam de documentação complementar para avaliar decisões ou responsabilidades.",
        (("Encontre uma instituição no BCB", "https://www.bcb.gov.br/estabilidadefinanceira/encontreinstituicao"),),
    ),
)
SOURCE_BY_KEY = {source.key: source for source in SOURCES}


# A entrada com metric_key recebe a definição e os detalhes do registro central.
TERMS = (
    GlossaryTerm("ifdata", "IFData", "Perímetros e contabilidade",
        "É a plataforma do Banco Central que divulga informações de balanço, resultado, capital e carteira de crédito das instituições supervisionadas.",
        "Os dados são trimestrais, com recortes de divulgação próprios. "
        "Os relatórios contábeis e de crédito mudaram em 2025; confira a competência, o perímetro e as colunas do relatório usado.",
        ("ifdata", "ifdata_credit"), (*REPORTS, DRE, PORTFOLIO), aliases=("IF.data", "relatórios do BCB", "formato IFData", "mudanças 2025")),
    GlossaryTerm("scr", "SCR e SCR.data", "Perímetros e contabilidade",
        "SCR é o sistema que recebe informações de operações de crédito das instituições. "
        "SCR.data é a divulgação pública de agregados dessas operações por região, produto e perfil.",
        "A base pública reúne recortes de operações e preserva o sigilo. "
        "Ela tem periodicidade mensal e escopo distinto dos balanços e das carteiras trimestrais do IFData.",
        ("scr", "ifdata_credit"), (STATISTICS, PORTFOLIO), aliases=("Sistema de Informações de Créditos", "3040", "SCR.data")),
    GlossaryTerm("sgs", "SGS", "Perímetros e contabilidade",
        "É o Sistema Gerenciador de Séries Temporais do Banco Central. "
        "Cada série tem um código, um conceito, uma unidade e um histórico próprios.",
        "As séries de crédito usadas no app são mensais. "
        "Ao cruzar séries, confira se os recortes e as últimas datas disponíveis são compatíveis.",
        ("sgs",), (STATISTICS,), aliases=("séries temporais", "código SGS")),
    GlossaryTerm("olinda", "Olinda: acesso aos dados do BCB", "Perímetros e contabilidade",
        "É uma forma de acesso eletrônico às bases públicas do Banco Central, usada pelo app para consultar relatórios, taxas e pagamentos.",
        "O nome do serviço identifica o canal de consulta. "
        "O conceito, a frequência e o escopo continuam sendo os da base de origem.",
        ("ifdata", "rates", "payments"), (DRE, RATES, PAYMENTS), aliases=("API", "dados abertos", "OData")),
    GlossaryTerm("individual", "Instituição individual", "Perímetros e contabilidade",
        "É a pessoa jurídica identificada por seu CNPJ, vista separadamente das demais empresas do grupo.",
        "Use esse recorte para examinar a entidade com a qual existe uma relação contratual. "
        "O patrimônio e o resultado do grupo podem ser diferentes dos dessa instituição.",
        ("ifdata", "cosif_4010", "statements"), (DRE, COSIF, STATEMENTS), aliases=("CNPJ", "não consolidado", "individual")),
    GlossaryTerm("prudential", "Conglomerado prudencial", "Perímetros e contabilidade",
        "É o conjunto de entidades sob uma instituição líder, consolidado para acompanhar o risco e o capital do grupo.",
        "Inclui entidades financeiras e outras entidades previstas nas regras prudenciais, com eliminação de operações internas. "
        "Compare grupos com o mesmo perímetro e confira sua composição na data-base.",
        ("ifdata", "cosif_prudential"), (*REPORTS, DRE, COSIF), aliases=("consolidado", "prudencial", "grupo", "líder")),
    GlossaryTerm("financial", "Conglomerado financeiro", "Perímetros e contabilidade",
        "É a consolidação do subconjunto de entidades do grupo autorizadas pelo BCB que integram a definição de conglomerado financeiro.",
        "Instituições de pagamento e administradoras de consórcio ficam fora desse conceito. "
        "O app concentra suas consultas nos recortes prudencial e individual; a visão financeira aparece na leitura das fontes e da série histórica.",
        ("ifdata", "ifdata_credit"), aliases=("financeiro", "consolidação")),
    GlossaryTerm("independent", "Instituição independente", "Perímetros e contabilidade",
        "É uma instituição que não integra um conglomerado no recorte de divulgação. Ela pode aparecer na mesma lista dos conglomerados.",
        "Na visão de conglomerados e independentes do IFData, as operações de agências no exterior "
        "são consideradas para independentes a partir de 2018. Verifique o recorte antes de comparar com a visão individual.",
        ("ifdata",), REPORTS, aliases=("independente", "exterior")),
    GlossaryTerm("cosif", "COSIF", "Perímetros e contabilidade",
        "É o padrão contábil do Banco Central: define contas e critérios usados pelas instituições reguladas para registrar suas operações.",
        "Uma conta COSIF descreve o conteúdo contábil. O documento informa o perímetro: "
        "4010 é individual; 4060 e 4066 são prudenciais. O plano de contas mudou em 2025.",
        ("cosif_4010", "cosif_prudential", "ifdata"), (COSIF, DRE), aliases=("plano de contas", "conta contábil", "padrão contábil")),
    GlossaryTerm("cadoc", "Cadoc e código do documento", "Perímetros e contabilidade",
        "Cadoc é o catálogo dos documentos enviados ao BCB. Cada código identifica um conjunto de informações e sua forma de apresentação.",
        "Guarde o código junto com a instituição e a data-base. Dois documentos do mesmo mês podem "
        "ter escopos ou finalidades diferentes, como o 4060 e o 4066.",
        ("cosif_4010", "cosif_prudential", "statements"), (COSIF, STATEMENTS), aliases=("4010", "4016", "4060", "4066", "9011")),
    GlossaryTerm("date", "Data-base e data de atualização", "Comparações e leitura",
        "Data-base é a data a que o número se refere. Data de atualização é quando a informação foi consultada ou incorporada ao app.",
        "Uma base atualizada hoje pode trazer dados de meses anteriores. "
        "Confira a última competência de cada fonte ao cruzar indicadores.",
        modules=(*REPORTS, "Atualizar Base"), example="Um balancete de junho continua sendo junho mesmo quando baixado em outubro.",
        aliases=("competência", "periodicidade", "defasagem", "atualização", "corte")),
    GlossaryTerm("missing", "N/D, zero e validação requerida", "Comparações e leitura",
        "N/D indica que a informação ou o cálculo está indisponível. Zero é um valor informado. "
        "Uma marca de validação sinaliza que o dado precisa de conferência antes da comparação.",
        "A falta de fonte, componente, vínculo confiável ou denominador válido pode impedir um indicador. "
        "Na Carteira 4.966, consulte o diagnóstico das células marcadas.",
        modules=(*REPORTS, PORTFOLIO), aliases=("ausente", "lacuna", "NaN", "n/d", "asterisco", "sanidade")),
    GlossaryTerm("stock_flow", "Estoque e fluxo", "Comparações e leitura",
        "Estoque é um saldo em uma data, como a carteira em junho. Fluxo é o que ocorreu durante um intervalo, como o lucro de janeiro a junho.",
        "Somar saldos mensais de carteira repete a exposição. Para receitas e despesas, "
        "confira se o valor já está acumulado antes de somar períodos.",
        ("ifdata", "cosif_4010", "cosif_prudential", "sgs"), (DRE, COSIF, STATISTICS), aliases=("saldo", "acumulado")),
    GlossaryTerm("ytd", "Acumulado no ano (YTD)", "Resultado e rentabilidade",
        "É o resultado de janeiro até a data-base escolhida. YTD é a sigla inglesa para acumulado no ano.",
        "O Relatório 4 do IFData acumula receitas e despesas por semestre. "
        "Para obter o ano até setembro ou dezembro, o app soma o primeiro semestre ao valor publicado do segundo.",
        ("ifdata",), (*REPORTS, DRE),
        example="Junho: lucro de 60. Setembro publicado: lucro de 20 desde julho. O YTD de setembro é 80.",
        aliases=("lucro líquido acumulado", "year to date", "semestral")),
    GlossaryTerm("annualization", "Anualização", "Resultado e rentabilidade",
        "Expressa um resultado de parte do ano como uma taxa anual, mantendo o ritmo observado no período.",
        "É uma convenção de comparação sensível à sazonalidade e a eventos pontuais. "
        "A taxa anualizada não estima o resultado que efetivamente ocorrerá até dezembro.",
        ("ifdata",), REPORTS, formula="Março × 4; junho × 2; setembro × 12/9; dezembro × 1, para fluxos YTD.",
        aliases=("anualizado", "run rate", "projeção")),
    GlossaryTerm("roe_ytd", "ROE Ac. Anualizado (%)", "Resultado e rentabilidade", "",
        "Na visão prudencial, o PL médio é aproximado pela média entre dezembro anterior e a data-base. "
        "Em Peers individual, o cálculo usa o PL atual da pessoa jurídica. "
        "Aportes, dividendos, sazonalidade e lucro extraordinário podem alterar bastante a leitura.",
        ("ifdata",), REPORTS, example="Lucro de 10 em seis meses e PL médio de 100 resultam em ROE anualizado de 20%.",
        aliases=("retorno sobre patrimônio", "ROE acumulado YTD", "rentabilidade"), metric_key="roe_ac_ytd_an"),
    GlossaryTerm("roe_quarter", "ROE Trim. Anualizado (%)", "Resultado e rentabilidade", "",
        "É mais sensível a oscilações recentes e itens extraordinários. Use o ROE acumulado para acompanhar a rentabilidade ao longo do ano.",
        ("ifdata",), REPORTS, aliases=("ROE trimestral", "retorno", "rentabilidade"), metric_key="roe_trim_an"),
    GlossaryTerm("net_income", "Lucro líquido", "Resultado e rentabilidade",
        "É o resultado final do período depois das receitas, despesas e tributos reconhecidos na demonstração de resultado.",
        "Confirme a janela: lucro do trimestre, do semestre e acumulado no ano têm durações diferentes. "
        "Compare com o mesmo período do ano anterior quando houver sazonalidade.",
        ("ifdata", "statements"), (*REPORTS, DRE, STATEMENTS), unit="R$", aliases=("LL", "resultado líquido")),
    GlossaryTerm("credit_revenue", "Receita de Crédito", "Resultado e rentabilidade", "",
        "Arrendamento, outras concessões e recuperações registradas em rubricas separadas têm tratamento próprio. "
        "O nome da linha delimita a receita usada pelo indicador.",
        ("ifdata",), (DRE, "Rankings", "Peers (Tabela Nova)"), metric_key="receita_credito"),
    GlossaryTerm("intermediation", "Resultado de intermediação financeira", "Resultado e rentabilidade",
        "Ajuda a acompanhar o resultado das atividades financeiras, como crédito, aplicações e captação, segundo as rubricas usadas na DRE.",
        "Confira a composição da linha na memória de cálculo. O rótulo de resultado bruto usado "
        "em indicadores do app soma rendas financeiras antes dos efeitos de perdas e captação; "
        "a abertura gerencial deve ser lida junto com suas demais despesas.",
        ("ifdata",), (DRE,), aliases=("NIM", "margem financeira", "intermediação bruta")),
    GlossaryTerm("efficiency", "Receitas de serviços e despesas administrativas", "Resultado e rentabilidade",
        "Receitas de serviços mostram ganhos com a prestação de serviços. Despesas administrativas refletem gastos de funcionamento registrados na DRE.",
        "Pessoal, outros gastos e tributos podem estar em rubricas próprias. "
        "Uma razão de eficiência exige definir quais receitas e despesas entram no cálculo.",
        ("ifdata", "statements"), (DRE, STATEMENTS), aliases=("eficiência", "tarifas", "pessoal", "custos")),
    GlossaryTerm("cet1", "Capital Principal (CET1)", "Capital e solidez",
        "É o capital regulatório de maior qualidade para absorver perdas. O índice CET1 compara esse capital aos riscos ponderados dos ativos.",
        "A folga depende dos requisitos aplicáveis à instituição e aos adicionais de capital. "
        "Confira o regime prudencial antes de usar um mínimo como referência.",
        ("ifdata",), REPORTS, formula="Índice CET1 = Capital Principal ÷ RWA Total", unit="%", aliases=("CET1", "common equity tier 1")),
    GlossaryTerm("tier1", "Capital Nível I", "Capital e solidez",
        "Reúne o Capital Principal e instrumentos complementares elegíveis de Nível I. "
        "Seu índice mostra quanto desse capital cobre os riscos ponderados.",
        "Capital regulatório e patrimônio contábil seguem critérios diferentes de elegibilidade e ajustes.",
        ("ifdata",), formula="Índice de Nível I = (Capital Principal + Capital Complementar) ÷ RWA Total", unit="%", aliases=("tier 1", "capital complementar")),
    GlossaryTerm("basel", "Índice de Basileia", "Capital e solidez", "",
        "O índice exige comparação com os requisitos da instituição. "
        "Liquidez, concentração e qualidade dos ativos precisam de indicadores próprios.",
        ("ifdata",), REPORTS, aliases=("Basileia total", "solvência", "PR"), metric_key="indice_basileia"),
    GlossaryTerm("rwa", "RWA: ativos ponderados pelo risco", "Capital e solidez",
        "É a medida regulatória de exposição usada nos índices de capital, com ponderações para os riscos de crédito, mercado e operacional.",
        "RWA e ativo total têm conceitos diferentes. Uma mudança de RWA pode vir de composição "
        "da carteira, modelos ou regras, mesmo com saldo contábil parecido.",
        ("ifdata",), REPORTS, aliases=("risk weighted assets", "risco ponderado", "crédito mercado operacional")),
    GlossaryTerm("pr", "Patrimônio de Referência (PR)", "Capital e solidez",
        "É o capital reconhecido para fins prudenciais, formado por instrumentos elegíveis e ajustes regulatórios.",
        "Pode diferir do patrimônio líquido contábil. "
        "O índice de Basileia relaciona o PR ao RWA.", ("ifdata",), REPORTS, aliases=("capital regulatório", "Nível II", "tier 2")),
    GlossaryTerm("capital_buffer", "Adicional de Capital Principal (ACP)", "Capital e solidez",
        "É uma exigência adicional de Capital Principal, composta pelos adicionais de conservação, contracíclico e sistêmico quando aplicáveis.",
        "Os percentuais dependem do regime, da instituição e da data-base. "
        "O app apresenta indicadores agregados; uma conclusão de enquadramento exige conferir as regras aplicáveis.",
        ("ifdata",), aliases=("buffer", "colchão de capital", "conservação", "contracíclico")),
    GlossaryTerm("leverage", "Alavancagem contábil e regulatória", "Capital e solidez",
        "A alavancagem contábil relaciona o tamanho do balanço ao patrimônio. "
        "A razão regulatória de alavancagem relaciona o capital Nível I à exposição definida pelo regulador.",
        "Quanto maior Ativo/PL, maior o balanço sustentado por cada real de patrimônio. "
        "Na razão regulatória, um percentual maior indica mais capital por unidade de exposição.",
        ("ifdata",), REPORTS, formula="Contábil: Ativo Total ÷ PL, em vezes. Regulatória: Nível I ÷ Exposição Total, em %.",
        aliases=("Ativo Total / PL", "razão de alavancagem", "exposição total")),
    GlossaryTerm("irrbb", "IRRBB", "Capital e solidez",
        "É o risco de alterações nas taxas de juros afetarem o resultado ou o valor econômico das posições da carteira bancária.",
        "O campo regulatório publicado tem metodologia própria. "
        "A leitura completa exige conhecer prazos, indexadores e proteção das posições.",
        ("ifdata",), aliases=("sensibilidade", "risco de juros", "banking book")),
    GlossaryTerm("asset", "Ativo total", "Balanço e captação",
        "É o total de recursos e direitos registrados no balanço, como crédito, títulos, caixa e participações.",
        "Mostra porte contábil. A composição, o risco e a disponibilidade desses ativos determinam sua qualidade.",
        ("ifdata", "statements"), (*REPORTS, DRE, STATEMENTS), unit="R$", aliases=("ativos", "tamanho", "balanço")),
    GlossaryTerm("equity", "Patrimônio líquido (PL)", "Balanço e captação",
        "É a diferença contábil entre ativos e passivos. Representa o patrimônio atribuível aos proprietários, sujeito aos ajustes da contabilidade.",
        "Aportes, distribuição de resultados e ajustes de avaliação alteram o PL. "
        "O capital aceito pelo regulador é apurado por regras próprias.",
        ("ifdata", "statements"), (*REPORTS, DRE, STATEMENTS), unit="R$", aliases=("PL", "equity", "patrimônio")),
    GlossaryTerm("credit_balance", "Carteira de Crédito*", "Balanço e captação", "",
        "A composição do balanço e a carteira ativa do SCR usam bases diferentes. "
        "O trecho até 2024 e a alternativa líquida têm parcelas já deduzidas de provisão.",
        ("ifdata",), REPORTS, aliases=("carteira bruta", "crédito contábil", "crédito com asterisco"), metric_key="carteira_credito"),
    GlossaryTerm("liquid_assets", "Ativos líquidos", "Balanço e captação",
        "É a aproximação usada pelo app para ativos de maior liquidez: disponibilidades, aplicações interfinanceiras e títulos e valores mobiliários.",
        "Parte dos títulos pode ter restrição, risco de preço ou prazo longo. "
        "A aproximação exige leitura da composição e tem finalidade diferente dos indicadores regulatórios LCR e NSFR.",
        ("ifdata",), REPORTS, formula="Disponibilidades + Aplicações Interfinanceiras de Liquidez + TVM", unit="R$",
        aliases=("liquidez", "LCR", "NSFR", "AIL", "TVM")),
    GlossaryTerm("deposits", "Depósitos totais", "Balanço e captação",
        "São recursos mantidos por clientes e outras contrapartes na instituição, nas categorias de depósitos apresentadas no passivo.",
        "O app prioriza o agregado oficial. Quando recorre aos componentes, a soma depende de "
        "todas as parcelas necessárias. Prazo, concentração e estabilidade dos depósitos exigem análise adicional.",
        ("ifdata",), REPORTS, unit="R$", aliases=("funding", "depósitos à vista", "poupança", "depósitos a prazo")),
    GlossaryTerm("funding", "Core Funding: base de captação", "Balanço e captação",
        "É a base de recursos captados que o app usa em comparações com a carteira de crédito.",
        "Até 2024 usa Captações. A partir de 2025 inclui também instrumentos de dívida elegíveis "
        "a capital. O termo é uma definição analítica do app e não assegura estabilidade dos recursos.",
        ("ifdata",), REPORTS, formula="Até 2024: Captações (e). Desde 2025: Captações (e) + Instrumentos de Dívida Elegíveis a Capital (h).",
        unit="R$", aliases=("captações", "dívida subordinada", "funding")),
    GlossaryTerm("credit_funding", "Crédito / Captações (%)", "Balanço e captação",
        "Compara a carteira contábil de crédito à base de captação usada pelo app. "
        "Ajuda a acompanhar quanto dessa base está associado ao tamanho da carteira.",
        "As duas bases mudaram em 2025. Um percentual alto exige olhar outras fontes de financiamento, "
        "prazos e liquidez. A razão fica indisponível quando falta componente obrigatório.",
        ("ifdata",), REPORTS, formula="Carteira de Crédito* ÷ Core Funding", unit="%", aliases=("crédito funding", "carteira/core funding")),
    GlossaryTerm("funding_cost", "Despesa de captação / Captação", "Balanço e captação",
        "Relaciona a despesa com a obtenção de recursos ao saldo captado, para acompanhar o custo contábil de financiamento da instituição.",
        "A despesa é um fluxo anualizado e a captação é um saldo da data-base. "
        "A composição da base pode diferir do Core Funding. Confira o sinal e as rubricas na memória de cálculo.",
        ("ifdata",), (DRE,), formula="Despesa de captação YTD × (12 ÷ meses decorridos) ÷ Captações", unit="%",
        aliases=("Desp Captação / Captação", "custo de funding", "despesa de funding")),
    GlossaryTerm("credit_equity", "Carteira de crédito / PL", "Balanço e captação",
        "Mostra quantos reais de crédito são sustentados por cada real de patrimônio contábil.",
        "Confira se a tela expressa a relação em vezes ou em percentual. "
        "A mudança da carteira em 2025 também afeta a comparação histórica.",
        ("ifdata",), REPORTS, formula="Carteira de Crédito* ÷ Patrimônio Líquido", aliases=("Crédito/PL", "alavancagem de crédito")),
    GlossaryTerm("credit_loss_cost", "Custo de Crédito (%)", "Carteira e perdas", "",
        "É um fluxo da DRE dividido por um estoque do balanço. Snapshot e Rankings usam o valor sem o sinal; "
        "a tabela Peers preserva a distinção entre despesa positiva e reversão negativa ao inverter o sinal da DRE. "
        "O cálculo depende da linha específica de operações de crédito disponível desde 2025.",
        ("ifdata",), REPORTS, aliases=("cost of risk", "f3", "custo do risco"), metric_key="custo_credito"),
    GlossaryTerm("credit_loss_revenue", "Custo de Crédito / Receita de Crédito (%)", "Carteira e perdas", "",
        "Ambos os valores usam a mesma janela acumulada. A receita deve ser positiva e "
        "as rubricas precisam estar disponíveis. Confira o sinal na DRE: Peers apresenta despesa positiva "
        "e reversão negativa, enquanto os indicadores que usam valor absoluto retiram essa distinção.",
        ("ifdata",), REPORTS, metric_key="custo_credito_receita"),
    GlossaryTerm("provision_income", "Despesa com perdas / Resultado de intermediação bruto", "Carteira e perdas",
        "Compara o resultado com perdas esperadas às rendas financeiras agregadas usadas pelo app. "
        "Ajuda a acompanhar seu peso na geração de receitas financeiras.",
        "O numerador inclui tipos de ativos além das operações de crédito. "
        "O indicador Custo de Crédito / Receita de Crédito usa uma composição específica de crédito. "
        "Confira sinais e valores pequenos no denominador.",
        ("ifdata",), (DRE,), formula="Resultado com Perda Esperada (f) ÷ soma das rendas financeiras (a a e)", unit="%",
        aliases=("Desp PDD / Resultado Intermediação Fin. Bruto", "PDD receita", "resultado bruto")),
    GlossaryTerm("provision", "Provisão, PDD e perda esperada", "Carteira e perdas",
        "A provisão é o ajuste contábil para perdas de crédito estimadas. PDD é um rótulo tradicional "
        "que o app ainda usa em algumas telas. Desde 2025, a leitura segue o modelo de perda esperada aplicável.",
        "Separe o saldo da provisão no balanço do resultado com perdas na DRE. "
        "No indicador da Carteira 4.966, a PDD usa somente as parcelas de perda esperada, sem ajustes de valor justo e hedge.",
        ("ifdata", "cosif_prudential", "ifdata_credit"), (*REPORTS, DRE, PORTFOLIO), aliases=("ECL", "perda esperada", "PDD", "provisionamento")),
    GlossaryTerm("stage1", "Estágio 1", "Carteira e perdas",
        "No modelo de três estágios, reúne ativos sem aumento significativo do risco de crédito desde o reconhecimento inicial. "
        "A perda esperada considera o horizonte de doze meses.",
        "É uma classificação contábil que depende da metodologia aplicável à instituição. "
        "A avaliação inclui outros sinais de risco além do atraso.",
        ("cosif_prudential",), aliases=("estágio 1", "doze meses", "12 meses")),
    GlossaryTerm("stage2", "Estágio 2", "Carteira e perdas",
        "No modelo de três estágios, reúne ativos cujo risco de crédito aumentou significativamente desde a contratação. "
        "A perda esperada passa a considerar toda a vida do instrumento.",
        "Pode incluir contratos com pagamentos em dia. "
        "No app, o valor depende da publicação da conta e da identificação correta do conglomerado.",
        ("cosif_prudential",), REPORTS, formula="Conta 3312000001 no documento 4060", unit="R$", aliases=("estágio 2", "deterioração", "lifetime")),
    GlossaryTerm("stage3", "Estágio 3", "Carteira e perdas",
        "No modelo de três estágios, reúne ativos com problema de recuperação de crédito, com perda esperada calculada para toda a vida do instrumento.",
        "O valor contábil do estágio e os agregados de inadimplência do SCR têm fontes e bases próprias. "
        "Compare conceitos e denominadores antes de interpretar a diferença.",
        ("cosif_prudential", "ifdata_credit"), REPORTS, formula="Conta 3313000000 no documento 4060", unit="R$", aliases=("estágio 3", "impaired")),
    GlossaryTerm("coverage", "Cobertura por provisão", "Carteira e perdas",
        "Compara a provisão com uma base de risco, como a inadimplência, o estágio 3 ou os estágios 2 e 3 combinados.",
        "O nome do denominador é parte do indicador. Uma provisão total pode cobrir perdas "
        "de ativos fora desse denominador. A razão é uma aproximação e exige o mesmo perímetro e período.",
        ("ifdata", "cosif_prudential", "ifdata_credit", "sgs"), (*REPORTS, PORTFOLIO, STATISTICS),
        formula="Magnitude da provisão ÷ base de risco explicitada no indicador", unit="% ou vezes, conforme a tela",
        aliases=("PDD/Estágio 3", "perda esperada/est2+3", "provisão/inadimplência", "índice de cobertura")),
    GlossaryTerm("provision_ratio", "Provisão / Carteira de crédito", "Carteira e perdas",
        "Mostra o peso da provisão para perdas esperadas em relação ao saldo da carteira escolhido como denominador.",
        "O app usa bases distintas conforme a tela: carteira contábil ou Total Geral do Relatório 16. "
        "Uma diferença no percentual pode decorrer da base usada, da composição e das premissas de perda.",
        ("ifdata", "ifdata_credit"), (*REPORTS, PORTFOLIO), formula="Provisão para perdas esperadas ÷ carteira indicada na tela", unit="%",
        aliases=("Perda Esperada / Carteira de Crédito Bruta", "PDD/Carteira Total", "provisionamento relativo")),
    GlossaryTerm("default_balance", "Inadimplência", "Carteira e perdas", "",
        "Na Carteira 4.966, o valor é publicado no Relatório 16. "
        "SCR.data e séries SGS têm escopos próprios; confira a fonte ao cruzar os resultados.",
        ("ifdata_credit", "scr", "sgs"), (*REPORTS, PORTFOLIO, STATISTICS), aliases=("atraso 90 dias", "arrasto", "NPL"), metric_key="inadimplencia"),
    GlossaryTerm("default_ratio", "Inadimplência / Carteira Total", "Carteira e perdas", "",
        "Na Carteira 4.966, o denominador é o Total Geral do Relatório 16. "
        "O indicador com carteira contábil no denominador pode ter resultado diferente.",
        ("ifdata_credit",), (*REPORTS, PORTFOLIO), metric_key="inadimplencia_carteira_total"),
    GlossaryTerm("problem_assets", "Ativos Problemáticos / Carteira Total", "Carteira e perdas", "",
        "Abrange sinais de não pagamento além do atraso. "
        "O relatório por instrumentos começa em mar/2025 e tem conceito distinto do estágio 3 contábil.",
        ("ifdata_credit",), (*REPORTS, PORTFOLIO), aliases=("ativo problemático", "reestruturação"), metric_key="ativos_problematicos_carteira_total"),
    GlossaryTerm("scr_active", "Carteira ativa do SCR", "Carteira e perdas",
        "É o saldo das operações de crédito a vencer e vencidas incluídas no recorte do SCR.",
        "A origem por operação e o escopo geográfico podem gerar diferenças frente ao balanço COSIF. "
        "No SCR.data, os filtros definem quais operações entram no total.",
        ("scr", "ifdata_credit"), (STATISTICS, PORTFOLIO), formula="Carteira a vencer + carteira vencida", unit="R$", aliases=("total geral", "carteira ativa")),
    GlossaryTerm("scr_ratios", "Taxas de inadimplência no SCR.data", "Carteira e perdas",
        "Medem a proporção da carteira ativa atingida pela inadimplência ou por outra condição de risco, no recorte selecionado.",
        "O app soma os saldos antes de dividir. "
        "Uma média simples das taxas de regiões ou produtos dá o mesmo peso a carteiras de tamanhos diferentes.",
        ("scr",), (STATISTICS,), formula="Soma dos saldos inadimplentes ÷ soma da carteira ativa", unit="%",
        example="Carteira de 100 com 10% de atraso e carteira de 900 com 2%: juntas, têm 2,8% de inadimplência.", aliases=("razão de somas", "média ponderada", "taxa SCR")),
    GlossaryTerm("past_due", "Saldo vencido e atraso de 15 a 90 dias", "Carteira e perdas",
        "Saldo vencido mede as parcelas cujo pagamento já atrasou. "
        "A faixa de 15 a 90 dias ajuda a acompanhar sinais de dificuldade antes do corte de inadimplência.",
        "A inadimplência por arrasto inclui o saldo inteiro da operação. "
        "O atraso inicial pode evoluir ou ser regularizado; a base agregada não estima a probabilidade dessa migração.",
        ("scr",), (STATISTICS,), aliases=("vencido acima de 90 dias", "atraso 15-90 dias", "indicador antecedente")),
    GlossaryTerm("instruments", "Carteiras C1 a C5", "Carteira e perdas",
        "São agrupamentos de instrumentos financeiros divulgados no Relatório 16, usados para organizar a carteira na leitura da Resolução 4.966.",
        "C1 a C5 são carteiras de instrumentos e não uma sequência equivalente aos estágios 1, 2 e 3. "
        "O total também pode conter parcelas não informadas, não individualizadas e exterior, conforme o relatório.",
        ("ifdata_credit",), (PORTFOLIO,), aliases=("C1 C2 C3 C4 C5", "4966", "4.966", "classificação", "nível de risco A H")),
    GlossaryTerm("borrower", "Porte PJ e faixa de renda PF", "Carteira e perdas",
        "Organizam os tomadores por tamanho da empresa ou renda individual, segundo a informação declarada pela instituição no SCR.",
        "As faixas PJ usam limites nominais; a faixa grande pode decorrer de receita ou ativo. "
        "As faixas PF usam salários mínimos da data-base e admitem renda presumida ou estimada.",
        ("scr",), (STATISTICS,),
        formula="PJ: micro até R$ 360 mil de receita anual; pequena até R$ 4,8 milhões; "
        "média até R$ 300 milhões de receita e R$ 240 milhões de ativo; "
        "grande acima de R$ 300 milhões de receita ou R$ 240 milhões de ativo. "
        "PF: faixas em salários mínimos vigentes na data-base.",
        aliases=("micro pequena média grande", "rendimento", "salário mínimo", "porte", "PF", "PJ")),
    GlossaryTerm("geography", "UF, região e segmento no SCR.data", "Carteira e perdas",
        "UF e região localizam o tomador; o segmento identifica o tipo de instituição credora, como banco, cooperativa, financeira ou SCD/SEP.",
        "A UF usa a residência da pessoa física ou a sede da empresa. "
        "A cobertura dos segmentos varia no tempo e a visão de série completa do app tem menos detalhamento.",
        ("scr",), (STATISTICS,), aliases=("mapa", "CEP", "fintech", "SCD", "SEP", "instituição de pagamento", "cooperativa")),
    GlossaryTerm("operations", "Número de operações e sigilo", "Carteira e perdas",
        "É a contagem de contratos do recorte. No SCR.data, algumas contagens são suprimidas pelo BCB para proteger o sigilo.",
        "A fonte marca contagens sigilosas com -1. O app as retira da soma e mostra a cobertura "
        "no diagnóstico; a quantidade exibida nesses recortes é subestimada.",
        ("scr",), (STATISTICS,), unit="Operações", aliases=("supressão", "contratos", "sigilo", "-1")),
    GlossaryTerm("product", "Modalidade e submodalidade de crédito", "Juros e mercado de crédito",
        "Modalidade agrupa operações com características semelhantes. Submodalidade detalha o produto, como cartão rotativo ou uma forma de consignado.",
        "As classificações diferem entre fontes e podem mudar ao longo do tempo. "
        "No SCR.data, modalidade e submodalidade devem ser mantidas juntas para identificar o recorte.",
        ("scr", "ifdata_credit", "rates", "sgs"), (STATISTICS, RATES), aliases=("produto", "cartão", "consignado", "capital de giro")),
    GlossaryTerm("concessions", "Saldo e concessões de crédito", "Juros e mercado de crédito",
        "Saldo é a carteira existente no fim do período. Concessões são os valores das novas operações contratadas durante o período.",
        "Uma alta nas concessões pode coincidir com queda de saldo quando amortizações, liquidações ou baixas superam as novas operações.",
        ("sgs",), (STATISTICS,), aliases=("crédito novo", "volume contratado", "estoque")),
    GlossaryTerm("resources", "Recursos livres e direcionados", "Juros e mercado de crédito",
        "Recursos livres financiam operações com condições negociadas pelas instituições. "
        "Recursos direcionados seguem destinação ou condições específicas, como parte do crédito rural e imobiliário.",
        "A composição por produto e tomador afeta juros e inadimplência. "
        "Compare taxas usando a mesma origem de recursos e a mesma modalidade.",
        ("sgs", "scr"), (STATISTICS,), aliases=("livre", "direcionado", "rural", "habitacional")),
    GlossaryTerm("rates", "Taxa mensal e taxa anual de juros", "Juros e mercado de crédito",
        "São formas de expressar a taxa observada: por mês (% a.m.) ou por ano (% a.a.). "
        "A aba de produtos usa os valores publicados pelo BCB para a mesma observação.",
        "Juros compostos tornam a taxa anual diferente de doze vezes a taxa mensal. "
        "Confira produto, período, indexador e a unidade antes de comparar.",
        ("rates", "sgs"), (RATES, STATISTICS), formula="Equivalência composta: taxa anual = (1 + taxa mensal em decimal)^12 − 1",
        aliases=("a.m.", "a.a.", "juros compostos", "taxa média")),
    GlossaryTerm("monthly_rates", "Visão mensal das taxas por produto", "Juros e mercado de crédito",
        "Na aba de taxas por produto, cada ponto mensal usa a última observação disponível da instituição naquele mês.",
        "Instituições podem ter observações finais em dias diferentes. "
        "Confira a janela oficial e as lacunas; o ponto mensal não é uma média de todo o mês.",
        ("rates",), (RATES,), aliases=("última observação", "janela diária", "diário", "histórico de taxas")),
    GlossaryTerm("spread", "Spread e custo do crédito no mercado", "Juros e mercado de crédito",
        "Spread mede a diferença entre a taxa cobrada e o custo de captação de referência, "
        "segundo a série. Indicadores de custo do estoque abrangem as operações que permanecem na carteira.",
        "Taxas de novas concessões, custo do estoque e Custo de Crédito da DRE têm definições próprias. "
        "O Custo de Crédito usado nas comparações de bancos se refere ao resultado com perdas esperadas.",
        ("sgs", "rates", "ifdata"), (STATISTICS, RATES), aliases=("ICC", "indicador de custo do crédito", "spread bancário")),
    GlossaryTerm("payment_volume", "Quantidade e valor de pagamentos", "Pagamentos",
        "Quantidade conta transações. Valor mede o dinheiro movimentado. "
        "Os dois ajudam a entender o uso de um instrumento de pagamento.",
        "O app indica a escala nos eixos e tabelas. "
        "Uma transação de grande valor pode alterar a participação financeira sem alterar muito a participação em quantidade.",
        ("payments",), (PAYMENTS,), aliases=("Pix", "TED", "boleto", "DOC", "TEC", "cheque", "volume financeiro")),
    GlossaryTerm("ticket", "Ticket médio", "Pagamentos",
        "É o valor médio de uma transação no instrumento e período escolhidos.",
        "Converta quantidade e valor para escalas compatíveis antes de dividir. "
        "A média pode ser influenciada por poucas transações de grande valor.",
        ("payments",), (PAYMENTS,), formula="Valor financeiro ÷ número de transações, após ajustar as unidades", unit="R$ por transação"),
    GlossaryTerm("mdr", "MDR e tarifa de intercâmbio", "Pagamentos",
        "MDR é a taxa de desconto cobrada do estabelecimento nas vendas com cartão. "
        "Intercâmbio é a tarifa transferida ao emissor do cartão na relação com o credenciador.",
        "São medidas de etapas distintas da transação. "
        "Função do cartão, período, bandeira e forma de agregação afetam a comparação.",
        ("payments",), (PAYMENTS,), aliases=("TIC", "taxa de desconto", "merchant discount rate", "adquirência")),
    GlossaryTerm("payment_access", "Canal de acesso e infraestrutura", "Pagamentos",
        "Canal identifica como a transação foi acessada, por exemplo celular, agência ou internet banking. "
        "Infraestrutura inclui terminais de aceitação, caixas eletrônicos e estabelecimentos credenciados.",
        "Algumas séries de canal incluem serviços financeiros e não financeiros. "
        "Confira a atividade contada antes de comparar com transações de um instrumento específico.",
        ("payments",), (PAYMENTS,), aliases=("ATM", "POS", "PDV", "celular", "internet banking", "terminais")),
    GlossaryTerm("qoq_yoy", "QoQ, YoY e pontos percentuais", "Comparações e leitura",
        "QoQ compara com o trimestre anterior. YoY compara com o mesmo período do ano anterior. "
        "Pontos percentuais medem a diferença direta entre duas taxas.",
        "Confira se a variação usa um saldo, um fluxo do trimestre ou YTD. "
        "Taxas e valores próximos de zero ou negativos precisam de leitura própria.",
        modules=REPORTS, example="Uma taxa de 10% para 12% subiu 2 pontos percentuais, ou 20% em termos relativos.",
        aliases=("p.p.", "delta", "variação", "trimestre contra trimestre", "ano contra ano")),
    GlossaryTerm("peers", "Peers e comparação entre instituições", "Comparações e leitura",
        "Peers são instituições escolhidas como referências para comparação. "
        "A escolha deve considerar porte, negócio, composição da carteira e fonte de recursos.",
        "Use o mesmo período e perímetro. Modelos de negócio diferentes podem sustentar "
        "níveis diferentes de rentabilidade, capital e alavancagem.",
        modules=("Peers (Tabela Nova)", "Rankings", "Scatter Plot"), aliases=("pares", "pool", "benchmark", "mediana")),
    GlossaryTerm("ranking", "Ranking e participação no recorte", "Comparações e leitura",
        "Ranking ordena as instituições com dados disponíveis para o indicador. "
        "Participação compara um valor ao total da seleção exibida.",
        "Filtros e lacunas alteram quem entra na comparação. Em Contas COSIF, "
        "a ordenação e a participação usam o valor absoluto calculado; preserve o sinal para interpretar o resultado.",
        modules=("Rankings", COSIF, STATISTICS, PAYMENTS), aliases=("market share", "share", "top", "valor calculado abs")),
    GlossaryTerm("scatter", "Gráfico de dispersão", "Comparações e leitura",
        "Cada ponto representa uma instituição em dois indicadores. "
        "A posição ajuda a localizar diferenças e possíveis relações entre as variáveis.",
        "Uma relação visual não estabelece causa. "
        "Amostra, porte e modelo de negócio podem explicar a posição dos pontos.",
        modules=("Scatter Plot",), aliases=("scatter", "correlação", "quadrante")),
    GlossaryTerm("cosif_value", "Valor calculado em Contas COSIF", "Perímetros e contabilidade",
        "É o valor usado na comparação da conta escolhida: saldo da data-base ou fluxo reconstruído para o trimestre ou acumulado.",
        "Contas de resultado acumulam por semestre. As contas de saldo mantêm a posição da data-base. "
        "O app verifica a natureza da conta e os meses necessários para calcular a janela escolhida.",
        ("cosif_4010", "cosif_prudential"), (COSIF,), aliases=("valor calculado", "conta sintética", "trimestre isolado", "acumulado semestral")),
    GlossaryTerm("fgc", "FGC: AR, VR e CR", "Balanço e captação",
        "AR significa Ativos de Referência, VR significa Valor de Referência e CR significa Captação de Referência. "
        "São conceitos da base de contribuições ao FGC.",
        "Em Contas COSIF, AR e VR vêm do balancete individual quando publicados. "
        "CR permanece N/D quando a subconta necessária não aparece no arquivo público. "
        "Esses valores precisam da regra do FGC para interpretar contribuição e elegibilidade.",
        ("cosif_4010",), (COSIF,), aliases=("FGC", "AR", "VR", "CR", "Fundo Garantidor de Créditos", "contribuição")),
    GlossaryTerm("statements", "BP, DRE, DRA, DFC e DMPL", "Perímetros e contabilidade",
        "BP mostra a posição patrimonial; DRE, o resultado; DRA, o resultado abrangente; "
        "DFC, as movimentações de caixa; DMPL, as mudanças do patrimônio líquido.",
        "Na consulta 9011, o app mostra os blocos presentes no documento. "
        "Confira sua unidade e as referências internas: A indica acumulado e S indica semestre.",
        ("statements",), (STATEMENTS,), aliases=("balanço patrimonial", "fluxo de caixa", "mutações do patrimônio", "9011", "referência A S")),
    GlossaryTerm("governance", "Conselho e diretoria", "Governança",
        "São órgãos de administração com funções próprias de supervisão e gestão. "
        "A aba reúne os cargos e vínculos disponibilizados no cadastro do BCB.",
        "O cadastro pode refletir a situação atual, com cobertura parcial. "
        "Atas, estatuto e documentos de mandato são necessários para uma análise histórica ou de responsabilidades.",
        ("registry",), ("Conselho e Diretoria",), aliases=("administradores", "mandato", "governança")),
)

ESSENTIAL_KEYS = ("individual", "prudential", "cosif", "date", "missing", "ytd", "credit_balance", "default_balance")


READING_GUIDES = (
    ReadingGuide("perimeter", "Como escolher entre individual e conglomerado?",
        "Comece pela entidade que deseja examinar. Use individual para a pessoa jurídica e prudencial "
        "para acompanhar o grupo e seu capital. Mantenha o recorte ao longo da comparação e "
        "confira a composição do grupo na data-base.",
        "Uma subsidiária pode ter patrimônio e resultado próprios, enquanto o índice de capital mostrado "
        "para o conglomerado se refere ao conjunto consolidado.", ("ifdata", "registry")),
    ReadingGuide("history", "Quando a série prudencial começa?",
        "A metodologia do IFData distingue os relatórios: informações contábeis prudenciais a partir de "
        "mar/2014, capital prudencial a partir de mar/2015 e carteiras de crédito prudenciais a partir de "
        "mar/2025. A cobertura carregada pelo app depende de cada base.",
        "Usar mar/2015 como início de uma comparação que exige capital é coerente. "
        "Esse corte não descreve o início de todos os relatórios contábeis prudenciais.", ("ifdata", "ifdata_credit")),
    ReadingGuide("ifdata_2025", "O que mudou no IFData em 2025?",
        "O novo COSIF passou a valer em jan/2025. Os relatórios de ativo e resultado ganharam "
        "novas rubricas e composições. Nas carteiras de crédito, houve passagem da visão financeira "
        "para a prudencial e o relatório por níveis de risco foi substituído pelo de carteiras de instrumentos.",
        "O app sinaliza a Carteira de Crédito* e muda a composição de Core Funding em 2025. "
        "Uma variação entre dez/2024 e mar/2025 pode combinar movimento econômico e mudança de base.",
        ("ifdata", "ifdata_credit")),
    ReadingGuide("dre_layout", "Como ler mudanças de formato na DRE?",
        "No formato de 2025, resultado com perda esperada ganhou aberturas por tipo de ativo. "
        "Algumas colunas também mudam entre competências, inclusive nos blocos de tributos e lucro "
        "dos formatos usados desde dez/2025. O app resolve as rubricas pelo período e preserva a memória de cálculo.",
        "Uma coluna ausente no leiaute antigo não demonstra uma despesa igual a zero. "
        "Ao comparar períodos, consulte a rubrica de origem e a composição da linha gerencial.", ("ifdata",)),
    ReadingGuide("ytd", "Como comparar trimestre, semestre e acumulado no ano?",
        "Balanço mostra o saldo da data-base. Receitas e despesas do Relatório 4 acumulam por semestre. "
        "O trimestre de junho é junho menos março; o de dezembro é dezembro menos setembro. "
        "Março e setembro já representam os primeiros três meses de cada semestre.",
        "Junho publicado = 60; setembro publicado = 20 desde julho. "
        "O YTD de setembro é 80 e o trimestre de julho a setembro é 20. "
        "Se junho estiver ausente, o YTD de setembro fica N/D.", ("ifdata", "cosif_4010", "cosif_prudential")),
    ReadingGuide("credit_sources", "Por que a carteira muda entre as telas?",
        "O balanço registra saldos contábeis por rubrica. O SCR parte das operações informadas pelas "
        "instituições. Carteira de Crédito*, Total Geral do Relatório 16 e carteira ativa do SCR.data "
        "podem ter composição, perímetro e cobertura geográfica diferentes.",
        "Inadimplência dividida pelo Total Geral do Relatório 16 é uma razão da mesma fonte. "
        "Ao trocar o denominador pela carteira contábil, passa-se a medir uma relação entre bases distintas.",
        ("ifdata", "ifdata_credit", "scr")),
    ReadingGuide("scr_2025", "Como ler ativos problemáticos antes e depois de 2025?",
        "No SCR.data, a metodologia até dez/2024 combinava atraso superior a 90 dias e sinais de "
        "não pagamento, com tratamento de reestruturações e níveis E a H. Desde jan/2025, "
        "o critério usa as operações marcadas pela instituição como ativos problemáticos.",
        "Uma mudança da taxa entre 2024 e 2025 precisa ser lida junto com essa quebra. "
        "A diferença observada, sozinha, não permite quantificar melhora ou piora econômica.", ("scr",)),
    ReadingGuide("weights", "Como agregar percentuais de regiões, produtos ou bancos?",
        "Some os numeradores e os denominadores do mesmo recorte antes de dividir. "
        "A média simples de taxas representa uma instituição ou recorte típico; a razão de somas "
        "representa a participação no estoque agregado.",
        "Uma carteira de 100 com 10 inadimplentes e outra de 900 com 18 inadimplentes somam "
        "28 em 1.000, ou 2,8%. A média simples das duas taxas seria 6%.", ("scr", "ifdata_credit")),
    ReadingGuide("missing", "Como interpretar N/D e indicadores marcados?",
        "Confira o diagnóstico: pode faltar um relatório, uma rubrica, um mês necessário, "
        "um vínculo cadastral confiável ou um denominador válido. Uma marca de atenção na "
        "Carteira 4.966 também pode indicar inconsistência entre componentes.",
        "Estágio 3 ausente impede a cobertura Provisão/Estágio 3. "
        "Tratar essa ausência como zero geraria uma interpretação indevida do risco.",
        ("ifdata", "cosif_prudential", "ifdata_credit")),
    ReadingGuide("units", "Como conferir unidades e sinais?",
        "Leia a unidade na tabela, no eixo e no documento. R$, R$ mil, R$ milhão e R$ bilhão "
        "têm escalas distintas. Percentual e vezes também exigem leitura própria. "
        "Despesas podem estar negativas e algumas razões usam sua magnitude.",
        "2,5 vezes corresponde a 250%. Uma despesa de −10 usada em valor absoluto continua "
        "exigindo a leitura do sinal original para distinguir despesa e reversão.",
        ("ifdata", "statements", "payments")),
    ReadingGuide("rates", "O ponto mensal de juros é a média do mês?",
        "Na aba de taxas por produto, o app seleciona a última observação disponível do mês. "
        "Cada observação segue a janela oficial do BCB. Na área SGS, as séries mensais seguem "
        "a metodologia e a unidade de cada série.",
        "Dois bancos podem ter seu último ponto em datas diferentes. "
        "Confira as janelas antes de atribuir a diferença apenas a uma mudança de preço.", ("rates", "sgs")),
    ReadingGuide("payments", "Por que a participação dos pagamentos muda com a frequência?",
        "A base mensal do SPB cobre um conjunto menor de instrumentos. Cartões e várias outras "
        "aberturas estão na base trimestral. A participação usa o total dos instrumentos incluídos "
        "no recorte, conforme a seleção da tela.",
        "A participação do Pix entre os instrumentos mensais pode ser maior que sua participação "
        "no trimestre quando cartões também entram no denominador.", ("payments",)),
    ReadingGuide("freshness", "Atualizar o app atualiza todas as fontes?",
        "Cada fonte tem seu calendário e sua forma de consulta. Parte das telas usa bases publicadas "
        "pelo app; DRE gerencial e documento 9011 fazem consultas ao BCB. Uma atualização local "
        "precisa ser publicada para chegar à versão distribuída.",
        "O fato de um mês estar disponível no SCR.data não implica que o IFData já tenha "
        "divulgado o trimestre correspondente. Confira a competência e a origem em cada tela.",
        ("ifdata", "scr", "statements")),
)


MODULE_GUIDES = (
    ModuleGuide("Snapshot", "Consultar o retrato de uma instituição na data-base e suas variações.",
        ("ifdata", "ifdata_credit", "cosif_prudential"), "Os indicadores podem vir de relatórios distintos. Confira o denominador e o motivo de eventuais lacunas."),
    ModuleGuide("Rankings", "Localizar a posição das instituições em um indicador e comparar sua evolução.",
        ("ifdata", "ifdata_credit"), "A lista reflete os filtros e as instituições com dado disponível, com modelos de negócio possivelmente diferentes."),
    ModuleGuide("Peers (Tabela Nova)", "Comparar um conjunto escolhido de instituições por métricas de capital, carteira, resultado e captação.",
        ("ifdata", "ifdata_credit", "cosif_prudential"), "Escolha pares com porte, atividade, período e perímetro comparáveis. Veja as regras de cada razão."),
    ModuleGuide("Conselho e Diretoria", "Consultar cargos e vínculos de administradores disponíveis no BCB.",
        ("registry",), "A consulta cadastral não reconstitui toda a história de mandatos e decisões."),
    ModuleGuide("Evolução", "Acompanhar a trajetória dos indicadores de instituições selecionadas.",
        ("ifdata",), "Considere aquisições, alterações de grupo e as quebras contábeis de 2025 ao ler crescimentos e mudanças de nível."),
    ModuleGuide("Scatter Plot", "Comparar instituições em dois indicadores e localizar diferenças no conjunto.",
        ("ifdata", "ifdata_credit"), "Uma associação visual requer examinar período, cobertura, porte e composição dos negócios."),
    ModuleGuide(DRE, "Examinar o resultado e a abertura gerencial nos recortes individual ou prudencial.",
        ("ifdata",), "A tela consulta o BCB por competência e perímetro e identifica eventual recuperação de base validada. Confira o leiaute e a janela acumulada."),
    ModuleGuide(STATEMENTS, "Consultar demonstrações individuais e comparar até duas competências do documento 9011.",
        ("statements",), "As unidades, referências e demonstrações dependem do documento enviado pela instituição."),
    ModuleGuide(COSIF, "Pesquisar contas contábeis e comparar os saldos ou fluxos por instituição, na visão individual ou prudencial.",
        ("cosif_4010", "cosif_prudential"), "Confira documento, natureza da conta e meses usados no cálculo. A visão individual mantém os saldos por CNPJ-base."),
    ModuleGuide(PORTFOLIO, "Examinar carteiras de instrumentos, inadimplência, ativos problemáticos e provisões a partir de 2025.",
        ("ifdata_credit", "ifdata"), "Carteiras C1 a C5 e estágios contábeis são classificações distintas. As células marcadas têm diagnóstico de validação."),
    ModuleGuide(STATISTICS, "Acompanhar o mercado de crédito por séries SGS e detalhar inadimplência por região e perfil no SCR.data.",
        ("sgs", "scr"), "SGS e SCR.data têm conceitos próprios. A visão regional de série completa oferece menos aberturas que a base detalhada."),
    ModuleGuide(RATES, "Comparar taxas médias observadas por instituição, produto e janela de contratação.",
        ("rates",), "A visão mensal usa a última observação de cada mês. Verifique a unidade da taxa e as janelas de cada instituição."),
    ModuleGuide(PAYMENTS, "Acompanhar transações, valores, canais, cartões, tarifas e infraestrutura de pagamentos.",
        ("payments",), "Os instrumentos cobertos e os denominadores de participação mudam entre as bases mensal e trimestral."),
    ModuleGuide("Atualizar Base", "Consultar o estado das bases, extrair novas competências e publicar dados do app.",
        ("ifdata", "cosif_4010", "cosif_prudential", "scr", "sgs", "rates", "payments"),
        "A frequência da fonte, a extração local e a publicação são etapas diferentes. O diagnóstico informa o que cada base efetivamente contém."),
)


def all_terms() -> tuple[GlossaryTerm, ...]:
    """Resolve definições compartilhadas sem criar uma segunda regra de cálculo."""
    result = []
    for term in TERMS:
        if term.metric_key:
            metric = get_metric_definition(term.metric_key)
            if metric is None:
                raise ValueError(f"Métrica do glossário sem registro: {term.metric_key}")
            term = replace(term, title=metric.display_name, definition=metric.short_definition,
                           formula=metric.formula, unit=metric.unit)
        result.append(term)
    return tuple(result)


def technical_details(term: GlossaryTerm) -> dict[str, str]:
    details = {"Fórmula / regra": term.formula, "Unidade": term.unit}
    if term.metric_key:
        metric = get_metric_definition(term.metric_key)
        if metric is not None:
            details.update({
                "Fórmula / regra": metric.formula,
                "Unidade": metric.unit,
                "Periodicidade": metric.periodicity,
                "Fonte do indicador": metric.source_label,
                "Campos / contas": "; ".join((*metric.ifdata_fields, *metric.cosif_accounts)),
                "Quando fica N/D": metric.null_policy,
                "Detalhe metodológico": metric.long_definition,
                "Observações": metric.observations,
            })
    return {key: value for key, value in details.items() if value}


def normalize_search(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return " ".join(re.findall(r"[a-z0-9]+", text))


def matches_query(query: str, *texts: str) -> bool:
    tokens = normalize_search(query).split()
    haystack = normalize_search(" ".join(texts))
    return all(token in haystack for token in tokens)


def search_terms(query: str = "", topic: str = "Todos os temas") -> tuple[GlossaryTerm, ...]:
    matches = []
    for term in all_terms():
        if topic != "Todos os temas" and term.topic != topic:
            continue
        source_text = " ".join(SOURCE_BY_KEY[key].name for key in term.sources)
        if matches_query(query, term.title, term.definition, term.caution, term.example,
                         term.topic, source_text, *term.aliases, *term.modules,
                         *technical_details(term).values()):
            matches.append(term)
    # Títulos e siglas precedem resultados em que a expressão só aparece na ressalva.
    if normalize_search(query):
        matches.sort(key=lambda term: (not matches_query(query, term.title, *term.aliases), term.title.casefold()))
    else:
        matches.sort(key=lambda term: term.title.casefold())
    return tuple(matches)
