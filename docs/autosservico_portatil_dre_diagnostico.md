# Diagnóstico do aviso da DRE Individual

O aviso observado na seleção padrão de `321 SOCIEDADE DE CRÉDITO DIRETO S.A.` (`CodInst 54647259`) é produzido pela linha **Desp. JSCP Cooperativas**, em mar/26 e jun/26. O recorte local reproduziu as funções atuais do aplicativo e encontrou 52 verificações aprovadas e duas classificadas como erro. As duas têm valor bruto e YTD ausentes; não houve diferença aritmética calculável.

O mapeamento de `data/dre_mapping.json` declara a fonte antiga `Juros Sobre Capital Social de Cooperativas (k)`, a fonte nova `Despesas de Juros Sobre Capital Próprio de Cooperativas (r)` e uma lista `sources_new_q4` vazia. Essa lista explícita faz o resolver deixar a linha sem valor em dez/2025 e em todo o ano de 2026. A coluna nova também está ausente do bundle individual examinado.

A linha permanece na tabela porque os registros de set/24 e dez/24 contêm zero para a fonte antiga. O builder descarta uma linha somente quando todos os valores de todo o recorte histórico estão ausentes. Ao validar mar/26 e jun/26, a regra `mar_jun_sem_soma_sem_anualizacao` exige uma diferença numérica entre bruto e YTD; quando ambos são ausentes, classifica o resultado como `erro`. A tela emite o aviso sempre que alguma verificação tem status diferente de `OK`.

Isso identifica uma lacuna de fonte ou de aplicabilidade que o mapeamento e o validator atuais não distinguem. O recorte não permite concluir se a despesa deveria existir para essa SCD, ser zero ou ser marcada como não aplicável. Nenhum valor foi preenchido e nenhuma fórmula, mapeamento, validação ou tela foi alterada.

A identidade **Resultado de Intermediação Financeira Bruto = soma das cinco receitas componentes** passou em ambos os períodos. Esse resultado não constitui uma auditoria de toda a DRE ou das demais instituições.

## Evidência e limites

- Fonte: bundle local `data/bundled/dre_individual/dados.parquet`, oito registros de set/24 a jun/26 para o código selecionado. O DataFrame usado continha 87 colunas, incluindo `ano` e `mes` acrescentados pela preparação existente.
- Execução: funções extraídas de `app1.py` por AST e executadas sem importar o aplicativo inteiro; mesmas regras de agrupamento, mapeamento, YTD, períodos padrão e validator.
- Resultado: 52 linhas YTD nos dois períodos selecionados; 54 verificações, com 52 `OK` e dois `erro`, ambos em **Desp. JSCP Cooperativas**.
- Recursos: 1,141 segundo, pico de 272,0 MiB, guarda de 768 MiB e 45 segundos; nenhuma tentativa de rede e nenhuma gravação de dados.
- O bundle, o mapeamento e as funções relevantes preservam a identidade registrada com o baseline anterior à atualização das bases. A reprodução confirma a causa no recorte local. A sessão pública original não foi reexecutada com a versão antiga.
- Evidência externa ao código: `outputs/publicacao-atualizacao-bases-2026-10-10/etapa2/dre-individual-diagnostico.json`, no checkout primário de trabalho.

Uma revisão posterior pode definir como distinguir ausência de fonte, não aplicabilidade e diferença numérica na validação. Essa decisão precisa preservar a ausência de dado e verificar o layout publicado pelo Banco Central antes de modificar o comportamento financeiro.
