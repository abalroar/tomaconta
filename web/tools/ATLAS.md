# Crédito PF/PJ no Atlas SFN

`export_atlas.py` materializa numerador e denominador do SCR.data no grão mês × UF × renda/porte × modalidade oficial. A consulta usa `utils.scr_data_query.filtrar/agregar`, com promoção dos saldos para float64 antes da soma. Não calcula média de taxas.

```sh
.venv/bin/python web/tools/export_atlas.py --scr-cache data/cache/scr_data
cd web
node --test tests/atlas-data.test.mjs
```

O cache deve ter `metadata.json` e `staging/annual/{ano}.parquet`, ou os nomes flat dos assets de release (`scr_data_metadata.json`, `scr_data_ano_{ano}.parquet`). A janela inicia em jan/2024 por padrão e vai até `periodo_final` do metadata; `--start` e `--end` permitem uma janela explícita. Não há acesso à rede nem reconstrução de origem ou mudança no cache.

Os anuais precisam da classificação `modalidade_bcb` preenchida (schema 2). Versões antigas descartavam `origem` antes dessa classificação. Ela é necessária para separar as modalidades livres e direcionadas de PJ; uma ausência provoca falha explícita e preserva os assets anteriores.

Saídas em `web/public/data`, alterável por `--output`:

- `atlas-pf.json`: PF por nove faixas de renda, sete modalidades, 27 UFs.
- `atlas-pj.json`: PJ por cinco portes, nove modalidades PJ e as duas modalidades rotuladas PF presentes no cliente PJ.
- `atlas-validation.json`: contagens, comparação com o módulo de consulta original e hashes dos dois arquivos efetivamente entregues.

As duas modalidades PF em PJ vêm da nota 1 do de-para oficial (subdomínios 0202/0203). São mantidas no total e identificadas na interface como “classificação PF”. Não foram movidas para Outros. “Indisponível” e “Sem rendimento” permanecem no universo; somente observações realmente ausentes produzem N/D. Zero observado com carteira positiva produz 0%.

A participação de uma modalidade é `carteira da modalidade / carteira completa do mesmo mês, cliente, renda/porte e UF`. Selecionar uma modalidade não altera esse denominador. As faixas são observações de cada competência, sem seguimento de uma coorte fixa de tomadores.

A geografia se refere ao tomador. O cadastro de agências tem origem, data e universo próprios. O SCR agregado não identifica o banco individual que concedeu o crédito.

Fontes: [SCR.data](https://www.bcb.gov.br/estabilidadefinanceira/scrdata), [metodologia v2](https://www.bcb.gov.br/pda/desig/metodologia_versao2.pdf), [de-para oficial](https://www.bcb.gov.br/content/estabilidadefinanceira/Leiaute_de_documentos/scrdoc3040/Equivalencia_Modalidades.xlsx).

Os primeiros assets desta integração usam os anuais schema 2 já publicados no release `v1.2-scr-cache` do projeto, de jan/2024 a jul/2026. Os hashes dos anuais, metadata e módulos de cálculo ficam no próprio JSON. A coleta e a publicação compartilhada reutilizam seu cache atualizado, permitindo novas competências sem alterar o frontend.
