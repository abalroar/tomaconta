# Prompt mestre — tabulação comparativa CRI × FIDC Solfácil

> **O que é este arquivo.** O texto abaixo da linha é um prompt autocontido, para colar em uma
> sessão nova. Ele instrui a construção de dois entregáveis (workbook `.xlsx` + deck `.pptx`)
> comparando os FIDCs e os CRIs da Solfácil em dez dimensões estruturais.
>
> **Insumos verificados na rodada de elaboração (21–22/08/2026):**
> - Deck interno de 34 slides (`Solfacil_Definitivo_draft.pptx`) — universo de 7 FIDCs com CNPJs,
>   6 operações de CRI / 34 séries, ~R$ 3,67 bi nominais.
> - `INICIO_SOLFACIL_29092025_V005.pdf` — Anúncio de Início da 4ª emissão Kanastra: 7 séries
>   (1 privada + 6 públicas), R$ 436,5 mi públicos, camadas Super Sênior A/B, Sênior A/B, Mezanino,
>   Subordinado; Itaú BBA (líder), Bradesco BBI e XP; Oliveira Trust como agente fiduciário;
>   Moody's AAA/AAA/AA−/AA−; classificação ANBIMA "pulverizado, máx. 20% por devedor"; título verde.
>
> **Decisões de escopo tomadas com o solicitante:** entregar `.xlsx` **e** `.pptx`; tratar o deck
> interno e as fontes públicas com peso probatório igual, explicitando conflitos; prompt único em
> português com schema completo de colunas.
>
> **Ambiente do repositório:** `openpyxl 3.1.5`, `XlsxWriter`, `python-pptx 0.6.23` e `pandas`
> disponíveis. Não há `pypdf` nem `poppler` instalados.

---

# Tabulação comparativa dos CRIs e FIDCs da Solfácil — Excel + deck

## 0. Papel e resultado esperado

Você é analista sênior de crédito estruturado. Produza dois entregáveis que contam a mesma história
com os mesmos números:

1. `outputs/solfacil/Solfacil_CRI_FIDC_<AAAAMMDD>.xlsx` — workbook analítico, todas as tabelas como
   tabelas nativas do Excel, gráficos nativos, legível por quem não é de renda fixa.
2. `outputs/solfacil/Solfacil_CRI_FIDC_<AAAAMMDD>.pptx` — deck curto (12–16 slides) que resume o
   workbook.
3. Camada de dados auditável em `data/solfacil/*.csv` — **o Excel e o PPTX são gerados a partir dela,
   nunca digitados à mão**. Um número que não estiver num CSV não pode aparecer em nenhum entregável.

Branch de trabalho: `claude/cris-fidcs-solfacil-analysis-qr0g0r`. Commit e push ao final. Sem PR.

Ambiente: `openpyxl`, `XlsxWriter`, `python-pptx`, `pandas` instalados. Não há `pypdf` nem `poppler`.

## 1. Universo a cobrir (ponto de partida, sujeito a confirmação)

**FIDCs (7):** Solfácil FIDC I a VII.
`I 36.771.685/0001-17 · II 42.462.306/0001-00 · III 49.920.525/0001-34 · IV 44.909.456/0001-44 ·
V 47.240.785/0001-33 · VI 57.028.406/0001-08 · VII 63.505.455/0001-89`

**Operações de CRI (6, 34 séries, ~R$ 3,67 bi):** Kanastra 1ª (15/01/2024), 2ª (25/06/2024),
3ª (28/05/2025), 4ª (28–29/09/2025), VERT 174ª (29/05/2026), VERT 177ª (31/07/2026).

Primeira tarefa: **confirmar que o universo está completo na data-base**. Procure FIDC VIII+ no cadastro
CVM e emissões de CRI Solfácil posteriores a 21/08/2026 (Kanastra, VERT e qualquer outra securitizadora).
Se encontrar, inclua. Se não encontrar, registre a busca feita — ausência confirmada é informação.

Data-base do trabalho: última competência disponível por veículo. Declare-a em cada aba; nunca misture
competências numa mesma tabela sem coluna de data-base.

## 2. Fontes e tratamento de conflito

Fontes obrigatórias, todas com o **mesmo peso probatório**:

| Fonte | O que extrair |
|---|---|
| CVM — Cadastro de Fundos | CNPJ, situação, início, administrador, gestor, custodiante |
| CVM — Informe Mensal FIDC | PL, carteira, PDD, aging por faixa, cotas por classe, emissões/amortizações |
| CVM — Informe Mensal CRI | saldo devedor, PDD, amortização e juros pagos por série |
| CVM — Fundos.NET | regulamentos, suplementos, termos de securitização, aditamentos, prospectos |
| CVM — Ofertas públicas | volume registrado, subscritores por tipo, encerramento |
| ANBIMA Data | taxas indicativas, estoque, classificação de mercado |
| Vórtx / Oliveira Trust / agentes fiduciários | relatórios mensais e anuais, notificações, PU |
| Kanastra / VERT (páginas de documentos das emissões) | termos consolidados, curvas |
| Anexos desta conversa | deck de 34 slides; Anúncio de Início da 4ª emissão Kanastra |

Regra de conflito — **explícita, nunca silenciosa**: quando duas fontes divergirem sobre o mesmo campo
(inclusive deck × documento público), registre as duas na aba `Conflitos` com valor, fonte, data-base e
a decisão adotada com uma frase de justificativa. O valor adotado entra nas demais abas com marcação
`conflito=sim`. Divergências conhecidas para testar de saída: número de séries e volume da 4ª emissão
Kanastra (deck: 7 séries / R$ 450,0 mi × Anúncio de Início: 6 séries públicas / R$ 436,5 mi + privada);
datas de emissão 28/09 × 29/09/2025.

Toda linha de dado carrega `fonte_id`. A aba `Fontes` mapeia `fonte_id → documento, URL, data de acesso,
data-base, trecho/página`. Sem `fonte_id`, a linha não entra.

## 3. Regras de integridade — não negociáveis

- `n/d` **nunca** vira 0, média, nem "aproximadamente". Campo ausente é `n/d` e conta como lacuna.
- Todo campo tem status: `Documentado` (consta em documento) · `Inferido` (deduzido — exige nota de
  método na própria linha) · `n/d`.
- **Limite contratual ≠ praticado.** "Preço de aquisição ≤ 104% do saldo contábil" é teto; o preço
  efetivo é `n/d`. Colunas separadas, sempre.
- Todo percentual carrega o denominador no nome da coluna (`pdd_pct_carteira`, não `pdd_pct`).
- Datas em `AAAA-MM-DD`. Valores em R$ com unidade no cabeçalho (`R$ mi`). Prazos em dias **e** meses.
- Proibido inventar ISIN, rating, taxa, titular ou competência não publicada. Proibido extrapolar
  tendência para competência não divulgada.
- Quando a análise não for possível com dado público, escreva o que falta e a quem pedir — não preencha.

## 4. Estrutura do workbook

Padrão de todas as abas: linha 1 = título da aba; linha 2 = **uma leitura em português claro, no máximo
duas frases**; linha 3 = data-base e fontes; linha 5 em diante = tabela nativa (`ListObject`) nomeada
`tbl_<aba>`. Congelar painéis abaixo do cabeçalho. Sem células mescladas na área de dados.

**`00_Painel`** — 8 a 10 indicadores-chave, o mapa do programa (originação → warehouse FIDC → take-out
CRI → investidores), e o índice clicável das abas. Nada de números que não apareçam detalhados adiante.

**`01_Veiculos`** — uma linha por veículo (7 FIDCs + 6 CRIs).
`veiculo_id · tipo (FIDC/CRI) · nome · cnpj_ou_emissora · securitizadora · data_inicio_ou_emissao ·
situacao · administrador · gestor · custodiante · agente_fiduciario · auditor · agencia_rating ·
pl_ou_saldo_R$mi · carteira_R$mi · data_base · fonte_id`

**`02_Series`** — a espinha dorsal: uma linha por **cota de FIDC e por série de CRI** (as 34 séries de CRI
+ todas as classes/subclasses dos 7 fundos). Dimensão (ii).
`veiculo_id · camada (Super Sênior A/B, Sênior A/B, Mezanino A/B, Júnior/Subordinada) · serie · isin ·
data_emissao · data_vencimento · prazo_meses · montante_emitido_R$ · montante_subscrito_R$ ·
saldo_atual_R$ · pct_da_emissao · indexador (Pré/DI+/DI%/IPCA+) · taxa_contratada · pu_atual ·
rating_agencia · rating_nota · colocacao (pública/privada) · retida_pelo_originador (sim/não/n/d) ·
data_base · fonte_id · status`

**`03_Elegibilidade`** — dimensão (i). Uma linha por veículo, colunas de critério, para que a comparação
FIDC × CRI seja horizontal e literal.
`veiculo_id · adimplencia_na_cessao · seasoning_minimo_meses · idade_maxima_devedor · prazo_max_recebivel_dias ·
prazo_max_recebivel_meses · wam_max_dias · ticket_max_PF_R$ · ticket_max_PJ_R$ · tipos_de_ativo (CCB PF/PJ,
CPR-F) · carencia_max_dias · preco_max_aquisicao_pct_saldo · quem_atesta_elegibilidade · restricao_geografica ·
restricao_score · vedacoes_expressas · redacao_literal (citação curta) · fonte_id · status`
Inclua linha derivada `Δ FIDC→CRI` por par cedente/cessionário mostrando qual critério aperta e quanto.

**`04_Concentracao`** — dimensão (vi).
`veiculo_id · cap_individual_pct · cap_top10_pct · cap_por_devedor_ANBIMA_pct · cap_por_integrador ·
cap_por_UF · cap_PJ_pct · cap_por_safra · concentracao_observada_individual · concentracao_observada_top10 ·
folga_vs_limite_pp · data_base · fonte_id`

**`05_Prazos_WAM`** — dimensões (v) e (viii), e a resposta ao descasamento de prazo.
`veiculo_id · wam_contratual_max_dias · wam_observado_dias · prazo_medio_recebivel_meses ·
prazo_max_recebivel_meses · vencimento_do_veiculo · prazo_do_veiculo_meses · duration_serie_mais_longa ·
gap_ativo_passivo_meses · periodo_revolvencia_meses · inicio_amortizacao · fonte_id`
Gráfico nativo de barras horizontais: recebível × FIDC × cada série de CRI, na mesma escala de meses.

**`06_Waterfall`** — dimensão (iv). Ordem de pagamentos linha a linha, comparável entre veículos.
`veiculo_id · regime (pró-rata/target/sequencial/revolvência) · ordem_1..ordem_n (descrição de cada degrau) ·
gatilho_de_mudanca_para_sequencial · quem_recebe_juros_antes_de_principal · super_senior_prioridade ·
senior_prioridade · mezanino_prioridade · junior_prioridade · cash_sweep (sim/não) ·
reserva_de_despesas · reserva_de_juros · reserva_MTM · fonte_id`
Aba complementar **`06b_Waterfall_Visual`**: diagrama em células (blocos coloridos) dos dois regimes lado a
lado — pró-rata condicionado × sequencial pós-evento. Sem SmartArt, sem imagem colada.

**`07_Subordinada`** — pode a subordinada ser sacada e o que sobra para a sênior.
`veiculo_id · saque_permitido (sim/não) · quem_solicita · quem_autoriza · quorum · testes_exigidos ·
pisos_de_subordinacao_pct · indices_de_cobertura · trava_temporal · vedacoes_pos_evento ·
principal_subordinado_ja_pago_R$mi · primeira_ocorrencia · ultima_ocorrencia ·
subordinacao_antes_do_saque_pct · subordinacao_depois_pct · variacao_pp · fonte_id`
Coluna calculada `impacto_na_senior`: attachment point da sênior antes e depois de cada saque observado,
com fórmula visível na aba `Metodologia`.

**`08_PDD`** — dimensão (vii). Matriz veículo × faixa de atraso.
`veiculo_id · ate_15d · 16_30d · 31_60d · 61_90d · 91_120d · 121_150d · 151_180d · acima_180d ·
base_de_incidencia (saldo integral da CCB × parcelas vencidas) · efeito_vagao/arrasto (sim/não/n/d) ·
tratamento_do_dia_181 · pdd_adicional_discricionaria · pdd_observada_pct_carteira ·
saldo_90d_pct_carteira · razao_pdd_sobre_90d · fonte_id`
A coluna `efeito_vagao` é obrigatória e explicada em uma frase: se a provisão incide sobre o saldo
integral do contrato ou só sobre a parcela vencida — é ela que explica PDD/>90d acima de 100%.

**`09_Eventos`** — dimensão (ix). Uma linha por evento, por veículo.
`veiculo_id · tipo (Avaliação · Liquidação Antecipada · Amortização Antecipada · Desalavancagem ·
Vencimento Antecipado do CRI · Resgate Compulsório) · descricao_do_gatilho · parametro_numerico ·
consequencia_automatica · quorum_de_dispensa · prazo_de_cura · ja_ocorreu (sim/não) ·
data_da_ocorrencia · fonte_id`
Inclua os gatilhos quantitativos comparáveis: piso de subordinação, índice de cobertura, PDD máxima,
inadimplência máxima, queda de rating em N níveis, descumprimento de índices do originador, troca de
controle, insolvência do cedente/servicer.

**`10_Subscritores`** — dimensão (iii).
`veiculo_id · serie · qtd_cotistas_PF · qtd_fundos · qtd_IFs · qtd_outras_PJ · qtd_total ·
ticket_medio_R$ · pct_distribuido_varejo · coordenadores · titulares_atuais (n/d se não público) ·
concentracao_maior_titular · fonte_da_posicao · data_base · fonte_id`
Separe **distribuição na emissão** (público, via CVM/ofertas) de **posição corrente** (em geral `n/d`).
Não confunda as duas — é o erro mais comum nesse tipo de tabela.

**`11_Matriz_FIDC_CRI`** — dimensão (x). Matriz 7 FIDCs (linhas) × 6 CRIs (colunas), com três estados:
- `Cedeu` — com data, volume cedido e fonte;
- `Pode ceder` — o mandato do FIDC permite originar ativo que passa nos critérios daquele CRI (deduzido do
  cruzamento da aba `03_Elegibilidade`: prazo, WAM, ticket, concentração, tipo de ativo);
- `Não elegível` — com o critério que bloqueia, nomeado.
Tabela longa auxiliar `11b_Cessoes` com uma linha por cessão documentada:
`data · fidc_cedente · cri_cessionario · volume_R$mi · pct_do_pool_do_CRI · preco_pct_saldo (n/d se não
divulgado) · cessao_direta_do_originador (sim/não) · fonte_id`

**`12_Custo_Captacao`** — o custo de todos, marcado a hoje.
`veiculo_id · serie · saldo_atual_R$ · indexador · taxa_contratada · taxa_equivalente_CDI_hoje ·
taxa_equivalente_pre_hoje · spread_sobre_DI_bps · custo_ponderado_da_camada`
Depois, por veículo: `custo_medio_ponderado_das_cotas_publicas · custo_da_subordinada (residual, marcar
n/d se não apurável) · custos_fixos_anualizados_bps (administração, gestão, custódia, auditoria, rating,
agente fiduciário, escrituração, distribuição amortizada) · custo_all_in_bps · fonte_id`
Fechamento: comparação **all-in FIDC × all-in CRI** na mesma métrica, com uma frase honesta sobre o que a
comparação não captura (preço de cessão, hedge, capital retido).

**`13_Cronograma_Pagamentos`** — a "morte" das estruturas ao longo do tempo.
Uma linha por `serie × mês`: `veiculo_id · serie · competencia · saldo_inicial · juros_programados ·
amortizacao_programada · saldo_final · juros_pagos_realizado · amortizacao_paga_realizada ·
status (Realizado/Projetado) · fonte_id`
Realizado vem dos informes mensais; projetado, das curvas contratuais dos termos. **Nunca misturar os dois
sem a coluna `status`.** Gráfico nativo de área empilhada por camada (Super Sênior → Sênior → Mezanino →
Júnior) mostrando o saldo caindo mês a mês, um gráfico por operação de CRI e um consolidado.

**`14_Antes_Depois`** — o take-out mudou o perfil do FIDC?
Por evento de cessão, competências t−3 a t+3 do FIDC cedente:
`fidc · competencia · mob · pl_R$mi · carteira_R$mi · pdd_pct_carteira · saldo_90d_pct_carteira ·
wam_observado · ticket_medio · subordinacao_pct · evento (cessão em t=0)`
Gráfico de linha com marcador na data da cessão. Leitura obrigatória logo abaixo: o que os dados mostram e
o que **não** permitem afirmar (sem tape por CCB não se separa cherry-pick de mudança de denominador).

**`15_FIDC_vs_CRI`** — a visão honesta pedida. Uma linha por dimensão comparada, três colunas de veredito:
`dimensao · como_funciona_no_FIDC · como_funciona_no_CRI · vantagem_real (FIDC/CRI/neutro) ·
evidencia · o_que_falta_para_confirmar`
Dimensões: velocidade de originação, prazo do passivo, risco de rollover, custo, base de investidores,
granularidade exigida do pool, retenção de risco pelo originador, flexibilidade de revolvência, custo fixo
por veículo, transparência pós-emissão.

**`16_Conflitos`** · **`17_Fontes`** · **`18_Metodologia`** · **`19_Glossario`**
`18_Metodologia`: fórmula de cada métrica calculada (WAM, subordinação, attachment, custo all-in,
equivalência de taxas, folga ao piso) com uma linha de qualificador cada.
`19_Glossario`: 15–20 termos em português direto — waterfall, pró-rata, sequencial, attachment point,
efeito vagão, seasoning, take-out, warehouse, cash sweep, MTM, cota subordinada. Uma frase por termo, sem
definir jargão com jargão.

## 5. Perguntas que os entregáveis precisam responder de forma direta

Cada uma tem endereço fixo. Se o dado público não permitir responder, escreva **por que** e o que falta.

1. **Descasamento de prazo** (`05`): se o recebível médio é de ~50 meses, quantos anos tem o FIDC e quantos
   anos tem cada CRI? Mostre os três na mesma escala e explique quem carrega o risco de refinanciamento.
2. **Seleção do pool** (`03` + `11`): como cada CRI escolhe os recebíveis que compra — critério a critério,
   com a redação literal. Diga explicitamente se algum exige safra performada, MoB mínimo ou histórico de
   inadimplência do lote.
3. **Antes × depois do take-out** (`14`): a inadimplência e a qualidade do FIDC mudaram após as cessões?
4. **Saque da subordinada** (`07`): em algum caso a cota subordinada — que é da originadora — pode ser
   sacada deixando a sênior menos protegida? Quais testes, qual quórum, quais travas, e o que já ocorreu.
5. **Pró-rata** (`06` + `07`): quando o pagamento é pró-rata, quando vira sequencial, e sob que condições a
   subordinada sai antes do fim.
6. **Curva de morte** (`13`): gráfico da amortização programada e realizada por camada ao longo do tempo.
7. **Custo de captação hoje** (`12`): quanto custa cada estrutura, all-in, na mesma unidade.
8. **Matriz de cessão** (`11`): quais FIDCs já cederam e quais podem ceder para quais CRIs.

## 6. Métodos de cálculo obrigatórios

- **WAM**: distinga o teto contratual (ex.: 2.400 dias) do prazo médio ponderado observado. Nunca reporte um
  como se fosse o outro.
- **Equivalência de taxas**: para comparar Pré, DI+, %DI e IPCA+ na mesma régua, converta tudo para spread
  sobre DI na data-base usando a curva DI futura (B3) e a inflação implícita (NTN-B) daquela data. Registre a
  curva usada, a data e a fonte na aba `18_Metodologia`. Sem a curva, marque `n/d` — não estime de cabeça.
- **Custo all-in**: custo ponderado das cotas/séries públicas + custos fixos anualizados em bps sobre o PL
  médio. Se algum custo fixo não for público, some o que é conhecido e declare o que ficou de fora.
- **Attachment point**: (NAV mezanino + NAV júnior) / carteira bruta. Recalcule antes e depois de cada saque
  subordinado observado.
- **Folga ao piso**: `[Sub_NAV − piso × PL] / [1 − piso]`.
- **Efeito vagão**: sinalize quando `PDD / saldo >90d` ultrapassar 100% — é o indício de que a provisão
  incide sobre o saldo integral do contrato, não sobre a parcela vencida.

## 7. Design do Excel — o que fazer e o que não fazer

**Fazer:** toda tabela como `ListObject` com nome `tbl_*` e estilo único do arquivo · formatos numéricos
declarados (R$ com separador de milhar, % com uma casa, datas ISO) · larguras de coluna definidas ·
congelamento de painéis · gráficos **nativos** (`openpyxl.chart` / `xlsxwriter`), nunca imagens ·
paleta de uma cor neutra + dois acentos, no máximo · formatação condicional em no máximo três lugares do
arquivo inteiro, sempre com legenda · uma leitura em português claro no topo de cada aba.

**Não fazer:** células mescladas na área de dados · abas com mais de uma tabela sem separação clara ·
cores como decoração · ícones e semáforos espalhados · texto em caixa alta para ênfase · repetir a mesma
informação em três abas · frases de efeito ("estrutura robusta", "posicionamento privilegiado") ·
jargão sem tradução · qualquer número sem `fonte_id` rastreável.

## 8. Design do deck

`python-pptx`, 16:9, 12–16 slides, mesma paleta e mesmos números do workbook (lidos dos mesmos CSVs).
Um slide, uma ideia. Tabelas nativas do PowerPoint, nunca captura de tela do Excel. Rodapé de cada slide
com data-base e fonte. Sem bullets de terceiro nível. Sem slide de "destaques" genérico.

Roteiro sugerido: (1) capa com o universo em números · (2) mapa do programa · (3) linha do tempo das
emissões e take-outs · (4) tamanho por camada · (5) elegibilidade FIDC × CRI · (6) prazos na mesma escala ·
(7) waterfall nos dois regimes · (8) subordinada: quando pode sair · (9) PDD e efeito vagão ·
(10) concentração · (11) matriz FIDC→CRI · (12) curva de morte das estruturas · (13) custo all-in ·
(14) antes × depois do take-out · (15) vantagem real do CRI × FIDC, com o que ainda não dá para afirmar ·
(16) lacunas e o que pedir a quem.

## 9. Ordem de execução

1. **Inventário de fontes** — liste documento por documento, por veículo, com URL e status (obtido /
   não localizado). Só avance com o inventário fechado.
2. **Extração** para os CSVs de `data/solfacil/`, campo a campo, com `fonte_id` e `status`.
3. **Reconciliação** — rode as comparações deck × público, preencha `Conflitos`, decida cada caso.
4. **Cálculos** — as métricas derivadas da seção 6, em código, reproduzíveis.
5. **Build do `.xlsx`**.
6. **Build do `.pptx`** a partir dos mesmos CSVs.
7. **Validação** — checklist da seção 10.
8. **Commit e push** no branch `claude/cris-fidcs-solfacil-analysis-qr0g0r`, com o script de geração
   versionado em `tools/`.

Não pule para o build antes da camada CSV estar fechada. Se uma fonte não for acessível, registre e siga —
não pare a produção inteira por uma lacuna, e não a preencha por conta própria.

## 10. Checklist de aceite

- [ ] Todo número dos dois entregáveis rastreia até uma linha de CSV com `fonte_id`.
- [ ] Nenhum `n/d` foi substituído por zero, média ou estimativa.
- [ ] Divergência deck × fonte pública aparece em `Conflitos` com decisão justificada.
- [ ] As 34 séries de CRI e todas as classes dos 7 FIDCs estão em `02_Series`.
- [ ] As oito perguntas da seção 5 têm resposta localizável, ou a lacuna nomeada.
- [ ] Toda tabela é `ListObject` nomeado; nenhum gráfico é imagem.
- [ ] Limites contratuais e valores praticados estão em colunas separadas.
- [ ] `13_Cronograma_Pagamentos` distingue Realizado de Projetado em toda linha.
- [ ] O glossário cobre todo jargão usado; nenhum termo é definido com outro jargão.
- [ ] Excel e PPTX não se contradizem em nenhum número.
- [ ] `18_Metodologia` traz a fórmula e o qualificador de cada métrica calculada.
- [ ] A aba `15_FIDC_vs_CRI` diz onde o CRI de fato ganha, onde não ganha, e o que não dá para afirmar
      com dado público.
