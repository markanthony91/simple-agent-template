# Consulta de desconto com pausa — implementação local

Base 0.14.6 / 312cd9c, preservando a correção de checkpoints e o resumo parcelado.
Candidato local 0.15.0. Nenhum deploy, restart, mudança no Assistant salvo ou OKF.
Canais tem alteração pareada local em feat/cash-discount-pause; o chat não requer
mudança de código para mostrar os eventos values já suportados.

`check_cash_payment_condition(policy_path)` consulta somente a modalidade à vista
para cliente identificado, depois da leitura da política canônica. A decisão de
chamar é semântica, feita pela LLM; não há lista de frases/regex de intenção.
O middleware substitui o conteúdo da chamada pela mensagem determinística:

> Entendi, Eduardo. Vou verificar internamente se consigo uma condição especial para pagamento à vista hoje.

Essa atualização de mensagem é emitida antes da execução da tool. A execução
assíncrona aguarda cinco segundos com asyncio.sleep; só depois abre a transação
curta de consulta/cálculo. Não mantém conexão/transação de banco durante a pausa.
No caminho síncrono a espera ocorre na thread de execução, não no event loop.
A pausa não é um mecanismo de aprovação humana nem muda a política.

Usa os validadores e o gerador de oferta existentes. Guarda a oferta disponível
para conferência numérica, mas não cria acordo, PIX/boleto ou envio. Não aceita
percentual ou valor financeiro calculado pela LLM. Respeita faixas por atraso,
identidade, elegibilidade, política publicada, escopo e recibo de leitura.

Quando o retorno autoriza 3%, R$ 5.697,22 e ambos os métodos:

> Eduardo, consegui uma condição especial para pagamento à vista hoje, com 3% de desconto. Com essa condição, o valor para quitação fica em R$ 5.697,22. Você prefere pagar por PIX ou boleto?

Nome, desconto, valor e meios vêm do backend. Sem desconto, não afirma ter
conseguido condição especial; com um único meio, informa apenas aquele meio.
Falhas não geram frase de sucesso. Erros recuperáveis de navegação usam o limite
de uma recuperação já existente; não repetem a pausa no mesmo turno.

Após escolha do meio, generate_payment_offer revalida normalmente a política
e só então cria o acordo e pagamento. A consulta não substitui essa validação.

## Integração e limites

- Tool registrada no manifesto e bloqueada para sessões sem dívida vinculada.
- A chamada deve vir sozinha e sem texto da LLM. Chamadas paralelas da consulta
  são recusadas antes do cálculo; o fluxo existente limita a recuperação. O template substitui o conteúdo
  persistido após o modelo; tokens eventualmente emitidos antes dessa atualização
  não são uma garantia de supressão de conteúdo indevido da LLM em streaming.
- Playground usa os eventos values já existentes e mostra a chamada e a resposta
  em momentos separados. O atraso mínimo é entre eventos do servidor; latência e
  buffering da rede podem mudar o intervalo percebido pelo cliente.
- Canais possui patch pareado local: runs/stream para turnos normais, entrega do
  anúncio antes da conclusão e persistência dos blocos. Exige intervalo mínimo de
  cinco segundos após o aceite do primeiro pelo provedor. O worker ainda é serial.
  Este patch isolado com Canais antigo entrega apenas a resposta final no WhatsApp.
- O AGENTS.md local documenta a tool. Instruções salvas do Assistant continuam
  intactas; na ativação, alinhar o Workflow e AGENTS reais ao manifesto publicado.
- Nenhum teste real com devedor, chamada LLM, email, WhatsApp ou banco de produção.

## Orientação para o Workflow na futura ativação

Quando o cliente identificado pedir desconto/condição à vista sem ainda escolher
o meio, preserve o contexto e leia a política aplicável. Use
check_cash_payment_condition sem antecipar nome de método, percentual ou valor.
O backend conduz as duas mensagens e a pausa. Continue após a escolha do cliente
usando generate_payment_offer. Se o meio já foi escolhido e o cliente pediu a
proposta, siga o fluxo normal de geração, sem perguntar o mesmo dado novamente.

## Evidência local

O teste do grafo executa a espera real de cinco segundos e observa duas mensagens
AI; durante a pausa outra tarefa consegue escrever na mesma sessão. Cancelamento
nesse intervalo não cria oferta nem pagamento. Faixas 5%/8%/10%, desconto zero,
meio único e bloqueios de identidade/leitura continuam cobertos.

Navegador Chromium com chat compilado local 0.6.5 e API sintética em localhost:
primeira frase visível antes da segunda, sem duplicação; intervalo observado
5.337 ms. Essa conferência testa o consumidor de eventos, não a escolha semântica
de uma LLM real nem a entrega no aparelho WhatsApp. Nenhuma chamada externa.

Suíte local: 463 testes aprovados, 1 ignorado, cobertura 89,69%; Ruff e diff-check
aprovados. Canais pareado: 108 testes, cobertura 94,78%.
