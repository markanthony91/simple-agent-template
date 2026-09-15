---
type: Policy
title: Negociação sintética do piloto
status: draft
okf_version: "0.2"
institution: banco-aurora
product: cartao_de_credito
test_only: true
effective_from: "2026-01-01T00:00:00Z"
effective_until: "2027-01-01T00:00:00Z"
source: Cenário sintético de validação, sem efeito comercial
negotiation:
  max_installments: 6
  max_discount_percentage: "0"
  payment_types: [cash, installment]
---

# Negociação sintética do piloto

## Escopo e vigência

Somente cliente sintético da instituição `banco-aurora`, produto `cartao_de_credito`.
O campo `status` acima determina o ciclo de vida: draft exige revisão humana;
published permite uso neste laboratório sintético durante a vigência declarada.
Não altera as políticas já publicadas nem concede condições a clientes reais.

## Condições do cenário

O teste aceita pagamento à vista em uma parcela ou parcelamento em até seis
parcelas, sem desconto. Não há juros adicionais neste cenário sintético.
Os limites de elegibilidade do cliente podem restringir estas condições.
Este cenário não inclui entrada separada; isso não representa uma proibição
para outras políticas nem transforma entradas opcionais em obrigatórias.

## Fonte dos valores

Saldo, cliente e dívida não ficam neste documento. Devem ser consultados nas tools
transacionais após a validação da identidade na conversa.
Todo valor de proposta, inclusive pagamento à vista sem desconto, deve vir de
`generate_offer`. Não calcular exemplos financeiros na resposta.
Apresentar o total e o cronograma retornados; parcelas podem diferir por centavos.

## Confirmação

Somente uma oferta válida retornada pelo motor pode ser apresentada para aceite.
O cliente confirma o ID exato como nova mensagem antes de `create_agreement`.
O fechamento permanece simulado, sem gerar cobranças ou ações externas.
