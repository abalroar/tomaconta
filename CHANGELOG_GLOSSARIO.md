# CHANGELOG_GLOSSARIO

Data: 2026-04-04

## Decisões do usuário (Etapa 4)
1. ROE: manter dois verbetes canônicos:
   - ROE Ac. Anualizado (%)
   - ROE Trim. Anualizado (%)
2. Duplicatas textuais: consolidar para um verbete canônico por métrica, preservando histórico em comentário no código.
3. Métricas de capital ausentes no glossário central: adicionar IRRBB e Razão de Alavancagem.
4. Variáveis com exibição incerta: mover para seção “Definições históricas / não exibidas por padrão”.
5. Nome canônico: “Carteira de Crédito Bruta”, com alias “Carteira de Crédito* (Peers)”.

## Verbetes adicionados
- Razão de Alavancagem
- IRRBB
- ROE Trim. Anualizado (%)
- Seção de legado com tags `[LEGADO — verificar se ainda aplicável]`:
  - Crédito/Ativo (%)
  - Carteira de Crédito/Core Funding (%)
  - Passivo Exigível
  - Títulos e Valores Mobiliários (TVM)

## Verbetes atualizados (antes × depois)
- Core Funding: removida duplicidade textual e unificado critério de 2025+.
- Perda Esperada: removida duplicidade textual e consolidada em um verbete canônico.
- Depósitos Totais: removida duplicidade textual e consolidada em um verbete canônico.
- Carteira de Crédito Bruta / Carteira de Crédito*: canônico definido como “Carteira de Crédito Bruta”, mantendo alias contextual da aba Peers.
- Índices de capital e rentabilidade: padronizados com campos fixos (Aba, Fonte, Fórmula, Unidade, Interpretação, Limitação, Periodicidade).

## Verbetes marcados como LEGADO
- Crédito/Ativo (%)
- Carteira de Crédito/Core Funding (%)
- Passivo Exigível
- Títulos e Valores Mobiliários (TVM)

## Observações
- Foi preservado comentário no código com referência à versão anterior do glossário para rastreabilidade (`# [VERSÃO ANTERIOR]`).
- Não foram alteradas outras abas além da aba Glossário (bloco `elif menu == "Glossário":`).

## Ajuste pós-review (resgate de conteúdo histórico)
- Reincorporadas explicações narrativas que existiam antes da reestruturação:
  - Contexto de Conglomerado Prudencial
  - Exemplos (PAN/BTG, Digio/Bradesco, consolidado do Original)
  - Justificativa de início da série principal em Mar/2015
- Mantida a estrutura temática nova, somando conteúdo antigo + conteúdo novo (sem remoção).

## Ajuste de usabilidade (tabelas por seção)
- Glossário reformulado para exibição em **tabelas por seção**:
  1) Capital e Regulação
  2) Balanço e Funding
  3) Rentabilidade e Eficiência
  4) Qualidade de Carteira
  5) Alavancagem e Relações de Estrutura
- Seção 6 movida para expander curto:
  - `Definições históricas / não exibidas por padrão`
