# Continuação da revisão de negociação — 0.14.10

Status: 0.14.10 publicada; compatibilidade da retomada 0.14.11 em validação local.
Base: artefato publicado 0.14.7 (`7936185`). A configuração de Workflow da
branch `feat/workflow-review-delay` (0.14.8 local) não faz parte desta alteração.

## Causa comprovada

Na conversa do Playground encerrada em 28/09/2026 às 23:44 (America/Sao_Paulo),
a LLM emitiu a abertura esperada com `finish_reason=stop` e nenhuma tool.
O Workflow v47 mandava continuar; a consulta começou somente após outra mensagem
do cliente. O middleware HTTP publicado apenas atrasava a entrega e não retornava
a execução ao modelo. Um teste feliz de temporização não cobria esse encerramento.

## Correção

`NegotiationContinuationMiddleware.after_model` reconhece somente uma resposta
composta pela frase existente de verificação, sem tool calls. Marca essa abertura
com `negotiation_review_resumed` e usa a transição nativa `jump_to=model` uma vez.
A instrução interna de continuação entra apenas no pedido ao modelo, sem adicionar
mensagem do cliente ou SystemMessage ao histórico persistido. Nenhuma tool nova.

O limite vale desde a última mensagem humana: outras sessões e novos turnos não
herdam a tentativa. Uma repetição da abertura depois da retomada é substituída
por indisponibilidade; não ocorre outra retomada. Respostas completas e chamadas
de tools que já estão em andamento seguem o fluxo normal.

Não altera valores, políticas, validação de identidade, documentos OKF, Workflow,
AGENTS.md ou configuração do modelo. A orientação interna exige obter os dados
faltantes e não escolher o meio de pagamento. Isso não equivale a uma nova
validação determinística da escolha de PIX/boleto: os controles financeiros
existentes continuam sendo a autoridade de execução.

A espera permanece em `CashMessageDelay`: uma pausa assíncrona de cinco segundos
por stream. Não há outra espera no agente. A continuação pode demorar mais se
consultas ou inferência levarem mais tempo; cinco segundos não são SLA de conclusão.
`runs/wait` recebe o resultado completo sem pausa visual.

Logs `NEGOTIATION_REVIEW_CONTINUATION` incluem hostname, ID da mensagem e status `resumed` ou
`exhausted`, sem texto da conversa ou dados pessoais. O marcador no checkpoint
permite verificar se a recuperação foi necessária.

## Validação

Testes executam o grafo LangChain real com modelo/consultas sintéticos e os dados
isolados pelo conftest do projeto. Abrangem caminhos síncrono/assíncrono, interrupção
após anúncio, limite da retomada, novo turno, tools sem duplicação, respostas
completas, falha de provedor, isolamento de sessões e streaming com a pausa existente.
Não enviam mensagens, e-mails ou pagamentos reais.

Resultado local: 474 testes aprovados, incluindo 13 cenários de continuação e
regressões do streaming nativo do Playground. Cobertura da suíte: 90%; middleware
de continuação: 98%. Ruff e `git diff --check` aprovados.
Validação com modelo real e Playground publicado ainda pendente.

Antes de publicar: confirmar o artefato de produção e a ausência de deploys
concorrentes, executar o procedimento de backup do serviço, publicar somente
runtime e validar em sessão sintética no Playground. Canais e Chat não precisam
de alteração. Rollback: artefato 0.14.7, preservando o volume.

## Complemento encontrado no teste publicado

No primeiro canário de 0.14.9, o modelo produziu abertura e continuação, mas o
Playground recebeu ambas sem intervalo. O SDK solicita `messages-tuple`; o servidor
emite deltas no evento `messages`, ausente no filtro de 0.14.7. A pausa posterior
do snapshot `values` não protege texto já exibido. A versão 0.14.10 cobre esse
formato também; o teste de regressão inclui mensagem inteira e fragmentos de 7
e 1 caractere, seguida de snapshot, preservando texto e metadados uma única vez.

## Resposta vazia na retomada com o provedor real

O canário de 0.14.10 confirmou pausa visual de 7,7 segundos com consultas OKF.
O cenário de encerramento após anúncio, porém, produziu `finish_reason=no_content`
na segunda chamada em dois testes isolados. O runtime corretamente rejeitou essa
resposta vazia. A 0.14.11 preserva a abertura e o marcador no estado, mas omite a
abertura somente no pedido imediato de continuação ao modelo. A orientação
temporária informa que ela já foi enviada. O pedido volta a terminar na mensagem
original do cliente; resultados posteriores de tools continuam integralmente
no contexto. Nenhum novo retry e nenhuma mensagem humana artificial.
