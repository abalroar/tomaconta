# Diagnóstico — IFs ausentes nos dropdowns das abas

## Resumo executivo
O aplicativo não usa uma lista única de instituições para todos os menus.
Cada aba monta o seu próprio dropdown com base no dataset que aquela aba carregou.

Isso faz com que IFs presentes no universo **BLOPRUDENCIAL** (mensal) não apareçam em abas que usam somente caches do **IFData** (trimestral) ou de relatórios específicos (ex.: DRE/Carteira 4.966).

## Evidências no código

### 1) A extração principal e outras abas usam IFData (TipoInstituicao=1) e recorte trimestral
A extração do IFData está configurada com `TIPO_INSTITUICAO = 1` e busca via endpoint `IfDataValores` (relatórios 1/2/3/4/5/11/13/16), que é um universo diferente do BLOPRUDENCIAL mensal.

### 2) As abas montam listas de instituições por dataset local da aba
- Em `Carteira 4.966`, as opções são construídas de `df_carteira['Instituição'].unique()`.
- Em `Evolução`, as opções são construídas de `df_ev['Instituição'].unique()`.

Na prática, se a IF não existir naquele dataframe da aba, ela não entra no dropdown.

### 3) A aba DRE já tem workaround específico
Na DRE, existe uma lógica explícita para combinar instituições do DRE com as do cache principal (com comentário citando DOCK), justamente para aparecer no dropdown mesmo sem dado no Relatório 4.

Ou seja: o próprio código já confirma que esse problema existe e foi tratado pontualmente só nessa aba.

## Por que ocorre com IFs como DOCK
- O universo que você listou vem de BLOPRUDENCIAL (mensal).
- Parte das abas depende do IFData trimestral e/ou de relatório específico.
- Se uma IF não tiver linha naquele dataset da aba (ou cache estiver defasado), ela não aparece no menu daquela aba.

## O que deve ser corrigido

1. **Unificar o catálogo de instituições para os dropdowns**
   - Criar uma função central para compor o "universo mestre" de IFs, unindo:
     - cache principal (Rel. 1),
     - DRE (Rel. 4),
     - Capital (Rel. 5),
     - Carteira 4.966 (Rel. 16),
     - BLOPRUDENCIAL (quando disponível).

2. **Separar 'lista de opções' de 'dados disponíveis no recorte'**
   - Dropdown mostra o universo mestre.
   - Após seleção, cada aba valida se há dados para a IF naquele relatório/período e exibe mensagem clara (em vez de sumir do menu).

3. **Padronizar normalização de nome/alias em um único ponto**
   - Reaproveitar a normalização já existente para evitar duplicidade de nomes e perdas por variação textual.

4. **Adicionar diagnóstico de cobertura por aba**
   - Exibir no UI algo como: "IF selecionada sem dados nesta aba para o período X".

## Impacto esperado após correção
- A mesma IF aparecerá de forma consistente nos dropdowns das abas.
- A ausência de dado passa a ser tratada como "sem dados para esta aba/período", e não como "IF inexistente".
