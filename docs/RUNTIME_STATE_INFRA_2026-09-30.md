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

Na preparação inicial, o SQLite implantado foi inspecionado apenas pelo catálogo,
sem leitura de linhas:
`sessions`, `tenants`, `portfolios`, `customers`, `debts`, `session_contexts`,
`payment_agreements` e `payment_instructions`. As migrações
`001_postgres_session_okf.sql`, `002_postgres_payments.sql` e
`003_sqlite_catalog.sql` foram aplicadas em uma transação ao banco novo. O
journal `runtime.schema_migrations` registra as três. Oito tabelas operacionais
correspondem às oito do SQLite; há ainda tabelas auxiliares de OKF e o schema
`langgraph` reservado. JSON armazenado como texto no SQLite usa JSONB no novo
banco.

O teste `tests/postgres_sqlite_catalog.sql` criou somente dados sintéticos em
transação revertida e validou vínculos de sessão, carteira, cliente, dívida,
acordo e pagamento, além da rejeição de carteira de outra empresa. Passou no
PostgreSQL local e no serviço novo. O serviço existente `Postgres-N6HF` do canário
não foi alterado.

### Validação com amostra anonimizada — 30/09/2026

O SQLite implantado foi aberto em modo somente leitura. Contagens na origem:
550 sessões, 1 empresa, 1 carteira, 190 clientes, 190 dívidas, 190 contextos,
30 acordos e 30 instruções. Dez cadeias ligavam contexto a instrução; havia
exemplos de PIX e boleto.

`scripts/validate_isolated_state.py --run` selecionou uma cadeia de cada meio,
com clientes distintos, e gravou **duas amostras anonimizadas** no PostgreSQL
isolado. IDs, nome, CPF, telefone, valores financeiros, códigos de pagamento,
autorização, histórico e texto de conversa foram substituídos ou excluídos
antes de sair do container de origem. Produto, atraso, modalidade, número de
parcelas e campos permitidos de elegibilidade/política preservam os tipos e
relações da origem. As amostras são marcadas `sample_only` e não servem para
atendimento nem para uma virada de dados. O comando é de uso único com IDs fixos;
uma segunda execução falha por chave duplicada em vez de sobrescrever a amostra.

O teste unitário do sanitizador passou. A transação no PostgreSQL confirmou
1 empresa, 1 carteira, 2 clientes, 2 dívidas, 2 sessões, 2 contextos, 2 acordos
e 2 instruções; a leitura por junção retornou duas cadeias e uma instrução de
cada meio. `EXPLAIN` mostrou `Index Scan` em
`session_contexts_customer_debt_idx` para a consulta por empresa, carteira,
cliente e dívida. O teste SQL de chave estrangeira rodou novamente e reverteu
suas linhas temporárias. Não houve migração de checkpoints ou documentos OKF.

## Redis

`PING`, `SET` com expiração, `GET` e `DEL` passaram via conexão interna ao
próprio serviço. A chave sintética foi removida. Redis não contém sessões,
checkpoints, acordos ou mensagens e ainda não foi vinculado ao Runtime.
Na nova validação, `PING`, `SET EX 3`, `GET` e `TTL` passaram; após quatro segundos
`EXISTS` retornou 0 e `DBSIZE` retornou 0.

O Runtime manteve o deployment
`119a74b3-00c2-469a-9e4c-5d20eb0eedaf` em estado `SUCCESS`. Não há no
serviço variáveis `SESSION_BACKEND`, `SESSION_DATABASE_URL`, `REDIS_URI`,
`REDIS_URL` ou `DATABASE_URL` apontando para os bancos novos.

### Adaptador PostgreSQL local

O adaptador `PostgresSessionStore` agora grava empresa, carteira, cliente,
dívida e vínculo da sessão na mesma transação da criação da Demo. O cadastro
é reconstruído dessas tabelas ao ler a sessão; o JSON da sessão deixa de
duplicar nome, CPF e telefone. Playground e WhatsApp sem vínculo continuam
sem registros normalizados. A consulta de segunda via usa o vínculo
`session_contexts`, como no SQLite. Reset mantém o cadastro e remove somente
o acordo/pagamento da sessão de origem.

Três testes de integração passaram em PostgreSQL 18 local descartável:
criação/leitura/reset com boleto, consulta a partir de outra sessão vinculada,
rollback de IDs duplicados e carteira de outra empresa, e isolamento de
Playground/WhatsApp sem vínculo. Quatro testes locais adicionais de backend e
sanitização passaram; o adaptador teve 85% de cobertura nesses testes. O
benchmark sintético recebeu IDs próprios e limpeza
ordenada das novas tabelas; sua execução completa com tools/LLM ainda não foi
repetida. Nenhuma variável ou deployment do Runtime foi alterado nesta etapa.

## Antes de qualquer virada

1. Revisar o adaptador local e executar o canário completo com tools em um
   serviço isolado; os testes de integração cobrem o contrato de persistência,
   mas não uma conversa inteira.
2. Definir credenciais de aplicação com privilégios mínimos, isolamento por
   empresa/carteira e estratégia de backup para o banco novo.
3. Planejar a cópia verificada do SQLite e, separadamente, a migração dos
   checkpoints/threads/Assistants de `/data/langgraph`. Redis não substitui
   nenhuma dessas persistências.
4. Executar canário com tráfego sintético, testar retomada, concorrência,
   `/reset-demo`, segunda via, streaming e falhas; definir limites de rollback.
5. Somente após aprovação de uma virada, conectar as variáveis do Runtime e
   preservar o SQLite e o volume originais para retorno controlado.
