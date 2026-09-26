# Medição das tools e índice OKF — 0.13.6

Publicada no Railway no deployment `8b7aa073-3f77-47df-bfc9-d9cab3ec7681`,
commit `4232d55`: status SUCCESS e `/info` acessível. Nenhum banco,
conversa, política, Workflow ou configuração de produção foi alterado nesta rodada.
Não houve exportação de conversas. Regras do gerador de ofertas foram preservadas na versão 0.13.6.
A evolução 0.13.7 está em [geração de ofertas](OFFER_FLEXIBILITY.md).

## Medição

Os eventos existentes `TOOL_CALL` mantêm hostname, tool, identificador da chamada,
resultado sanitizado e duração total. No término, incluem `phases_ms` e `counters`.
Os novos campos contêm somente nomes de etapas, durações e contadores.

| Campo em phases_ms | Mede |
|---|---|
| tool_guard | Verificações de habilitação/sessão, incluindo despacho assíncrono |
| tool_handler | Invocação LangChain completa, incluindo despacho e serialização |
| tool_execution | Corpo da tool síncrona, após entrar no executor |
| session_connect / session_schema | Abrir conexão / conferir tabelas |
| session_read / session_load | Ler e hidratar estado existente / carregar estado na transação |
| session_write_wait | Executar BEGIN IMMEDIATE, incluindo eventual espera pelo escritor |
| session_body / session_save | Trabalho dentro da transação / serialização e escrita |
| session_commit | Commit, incluindo eventual espera por leitores/disco |
| okf_document_read / okf_receipt | Ler documento ou seção / registrar evidência por sessão |
| okf_cache_wait / okf_index_build | Espera pelo lock do cache / construção do índice |
| okf_search_rank | Obter candidatos e ordenar resultados; no fallback inclui leitura/tokenização |

Etapas são inclusivas e algumas se sobrepõem: **não somar todas como se fossem
independentes**. `tool_handler - tool_execution` aproxima o custo de despacho e
framework; não é medição exclusiva de fila. Fila do run e tempo do modelo ficam
fora dessas métricas de tool e devem ser correlacionados com os logs do Runtime.

ContextVar separa chamadas e propaga as medições para os executores. O contexto é
restaurado em sucesso e falha. Chamadas diretas fora do middleware continuam
funcionando, sem criar um novo log independente para cada etapa.

Contadores: `okf_cache_hit`, `okf_cache_miss`, `okf_cache_bypass`,
`okf_cache_eviction`. Falhas inesperadas continuam propagadas ao runtime.

## Índice

Somente o serviço de tools, ao resolver o snapshot publicado da sessão, habilita
o índice. Rascunhos, overrides e seleção explícita de arquivos seguem a busca
sem cache. O algoritmo mantém normalização, aliases, score, desempate, trechos,
limites de resultados e marcadores canônicos existentes.

- Chave: raiz absoluta do armazenamento/bundle imutável e limite de caracteres.
- Até dois índices; até 32 MiB estimados de objetos retidos no cache.
- Construção limitada a 2 milhões de caracteres e 2.000 conceitos.
- Construções frias serializadas; buscas com índice pronto não seguram o lock.
- Bundles grandes demais usam a busca por arquivos. A rejeição é lembrada enquanto
  a entrada estiver no LRU, evitando reconstrução a cada consulta.
- Um bundle novo tem outra chave; conversas antigas continuam no snapshot fixado.
- Não editar arquivos publicados no mesmo caminho: publicar outro bundle.
- O índice não contém identidade, saldo ou proposta. Busca não registra leitura;
  `okf_read`/`okf_read_section` continuam necessários para o recibo financeiro.

Os 32 MiB limitam objetos estimados **retidos no cache**, não o RSS do processo.
Construção temporária, candidatos e referências em buscas em andamento podem
adicionar memória. Reiniciar o processo esvazia somente esse índice derivado.
A primeira busca de um bundle paga a construção; medir também esse caso frio.

## Validação

314 testes unitários passaram com uvloop, incluindo os casos assíncronos antes
pendentes. Cobertura: temporização 100%, índice 95%, OKFService 91%, SessionStore
96%; conjunto medido 94%. Lint e formatação dos arquivos alterados passaram.

Testes cobrem resultados exatos, ordenação, zero releituras em hits, snapshots e
raízes diferentes, limite de caracteres, drafts/overrides, descarte por bytes e
quantidade, construção concorrente, fallback, traversal, symlink, isolamento das
medições, falhas, recibos e schema da tool. A suíte financeira foi executada.

Comando (ambiente já instalado):

```bash
PYTHONPATH=src python -c 'import uvloop,pytest; uvloop.install(); raise SystemExit(pytest.main(["-q", "tests/unit_tests"]))'
PYTHONPATH=src python scripts/benchmark_runtime_search.py
```

Benchmark reproduzível com **519 documentos sintéticos**, não com o bundle atual
em produção; 20 rodadas por caso, ordem alternada aleatoriamente:

| Consulta | Arquivos, mediana | Índice pronto, mediana |
|---|---:|---:|
| Parcelamento / COMPANIES | 47,155 ms | 0,271 ms |
| Desconto PIX / COMPANIES | 48,727 ms | 0,332 ms |
| Informação / GLOBAL | 271,649 ms | 1,795 ms |
| Sem resultado / raiz | 210,889 ms | 0,029 ms |

160 comparações idênticas; nenhuma releitura de documento nas buscas aquecidas.
Construção e primeira consulta: 491,303 ms. Índice: 12.701.272 bytes estimados.
Esses números não medem a LLM nem comprovam ganho no WhatsApp/Playground publicado.

## Próxima medição em produção

Após publicação autorizada, observar chamadas normais pelos logs, sem exportar
conversas. Comparar mediana/p95 por tool, tempo de lock/commit, builds/hits do cache,
fila e memória sob atividade equivalente. Testes que criem dados sintéticos em
produção devem ter escopo acordado. Não inferir redução sustentada de RAM apenas
pelo reinício do serviço.
