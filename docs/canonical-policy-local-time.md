# Política canônica e horário local — somente local

## Diagnóstico e recuperação

Na conversa `01a0e960-ca04-73c0-a0e7-c013beb07b0a`, o agente passou
`limites-desconto.md` a `generate_payment_offer`. O documento lido tinha
`policy_role: auxiliary` e `canonical_policy: politica-negociacao.md`, mas não o
bloco `negotiation`. O retorno anterior era `policy_terms_undefined`, terminal.
Não se deve mudar o auxiliar para canonical nem duplicar os parâmetros financeiros.

Agora o runtime retorna:

```json
{
  "created": false,
  "reason": "canonical_policy_required",
  "canonical_policy_path": "<caminho canônico existente no mesmo snapshot>"
}
```

A referência pode ser relativa ao documento ou começar por um diretório raiz
reconhecido do OKF. O resolver existente verifica existência, grafia e fronteira
do bundle. Caminhos absolutos, URLs, subida com `..`, destino ausente, autorreferência
e symlink para fora do bundle são recusados. O documento auxiliar também precisa
ter recibo válido de leitura na sessão; retorno de ponteiro não é autorização.

A LLM recebe orientação para ler o alvo com `okf_read` e repetir a geração uma vez,
com os mesmos termos já escolhidos. O backend não procura outra política nem lê
as condições em lugar do agente. Referências cíclicas não causam tentativas sem
limite. `policy_terms_undefined` continua terminal para política realmente incompleta.
O campo `policy_role` permanece opcional nos documentos que já eram executáveis.

A política alvo ainda deve satisfazer identidade, recibo/hash, snapshot, escopo,
publicação, vigência, elegibilidade, desconto, parcelas e meio de pagamento.
Nenhum valor comercial foi alterado. A regra de papel auxiliar também é aplicada
no validador compartilhado para evitar execução por caminhos legados.

## utc_now

O nome fica igual por compatibilidade com os manifests e prompts existentes.
O retorno continua string ISO 8601, agora em `America/Sao_Paulo`, com offset.
Por exemplo: um relógio de teste em `2026-09-29T01:00:00+00:00` retorna
`2026-09-28T22:00:00-03:00`. A LLM usa essa hora local para a saudação e não deve
subtrair três horas de novo. Não há roteador determinístico de saudação nem nova
tool. Os testes comprovam conversão de fuso; não garantem obediência de toda LLM.

Docstring, catálogo e `config/AGENTS.md` padrão foram atualizados localmente.
A descrição padrão antiga do catálogo é substituída na leitura; descrições
customizadas e flags de habilitação são preservadas. O arquivo de registro salvo
não é regravado por essa atualização da descrição.

Timestamps técnicos continuam em UTC, e os cálculos existentes de atraso/vigência
não foram modificados. `config/AGENTS.md` é fallback: instruções salvas no Assistant
têm precedência. No rollout, revisar overrides que ainda digam que `utc_now`
retorna UTC e substituir por: “utc_now retorna America/Sao_Paulo em ISO com offset;
use a hora local para saudações, sem converter novamente”. Nenhum override de
produção foi alterado nesta rodada.

## Validação

Testes locais com banco e OKF sintéticos, provider substituído por modelo roteirizado:
auxiliar → erro específico → leitura canônica → geração PIX; métodos síncrono e
assíncrono; preservação de termos; leitura obrigatória; escopo incorreto; condições
indefinidas; recibo obsoleto; referências inválidas; ciclos; saída do bundle;
conversão de data/hora e compatibilidade do catálogo. Sem chamadas LLM, e-mails,
pagamentos reais ou deploy nesta rodada.

Resultado: 408 testes aprovados, 1 ignorado e 1 xfail preexistente; cobertura
89,80%. Ruff e verificação de whitespace aprovados.
