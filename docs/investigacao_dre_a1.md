# Investigação profunda — origem do `a1` e de-para DRE ↔ COSIF

## Pergunta investigada
Origem da linha **"Receita de Juros com Aplicações Interfinanceiras de Liquidez (a1)"** e como transformar a composição técnica em um mapeamento explicativo (com descrição) para uso operacional.

## Fontes usadas na investigação
1. Estrutura de mapeamento interna do projeto: `data/dre_cosif_mapping.json`.
2. Mapa de equivalência DRE nova × DRE antiga: `data/dre_mapping.json`.
3. Amostra local de balancete 4060 (Conglomerados Prudenciais e Instituições Independentes): `202509BLOPRUDENCIAL 2.CSV`.
4. Referência oficial COSIF (site BCB) para descrição textual das contas — nesta execução sem acesso direto por bloqueio de rede (`403`), então foi usada validação por evidência local.

## Achados

### 1) De onde vem o `a1`
- No desenho antigo da DRE (estrutura "letrada"), a família **(a)** era detalhada em subitens **(a1..a6)**.
- No repositório, esse histórico está explícito em `data/dre_mapping.json`, onde há o vínculo entre rótulos atuais e antigos.
- A solicitação recebida para **a1** (Receita de Juros com Aplicações Interfinanceiras de Liquidez) é compatível com esse modelo de subconta histórica.

### 2) Evidência operacional na base 4060
Na amostra `202509BLOPRUDENCIAL 2.CSV` aparecem as contas:
- `7140000004` (agregada)
- `7141000003` (renda com operações compromissadas)
- `7142000002` (renda com depósitos interfinanceiros)

Para instituições com as três linhas, observa-se coerência de composição entre conta agregada e detalhamento.

### 3) Conta `8115020001`
- A conta foi mantida no de-para conforme fórmula solicitada: `[7141000003] + [7142000002] + [8115020001]`.
- Ela **não aparece** na amostra local do 4060 analisada, então entrou como componente referenciado por fórmula IFData/COSIF e com observação explícita.

## Implementação feita
1. Atualizado `data/dre_cosif_mapping.json` para refletir o de-para da linha de aplicações interfinanceiras com granularidade de `a1`.
2. Criado gerador de planilha `tools/generate_dre_cosif_excel.py`.
3. Gerado arquivo de mapeamento simples em `data/dre_cosif_mapeamento_explicativo.csv` (coluna A: nome exato da linha na DRE; coluna B: contas COSIF/composição).
4. Gerada localmente a planilha final `data/DRE_COSIF_mapeamento_explicativo.xlsx` (artefato não versionado) com uma única aba `DRE_COSIF`, espelhando as colunas A/B do CSV.

## Limitação registrada
- Acesso HTTP direto aos domínios do BCB falhou nesta execução com `Tunnel connection failed: 403 Forbidden`.
- Resultado: descrição da conta `8115020001` foi preservada com anotação de origem por fórmula, pendente de conferência online quando o ambiente liberar conexão.
