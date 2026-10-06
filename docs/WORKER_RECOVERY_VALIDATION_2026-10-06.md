# Recuperação do worker e testes de clientes — 06/10/2026

Escopo: Agente de Homologação `accedeb1-4a8d-455e-a7ed-f4d2d7d92dec`,
deployment `7ad17203-f412-4f76-8094-e53dcbe8b400`, versão 0.17.3. O Agente
Principal continuou no deployment `75e22140-b751-4ac1-8372-222cd01fb051`.
O auto-deploy do Principal foi consultado no Railway e estava desativado.

Um run em execução recebe um lease de 30 segundos no PostgreSQL, renovado a
cada 5 segundos. Outro worker encerra como `failed`/`worker_lost` quando o
lease expira. O input não é reexecutado automaticamente: uma tool anterior
pode ter produzido um efeito externo, como o envio de uma instrução. O
operador deve reconciliar o resultado de negócio antes de tentar novamente.

## Evidências

| Verificação | Resultado |
| --- | --- |
| Runtime Python com PostgreSQL e Redis descartáveis | 490 passaram; 1 teste opcional ignorado por exigir chave Anthropic |
| Worker reiniciado com run órfão | Run terminou com `worker_lost`; input não foi reexecutado |
| Run ativo | Lease foi renovado; cancelamento continuou funcionando |
| Dockerfile e lock | Build local da versão 0.17.3 passou |
| Canais | 125 testes passaram; 95,67% de cobertura de linhas |
| Canais ↔ Runtime OSS local | Adaptador real concluiu `wait` e `stream` por HTTP com dados sintéticos e PostgreSQL/Redis descartáveis; nenhum envio à Meta |
| Canais ↔ homologação | Consulta autenticada do Assistant real passou por túnel privado; nenhum dado de cliente foi enviado |
| Playground | Build e teste de navegador passaram via Nix: OTP sintético, seleção de carteira e simulador |
| Homologação implantada | `/info` saudável; colunas e índice do lease presentes; OKF ativo com 572 arquivos |
| Conversa sintética na homologação | SSE HTTP 200, quatro eventos `values`, resposta final `ai` com `finish_reason=stop`, run `succeeded`; thread removida via API |
| Serviços públicos | Canais `/health` 200; Playground 200, catálogo sem login 401 e passthrough genérico 404 |

## Ainda necessário antes da virada

O Playground atual passa a URL do Runtime ao navegador e não envia a chave da
homologação. Seu passthrough genérico fica desativado com
`PLAYGROUND_ONLY=true`. Portanto, o teste de navegador provou a interface com
serviços sintéticos locais, não uma conversa Playground → homologação. Um
proxy autenticado no servidor é necessário para esse teste sem expor a chave.

O fluxo completo de Canais passou localmente contra o Runtime OSS; na
homologação foi feita apenas a consulta do Assistant, sem disparo de WhatsApp.
Faltam ainda reconciliação final dos dados operacionais, persistência dos
caminhos de simulador/ferramentas e ensaio controlado de rollback. Nenhum
tráfego de cliente foi redirecionado nesta etapa.
