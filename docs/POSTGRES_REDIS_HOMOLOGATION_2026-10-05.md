# Homologação PostgreSQL, Redis e OKF — 05/10/2026

Escopo: projeto Railway `511a294c-8d6a-4906-bd26-e8e33011eac5`, ambiente
`8830dd97-8668-467d-b2f5-6ebcb8807969`. Nenhum cliente foi roteado para o
Agente de Homologação (`accedeb1-4a8d-455e-a7ed-f4d2d7d92dec`). O Agente
Principal (`861cf8e9-935f-4673-baf0-6bb438eac5fb`) permaneceu no deployment
`75e22140-b751-4ac1-8372-222cd01fb051`.

## OKF

O canário estava sem bundle ativo porque `OKF_DATA_ROOT` apontava para
`/tmp/canary-data/okf`, apesar de o volume persistente estar em `/data`. Foi
copiado somente o bundle publicado ativo do principal e seu `active.json` para
`/data/okf` no canário. O hash de conteúdo conferiu com o manifesto:
`4827e5652977445cddf913d070caea0b95c8304b1b400335044601145dd95ae4`.
São 572 arquivos Markdown. A variável `OKF_DATA_ROOT` foi corrigida somente
no canário, que foi redeployado como
`8ceb7231-73eb-4972-adc9-0d037b650ece`.

Após o deploy, `okf_admin.status` retornou `active=true`, `file_count=572` e o
mesmo ID de bundle. A leitura de `index.md`, `limites-desconto.md` e
`parcelamento.md` passou. Nenhuma política foi alterada. Esta cópia é pontual;
publicações posteriores no principal não são sincronizadas automaticamente
com o canário. Antes da virada, comparar novamente o bundle ativo e estabelecer
um fluxo único de publicação.

## Testes

- Suíte Python no código do canário, com PostgreSQL e Redis descartáveis:
  489 passaram, 2 foram ignorados por pré-condições opcionais.
- Inicialização em PostgreSQL novo, sem histórico SQLite: 1 passou em banco
  descartável isolado.
- Transporte de Canais para WhatsApp: 5 passaram; streaming, progresso,
  deduplicação e tratamento de falhas: 8 passaram. São testes com transporte
  simulado; nenhuma mensagem foi enviada à Meta.
- No canário implantado, conversa sintética pelo Assistant principal da
  homologação: HTTP 200, quatro eventos `values`, mensagem final `ai` com
  `finish_reason=stop`. A thread sintética foi excluída via API (204).
- `okf_admin.status` passou pela API autenticada após o redeploy. O principal
  permaneceu no mesmo deployment.

## Limites que impedem a virada agora

1. Um teste local inseriu uma execução sintética no estado `running`, iniciou
   um worker novo e consultou o run após 2,5 segundos. Ele continuou em
   `running`. `_claim_run()` seleciona apenas `queued`; não existe recuperação
   automática do trabalho que o worker perdeu após uma queda. É necessário
   definir lease, timeout e política de retry/idempotência antes de enviar
   tráfego real.
2. O novo Playground usa URL de Runtime no navegador e desativa seu proxy
   genérico com `PLAYGROUND_ONLY=true`. O canário não tem domínio público e
   exige `X-Api-Key`. Falta um caminho autenticado, sem expor o token ao
   navegador, para testar a interface real contra o canário.
3. Os testes de Canais foram locais. Ainda falta um ensaio integrado de entrada
   sintética usando a rota real Canais → canário, sem envio ao provedor.
4. A paridade de sessões, acordos, instruções, Assistants e histórico é uma
   fotografia de 02/10. É preciso reconciliar o delta imediatamente antes da
   virada. Se o histórico antigo for descartado, novas conversas começarão sem
   retomada automática; registros operacionais não devem ser descartados.
5. `SIMULATOR_ROOT`, `TOOL_REGISTRY_ROOT` e `SESSION_ROOT` do canário ainda
   apontam para `/tmp/canary-data`. Confirmar quais desses dados devem
   persistir antes de usar o canário como Runtime principal; as sessões estão
   configuradas com `SESSION_BACKEND=postgres`.

Redis é coordenação efêmera; PostgreSQL guarda runs e checkpoints. O OKF
continua sendo um bundle de documentos em `/data/okf`. Esta etapa não moveu o
OKF para PostgreSQL nem mudou o serviço separado de OKF.
