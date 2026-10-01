# Infraestrutura isolada para futura migração do Runtime

Em 30/09/2026, foram criados dois serviços no projeto Railway
`agent-runtime-console` (`511a294c-8d6a-4906-bd26-e8e33011eac5`), ambiente
`production` (`8830dd97-8668-467d-b2f5-6ebcb8807969`):

| Serviço | ID | Uso nesta etapa |
| --- | --- | --- |
| `Postgres-zdaz` | `e1d98011-cd52-4005-866d-f863a99871a5` | Banco novo e exclusivo para o futuro estado do Runtime |
| `Redis` | `ff085d88-75c3-474d-bce5-1322efec3a20` | Instância nova, ainda sem consumidor |

Nenhum serviço de aplicação recebeu variáveis ou referências a esses bancos.
O deployment de `langgraph-simple-agent-clean` permaneceu
`119a74b3-00c2-469a-9e4c-5d20eb0eedaf`. Nenhum serviço preexistente foi
reiniciado. Ambos os bancos têm zero domínios e zero proxies TCP públicos.

## PostgreSQL

O SQLite implantado foi inspecionado apenas pelo catálogo, sem leitura de linhas:
`sessions`, `tenants`, `portfolios`, `customers`, `debts`, `session_contexts`,
`payment_agreements` e `payment_instructions`. As migrações
`001_postgres_session_okf.sql`, `002_postgres_payments.sql` e
`003_sqlite_catalog.sql` foram aplicadas em uma transação ao banco novo. O
journal `runtime.schema_migrations` registra as três. Oito tabelas operacionais
correspondem às oito do SQLite; há ainda tabelas auxiliares de OKF e o schema
`langgraph` reservado. JSON armazenado como texto no SQLite usa JSONB no novo
banco. Nenhum dado de produção foi copiado.

O teste `tests/postgres_sqlite_catalog.sql` criou somente dados sintéticos em
transação revertida e validou vínculos de sessão, carteira, cliente, dívida,
acordo e pagamento, além da rejeição de carteira de outra empresa. Passou no
PostgreSQL local e no serviço novo. Contagem final: zero linhas nas oito tabelas
operacionais. O serviço existente `Postgres-N6HF` do canário não foi alterado.

## Redis

`PING`, `SET` com expiração, `GET` e `DEL` passaram via conexão interna ao
próprio serviço. A chave sintética foi removida. Redis não contém sessões,
checkpoints, acordos ou mensagens e ainda não foi vinculado ao Runtime.

## Antes de qualquer virada

1. Implementar o adaptador PostgreSQL que grave e leia também as cinco tabelas
   normalizadas; o adaptador do canário atual usa apenas sessões e pagamentos.
2. Definir credenciais de aplicação com privilégios mínimos, isolamento por
   empresa/carteira e estratégia de backup para o banco novo.
3. Planejar a cópia verificada do SQLite e, separadamente, a migração dos
   checkpoints/threads/Assistants de `/data/langgraph`. Redis não substitui
   nenhuma dessas persistências.
4. Executar canário com tráfego sintético, testar retomada, concorrência,
   `/reset-demo`, segunda via, streaming e falhas; definir limites de rollback.
5. Somente após aprovação de uma virada, conectar as variáveis do Runtime e
   preservar o SQLite e o volume originais para retorno controlado.
