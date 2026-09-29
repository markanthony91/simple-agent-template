# Consulta da condição antes da emissão

Status: implementado localmente em 0.15.0; não publicado.
Base: origin/main 1052d6e (0.14.12), incluindo as correções de retomada e
a atualização de saudação do outro agente. PR para main; publicação pendente.

## Contrato

Tool: `get_payment_offer_preview` (read_only).

```json
{
  "payment_type": "cash",
  "policy_path": "<caminho canônico retornado pelo OKF e já lido>"
}
```

Para parcelado, informar `payment_type="installment"` e `installments` escolhido
pelo cliente. `down_payment_amount` é opcional, em reais com ponto decimal;
`installments` inclui a entrada, exatamente como na emissão. Não há argumento
`method` ou `discount_percentage`.

Sucesso: `available=true`, `payment_type`, `debt_amount`, `discount_percentage`,
`discount_amount`, `negotiated_amount`, `installments`, `installment_amount`,
`installment_schedule`, `allowed_methods`, `policy_source`, `snapshot_id` e
`is_simulation=true`. `down_payment_amount` aparece quando há entrada.
Os valores monetários são strings decimais; são formatados para apresentação,
sem recalcular totais ou parcelas.

Não cria OFF/AGR/PAY, código dummy, entrega ou registro de consulta na sessão.
O resultado da tool continua no histórico normal do LangGraph; read_only não
significa desativar checkpoints do chat. Sessão inexistente não é inicializada
pela consulta. A emissão continua revalidando identidade, elegibilidade, recibo,
snapshot, política, instituição/produto, vigência, limites e meio de pagamento.

Falhas: `available=false`, `reason`. Exemplo: política draft, recibo ausente ou
desatualizado, escopo incorreto, valores mínimos, elegibilidade ou parcelas fora
do limite. `canonical_policy_required` traz `canonical_policy_path`: ler e tentar
uma vez. `down_payment_required` traz `minimum_down_payment_amount`: perguntar
ao cliente antes de usar esse valor. Nunca gerar pagamento para contornar falha.

## Trecho para substituir a etapa de consulta de desconto no Workflow

```markdown
### Consulta de condição à vista antes da escolha do meio

Entrada: identidade confirmada e política canônica aplicável já lida no OKF.

1. Quando houver intenção de consultar condição especial à vista, envie:
   "Entendi, {{customer_first_name}}. Vou verificar internamente se consigo
   uma condição especial para pagamento à vista hoje."
   Use a frase em uma mensagem própria, sem antecipar desconto ou valor.
   Se o nome não estiver disponível, comece com "Entendi.".
2. Chame get_payment_offer_preview(payment_type="cash", policy_path=<caminho
   canônico já lido>). Não informe method e não chame generate_payment_offer
   apenas para descobrir o valor final.
3. Aguarde o resultado. Somente available=true permite apresentar a condição.
   Use discount_percentage, discount_amount e negotiated_amount exatamente
   como retornados, formatando apenas a apresentação em reais/percentual.
4. Em uma nova mensagem, apresente a condição e pergunte qual meio o cliente
   prefere entre os retornados em allowed_methods. Se houver um único meio,
   informe-o sem exigir que o cliente repita a escolha. Se o desconto for zero,
   não afirme que conseguiu desconto ou condição especial.
5. Com a escolha atual do cliente e intenção de seguir, chame
   generate_payment_offer com payment_type, method, policy_path e os demais
   termos já confirmados. Não peça novamente informações conhecidas.
6. available=true representa consulta; created=true representa emissão.
   Só created=true permite apresentar código de pagamento. Depois, siga a
   etapa existente de obtenção do e-mail e send_payment_instruction.
7. Se a consulta falhar, não prometa condição, não calcule pela LLM/calculator
   e não gere PIX/boleto. Para canonical_policy_required, leia o caminho
   retornado e tente uma vez; para outras falhas, esclareça o que falta.

A pausa de cinco segundos é aplicada pelo runtime no streaming após a frase
de verificação. Não solicitar que a LLM conte segundos nem criar uma tool de
espera. A consulta e o modelo podem acrescentar tempo à resposta.
```

A frase da abertura deve continuar em uma única linha/mensagem no chat; as
quebras do exemplo acima são apenas organização do documento. O marcador
`negotiation_review_delay_ms = 5000` não é interpretado por esta base publicada:
o gatilho continua sendo a frase atual.

Remova da etapa antiga a instrução de gerar uma oferta para conhecer o valor
antes de escolher PIX/boleto. Adicione a nova tool à lista de tools permitidas.
Se o AGENTS.md salvo no Assistant sobrescrever o padrão do projeto, acrescente:

> Para consultar a condição antes da escolha do meio, use get_payment_offer_preview.
> available=true não emite pagamento. Use generate_payment_offer somente após
> a escolha atual do cliente ou quando a política permitir um único meio.

## Validação e limites

Testes usam bundles e cadastros sintéticos, sem chamadas LLM, e-mail ou WhatsApp.
Cobrem as faixas 5%/8%/10%, PIX e boleto posteriores à consulta, parcelamento,
entrada opcional/obrigatória, centavos, política auxiliar, recibo, publicação,
vigência, escopo, sessão, elegibilidade, registro/enablement e auditoria numérica.
O teste de leitura compara o estado e o arquivo SQLite antes/depois e impede
qualquer chamada a SessionStore.transaction durante consultas repetidas.
Os caminhos de agente usam modelo falso: comprovam roteamento e contratos,
não que uma LLM real seguirá todas as instruções.

Validação local em 29/09/2026:
- Suíte completa: 514 passaram, 1 smoke externo ignorado por falta de
  ANTHROPIC_API_KEY, cobertura total 90,25% (limite exigido: 80%).
- Após adicionar a integração consulta + pausa: 35 testes específicos passaram.
- A integração usa create_agent com modelo falso, get_payment_offer_preview real
  e CashMessageDelay no SSE: intervalo entre abertura e continuação >= 4,9 s
  com sleep(5) real, valor vindo da consulta e nenhum pagamento persistido.
- Lint dos arquivos alterados e git diff --check passaram.

O mecanismo existente de pausa continua coberto pelos testes de message_delay.
Não houve validação de streaming no ambiente publicado nesta tarefa.
A consulta não adiciona um bloqueio determinístico que prove escolha do meio:
a fidelidade da LLM precisa de canário após deploy e ajuste do Workflow ativo.
Esse canário e a publicação ficam pendentes de autorização.
Acionar a consulta automaticamente a partir do texto da abertura não faz parte
desta mudança: a LLM chama a tool seguindo o Workflow. O usuário reiterou
explicitamente que não deve haver deploy nesta etapa.
