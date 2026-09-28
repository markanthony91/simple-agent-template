---
type: Policy
title: Política de negociação
description: '- Elegibilidade para negociar: Cliente identificado (3 primeiros dígitos
  do CPF confirmados), contrato elegível e sem acordo ativo.'
tags:
- Cartão de crédito
- Will Bank
status: stable
generated:
  by: process:wiki-scaffold
  at: 2026-09-17 18:01:16+00:00
okf_version: '0.2'
scope: institution
product: cartao_de_credito
institution: will-bank
company: fastpay
inherits:
- global
- product:Cartão de crédito
override: []
policy_role: canonical
auxiliary_policies:
- limites-desconto.md
- parcelamento.md
- pagamento-parametros.md
- negociacao-parametros.md
section_path: COMPANIES/fastpay/INSTITUTIONS/will-bank/CARTAO_DE_CREDITO/policies
slug: politica-negociacao
negotiation:
  payment_types:
  - cash
  - installment
  max_installments: 10
  max_discount_percentage: '10'
  min_negotiated_amount: '50.00'
  min_installment_amount: '200.00'
  by_payment_type:
    cash:
      max_discount_percentage: '10'
      initial_offer_discount_percentage: '3'
      discount_tiers:
      - min_days_overdue: 0
        max_days_overdue: 30
        offer_discount_percentage: '5'
      - min_days_overdue: 31
        max_days_overdue: 90
        offer_discount_percentage: '8'
      - min_days_overdue: 91
        max_days_overdue: 180
        offer_discount_percentage: '10'
      - min_days_overdue: 181
        max_days_overdue: null
        offer_discount_percentage: '10'
    installment:
      max_discount_percentage: '0'
      offer_discount_percentage: '0'
  installment_overdue_rule:
    min_days_overdue: 181
    max_installments: 12
    min_down_payment_percentage: '20'
  down_payment:
    allowed: true
    min_percentage: '10'
payment:
  methods:
  - pix
  - boleto
  methods_by_payment_type:
    cash:
    - pix
    - boleto
    installment:
    - boleto
  delivery_channels:
  - email
---

# Política de negociação — regras próprias Will Bank

> Herda: `01_AGENTE/Principios de Negociacao`, `04_NEGOCIACAO` e `11_COMPLIANCE_E_PRIVACIDADE`. Este documento registra **apenas o que é específico da Will Bank**. O restante vale conforme **Global** e **Cartão de crédito**.

## Hierarquia das políticas

Este é o documento **canônico da oferta**: define quando e como o agente negocia. Em caso de conflito, esta política prevalece. Os números ficam nas políticas auxiliares:

- [Limites de desconto](./limites-desconto.md) — desconto máximo, faixas de atraso, alçadas e exceções
- [Parcelamento](./parcelamento.md) — máximo de parcelas, entrada, juros e valor mínimo da parcela
- [Parâmetros de pagamento](./pagamento-parametros.md) — meios aceitos, validade, prazo de baixa e comprovante
- [Parâmetros de negociação](./negociacao-parametros.md) — ordem de oferta, número de propostas, validade e reabertura

## Regras
- Elegibilidade para negociar: **Cliente identificado (3 primeiros dígitos do CPF confirmados), contrato elegível e sem acordo ativo.**
- Faixas de atraso com tratamento diferenciado: **181+ dias: parcelamento em até 12x com entrada mínima de 20%.**
- Exceções autorizadas: **Desconto acima do máximo ou entrada reduzida, apenas com aprovação do supervisor.**

## Parâmetros definidos pela instituição (onboarding)

_Última atualização pelo onboarding: 25/09/2026, 16:47:24._

- **Elegibilidade para negociar:** Cliente identificado (3 primeiros dígitos do CPF confirmados), contrato elegível e sem acordo ativo.
- **Faixas de atraso com tratamento diferenciado:** 181+ dias: parcelamento em até 12x com entrada mínima de 20%.
- **Exceções autorizadas:** Desconto acima do máximo ou entrada reduzida, apenas com aprovação do supervisor.


## Contrato executável do runtime

Os blocos `negotiation` e `payment` consolidam os parâmetros dos documentos
auxiliares desta mesma instituição e produto. São uma extensão deste runtime,
não campos obrigatórios do formato OKF. Os dados do cliente e os valores da dívida
continuam vindo das tools, após a identificação.

### Desconto e modalidade

- À vista: a primeira oferta utiliza os **3%** definidos no onboarding de
  `limites-desconto.md`. As faixas de atraso **5% / 8% / 10% / 10%** permanecem
  registradas; não substituir a primeira oferta automaticamente pelo teto.
- O runtime atual executa a primeira oferta configurada. Progressão de desconto
  exige contrato próprio e estado de negociação validado; não prometer aumento
  nem alterar percentual a partir de uma instrução do cliente.
- Parcelado: **0% de desconto**, sem juros. Somente **boleto**, conforme a
  orientação vigente deste piloto. Não oferecer PIX parcelado.
- À vista: PIX ou boleto. Link de pagamento permanece descrito no auxiliar, mas
  não é uma capacidade de emissão deste runtime.
- Valor mínimo negociado: **R$ 50,00**. Valor mínimo de cada parcela: **R$ 200,00**,
  inclusive após distribuir os centavos. O backend calcula e valida os valores.

### Parcelamento por atraso

- Até 180 dias: teto documental de **10 parcelas**, sem entrada obrigatória.
  Entrada opcional é permitida, com mínimo de 10% do valor negociado.
- A partir de 181 dias, prevalece a regra desta política canônica: até **12
  parcelas com entrada mínima de 20%**. Sem a entrada exigida, o backend retorna
  `down_payment_required` e o mínimo calculado. Confirme com o cliente antes de
  gerar. Não dispensar a entrada nem calcular seu valor pela LLM.
- Os limites cadastrais do cliente também são validados. Um teto na política não
  amplia automaticamente a elegibilidade devolvida pelo backend.
- O teto é um limite de validação, não a oferta inicial. Siga a progressão do
  Workflow; não anuncie espontaneamente o máximo de parcelas.

### Uso pelas tools e limites de execução

`down_payment_amount` é opcional e recebe o valor escolhido pelo cliente, em
reais, com ponto decimal. `installments` conta todos os pagamentos, incluindo a
entrada: entrada + 3 parcelas posteriores corresponde a 4 pagamentos. A entrada
é identificada como primeiro pagamento e o restante é dividido nos demais.
Não confundir o mínimo permitido com consentimento automático do cliente.

Depois da validação de identidade e da leitura deste documento, use seu caminho
canônico em `generate_payment_offer`. Aproveite modalidade, quantidade e meio já
informados. Somente `created=true` comprova proposta, acordo e instrução simulados.
Não há aprovação humana no fluxo automático; exceções citadas nos documentos
originais não concedem autorização para ultrapassar o contrato executável.

Com o boleto emitido, `get_boleto_second_copy` recupera a instrução existente;
não gera nova proposta. O envio por e-mail usa `send_payment_instruction` após
receber o endereço do cliente. Nenhum retorno de consulta confirma envio.

A documentação auxiliar também descreve validade comercial, agendamento,
reenvios e exceções. Não confundir o TTL técnico da simulação com prazo comercial,
nem afirmar que renegociação progressiva, links de pagamento ou aprovação
por supervisor foram executados por uma tool que não oferece essas capacidades.
