# Aurora Sintética — rota LLM e gateway WhatsApp do escopo 7

Em 28/11/2026 às 06:56 UTC, o resolvedor de Canais retornou `google/gemini-3-flash-preview` como primário via Lovable `llm-bridge`, com fallback desabilitado. A consulta ao resolvedor levou 56 ms. O grafo de homologação concluiu duas conversas sintéticas sequenciais, com cinco chamadas ao modelo. A amostra mede latência com uma conversa por vez. A capacidade de 1.000 conversas simultâneas depende de medições adicionais da fila, da quota do provedor e da entrega.

| Conversa sintética | Primeiro texto do agente | Total do grafo | Chamadas LLM | Ferramentas executadas |
|---|---:|---:|---:|---|
| Saudação | 1.312 ms | 1.466 ms | 1 | Nenhuma |
| FAQ pública Consulta Lume | 5.159 ms | 5.493 ms | 4 | Duas `okf_index` e uma `okf_search` |

Os dois turnos terminaram com texto e registraram o modelo esperado nos metadados. O relógio começou antes de `graph.stream` e marcou o primeiro fragmento de texto não vazio aceito pelo filtro de streaming do Runtime. O total termina quando o grafo encerra. A sonda usou um processo separado no serviço hospedado de homologação, um checkpoint em memória por conversa e a lista de ferramentas do assistente restrita às leituras OKF. Esses tempos excluem a resolução de rota, fila HTTP/Redis, renderização do Playground e WhatsApp. A avaliação mediu latência e volume de chamadas. O conteúdo das respostas não foi pontuado nem armazenado.

## Chamadas ao bridge

Todos os cinco POSTs de inferência retornaram HTTP 200. As respostas do bridge apresentaram `sb-request-id` e `cf-ray` em 5/5 e nenhum cabeçalho `RateLimit`, `X-RateLimit` ou `Retry-After`. A quota de requisições/tokens do provedor e a frequência de 429 em carga continuam desconhecidas. Na FAQ, esperar pelos cabeçalhos das quatro chamadas consumiu 4.671 ms dos 5.493 ms totais. O tempo até os cabeçalhos inclui o caminho Runtime–bridge e o processamento anterior à resposta HTTP.

| Conversa | Início do POST relativo ao turno | Espera pelos cabeçalhos | Hash do sb-request-id |
|---|---:|---:|---|
| Saudação | 108 ms | 1.198 ms | `24de8ab00dae19c6` |
| FAQ | 58 ms | 1.337 ms | `47368a96b8aa6b84` |
| FAQ | 1.506 ms | 1.165 ms | `69da20e1ef494d7c` |
| FAQ | 2.773 ms | 1.241 ms | `721cc2a4431440ac` |
| FAQ | 4.230 ms | 928 ms | `6777292621888301` |

Os hashes das threads sintéticas foram `0478e87e3e95c38a` e `37a702823b068dd5`, respectivamente. A sonda usa os primeiros 16 dígitos hexadecimais do SHA-256 para permitir comparar um identificador conhecido sem registrar o original.

## WhatsApp

Às 06:57 UTC, em transação somente leitura, o banco próprio do gateway mostrou zero rotas cadastradas para o escopo 7, zero conversas WhatsApp no destino de homologação e zero mensagens inbound associadas. Foram aceitas zero mensagens nos sete dias anteriores. Portanto, o p50 e o p95 de ingresso até aceite pelo provedor ficaram sem amostra. A consulta não leu conteúdo de mensagem, telefone ou dados de contato. Não houve envio à Meta.

O gateway hospedado estava na versão 0.7.0 com worker habilitado. Os SHA-256 de `src/main.js`, `src/worker.js` e `src/transport.js` coincidiram com o checkout `zerai-conversation-gateway@067a5d6`. O worker verifica trabalho a cada segundo. Cada processo mantém um único ciclo ativo e aguarda até cinco jobs sequenciais por ciclo. Cada resposta aguarda o `/runs/wait` antes do envio à Meta. Uma chamada longa ocupa, portanto, o worker desse processo e pode atrasar as mensagens seguintes. A quantidade de réplicas e a taxa sustentada de aceites deste canal não foram medidas.

## Reproduzir

Com o Railway CLI autenticado no projeto, execute na raiz do Runtime. O primeiro comando consulta o banco do gateway em transação somente leitura. O segundo cria duas novas sessões sintéticas, resolve a rota vigente e gera tráfego real de inferência de homologação. Executa um turno por vez, permite apenas ferramentas de leitura OKF e limita as tentativas de inferência a seis no total.

```bash
python3 scripts/probe_aurora_route/railway_probe.py gateway
python3 scripts/probe_aurora_route/railway_probe.py route
```

O comando fixa os serviços Railway de homologação e gateway pelos respectivos IDs. O nome do ambiente Railway é `production` para os dois. A sonda valida o escopo e o assistente antes da inferência. A saída JSON carrega tempos, códigos HTTP, nomes de ferramentas e hashes de correlação.

### Canário HTTP/SSE de quatro conversas

A sonda `parallel.py` usa a conexão HTTP de homologação configurada no serviço do Playground. O modo `preflight` consulta a carteira e o assistente vigentes e verifica a coluna `started_at` no PostgreSQL. O modo `canary` abre quatro threads independentes e dispara uma saudação por thread simultaneamente. O cliente mede do início do POST ao primeiro texto SSE. O banco calcula a fila como `started_at - created_at` e o pico de concorrência pelos intervalos `[started_at, updated_at)`, correlacionados com os quatro IDs fornecidos pelo servidor. O p95 usa interpolação contínua sobre a amostra. O JSON sanitizado identifica os runs por hashes. O teste cobre a API interna HTTP do Playground até o Runtime e o retorno SSE. A interface no navegador e o proxy público ficam fora desse percurso.

```bash
python3 scripts/probe_aurora_route/parallel.py preflight
python3 scripts/probe_aurora_route/parallel.py canary
```

Em 28/11/2026 às 07:05:55 UTC o preflight confirmou o assistente e o escopo. A coluna `started_at` ainda estava ausente antes do deploy. O parser SSE passou em quatro streams locais concorrentes com eventos fragmentados. O cálculo SQL passou em um PostgreSQL 17 isolado com quatro intervalos de interseção conhecida. O painel de IA documentado pelo Lovable mostra uso e custo por requisição. Os conectores e a especificação pública consultados não forneceram a quota de RPM/TPM contratada para esta rota. [Documentação do AI Gateway](https://docs.lovable.dev/features/ai) · [Especificação pública da API Lovable](https://api.lovable.dev/v1/openapi.json)

#### Resultado pós-deploy

Em 28/11/2026 às 07:09:06 UTC, o preflight confirmou que a coluna `started_at` estava disponível após a publicação Railway `e8035f10`. Às 07:09:17 UTC, o serviço do Playground disparou uma única rodada de quatro saudações em threads distintas, com 2 ms entre o primeiro e o último POST. Os quatro streams entregaram texto, os quatro runs terminaram em `succeeded` e nenhuma ferramenta foi executada.

| Turno | Hash do run | Fila (ms) | Início → fim no PG (ms) | Primeiro texto SSE (ms) | Total SSE (ms) |
|---|---|---:|---:|---:|---:|
| 1 | `ff2cf8fb68d579c5` | 39,6 | 39,6 → 2468,4 | 2164 | 2551 |
| 2 | `e462bee646dfc518` | 44,1 | 44,3 → 2468,5 | 2202 | 2553 |
| 3 | `c420d533f4a411d8` | 44,0 | 45,4 → 2589,2 | 2186 | 2670 |
| 4 | `58f86d4f261b96aa` | 44,2 | 44,8 → 2673,9 | 2427 | 2754 |

Os intervalos no PostgreSQL são relativos à criação do primeiro run e compartilham o mesmo relógio. Os quatro estiveram em execução simultânea por **2.423,0 ms**. O p95 de fila foi **44,2 ms** e o p95 de primeiro texto no cliente SSE foi **2.393,3 ms**, ambos por interpolação contínua sobre quatro observações. Este canário confirma concorrência de quatro conversas curtas no escopo 7. Carga sustentada, entrega WhatsApp e concorrência de 1.000 conversas continuam fora da medição.
