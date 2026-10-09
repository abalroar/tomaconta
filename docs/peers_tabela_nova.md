# Peers (Tabela Nova)

Peers (Tabela Nova) é a única tabela de comparação de peers no menu. A tela antiga, seus exportadores e suas rotinas exclusivas de grupos foram removidos. A aba Evolução, os cálculos compartilhados e os produtores dos caches permanecem disponíveis.

## Consulta e interface

- Grupo inicial de três bancos, com identidade e ordem explícitas por base: conglomerados prudenciais ou bancos comerciais individuais.
- Até três competências, exibidas cronologicamente dentro de cada instituição.
- Variação contra trimestre anterior, mesmo trimestre do ano anterior ou sem variação. Percentuais variam em pontos percentuais; valores monetários, em percentual; múltiplos, em x.
- Cabeçalho completo (Indicador, instituições e competências): fundo laranja #EC7000 e texto branco. Corpo branco, fontes e espaçamentos compactos.
- Verde representa aumento; vermelho representa queda. A cor descreve a direção, sem julgar o indicador.
- Downloads sob os filtros. A geração ocorre no clique, sem etapa de preparar arquivos.
- Clique no nome do indicador abre seu cálculo; outro clique troca a seleção ou fecha o cálculo. Componentes e metodologia ficam em expanders.
- Uma consulta fechada com valores, referência, status, fonte, identidade do cache e hash dos dados sustenta os quatro formatos de exportação.

## Fórmulas e lacunas

O catálogo está em `utils/peers_table_model.py`. A nova aba mantém a fonte e os componentes usados pelo cache, com estas regras próprias:

- Custo de crédito: **−resultado f3 YTD anualizado / carteira ampliada**. Despesa líquida é positiva; resultado líquido positivo em f3 produz custo negativo. A relação custo/receita usa o resultado f3 YTD e receita YTD positiva. O denominador ampliado é uma proxy.
- A linha legada “Perda Esperada” é exibida como **Perdas e ajustes contábeis**, pois seu agregado inclui hedge e valor justo. Os índices relacionados recebem a mesma descrição.
- ROE é identificado como anualizado. Lucro YTD e ROE do segundo semestre exigem a base de junho para recomposição.
- Ativos líquidos exigem os três componentes. Ausência de componente mantém N/D.
- Lucro YTD não recebe variação contra o trimestre anterior, devido à diferença de janelas. Denominador monetário de referência não positivo mantém a variação indisponível.
- Comparações de carteira ampliada, core funding e razões selecionadas que atravessam a mudança de definição de 2025 marcam os valores afetados com asterisco e apresentam o motivo na nota de rodapé.
- Registros duplicados por instituição/competência são rejeitados.

Essas regras afetam a consulta da nova aba; os arquivos analíticos existentes não são recalculados.

Na base individual, o padrão tem seis indicadores do Rel. 1: ativo, carteira de crédito, captações, PL, lucro e ROE. Carteira e captações usam as definições individuais. O ROE do cache individual usa o PL atual. Indicadores cujos componentes não estão nessa base permanecem N/D, com motivo explícito; não recebem dados de conglomerados.

## Exportações

- Excel: números e percentuais nativos, linhas de variação com cores, dados e status sem escala, metodologia e consulta.
- PowerPoint: tabelas Office nativas, três bancos por bloco e paginação equilibrada; gráficos nativos com workbook incorporado, períodos selecionados, lacunas preservadas, cores configuráveis e rótulo do último ponto válido em negrito e na cor da série.
- PNG: tabela branca com linhas de variação coloridas. Usa Calibri quando instalada no servidor; fallback para DejaVu Sans.

Os formatos incluem base, quantidade de instituições, competências, fonte, tipo e data da consulta. Office recebe Calibri explicitamente.

## Grupos e GitHub

`data/peer_groups_v2.json` é o arquivo compartilhado, com schema 2. Os integrantes são códigos estáveis e nomes de apresentação, separados por base. Renomear uma instituição não muda sua identidade; integrante ausente é informado ao usuário.

Grupos pessoais ficam na sessão e podem ser baixados/importados em JSON. Esse fluxo informa seu limite de persistência.

Para habilitar publicação de grupos compartilhados, configure `PEERS_GROUPS_ADMIN_KEY` nos secrets do Streamlit e uma credencial GitHub de escrita já reconhecida pelo aplicativo (`GITHUB_PAT`, `GH_TOKEN` ou `GITHUB_TOKEN`). A chave de administração não deve ficar no repositório. A publicação usa a revisão SHA do arquivo e confirma o conteúdo com uma nova leitura. Conflito ou falha de confirmação não produz mensagem de sucesso. A configuração usa `abalroar/tomaconta`, branch `main`.

Na ausência do arquivo remoto, os grupos iniciais vêm do arquivo incluído na aplicação. Falha de consulta remota fica indicada no expander dos grupos.

## Validação

Execute a suíte com o Python do projeto e `scripts/check_menu_dispatch_uniqueness.py`. Os testes da nova aba verificam sinal e unidades, lacunas, base de junho, quebra de definição, duplicidades, números nativos do Excel, cores, tabelas e gráficos nativos, fontes dos rótulos, identidade dos grupos, conflito e confirmação de leitura.

Faça a validação interativa com um navegador real: abrir a aba, alternar o cálculo, trocar a referência/base e baixar os arquivos. O AppTest do Streamlit 1.53 não cobre o componente bidirecional v2 usado pela tabela. A inspeção visual dos arquivos deve incluir PowerPoint, especialmente séries com valores finais próximos.
