# Geração de ofertas — 0.13.7

## Escopo e estado

Alterações autorizadas: interpretação contextual, recuperação limitada de erros
OKF e redução das leituras repetidas na geração. Política comercial, Workflow,
Assistant, dados de clientes e esquema do banco não foram alterados. Não houve
exportação de conversas. Testes usam exclusivamente armazenamento temporário.

A versão 0.13.6 (índice OKF e medição de etapas) foi publicada primeiro:
`8b7aa073-3f77-47df-bfc9-d9cab3ec7681`, commit `4232d55`, SUCCESS, `/info` OK.
A versão 0.13.7 foi publicada no deployment
`2047a12e-ef62-4731-a98e-8f6f9280287b`, commit `e0bc6a1`: SUCCESS, healthcheck
`/info` aprovado pelo Railway e worker iniciado. O acesso HTTP externo foi
verificado separadamente. O teste semântico com provedor permanece pendente.
Pull request: https://github.com/markanthony91/simple-agent-template/pull/56.
Sincronização Trello bloqueada por DNS (wrapper encerrou com código 6).

## Antes e depois

| Caso sintético | 0.13.6 | 0.13.7 |
|---|---|---|
| Pedido completo em 3 parcelas no boleto | Criado | Criado |
| 3 parcelas informadas; boleto em outro turno | explicit_offer_terms_required | Criado |
| Contraproposta em 3x; cliente diz Sim | Criado | Criado |
| Mesma contraproposta; cliente diz Pode emitir | explicit_offer_terms_required | Criado |
| Política ainda não lida | Resposta fixa e fim do turno | Resultado orienta leitura OKF e permite uma nova tentativa |
| Duas tentativas sem resolver a leitura | Sem recuperação | Encerra sem gerar proposta |
| Política incompleta, limite excedido ou método proibido | Bloqueado | Bloqueado |
| LLM responde sem chamar tool | Backend podia substituir por chamada inferida | Backend preserva a decisão da LLM |
| Leituras do arquivo por geração bem-sucedida | 10 | 1 |

Os testes de frases acima invocam a tool com parâmetros determinados: comprovam
remoção da recusa indevida do backend, não compreensão semântica do modelo.

**Limite de autorização conversacional:** se alguém forçar a chamada da tool com
parâmetros válidos após uma recusa do cliente, o backend pode gerar a simulação,
tanto antes quanto depois desta mudança. O regex anterior também aceitava
“Não quero em 3 parcelas”. A interpretação da recusa passa a ser explicitamente
responsabilidade da LLM, instruída pelo contrato da tool a não chamar em recusa,
pergunta informativa ou intenção ambígua. Não há alegação de proteção semântica
independente do modelo. O atalho que podia forçar uma chamada foi removido.

## Validações preservadas

Identidade verificada e isolamento de sessão; recibo de leitura OKF com hash e
snapshot; publicação e vigência; instituição e produto; elegibilidade individual;
limites, descontos e meios definidos na política; cálculo Decimal; transação
atômica, rollback e idempotência. Nenhum desconto, parcela ou meio foi ampliado.

A reutilização fica restrita a bytes e metadados de um documento imutável dentro
de uma única operação. Cada etapa continua validando as condições. O contexto
é descartado inclusive em falha; a próxima chamada relê o arquivo e detecta
mudanças no hash. Autorização, identidade e proposta não entram nesse cache.
Logs incluem `policy_document_read`, `policy_document_reads` e
`policy_document_reuses`, sem conteúdo ou dados pessoais.

## Recuperação

`offer_terms_missing` solicita apenas a quantidade ausente; parcelamento sem
quantidade não é convertido silenciosamente em uma parcela. Além dele, somente
`policy_read_required`, `policy_receipt_mismatch`, `policy_not_found` e
`policy_scope_mismatch` retornam ao modelo para procurar/ler a evidência correta.
A tool continua retornando created=false; não há ação financeira parcial.
O resultado inclui orientação técnica que não deve ser exposta ao cliente.
São permitidas duas chamadas de geração por turno neste percurso (inicial e
uma nova tentativa). Um novo turno reinicia o limite. Não há busca automática
pelo backend. Após sucesso, o template validado encerra sem outra chamada LLM.
Erros de condições financeiras não são convertidos em autorização nem retentados.

## Medição local reproduzível

20 operações novas por modalidade e versão, com o mesmo bundle sintético e
bases temporárias, antes `4232d55` e depois código 0.13.7:

| Modalidade | Mediana antes | Mediana depois | Leituras antes/depois |
|---|---:|---:|---:|
| PIX à vista | 39,162 ms | 9,877 ms | 10 / 1 |
| Boleto em 3 parcelas | 48,119 ms | 8,676 ms | 10 / 1 |

Mede execução local da tool incluindo persistência temporária; não mede rede,
LLM, fila, entrega WhatsApp ou latência publicada. Diferenças do host e cache do
sistema operacional afetam o tempo. A redução de leituras é verificada por teste.

```bash
PYTHONPATH=src:. python scripts/benchmark_offer_validation.py
PYTHONPATH=src:. python -c 'import uvloop,pytest; uvloop.install(); raise SystemExit(pytest.main(["-q", "tests/unit_tests"]))'
```

316 testes passaram em 16,83 s. Cobertura: offer_policy 95%, payment_policy 82%,
payment_tools 81%, tool_middleware 93%; conjunto 89%. Inclui grafo síncrono e
assíncrono, recuperação real com okf_read, limite de tentativas, reset por turno,
resposta sem chamada LLM adicional, ausência de chamada forçada, hash alterado,
limites, escopo, rollback e idempotência. Testes obsoletos do parser foram
substituídos por testes do contrato contextual; o total não é comparável diretamente.

`scripts/evaluate_offer_intent.py` prepara 10 cenários antes/depois com escolha
livre de tool, mensagens sintéticas e leitura somente das instruções do Assistant.
Nenhuma tool é executada nem sessão criada. A tentativa desta rodada ficou
bloqueada por DNS/permissões locais antes de alcançar o provedor; não há resultado
semântico aprovado nem teste de conversa publicada nesta rodada.

## Rollback

Retornar à imagem 0.13.6 do deployment acima, preservando `/data`. Não há migração
nem necessidade de restaurar banco, bundle ou histórico. O rollback restaura
as limitações do parser antigo.
