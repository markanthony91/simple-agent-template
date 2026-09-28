# Segunda via de boleto

Status: publicado no runtime 0.14.1; tabelas aditivas presentes, sem violações de FK.
O teste conversacional publicado não chegou à recuperação: a política canônica
sem `negotiation` impediu criar o boleto. Os testes locais passaram; isso não
comprova o caminho completo em produção. Ver [release](RELEASE_0141_2026-09-28.md).

## O que foi implementado

`generate_payment_offer` persiste a sessão, o acordo e a instrução emitida em uma
única transação SQLite. As tabelas aditivas `payment_agreements` e
`payment_instructions` guardam os dados originais; não recalculam valores nem
criam uma segunda negociação. A origem é `origin_session_id`.

`get_boleto_second_copy(agreement_id="", installment_number=null)` é uma consulta.
O backend exige identidade validada e obtém empresa/tenant, carteira, cliente e
dívida de `session_contexts`. Todos os quatro precisam coincidir para consultar
outra sessão. O modelo não fornece CPF, telefone, cliente ou tenant como filtro.
Sem vínculo cadastral, o Playground consulta somente a sessão atual. Campos de
texto como `company` inferido do OKF não são autorização de acesso.

Resultados:

| Resultado | Orientação |
|---|---|
| `found=true` | Apresentar o código e valor exatos, identificando a simulação. |
| `identity_verification_required` | Confirmar identidade e retomar a intenção. |
| `agreement_selection_required` | Usar as opções retornadas para identificar o acordo. |
| `installment_selection_required` | Perguntar somente qual parcela. |
| `boleto_not_found` | Nenhum acordo localizado no escopo consultável; não prova ausência global. |
| `boleto_not_issued` | Não há instrução de boleto emitida para a seleção. |
| `agreement_not_payable` / `payment_not_payable` | Informar o status retornado; não apresentar código. |
| `boleto_reissue_required` | Vencimento registrado ultrapassado; a consulta não reemite. |
| `query_failed` | Consulta não concluída; não afirmar inexistência. |
| `real_boleto_not_supported` | Esta implementação suporta apenas a DEMO. |

Seleções retornam no máximo 20 itens e `has_more`. Não selecionar automaticamente
entre acordos ou parcelas ambíguos. `due_date=null` significa que o vencimento não
foi registrado. A data mostrada no e-mail atual é calculada no envio e NÃO é
usada como vencimento do boleto. Não completar esse campo por inferência.

A comparação de vencimento usa `America/Sao_Paulo`. Timestamps internos permanecem
UTC. Os cálculos existentes de atraso não foram alterados nesta feature.

## Limites que permanecem

- Os disparos atuais da DEMO geram IDs de cliente/dívida a partir do thread.
  Portanto, outro disparo ainda não é automaticamente o mesmo cadastro. Antes de
  demonstrar segunda via entre disparos reais, o adaptador precisa vincular ambos
  ao mesmo cadastro confiável. Não associar por nome ou pelos três dígitos do CPF.
- A vinculação compartilhada foi exercitada com dados sintéticos nos testes;
  não foi criado um endpoint público para mudar o dono da sessão.
- O gerador emite inicialmente a primeira instrução. O cronograma salvo não
  equivale a boletos emitidos para todas as parcelas; a consulta não cria os demais.
- Não há backfill automático de acordos anteriores. Novas gerações são indexadas;
  registros legados precisam de migração explicitamente autorizada para consulta.
- Não há integração com emissor real, PDF, reemissão ou atualização de vencimento.
- `send_payment_instruction` continua restrita ao e-mail e à sessão original.
  Recuperar um boleto de outra sessão não autoriza essa tool a enviá-lo por e-mail.

## Reset preservado

`/reset-demo` continua aceito apenas em sessões marcadas como Demo. Ele limpa
identidade e estado operacional e, na mesma transação, exclui os novos registros
cuja `origin_session_id` é a sessão reiniciada. As instruções são excluídas por FK
com cascade. Não apaga acordos de outras origens nem importa cópias para a sessão
que consultou uma segunda via. O histórico de conversa mantém o comportamento
anterior; reset não apaga texto já entregue.

Uma consulta em outra sessão deixa de encontrar o acordo após reset da origem.
Resetar só a sessão consultora não remove o acordo original. Esta regra foi
implementada localmente para não deixar registros recuperáveis após o reset que
o usuário já espera. Nenhum comando de reset foi executado em produção.

## WhatsApp: o que significa reutilizar o envio

Hoje o adaptador de WhatsApp chama o runtime, recebe a resposta final do agente e
a envia como texto ao remetente. A nova tool retorna o código ao agente; o agente
compõe a resposta e o adaptador entrega pelo mesmo caminho. Não é necessário um
segundo disparo dentro da tool. Isso evita duas mensagens concorrentes e usa o
tratamento de entrega/retry já existente no canal.

`found=true` comprova recuperação, não envio nem entrega. Não usar `sent=true` para
essa consulta. Não pedir e-mail para responder no próprio WhatsApp. Esta rodada
não altera Canais e não valida entrega real. PDF exigiria suporte a documento.

## Trecho para o Workflow

```markdown
### Segunda via de boleto
Entrada: cliente pede um boleto já existente, inclusive de atendimento anterior.
Preserve o pedido durante a identificação; não iniciar nova negociação.
Se a identidade não estiver validada, use verify_and_get_customer e aguarde sucesso.
Consulte get_boleto_second_copy, reaproveitando acordo/parcela já conhecidos.
Se houver seleção pendente, solicite apenas o dado faltante e consulte novamente.
Com found=true, apresente o código e valor retornados, marcando a simulação.
Informe vencimento apenas se due_date_available=true. Não calcule outro.
Não encontrado: explique o limite da consulta e ofereça consultar a pendência;
negociar novamente exige que o cliente queira seguir.
Falha técnica: informe que a consulta não pôde ser concluída, sem dizer que não existe.
Pago/cancelado/vencido: explique o status; não reemita nem gere outro acordo.
Saída: segunda via apresentada ou resultado explicado, sem prometer entrega externa.
```

Políticas e procedimentos institucionais continuam vindo do OKF. A simples
recuperação do documento existente não usa `generate_payment_offer` nem exige
pesquisar novamente descontos e limites para recalcular um acordo já firmado.

## Trecho para AGENTS.md

```markdown
Use somente ferramentas habilitadas no manifesto do runtime e seus argumentos reais.
get_boleto_second_copy consulta uma instrução existente; não emite, recalcula ou envia.
O backend determina o escopo pelo cliente/dívida vinculados à sessão verificada.
Use agreement_id retornado pela tool e installment_number quando necessário.
Somente found=true permite apresentar o payment_code e amount exatamente retornados.
Não confunda query_failed com boleto_not_found. Não repita a consulta sem novo dado.
Não invente vencimento, PDF, segunda via real ou confirmação de envio.
```

## Parametrização de ferramentas futuras

O projeto já possui `ToolRegistry`, listagem administrativa e habilitar/desabilitar
por nome; o middleware filtra o manifesto e bloqueia chamadas desabilitadas.
A nova tool está cadastrada ali e no conjunto financeiro, que bloqueia sessões sem
cadastro. `requires_auth` é metadado; a verificação real é feita dentro da função.

Para cada nova ferramenta:
1. Implementar contrato, validação, isolamento, retorno objetivo e testes no backend.
2. Registrar a função no grafo e metadados no catálogo. Cadastro textual não cria código.
3. Definir nome, descrição de quando usar, parâmetros, leitura/escrita, requisitos,
   efeitos e indicadores de sucesso/falha. A docstring e o schema vão ao modelo.
4. No AGENTS.md, documentar uso técnico comum; no Workflow, somente a etapa e
   condições de entrada/saída. Evitar copiar regras comerciais do OKF.
5. Habilitar pelo catálogo e validar que desabilitar também impede execução.

Não foi criado um interpretador de código, cadastro de endpoints arbitrários ou
novo roteador por intenção. Novas capacidades ainda precisam ser implementadas.
Os trechos acima são exemplos para revisão; o Workflow e o AGENTS.md salvos no
Assistant de produção não receberam esses exemplos. A única alteração do
Assistant nesse rollout foi alinhar o contrato de horário de `utc_now`.
