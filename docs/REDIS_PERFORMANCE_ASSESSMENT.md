# Redis: avaliação para o Runtime atual

## Conclusão

Redis pode ajudar na comunicação entre workers e no streaming quando o Runtime
usar uma arquitetura de produção com persistência externa. Adicionar uma instância
Redis ao Railway, sozinho, não altera o runtime-inmem iniciado por `langgraph dev`.
Não foi provisionado Redis nem realizada migração nesta avaliação.

O código instalado usa `StreamManager.message_stores` em memória para replay dos
streams resumíveis. Redis não corrige automaticamente a retenção desse objeto.
Atribuir a memória do servidor a um componente específico ainda exige medição.

## Papéis diferentes

- PostgreSQL: na arquitetura oficial do Agent Server, persiste threads, runs,
  assistants e, por padrão, checkpoints. O SQLite operacional da aplicação seria
  uma migração adicional, preservando atomicidade e isolamento por sessão.
- Redis: coordena workers, cancelamento, metadados temporários e Pub/Sub do
  streaming. Pub/Sub sozinho não é histórico nem garantia de replay.
- Cache OKF: Redis poderia compartilhar resultados entre réplicas. Com a única
  réplica atual, um índice local limitado por tamanho e por versão do bundle é uma
  alternativa mais simples a avaliar primeiro. Cache não reduz o número de rodadas
  que a LLM decide executar e não substitui recibos de leitura por sessão.

No benchmark existente, o protótipo local reduziu as buscas de negociação de
aproximadamente 130 ms para 2 ms. Eliminar uma rodada do modelo economizou cerca
de 2,19 s no experimento controlado. Esses números não são medições de Redis.

Se futuramente houver cache compartilhado, a chave precisa incluir a versão
imutável do bundle e todos os parâmetros relevantes da consulta, com isolamento
por domínio/tenant quando aplicável. Limites de memória e expiração devem ser
explícitos; não aplicar descarte de cache à identidade ou ao estado financeiro.
Redis também consome RAM e não garante redução da memória total da solução.

Os logs pós-deploy mostram concorrência de runs `max=1`. Sob carga simultânea,
esse limite também precisa ser medido; Redis não o aumenta automaticamente.

## Próximo passo recomendado

Medir a correção de acesso ao estado já autorizada. Depois avaliar a migração do
runtime de desenvolvimento para um servidor de produção com PostgreSQL + Redis,
em ambiente isolado, incluindo requisitos de licença, preservação dos dados,
reconexão do streaming, atomicidade e rollback. Não trocar apenas variáveis de
conexão no servidor atual.

Fontes oficiais consultadas:
- https://docs.langchain.com/langsmith/data-plane
- https://docs.langchain.com/langsmith/deploy-standalone-server
- https://docs.langchain.com/langsmith/agent-server-scale
- https://redis.io/docs/latest/develop/reference/eviction/

Evidência local: `docs/OKF_BENCHMARK_2026-09-25.md`, `Dockerfile`,
`src/simple_agent/startup.py` e runtime-inmem 0.34.0 instalado.
