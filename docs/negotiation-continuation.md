# Continuação da revisão de negociação — 0.14.9

Status: implementação local; publicação e validação no Railway pendentes.
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

Resultado local: 468 testes da suíte e 13 cenários específicos aprovados (três
dos cenários específicos foram acrescentados após a execução da suíte). Cobertura
da suíte: 90%; middleware de continuação: 98%. Ruff e `git diff --check` aprovados.
Validação com modelo real e Playground publicado ainda pendente.

Antes de publicar: confirmar o artefato de produção e a ausência de deploys
concorrentes, executar o procedimento de backup do serviço, publicar somente
runtime e validar em sessão sintética no Playground. Canais e Chat não precisam
de alteração. Rollback: artefato 0.14.7, preservando o volume.
