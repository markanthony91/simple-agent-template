# Workflow: revisão com pausa de cinco segundos

A pausa é responsabilidade do runtime 0.14.10 e usa a frase existente como gatilho.
`negotiation_review_delay_ms = 5000` não é interpretado como comando nessa versão.
Não há uma nova tool nem um evento externo necessário para continuar.

O Workflow ativo v47 já orienta a continuação na mesma execução. Ao editar a
etapa existente, substitua a orientação correspondente; não duplique o bloco.
Mantenha os critérios comerciais de entrada da etapa e as políticas OKF.

## Trecho de referência

```text
Quando os critérios da etapa de revisão de desconto à vista forem atendidos,
inicie a resposta exatamente com a abertura abaixo, sem título, aspas ou negrito.
Substitua {{customer_first_name}} pelo primeiro nome já confirmado na sessão:

Entendi, {{customer_first_name}}. Vou verificar internamente se consigo uma condição especial para pagamento à vista hoje.

Após a abertura, continue na mesma execução usando o contexto e as tools
existentes. Não encerre o turno aguardando outra mensagem do cliente ou evento.
Não solicite uma tool de espera: o runtime aplica a pausa na entrega.
Consulte a política aplicável no OKF quando necessário e apresente apenas
condições comprovadas. Não invente desconto nem calcule valores financeiros.
Se faltar uma escolha obrigatória, pergunte somente o que falta; não escolha
PIX ou boleto pelo cliente. Se a consulta falhar, explique a impossibilidade.
```

## Teste manual curto

1. Abra uma conversa sintética nova e conclua a identificação.
2. Informe: “Quero pagar à vista. Tem desconto?”
3. Depois: “Sem desconto não consigo fechar. Se conseguir reduzir, pago à vista hoje.”
4. A abertura deve aparecer primeiro. A continuação deve aparecer automaticamente
   após pelo menos cinco segundos, sem enviar “oi” ou clicar para continuar.
5. Se o meio de pagamento não foi escolhido, o agente deve perguntar somente
   por ele, respeitando a política; o teste não autoriza envio de e-mail.

O primeiro pedido genérico de desconto não é o gatilho comercial da etapa de
insistência do v47. Consultas e inferência podem tornar o intervalo maior que
cinco segundos; esse tempo não é um SLA de conclusão. `/runs/wait` retorna o
resultado completo e não serve para medir a pausa visual.
