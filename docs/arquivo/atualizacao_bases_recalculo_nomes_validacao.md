# Validação do cache local de nomes no recálculo

O ajuste em `canonicalize_institution_dataframe` reutiliza a resolução de um nome durante uma única chamada. A chave é o nome já resolvido por `CodInst`, pelo frame auxiliar ou pelo resolvedor de placeholders. Cada nova chamada começa com um cache vazio e usa o catálogo recebido naquela chamada. As regras de matching e os cálculos permanecem iguais.

O benchmark compara a função anterior extraída do commit `c2079ce5fb40cb1270a9605b8b777368d09d7414` com o ajuste local. Usou 12 instituições, os 46 períodos disponíveis e recortes das oito fontes trimestrais. O catálogo real da raiz foi carregado dos arquivos BLOPRUDENCIAL. O DataFrame final manteve exatamente as 552 linhas e 110 colunas, incluindo valores, índice, dtypes e atributos.

| Medida | Função anterior | Cache local |
| --- | ---: | ---: |
| Tempo do builder com cProfile | 6,450781 s | 0,918251 s |
| Chamadas de tokenização de nomes | 403.440 | 20.992 |

O processamento foi 7,025 vezes mais rápido nessa amostra. O processo completo ficou abaixo do limite de 768 MiB, com pico de 282,4 MiB, e terminou em 8,8 segundos. O diagnóstico bloqueou rede e escrita no worktree; registrou zero tentativas de HTTP e impediu apenas a criação incidental do arquivo de log durante o import.

Essa medição é local, inclui overhead do cProfile e cobre o builder. A entrada de métricas BLOP foi omitida, enquanto o catálogo BLOPRUDENCIAL real permaneceu ativo. O resultado não estima o tempo total da atualização ou da publicação no site.

Os testes verificam nomes repetidos e distintos, ambiguidade, valores ausentes, tipos `string` e `category`, coluna de nome personalizada, dtypes financeiros, índices repetidos e atributos. Também cobrem placeholders iguais com códigos diferentes, consulta ao frame auxiliar e ao resolvedor, troca do catálogo entre chamadas e comparação exata de 552 linhas com o catálogo real. O comportamento anterior de `np.nan` e a exceção anterior de `pd.NA` foram preservados.

| Grupo executado sequencialmente com rede bloqueada | Resultado | Pico de memória |
| --- | ---: | ---: |
| Cache nominal inicial, institutions, resolution, registry, critical_screens e conversão numérica | 245 passaram | 449,7 MiB |
| Cache nominal com os complementos, update_service, update_end_to_end e release_ops | 58 passaram | 344,7 MiB |

O primeiro grupo teve três tentativas de acesso externo impedidas pelo bloqueio de rede. O segundo grupo não registrou tentativas. Os sete casos finais de cache nominal estão em `tests/test_institution_dataframe_cache.py`. `git diff --check` passou.
