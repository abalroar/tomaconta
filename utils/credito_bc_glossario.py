"""Textos do glossário de Crédito BC compartilhados pela tela e pelo PPTX."""

SGS_ROWS = (('Crescimento real em 12 meses', '(Xₜ / índice IPCAₜ) ÷ (Xₜ₋₁₂ / índice IPCAₜ₋₁₂) − 1', '%'),
 ('Variação de taxa/spread', 'xₜ − xₜ₋₁₂', 'p.p.'),
 ('Participação', 'componente ÷ total', '%'),
 ('Cobertura', 'provisão / carteira ÷ inadimplência / carteira', '%'),
 ('Pré-inadimplência', 'Operações com atraso entre 15 e 90 dias', '% da carteira'),
 ('Inadimplência', 'Operações com atraso superior a 90 dias', '% da carteira'),
 ('Comprometimento total', 'amortização do principal + juros', '% da renda'),
 ('Outros — mix PF/PJ',
  'resíduo entre o total e os produtos explicitamente classificados',
  '% da carteira'),
 ('Crédito em % do PIB',
  'aguarda validação da série mensal de PIB usada no workbook histórico',
  '% do PIB'),
 ('MPMe', 'receita bruta até R$ 300 milhões ou ativos totais até R$ 240 milhões', 'classificação'))

SCR_SECTIONS = (('##### Conceitos oficiais do SCR.data',
  '- **Carteira ativa:** soma dos valores a vencer e vencidos das operações abrangidas pelo SCR. '
  'Na visão regional, **Carteira (R$ bi)** é o total da carteira da modalidade na UF, '
  'independentemente de a operação estar inadimplente. É o denominador das taxas.\n'
  '- **Inadimplência:** carteira integral das operações com alguma parcela em atraso superior a 90 '
  'dias, dividida pela carteira de todas as operações.\n'
  '- **Ativo problemático:** carteira das operações classificadas como ativos problemáticos '
  'dividida pela carteira total. Desde 2025, o BCB considera a classificação informada pelas '
  'instituições na característica especial 19.\n'
  '- **Localização:** a UF decorre do CEP de residência da pessoa física ou da sede da pessoa '
  'jurídica.\n'
  '- **Participação da UF:** carteira ativa da UF dividida pela carteira ativa do Brasil, após os '
  'mesmos filtros de cliente e modalidade.'),
 ('##### Escopo, periodicidade e limites',
  'O BCB atualiza o relatório mensalmente, no último dia útil, com divulgação cerca de 30 dias '
  'após o fechamento. O documento 3040 cobre operações de crédito cursadas no país acima do limite '
  'de identificação do SCR: R$ 1 mil até mai/2016 e R$ 200 desde jun/2016. Saldos de dependências '
  'ou controladas no exterior ficam fora da publicação. Recortes com até 15 operações têm a '
  'contagem protegida; os valores monetários permanecem no agregado publicado.'),
 ('##### Comparabilidade',
  'Os totais podem divergir do IF.data, do COSIF e de outras estatísticas do BCB por diferenças de '
  'documento, cobertura, tolerância de remessa e tratamento de agregações com poucas operações. '
  'Para dados consolidados de crédito, o BCB orienta consultar a Nota para a Imprensa e o SGS.'))

SCR_SOURCES = '**Fontes oficiais:** [SCR.data](https://www.bcb.gov.br/estabilidadefinanceira/scrdata) · [Metodologia](https://www.bcb.gov.br/content/estabilidadefinanceira/scr/scr.data/scr_data_metodologia.pdf) · [Documento 3040](https://www.bcb.gov.br/estabilidadefinanceira/scrdoc3040)'

SGS_READING = '- **Cores:** a paleta de linhas tem cinco cores, todas com pelo menos 3:1 de contraste sobre o branco e distância perceptual (ΔE) acima de 27 entre si. Da sexta série em diante a cor repete e o **traço tracejado** passa a distinguir.\n- **Espessura:** linha grossa é a série em foco, tracejada é o agregado, fina é contexto.\n- **Rótulos:** tamanho único de 12 px, sempre na horizontal. Fatia de barra que não comporta o rótulo nesse tamanho fica sem rótulo — o valor continua no tooltip — em vez de receber um texto encolhido ou deitado.\n- **Competência:** o rodapé de cada card informa a última competência que aquele card efetivamente alcança, que nem sempre é a do seletor.'


def texto_criterios(latest_label: str, source: str) -> str:
    return (
        f"- **SGS:** Banco Central do Brasil · última observação no cache: "
        f"**{latest_label}** · origem do cache: **{source}**.\n"
        "- **SCR.data:** dados do documento 3040, operação a operação; "
        "podem divergir do IF.data e dos balancetes COSIF. Tem calendário de "
        "publicação próprio e costuma ficar um mês atrás do SGS.\n"
        "- **Localização SCR:** a UF vem do CEP do tomador.\n"
        "- **Porte SCR:** PF usa faixa de renda; PJ usa faturamento. Os critérios "
        "não devem ser combinados no mesmo eixo.\n"
        "- **Sigilo SCR:** contagens iguais ou inferiores ao limite de divulgação "
        "podem ser suprimidas pelo BCB."
    )


def _paragrafos(markdown: str) -> list[str]:
    return [linha.removeprefix('- ').replace('**', '').strip()
            for linha in markdown.splitlines() if linha.strip()]


def secoes_glossario_deck(latest_label: str, source: str) -> list[tuple]:
    """Lâminas curtas e editáveis, com o mesmo conteúdo do glossário da tela."""
    fonte = "Fonte: Banco Central do Brasil · BCData/SGS e SCR.data"
    secoes = []
    for inicio in range(0, len(SGS_ROWS), 5):
        texto = '\n\n'.join(
            f"{indicador} ({unidade}): {definicao}"
            for indicador, definicao, unidade in SGS_ROWS[inicio:inicio + 5]
        )
        secoes.append((f"Glossário · Indicadores SGS ({inicio // 5 + 1}/2)",
                       (texto, fonte), []))
    blocos = [("Leitura dos gráficos na tela", SGS_READING), *SCR_SECTIONS,
              ("Fontes e critérios de leitura", texto_criterios(latest_label, source))]
    for titulo, markdown in blocos:
        partes, atual = [], []
        for paragrafo in _paragrafos(markdown):
            if atual and len('\n\n'.join([*atual, paragrafo])) > 900:
                partes.append('\n\n'.join(atual))
                atual = []
            atual.append(paragrafo)
        if atual:
            partes.append('\n\n'.join(atual))
        for indice, texto in enumerate(partes, 1):
            sufixo = f" ({indice}/{len(partes)})" if len(partes) > 1 else ""
            nome = titulo.removeprefix('##### ')
            secoes.append((f"Glossário · {nome}{sufixo}", (texto, fonte), []))
    import re

    links = re.findall(r"\[([^]]+)\]\(([^)]+)\)", SCR_SOURCES)
    fontes_scr = "\n\n".join(f"{nome}: {url}" for nome, url in links)
    secoes.append(("Glossário · Fontes oficiais SCR.data", (fontes_scr, fonte), []))
    return secoes
