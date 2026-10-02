# Backfill isolado de sessões — 2026-10-02

O runtime principal `langgraph-simple-agent-clean` continua em SQLite. Não houve
troca de tráfego, variáveis, serviço de chat ou Redis.

- Origem: snapshot consistente de `/data/sessions/sessions.sqlite3`, obtido com
  `sqlite3.Connection.backup` às 01:04 UTC. `quick_check=ok`, 1.331.200 bytes,
  SHA-256 `75c4333d953a5ad37b6d6c46e266d08ec18addd1754ed309b3464ef80c6d87ac`.
- Backup anterior do volume no Railway: `d5230819-3761-4911-bfc8-ca16f558b29f`
  (`pre-postgres-history-migration-2026-10-02`). A cópia SQLite portátil foi
  guardada fora do repositório em
  `/home/zerai/.local/share/zerai-migration/20261002/sessions.sqlite3`, com
  acesso restrito. Não mover essa cópia para Git ou logs.
- Destino: serviço isolado `agent-runtime-postgres-canary`, banco
  `postgres-runtime-canary`. A importação pelo
  `scripts/migrate_sqlite_snapshot.py` exige hash, ID explícito do serviço,
  `SESSION_BACKEND=postgres` e tabelas vazias. Os quatro conjuntos são gravados
  numa única transação; falha reverte tudo.
- Copiados: 579 sessões, 314 recibos de leitura OKF, 39 acordos e 39 instruções
  de pagamento. IDs foram preservados. Estados de sessões vinculadas incluem
  o `fixture` reconstruído a partir das tabelas normalizadas do SQLite.
- Paridade: hashes canônicos de sessões, acordos, instruções e recibos iguais
  entre origem e destino; 579/579 sessões lidas pelo `PostgresSessionStore`
  com estado equivalente; sessão sintética nova criada, lida e removida no
  canário. Testes locais do importador e seleção de backend: 4 aprovados.

Este backfill é um ponto no tempo. Antes de uma virada real, será preciso
reconciliar alterações posteriores ao snapshot e repetir a comparação. O
estado mais recente está registrado em `OSS_CHECKPOINT_CANARY_2026-10-02.md`.
Redis não foi ativado no runtime principal. O projeto não adotará LangSmith
Agent Server nem sua licença. Não usar este backfill como autorização de
cutover.

## Reconciliação posterior

Um segundo backup consistente do SQLite, SHA-256
`4ab773fbdb81918c2a186c854c43031c266216467d1806c4977b4b46b6825100`,
foi importado com `scripts/reconcile_sqlite_snapshot.py`. O canário passou
para 581 sessões, 316 recibos, 40 acordos e 40 instruções. A comparação
transacional dos quatro conjuntos passou e a repetição do comando não mudou
nenhuma linha. As dez sessões sintéticas de testes posteriores foram
removidas do canário; ele voltou a 581 sessões. O principal ainda tinha 581
sessões às 02:47 UTC. Revalidar antes de qualquer virada.
