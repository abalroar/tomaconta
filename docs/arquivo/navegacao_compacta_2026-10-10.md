# Navegação compacta — 10/10/2026

O cabeçalho reúne as 16 abas existentes em Instituições, Contábil e crédito, Mercado e Ajuda e dados. Em telas estreitas, um botão Menu abre a lista vertical com esses mesmos grupos. Os nomes das abas, aliases de URL e o callback compartilhado de navegação foram preservados.

A marca ocupa uma linha de 44 px. Os botões têm área mínima de toque de 44 px; a seleção recebe fundo azul claro e o foco de teclado é visível. A lista permite rolagem e o popover fecha após selecionar uma aba. O cabeçalho alterna sua posição de bloco após a seleção para desmontar o popover nativo: mudar apenas a chave do container não reinicia seu estado de abertura no Streamlit 1.53.1.

## Validação

- Suíte completa: 1.171 testes aprovados, com 14 avisos de depreciação existentes.
- Dispatcher: nenhum rótulo duplicado.
- AppTest: seleção nas versões desktop e móvel, com preservação do estado de instituições e da base Individual no callback.
- Navegador: larguras de 360, 390, 768, 844, 900, 950 e 1.280 px, incluindo janela baixa de 844 × 390. Cabeçalho sem transbordamento horizontal; controles visíveis com 44 px.
- Quatro popovers conferidos com seus 16 destinos; abertura por Enter e fechamento por Escape.
- Safari em iPhone real, por espelhamento autorizado pelo usuário: abertura de Menu, nomes completos, rolagem interna até Ajuda e dados, seleção de Glossário e Tabela de Peers e fechamento automático. A versão final foi conferida novamente após ajustar alinhamento e destaque da seleção.

A conferência do iPhone usou uma instância local temporária acessível na rede. A verificação pública ocorre separadamente após o merge.
