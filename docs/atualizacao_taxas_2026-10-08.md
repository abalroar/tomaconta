# Atualização de taxas por produto — 08/10/2026

Fonte: API oficial Banco Central, serviço Olinda taxaJuros v2 (`ConsultaDatas`, `ParametrosConsulta`, `ConsultaUnificada`).

- Última janela disponível: início 18/09/2026, término 24/09/2026.
- Base anterior: término 31/07/2026; 2.764.031 registros, 3.656 janelas.
- Base atual: 2.793.925 registros, 3.694 janelas desde 02/01/2012.
- Incremento: 38 janelas e 29.894 registros, extraídos sem falhas.
- Os 2.764.031 registros anteriores preservam chaves e taxas mensais/anuais.
- Calendário materializado coincide integralmente com ConsultaDatas(D).
- Zero duplicatas na chave janela/segmento/modalidade/instituição; zero nulos nos campos obrigatórios.
- A rotina reconciliou o staging legado antes da consolidação, descartando 3.368 linhas de outra periodicidade; isso não alterou os valores do histórico publicado.
- Leitores usados pela aba: visão mensal e diária validadas para os 22 produtos presentes na última janela.
- Testes específicos: 22 passed; git diff --check sem erros.

A aba consome os seis arquivos versionados em `data/cache/taxas_juros_historico/`. O manifesto global foi atualizado somente no registro de taxas, hashes dos seus assets e identificação da publicação. Os demais caches foram preservados.

Destino da publicação: GitHub Release `v1.1-cache`, repositório `abalroar/tomaconta`. A versão no app deve ser validada após merge e reboot, verificando `Base até: 24/09/2026`, seleção mensal até 09/2026 e série diária até 24/09/2026.

| Asset | SHA-256 | Bytes |
| --- | --- | ---: |
| taxas_juros_historico_dados.parquet | `a8307cd3b5f40ea55e70c514359a87d6c49d403c02664e6b673bb4c79c5eab79` | 18536130 |
| taxas_juros_historico_metadata.json | `8b4f9c0e91588e9709c8cebf82bd7f1881148ba852bea1ca12c45f924a525772` | 68891 |
| taxas_juros_historico_dim_parametros.parquet | `70ee6dbbaac7041a12d7acfeb3bd841e6e573d6f3daa3d8a882683edc8642c3b` | 4342 |
| taxas_juros_historico_dim_datas.parquet | `42604421d5f64f762100be75619178bc17fb5d0cc8b6ca2dbf977f632a46d639` | 68615 |
| taxas_juros_historico_dim_instituicoes.parquet | `0c5a867efbbb220bb6b2cf4d166a9b969450a3c84ecb70a57bf8c346e16221a8` | 21483 |
| taxas_juros_historico_manifest.json | `ebb2910dfe63d44bde4cbe99441d9e5822746c4fcd2f3496ad81c917ee01840e` | 2309 |
