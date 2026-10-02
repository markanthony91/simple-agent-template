# Migração isolada de estado LangGraph OSS — 2026-10-02

Projeto Railway `511a294c-8d6a-4906-bd26-e8e33011eac5`, ambiente
`8830dd97-8668-467d-b2f5-6ebcb8807969`. O principal
`langgraph-simple-agent-clean` (`861cf8e9-935f-4673-baf0-6bb438eac5fb`)
permanece em `langgraph dev` e SQLite; seu deployment observado é
`75e22140-b751-4ac1-8372-222cd01fb051` (0.15.0). O canário isolado
`agent-runtime-postgres-canary` (`accedeb1-4a8d-455e-a7ed-f4d2d7d92dec`)
executa `simple_agent.oss_runtime:app` com checkpoints e sessões PostgreSQL.
Não houve mudança de rota em Canais ou Chat UI, e o canário não tem domínio
público. Não usamos licença nem LangSmith Agent Server.

## Origem e preservação

- A API viva do principal exportou 460 threads `agent`, 5.374 mensagens,
  em 02/10 01:59 UTC. SHA-256 do gzip:
  `e7748285467dc99897f7a044e650f8f8ebcbd7feb00d51db25f790e21f3bb591`.
  O exportador seleciona apenas os campos necessários e não imprime conteúdo.
- O banco do canário arquivou as 460 threads com estado final, metadados e
  horários. As 452 threads `idle` foram gravadas no `PostgresSaver`; 8 threads
  `error` ficaram consultáveis no arquivo, sem checkpoint retomável. Dessas,
  5.325 mensagens pertencem às 452 retomáveis; 49 às 8 arquivadas.
- Um processo novo releu e comparou IDs, tipos, conteúdo e chamadas de tool
  das 5.325 mensagens; nenhuma divergência foi encontrada. O teste não
  promete recuperar checkpoints intermediários nem execuções interrompidas.
- Sete configurações de Assistant foram copiadas com seus IDs e versões.
  SHA-256 do snapshot:
  `90861d72892fba34fc630a37c37cfe3b67d7ac658c5db25d354d952ce9ba0470`.
- A cópia portátil de SQLite foi reconciliada com o principal: 581 sessões,
  316 recibos OKF, 40 acordos e 40 instruções, com hashes equivalentes no
  instante da cópia. SHA-256 do backup consistente:
  `4ab773fbdb81918c2a186c854c43031c266216467d1806c4977b4b46b6825100`.
- O backup anterior do volume principal no Railway
  `d5230819-3761-4911-bfc8-ca16f558b29f` e as cópias locais restritas em
  `/home/zerai/.local/share/zerai-migration/20261002/` permanecem como
  segurança. Não publicar esses arquivos no Git.

O arquivo `/data/langgraph/.langgraph_checkpoint.1.pckl` observado no
principal tinha 2.810.759.403 bytes e mtime antigo; a API possuía estados
mais recentes. Por isso o arquivo do volume não foi usado como fonte única.
A causa exata da ausência de atualização desse arquivo não foi provada.

## Serviço OSS e testes

O entrypoint OSS é ativado somente por `OSS_RUNTIME_ENABLED=true`. Ele exige
`SESSION_BACKEND=postgres`, `LANGGRAPH_STRICT_MSGPACK=true` e
`OSS_RUNTIME_API_TOKEN` com 32 caracteres ou mais. A API fornece os endpoints
necessários para leitura de Assistants, criação/busca/leitura de threads,
histórico, atualização de contexto e runs `wait`/`stream`. As rotas, exceto
`/info`, exigem `X-Api-Key`; origens de browser são configuradas em
`OSS_RUNTIME_CORS_ORIGINS`. A configuração do serviço principal não foi
alterada por esta migração.

O canário passou por:

1. Releitura das 452 threads e 5.325 mensagens em outro processo.
2. Leitura de uma thread arquivada em erro, inclusive mensagens e histórico
   final, sem habilitar sua retomada.
3. Teste sintético de `ensure_whatsapp_session`, thread nova, resposta do
   agente, segunda mensagem via SSE, estado persistido e releitura por outro
   processo.
4. Teste HTTP real da implantação com o Assistant principal
   `dd5766a7-2237-5e12-b949-7236c459698c`, usando a conexão LLM `lovable`
   copiada apenas para o canário. Não foram acionadas tools de pagamento,
   mensagens externas ou dados de clientes.
5. Atualização/leitura de um Assistant sintético, streaming `okf_admin` e
   remoção da thread temporária. Os dez registros sintéticos acumulados nos
   primeiros testes foram removidos. Após a limpeza: 581 sessões, 460 threads
   arquivadas, 452 checkpoints e zero threads sintéticas.
6. Suíte local após alinhar o código do canário com o runtime 0.15.0:
   488 testes unitários aprovados.

Às 02:47 UTC, o principal ainda tinha 460 threads `agent`, 581 sessões e
versões de Assistant iguais às do snapshot. Essa paridade é pontual e deverá
ser refeita imediatamente antes de qualquer virada.

## Gates antes de avaliar a virada

- Reconciliar qualquer sessão, Assistant ou thread criada/alterada após a
  última leitura; a importação inicial de checkpoints recusa destino não
  vazio, portanto precisa de um procedimento de delta ou uma nova carga
  controlada em banco isolado.
- Testar o Chat UI real contra um endpoint de canário protegido, incluindo
  histórico, stop/cancelamento, painel administrativo e fluxo de upload. O
  teste HTTP até agora cobriu o contrato essencial, não toda a interface.
- Testar o transporte de Canais com entrada sintética, sem enviar WhatsApp,
  SMS ou e-mail. Confirmar o formato SSE e a regra de conclusão que exige
  `finish_reason=stop`.
- Rever o comportamento de runs interrompidos/reconexão. O adaptador atual
  executa runs em streaming na conexão HTTP e não oferece API de rejoin.
- Confirmar backup, janela de parada de novas gravações, paridade final,
  configuração de rota e procedimento de retorno ao principal. Não fazer a
  virada com base apenas nos testes desta página.
