# Contrato canônico por modalidade — runtime 0.14.2

## Extensão para políticas com limites por atraso

O documento canônico pode declarar `max_discount_tiers` em cada ramo de
`by_payment_type` e `installment_tiers` em `negotiation`. O backend seleciona a
faixa pelo atraso da dívida na sessão, limita o desconto solicitado e a
quantidade de pagamentos, e exige `down_payment.min_amount` quando há
parcelamento. A entrada conta como primeiro pagamento. Omissão de
`discount_percentage` gera proposta sem desconto nesse contrato; as políticas
legadas continuam com o percentual fixado no documento. Lacunas ou sobreposições
na faixa aplicável falham fechadas. A elegibilidade individual pode impor um
teto adicional. A política v7 deixa o dia 181 sem faixa; esse dia exige correção
da fonte comercial antes de qualquer proposta.

Desconto positivo exige `discount_basis: current_amount` na modalidade. A v7
descreve descontos sobre encargos ou principal, mas o simulador só entrega o
saldo total; por isso seu frontmatter não declara essa base e uma proposta com
desconto positivo é recusada até que a origem financeira forneça os componentes.

O gerador lê `negotiation` e `payment` do frontmatter do documento canônico.
Esses campos são uma extensão do runtime, não uma exigência geral do OKF 0.2.
O schema antigo continua aceito. O novo `by_payment_type` separa desconto à vista
de desconto parcelado, sem transformar desconto à vista em desconto de boleto parcelado.

Fonte desta revisão: bundle `okf_wiki_v6_2026-09-28-20260928T025106Z-f44695b6`.
O manifesto registra hashes dos seis documentos consultados. Só o documento
[politica-negociacao.md](will-bank/politica-negociacao.md) é alterado no bundle.
O produto técnico foi alinhado ao cadastro (`cartao_de_credito`); o nome de
exibição segue Cartão de crédito. Não há alteração de cadastro de clientes.

## Interpretação das regras publicadas

- Primeira oferta à vista: 3%, conforme onboarding em limites-desconto.md.
- Faixas 5%/8%/10%/10% preservadas. `initial_offer_discount_percentage` identifica
  explicitamente a primeira oferta e não pode ultrapassar nenhuma faixa.
- Sem `initial_offer_discount_percentage`, `discount_tiers` mantém seu comportamento
  anterior: seleciona o percentual diretamente pelo atraso confiável.
- Com primeira oferta declarada, chamadas legadas também não podem elevar seu
  desconto. Progressão posterior exige contrato de negociação e consentimento;
  não foi implementada nesta mudança.
- Parcelado: 0%, mínimo de R$ 200 por parcela, mínimo negociado de R$ 50.
- Teto geral: 10 pagamentos; regra canônica de 181+ dias: até 12, com entrada
  mínima de 20%. Elegibilidade cadastral pode restringir esses tetos.
- Entrada opcional nos demais casos: mínimo de 10%, conforme parcelamento.md.
- PIX e boleto à vista; parcelamento somente boleto, como solicitado no piloto.
- Os valores são parâmetros da empresa no documento, não constantes do código.

## Entrada opcional

`generate_payment_offer` aceita `down_payment_amount`, uma string decimal em BRL;
o padrão `"0"` mantém o cronograma sem entrada. Exemplo: `"1000.00"`.
O cliente escolhe o valor; o modelo não calcula nem inventa uma entrada.
`installments` mantém o significado de quantidade total de pagamentos, inclusive
a entrada. Entrada mais três pagamentos posteriores significa `installments=4`.

O backend calcula o total, valida a entrada e distribui o restante nos demais
pagamentos, com fechamento exato dos centavos. A primeira instrução emitida é a
entrada. O código e a segunda via dessa instrução mantêm o mesmo valor.
Parcela mínima é verificada sobre as parcelas restantes, não sobre a entrada.

Se faltar uma entrada exigida ou o valor ficar abaixo do mínimo:

```json
{"created": false, "reason": "down_payment_required", "minimum_down_payment_amount": "1174.69"}
```

Esse número de exemplo vem do backend para saldo sintético R$ 5.873,42 e mínimo
20%, arredondado para cima ao centavo. Nenhum acordo é criado nesse retorno.
Após confirmação do cliente, a LLM pode reenviar a tool com esse valor.

O chat identifica `Entrada (1ª parcela)` e apresenta cada pagamento em uma linha.
O contexto de e-mail identifica `1 (entrada)`; os pagamentos seguintes seguem a
numeração total e o intervalo já existente de 30 dias. Não foi alterado o template
de Canais nem enviado e-mail real. Pagar só a entrada não liquida o acordo inteiro;
a simulação de baixa exige todos os pagamentos do cronograma liquidados.

## Instruções para o gerador de bundles

Consolide no documento canônico os parâmetros aprovados e compatíveis com o
runtime. Não basta adicionar `policy_role: canonical`: o corpo em prosa não é
interpretado pelo validador financeiro. Documentos auxiliares continuam servindo
para explicação e navegação; não autorizam geração por si mesmos.

Use os identificadores técnicos do cadastro em `institution` e `product`, preserve
o ciclo de vida e referências existentes, e valide o bundle antes da publicação.
Não publique silenciosamente conflitos entre o corpo e o frontmatter. Datas,
validade comercial, juros, links de pagamento e exceções humanas não passam a ser
capacidades implementadas só porque aparecem no texto.

## Rollout

Publicar o runtime compatível antes do novo bundle. As versões publicadas são
imutáveis; criar draft do ativo, editar somente o canônico, validar e publicar.
A base anterior permanece disponível para rollback. Conversas antigas preservam
seu snapshot: testar em conversas novas, sem resetar conversas reais.
