# Réplicas do Runtime OSS de homologação

Em 28/11/2026 às 06:57 UTC, o disco do Agente de Homologação continha os sete snapshots referenciados pelas 205 sessões Aurora com versão fixada. Os 193 recibos do escopo 7 conferiram com o SHA-256 dos respectivos documentos. No conjunto de todos os escopos, faltavam 17 dos 30 snapshots, afetando 553 das 943 sessões com versão fixada e 302 dos 544 recibos. Uma cópia fiel dos arquivos disponíveis preservaria essa lacuna.

## Onde o estado reside

Inventário de leitura do serviço Railway `accedeb1-4a8d-455e-a7ed-f4d2d7d92dec` no ambiente `8830dd97-8668-467d-b2f5-6ebcb8807969`.

| Estado | Fonte no serviço de homologação | Consequência para outra réplica |
|---|---|---|
| Threads, runs, checkpoints, assistentes e versões, instruções fixadas | PostgreSQL, schema `langgraph` | Usar o mesmo banco e o mesmo schema |
| Sessões, contexto da carteira, acordos, instruções de pagamento e recibos OKF | PostgreSQL, schemas `runtime` e `okf` | As sessões fixam IDs de bundle. As tabelas de metadados e recibos não contêm o texto Markdown |
| Sinalização de fila e streaming | Redis, DB lógico configurado para Runtime | Usar a mesma instância, DB e namespace. Consultar o status durável no PostgreSQL quando a conexão cair |
| OKF publicado, ponteiro ativo, versões anteriores, cache por carteira, drafts e operações RAW | `/data/okf`, 2.581 arquivos e 9.546.056 bytes | 14 diretórios de bundle com `index.md`. O serviço OKF remoto fornece a release ativa da carteira. Uma thread que já fixou uma versão depende dos arquivos daquele snapshot |
| Cliente simulado padrão e arquivos por carteira | `/data/simulator`, 5 arquivos e 2.950 bytes | A fixture do escopo 7 existe. O Runtime consulta arquivos também ao criar o contexto de uma sessão |
| Catálogo e habilitação das ferramentas | `/tmp/canary-data/tools`, 1 arquivo e 3.492 bytes | O estado está fora do volume. Um processo novo pode recriar as habilitações padrão |
| Checkpoints antigos do servidor de desenvolvimento e SQLite | `DATA_ROOT=/tmp/canary-data`, `SESSION_ROOT=/tmp/canary-data/sessions` | O candidato OSS com PostgreSQL dispensa o link `.langgraph_api`. O modo legado continua usando disco |

As árvores OKF, simulador e tools estavam estáveis em duas leituras. Os digests SHA-256 incluem nomes relativos, tipos e conteúdo.

```text
okf        1ab3aaaf1a74f13b69c7daea7eaecd1e1d0eec3bda6ae595b2ff3a1bcf451187
simulator  7fd62f18c16224fa28c8ac3a454ba7a96bf1d18c8fc00ca43e2a03f8f787f8a5
tools      57f39a3c01d6e01c593576f8731b5b63d3cdea1d289d47d0a34b92171100c36c
```

## Orçamento PostgreSQL

A conexão configurada pelo Runtime aponta para o serviço `4fe1fa72-c700-44fe-9132-6c8240d9e556`. Às 06:55:43 UTC, `max_connections=500`, três conexões eram reservadas ao superusuário, zero aos demais papéis privilegiados e havia outra conexão de cliente ociosa. Banco e papel estavam com limite `-1`. Restavam **496 vagas comuns naquele instante**. Como exemplo de dimensionamento, reservar outras 50 para manutenção, chegadas de clientes e variação deixa 446 vagas adicionais. A reserva de 50 é uma hipótese operacional.

No candidato com fila Redis, cada worker de execução mantém até uma conexão PostgreSQL dedicada durante o turno. Operações HTTP, observação do run e renovação da lease usam o pool OSS. Ferramentas usam um segundo pool de sessões. O cálculo abaixo considera um único DSN estável por processo em regime.

```text
réplicas × processos por réplica × (OSS_RUNTIME_WORKERS + OSS_RUNTIME_DB_POOL_SIZE + SESSION_DATABASE_POOL_SIZE)
```

Com um processo por réplica, 8 workers, pool OSS de 8 e pool de sessões de 5, duas réplicas chegam a 42 conexões e quatro chegam a 84. Somar processos que convivem durante o rollout, conexões de bootstrap/migrations e consumidores externos ao reservar capacidade. A cifra de 496 é uma amostra ociosa. Mil execuções simultâneas exigiriam ao menos mil conexões dedicadas com a implementação atual. Mil conversas abertas podem esperar na fila, com latência dependente dos workers, do provedor e da taxa de chegada.

O worker precisa de afinidade com a mesma sessão PostgreSQL para manter advisory locks e usar o checkpointer até finalizar. Migrations e bootstrap adquirem o mesmo lock em autocommit, tentam novamente quando ocupado e liberam a sessão ao terminar. Isso permite que os índices concorrentes do checkpointer avancem quando quatro processos inicializam juntos.

## Reproduzir a conferência

Na origem quiescente ou em um snapshot consistente, executar com as variáveis de caminho do serviço. Os relatórios contêm contagens e hashes agregados. Para o primeiro ensaio, usar PostgreSQL/Redis de teste e estados sintéticos aprovados em diretórios distintos para cada réplica.

```bash
python scripts/audit_replica_storage.py --postgres --scope 7 > /tmp/aurora-origem.json
# Na réplica candidata, com uma cópia desse relatório disponível.
python scripts/audit_replica_storage.py --postgres --scope 7 --compare /tmp/aurora-origem.json
```

O escopo filtra as referências de sessão e recibo no PostgreSQL. O hash cobre integralmente os três diretórios configurados. Código de saída 1 identifica árvore divergente, conjunto de referências diferente da origem em modo PostgreSQL, bundle referenciado sem índice ou recibo cujo documento diverge ou falta. Remover `--scope 7` para avaliar o conjunto completo. Registrar a quantidade de versões e recibos para evitar interpretar um banco de sessões vazio como aprovação de continuidade.

O Railway restringe réplicas em serviços com volume. Para homologação isolada e estado sintético congelado, duas cópias conferidas permitem ensaiar continuidade e perda de um processo. Para tráfego com mutações, as réplicas precisam buscar o mesmo snapshot fixado em um repositório durável por ID, consultar uma única versão das configurações de tools e simulador e encaminhar escrita de drafts e RAW a um único serviço. Até implementar e validar esse caminho, manter o serviço atual com o volume. Uma nova release deve poder atender em disco vazio tanto uma thread existente quanto outra criada após a publicação. Verificar também uma habilitação de ferramenta e uma alteração de fixture feitas entre esses dois atendimentos. O retorno ao serviço original preserva volume e referências históricas. [Documentação de volumes do Railway](https://docs.railway.com/volumes/reference)
