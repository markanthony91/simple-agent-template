# Benchmark OKF, geração de oferta e Railway

Medição de 25/09/2026, aproximadamente 22h07–22h18 (America/Sao_Paulo).
Os arquivos de evidência usam UTC: 26/09, 01h07–01h18.

## Conclusão

Não encontramos saturação de CPU ou eventos de falta de memória durante os testes.
A RAM está alta e merece investigação própria. A maior parte do tempo da oferta
fica fora da execução das tools: chamadas ao modelo, rede e orquestração.

Um índice em memória acelerou a busca isolada em aproximadamente 60 vezes nas
consultas de negociação, mas economizou apenas cerca de 130 ms por busca.
Eliminar uma rodada do modelo economizou cerca de 2,19 s no experimento controlado.
Isso favorece primeiro reduzir idas e voltas desnecessárias, sem retirar as
validações ou a consulta à política aplicável. Migrar para JSONB ainda não tem
justificativa demonstrada por este benchmark.

## Escopo e proteção dos dados

- Runtime: `langgraph-simple-agent-clean`, Railway production, versão 0.13.4.
- Modelo observado: `google/gemini-3-flash-preview`.
- Bundle: `okf-will-bank-cash-tiers-20260925-20260926T001809Z-f35ea74f`.
- 571 arquivos Markdown, 519 conceitos indexados e 5.749 tokens distintos.
- Duas conversas sintéticas novas no Playground, até criar proposta: PIX e boleto.
- Nenhum envio de e-mail/WhatsApp, exportação de conversas completas ou backup do banco.
- Nenhuma alteração de código, configuração, política ou conteúdo existente em produção
  nesta rodada. A criação das duas conversas e propostas é efeito dos testes autorizados.
- O protótipo de índice existiu somente na RAM de um processo separado. Hashes dos
  documentos antes/depois coincidiram; o ponteiro do bundle ativo permaneceu igual.
- Evidências persistidas contêm tempos, caminhos, nomes de tools e resultados booleanos;
  não contêm CPF, corpo de conversa, credenciais ou códigos de pagamento.

## 1. Busca isolada: arquivos versus índice em memória

Mesmo bundle e mesma máquina. O protótipo mantém tokenização, pontuação, desempate,
ordenação e resposta do serviço atual. Foram 30 repetições de oito consultas por
implementação: 480 execuções cronometradas, com comparação exata das respostas.
Os pares alternaram a ordem aleatoriamente, com cache de arquivos do SO aquecido.

| Consulta | Arquivos, mediana | Memória, mediana | Leituras de arquivo por busca |
|---|---:|---:|---:|
| À vista / PIX | 131,27 ms | 2,24 ms | 51 → 0 |
| Parcelamento / boleto | 134,00 ms | 2,26 ms | 51 → 0 |
| Três parcelas | 131,83 ms | 2,12 ms | 51 → 0 |
| Cinco parcelas | 133,88 ms | 2,28 ms | 51 → 0 |
| Desconto à vista | 139,44 ms | 1,71 ms | 51 → 0 |
| Contestação, ramo GLOBAL | 1.120,34 ms | 18,67 ms | 295 → 0 |
| Terceiro, ramo GLOBAL | 814,61 ms | 4,87 ms | 295 → 0 |
| Termo sem resultado | 129,58 ms | 0,27 ms | 51 → 0 |

Construção inicial do índice: **2,17 s**. Leitura isolada de `parcelamento.md`:
mediana **0,79 ms**, p95 **1,34 ms**. O acesso direto a esse arquivo não explica
vários segundos de espera. Chamadas completas às tools também incluem estado de
sessão, registro de evidência e middleware, ausentes desta medição isolada.

O protótipo preservou o ranking existente; não demonstrou melhora de relevância.
A política de parcelamento apareceu em primeiro lugar; a de PIX ficou em segundo,
atrás de parâmetros de pagamento. As consultas GLOBAL não tiveram avaliação humana
de relevância. Não medimos PostgreSQL, JSONB, GIN ou SQLite FTS5.

Ainda faltariam invalidação por bundle/publicação, concorrência e controle de memória
para transformar o protótipo em cache de produção.

## 2. Evidência do uso dos índices de navegação

O verificador acumula destinos expostos pelas respostas anteriores de `okf_index`
e `okf_search` e verifica os argumentos das próximas chamadas.

| Cenário | Sequência real | Resultado |
|---|---|---|
| PIX | índice raiz → busca em COMPANIES → `politica-negociacao.md` → gerar oferta | 3/3 destinos expostos; proposta criada |
| Boleto | índice raiz → busca em COMPANIES → `parcelamento.md` e `pagamento-parametros.md` → gerar oferta | 4/4 destinos expostos; proposta criada |

O escopo COMPANIES veio do índice raiz; os caminhos dos documentos vieram da busca.
Não houve diretório ou caminho inventado. Nenhuma pesquisa continuou após o lote
de leitura. As duas leituras do boleto foram emitidas **no mesmo lote**, em paralelo.
Portanto, a segunda leitura não adicionou uma rodada do modelo neste teste.

Isso comprova o uso correto dos destinos nos dois cenários observados. Não comprova
que todos os índices foram navegados: `COMPANIES/index.md` não foi aberto, logo não
podemos atribuir ganho à descrição recentemente adicionada naquele índice. O fluxo
usou o atalho de busca previsto no Workflow atual; não percorreu todos os índices filhos.

O índice invertido experimental é outra coisa: seu uso foi comprovado por respostas
idênticas e **zero releituras dos documentos por consulta**. Ele não está no runtime.

## 3. Tempo no chat e no servidor

| Oferta | Playground¹ | Stream no navegador | Execução total no servidor² | Tools, tempo de parede³ |
|---|---:|---:|---:|---:|
| PIX | 11,03 s | 8,18 s | 8,04 s | 0,62 s |
| Boleto | 12,11 s | 9,19 s | 9,03 s | 0,91 s |

¹ Da ação de enviar até o teste observar o encerramento da geração; inclui renderização
e polling do Playwright, não equivale à primeira palavra visível.
² Inclui fila: 0,98 s no PIX e 0,78 s no boleto.
³ União dos intervalos, sem contar duas vezes as leituras paralelas.

Descontando fila e tools, restaram **6,43 s** no PIX e **7,34 s** no boleto.
Esse restante inclui modelo, rede e orquestração; não é uma medição exclusiva da LLM.
A diferença de aproximadamente 2,9 s entre stream e observação do Playground precisa
de instrumentação própria para separar interface, SDK e polling do teste.

Correção dos números anteriores: o teste antigo incluía uma consulta de auditoria ao
estado da conversa após terminar a resposta. Nesta rodada ela acrescentaria 2,34–3,33 s
por turno. Esses segundos foram separados e não são atribuídos ao tempo de geração.

Conversas sintéticas:
- PIX: `01a0db44-48b3-7330-97d3-d288ab3cb810`.
- Boleto: `01a0db44-f9aa-7923-8588-3e3fec61baa6`.

## 4. Experimento controlado: uma rodada a menos do modelo

Usamos o prompt atual (59.876 caracteres) e os documentos reais, com contexto sintético.
Comparamos solicitar leitura e depois solicitar proposta contra receber a política
completa no resultado da busca e solicitar proposta diretamente.

| Variante | Casos | Rodadas por caso | Mediana do trecho |
|---|---:|---:|---:|
| Busca com leitura separada | 6 | 2 | 3,75 s |
| Busca com conteúdo consolidado | 6 | 1 | 1,56 s |

Economia observada: **2,19 s, aproximadamente 58% desse trecho**. Foram 18 chamadas
ao provedor; as 12 propostas de argumentos estavam corretas. Nenhuma tool financeira
foi executada nesse experimento.

Limitação essencial: as escolhas de tool foram forçadas para isolar o custo da rodada.
Isso não demonstra qualidade de seleção autônoma nem garante igual redução na conversa
completa. Antes de adotar, testar escolha livre, múltiplas políticas, falhas e ausência
de evidência. O provedor já informou uso de cache de prompt em 16 das 18 chamadas;
não devemos tratar cache do provedor como recurso inexistente.

## 5. Railway: picos e correlação

Nas amostras que cobrem as janelas das duas conversas, com margem de 30 segundos:

| Recurso | Máximo observado | Limite |
|---|---:|---:|
| CPU | 0,241 vCPU | 24 vCPU |
| RAM | 18,22 GB reportados pela métrica | 24 GB |

O snapshot final do cgroup mostrou 17,30 GB ocupados, nenhum evento OOM/OOM kill,
nenhum período de CPU limitado pela quota e pressão de memória média igual a zero.
Na série histórica anexada houve picos de 1,36 vCPU e 18,88 GB, anteriores às
conversas deste benchmark; não são prova de causa da demora nelas.

**Não há evidência de saturação de CPU ou falta de memória causando as ofertas lentas.**
A RAM alta é um achado real que merece investigação, sem afirmar vazamento ainda.
A série anexada tem resolução de um minuto e pode perder picos curtos; não medimos latência de disco,
contenção SQLite nem toda a infraestrutura do provedor.

Também houve um desvio importante: `verify_and_get_customer` levou **6,73 s** no
primeiro chat e **0,10 s** no segundo. Esse intervalo pertence à execução da tool,
não à pesquisa OKF. No código, `SessionStore.transaction` abre `BEGIN IMMEDIATE`
e grava estado; as tools OKF também passam por transações. Espera por lock/I/O é uma
hipótese a instrumentar, não uma causa comprovada por esta coleta.

## 6. Próximos passos recomendados

1. Instrumentar espera por transação, duração de cada chamada ao modelo e término do
   stream/interface para explicar a identificação de 6,7 s e a parcela residual.
2. Prototipar retorno de conteúdo suficiente junto à busca, com proveniência e registro
   de leitura preservados; testar o agente livre antes de trocar o contrato da tool.
3. Se necessário, adicionar índice em memória vinculado ao bundle ativo. O benefício
   é maior em GLOBAL e sob carga; nas buscas atuais de negociação economiza ~0,13 s.
4. Investigar RAM separadamente. Não aumentar servidor ou migrar para JSONB apenas
   com estes resultados. Se for comparar banco, medir consultas equivalentes com
   índice de busca apropriado; armazenar JSONB sozinho não resolve rodadas da LLM.

## Evidências e reprodução

- [Busca e equivalência](OKF_BENCHMARK_RESULTS.json).
- [Playground e destinos previamente expostos](CHAT_BENCHMARK_RESULTS.json).
- [Tools, lotes e tempos do servidor](CHAT_SERVER_TIMINGS.json).
- [Medições históricas corrigidas](PRIOR_TEST_TIMINGS.json).
- [Chamadas controladas ao provedor](MODEL_BENCHMARK_RESULTS.json).
- [Séries Railway](RAILWAY_BENCHMARK_METRICS.json).
- [Snapshot cgroup](RAILWAY_CGROUP_SNAPSHOT.json).

Scripts em `scripts/benchmark_okf.py`, `benchmark_chat.cjs`, `benchmark_model.py`
e `collect_benchmark_evidence.py`. A busca é executável com
`PYTHONPATH=src python scripts/benchmark_okf.py --root /caminho/do/bundle --rounds 30`.
Os scripts de chat criam sessões e propostas sintéticas; o de modelo consome o provedor.
Não executá-los como parte de um teste unitário offline.

Esta entrega é evidência e ferramenta de benchmark, sem deploy ou alteração do runtime.
