# Canário de checkpoints LangGraph OSS — 2026-10-02

Escopo: projeto Railway `511a294c-8d6a-4906-bd26-e8e33011eac5`, ambiente
`8830dd97-8668-467d-b2f5-6ebcb8807969`. O serviço principal
`langgraph-simple-agent-clean` (`861cf8e9-935f-4673-baf0-6bb438eac5fb`)
permanece no deployment `ae728de5-779f-4d66-bb86-ca67f0bca124`, com
`langgraph dev` e SQLite operacional. O canário
`agent-runtime-postgres-canary` (`accedeb1-4a8d-455e-a7ed-f4d2d7d92dec`)
permanece isolado no deployment `ffbe67ee-25bb-493f-8434-a1e2ed911fb7`.
Nenhum tráfego, variável ou deployment do serviço principal foi alterado.
Não usar LangSmith Agent Server nem licença.

Status: preparação e testes isolados concluídos; a etapa de tráfego sintético
pela interface HTTP OSS continua pendente pelos bloqueios abaixo.

## Verificações concluídas

1. O snapshot SQLite do serviço principal foi refeito de forma consistente às
   01:26 UTC. SHA-256 `75c4333d953a5ad37b6d6c46e266d08ec18addd1754ed309b3464ef80c6d87ac`,
   igual ao snapshot importado. As quatro tabelas do canário mantinham os
   mesmos totais e hashes: 579 sessões, 314 recibos OKF, 39 acordos e 39
   instruções. Paridade válida apenas no instante da leitura; repetir antes
   de qualquer migração de tráfego.
2. `scripts/probe_oss_checkpoint.py` usou o pacote OSS
   `langgraph-checkpoint-postgres==3.1.2` com `LANGGRAPH_STRICT_MSGPACK=true`
   numa schema separada do PostgreSQL do canário. Migrou três checkpoints de
   uma conversa sintética, preservou IDs, retomou a conversa e persistiu uma
   conversa nova. Não chamou LLM, tools de negócio ou canais. Resultado:
   `synthetic_legacy_checkpoints=3`, `old_thread_resumed=true`,
   `new_thread_persisted=true`. As linhas sintéticas foram removidas;
   `checkpoints`, `checkpoint_blobs` e `checkpoint_writes` ficaram em zero.
3. `scripts/probe_managed_graph_hydration.py` carregou no grafo real do canário
   o **estado final** de uma conversa antiga concluída com quatro mensagens.
   Verificou conteúdo e contagem das mensagens e acrescentou duas mensagens
   sintéticas sem invocar o modelo. A thread de teste foi removida. Isso prova
   continuidade de mensagens nessa amostra, não preservação da cadeia inteira
   de checkpoints nem retomada de uma execução pendente.
   Os arquivos temporários com essa amostra foram removidos do principal,
   do canário e da estação local após o teste.

## Bloqueios para a virada

- Às 01:40:53 UTC, `/data/langgraph/.langgraph_checkpoint.1.pckl` tinha
  2.810.759.403 bytes e mtime de 01/10 04:13:35 UTC. Os arquivos `.2.pckl`
  e `.3.pckl` haviam sido atualizados às 01:40:50 UTC. Uma conversa criada
  depois de 04:13 UTC tinha 28 mensagens acessíveis pela API. Portanto, uma
  cópia somente dos arquivos do volume não comprova que captura o histórico
  vivo. O motivo específico de `.1.pckl` não avançar ainda não foi provado.
- Canais e o Chat UI usam endpoints do servidor LangGraph atual, como
  `/assistants`, `/threads` e `/runs/stream`. O pacote OSS de checkpoints não
  fornece esses endpoints. Falta um serviço HTTP compatível e testes de
  streaming, retomada, isolamento e rollback antes de apontar qualquer
  cliente para o canário.
- O código `managed_graph.py` tem o mesmo hash entre o serviço principal e o
  canário, mas `tool_middleware.py` diverge. O teste de hidratação não prova
  paridade de comportamento de uma negociação real.

Próxima etapa: reconciliar o histórico vivo da API com o volume, definir o
contrato HTTP OSS necessário para Canais/Chat UI e validar o artefato completo
em canário isolado. Somente depois executar tráfego sintético, teste de
rollback e nova comparação de dados. Não houve cutover.
