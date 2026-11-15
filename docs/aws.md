# Implantação na AWS

Nenhum recurso da AWS é criado por este repositório. Este guia descreve a implantação recomendada.

## Arquitetura da primeira etapa

Um servidor **EC2 com disco EBS**, rodando os containers de `docker-compose.yml`. App e atualização
compartilham o volume `cache`. Backup e cópias no **S3**, acesso pelo **ALB** com HTTPS e, se a instituição
exigir, login corporativo no próprio ALB.

**Não use EFS.** As travas e a promoção de arquivos usam `flock`, `fsync` e renomeação atômica em um disco local;
a garantia não vale para NFS. Por isso também não há réplicas nesta etapa. Vários servidores exigem um adaptador
de `ProtocolDataStore` para S3 com promoção condicional, além de fila e trava centrais.

## Dimensionamento

Pico medido em container Linux na verificação da análise financeira: **cerca de 2,0 GB** (`peak_memory_mb` em cada
relatório). Atualizar tudo levou 24 minutos no teste. A imagem tem 1,3 GB.
Use ao menos **4 GB de RAM** (`t3.medium`) e **30 GB** de disco. Confirme o pico da primeira execução completa.

## Implantação

```sh
cp .env.example .env   # defina TOMACONTA_ADMIN_PASSWORD
docker compose up -d --build app
curl -fsS http://localhost:8501/_stcore/health
```

No primeiro uso, a base instalada na imagem é suficiente para abrir o site.

## Atualização

Pela tela, em **Atualizar Base**. Ou pelo agendador, a partir do volume:

```sh
docker compose run --rm atualizacao
```

Sugestão de `cron` no servidor, todo dia às 6h: `0 6 * * * cd /opt/tomaconta && docker compose run --rm atualizacao`.
Código de saída diferente de zero significa revisão pendente ou fonte com falha; o resumo fica em
`data/cache/financial_analysis_updates/tudo-*.json`. Um item de revisão mantém a base anterior até a decisão na tela.

## Backup

```sh
docker run --rm -v tomaconta_cache:/dados:ro -v ~/.aws:/root/.aws:ro amazon/aws-cli s3 sync /dados s3://SEU-BUCKET/cache
```

Ative o versionamento do bucket e use uma IAM role no servidor em vez de chaves. Restaure com `s3 sync` no sentido
inverso, com o app parado.

## Limpeza

`python tools/prune_caches.py` lista relatórios antigos, envios e temporários. `--apply` remove. As bases e as fontes
arquivadas não são tocadas.

## Caminho alternativo já existente

`tools/update_service_cli.py` oferece API, worker e revisões imutáveis com ativação atômica, descritos em
`docs/autosservico_portatil_etapa_2.md`. O fluxo por botões da análise financeira também grava nessas revisões quando
`TOMACONTA_OFFICIAL_STORE_DIR` está definido. Não foi validado nesta configuração de containers.

## Lista para a virada

- [ ] Definir `TOMACONTA_ADMIN_PASSWORD` e trocar a senha antiga, que está no histórico do Git.
- [ ] Subir o app e comparar Snapshot, Peers e Análise com o site atual.
- [ ] Rodar `docker compose run --rm atualizacao` e conferir `peak_memory_mb`.
- [ ] Configurar backup, HTTPS, alarme de disco e o agendador.
