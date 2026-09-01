# Malha geográfica

`uf_brasil.geojson` — malha das 27 unidades da federação, qualidade mínima,
baixada da API de malhas do IBGE:

```
https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR?formato=application/vnd.geo+json&qualidade=minima&intrarregiao=UF
```

Cada feature traz `properties.codarea` com o código IBGE da UF (2 dígitos), que
casa com a coluna `codigo_ibge` de `dim_geo` do cache `scr_data`. É o que o
`featureidkey` do coroplético da aba "Inadimplência (SCR)" usa.

Arquivo estático (~96 KB): a malha das UFs não muda. Refazer o download só se o
IBGE alterar a divisão territorial.
