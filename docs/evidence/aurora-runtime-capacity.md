# Capacidade do Runtime OSS e perda de réplica

Homologação local em 28/11/2026. Na bateria de 0,5 s com tráfego distribuído, o Runtime era o 0.20.0. O cliente entrou pela API HTTP/SSE em processos Uvicorn independentes. PostgreSQL 17.10 e Redis 8.6.3 foram criados para o ensaio. O Runtime usou o grafo gerenciado, o SDK de modelo, a fila e os checkpoints reais. Um servidor OpenAI-compatible em loopback demorou 250 ms antes do primeiro fragmento e outros 250 ms antes do segundo. As carteiras usaram a lista de ferramentas vazia e dados exclusivamente gerados pelo ensaio.

Cada patamar pré-abriu o número indicado de conversas, divididas por igual entre dois Assistants com tenants e escopos sintéticos independentes. Cada conversa enviou dois turnos, com as entradas iniciais distribuídas uniformemente ao longo de 60 s e espera de 35–45 s após receber a primeira resposta. O segundo turno entrou por outra réplica. A verificação exigiu que os fragmentos e o estado final contivessem o marcador da carteira, da conversa e do turno corretos.

A fila mede o tempo entre o commit da inserção e o commit do claim pelo executor. Na rodada dimensionada, um observador local recebeu as duas notificações do PostgreSQL e cronometrou a diferença com relógio monotônico. O primeiro texto e o fim usam o relógio monotônico do cliente a partir do envio do POST. Os picos de fila e de executores são amostrados a cada segundo. O pico de SSE conta requisições pendentes no cliente, inclusive enquanto aguardam cabeçalhos. Contagem de conversas abertas, entradas por segundo, inferências em curso e requisições pendentes medem partes diferentes da carga.

## Duas réplicas com quatro executores cada

| Conversas | Turnos corretos | Pico de requisições pendentes | Pico na fila | Fila p95 (s) | Primeiro texto p95 (s) | Fim p95 (s) |
|---:|---:|---:|---:|---:|---:|---:|
| 100 | 200/200 | 5 | 1 | — | 0,360 | 0,711 |
| 250 | 500/500 | 15 | 6 | — | 0,793 | 1,553 |
| 500 | 1.000/1.000 | 105 | 92 | — | 6,955 | 7,339 |
| 1.000 | 2.000/2.000 | 642 | 632 | 63,285 | 63,671 | 64,112 |

O observador monotônico entrou durante o patamar de 500 e cobriu 277 dos 1.000 turnos (p95 de 4,125 s nessa amostra parcial). Para 1.000 cobriu todos os turnos. A quantidade de execuções no banco coincidiu com a de POSTs em cada patamar. No último patamar o cliente enviou até 30 turnos em um segundo.

Houve saltos no relógio civil do WSL2. O p95 de fila calculado pelo PostgreSQL foi de 0,043 / 0,432 / 6,610 / 63,137 s nos quatro patamares, respectivamente. Em 100, 250 e 500 houve pelo menos 3, 7 e 20 durações fisicamente impossíveis (negativas ou superiores à maior duração fim a fim de todo o patamar). Para 1.000 houve diferença absoluta superior a 1 s frente ao observador monotônico em 93 dos 2.000 turnos. As decisões de latência usam o relógio monotônico.

## Quatro réplicas com oito executores cada

| Conversas | Turnos corretos | Pico de chegadas/s | Pico de requisições pendentes | Pico de conexões de cliente no PG | Fila p95 (s) | Primeiro texto p95 (s) | Fim p95 (s) |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | 200 | 5 | 5 | 53 | 0,034 | 0,384 | 0,763 |
| 250 | 500 | 11 | 9 | 56 | 0,038 | 0,383 | 0,735 |
| 500 | 1.000 | 18 | 21 | 68 | 0,046 | 0,441 | 0,846 |
| 1.000 | 2.000 | 35 | 48 | 76 | 0,135 | 0,746 | 1,258 |

O modelo recebeu exatamente uma chamada por turno em cada patamar. O cliente conferiu a resposta com o valor persistido no PostgreSQL, e as duas transições monotônicas foram capturadas para todos os turnos. Em 1.000 conversas, o pico amostrado foi de 32 executores ocupados e 9 turnos na fila. O p99 do primeiro texto foi de 0,902 s e o máximo observado foi de 1,160 s. Em 21 das 2.000 entradas o cálculo pelo relógio civil do PostgreSQL divergiu em mais de 1 s. A maior fila monotônica foi de 0,409 s.

## Rajada isolada

No mesmo dimensionamento, um ensaio independente liberou 100 conversas ao mesmo tempo, com um turno cada. Houve 100 sucessos e 100 chamadas ao modelo. O pico observado foi de 100 POSTs pendentes. O p95 da fila foi de 2,305 s, o primeiro texto de 3,863 s e o fim de 4,204 s.

## Sensibilidade à duração da inferência

A versão 0.20.1 do Runtime recebeu a mesma carga de 1.000 conversas com quatro réplicas de 24 executores e um PostgreSQL descartável configurado para até 160 conexões. O modelo sintético esperou 2 s até o primeiro fragmento e mais 2 s para completar. A ocupação prolongada de um executor representa o efeito da demora por turno. Na FAQ hospedada, os 5,493 s incluíram quatro inferências sucessivas e três operações OKF. O ensaio local fez uma inferência por turno e usou ferramentas desabilitadas.

Dos 2.000 POSTs, 2.000 tiveram sucesso persistido. O provedor recebeu 2.000 chamadas. Houve 0 erros de transporte, conteúdo ou persistência detectados pelo cliente. Fila p95 5,562 s, primeiro texto p95 7,728 s e fim p95 9,930 s. O pico foi de 35 chegadas/s, 243 POSTs pendentes, 96 executores ocupados, 139 na fila e 146 conexões de cliente no PostgreSQL.

Em 123 amostras aproximadamente a cada segundo, os quatro processos Runtime chegaram juntos a 3,43 vCPUs e 666 MiB de RSS. O processo principal e os subprocessos do PostgreSQL chegaram juntos a 0,52 vCPUs e 4223 MiB de RSS. Os máximos de CPU e memória podem ocorrer em instantes diferentes. RSS soma as páginas compartilhadas em cada PID. Na amostra de 2026-11-28T07:15:53.801451+00:00, a memória proporcional (PSS) foi 580 MiB para o Runtime e 368 MiB para o PostgreSQL. O mínimo de memória disponível do host foi 2684 MiB. Cliente, Redis e modelo sintético também usaram recursos do mesmo WSL2 com 12 CPUs visíveis. Os valores descrevem esse ensaio.

## Reconexão com perda do processo

Com um executor em cada uma de duas réplicas, A recebeu dois POSTs. O primeiro ficou bloqueado no provedor pelo executor de A. Ao iniciar B, o segundo ficou bloqueado pelo executor de B. O cliente já havia lido o primeiro fragmento de cada resposta quando o ensaio encerrou o processo A com SIGKILL.

A conexão pelo mesmo run ID no endpoint GET da réplica B recebeu os novos fragmentos da execução sobrevivente e o valor final integral em 0,375 s. O banco registrou sucesso. A execução cujo executor foi encerrado retornou evento SSE de erro e estado persistido failed/worker_lost. Houve uma única chamada ao modelo para cada entrada. O tempo local de 4,908 s entre a queda e a observação do órfão inclui a idade da reserva e os saltos de relógio do host. A reconexão exige que o cliente tenha recebido e guardado o identificador antes da queda.

## Reprodução

Ativar o ambiente Python do projeto e disponibilizar initdb, postgres e redis-server no PATH. Usar um nome novo para cada arquivo de saída.

```bash
python scripts/benchmark_oss_capacity.py --replicas 2 --workers 4 --output /tmp/oss-2x4.json
python scripts/benchmark_oss_capacity.py --replicas 4 --workers 8 --users 1000 500 250 100 --output /tmp/oss-4x8.json
python scripts/benchmark_oss_capacity.py --replicas 4 --workers 8 --users 100 --turns 1 --spread 0 --output /tmp/oss-burst.json
python scripts/benchmark_oss_capacity.py --replicas 4 --workers 24 --model-seconds 4 --users 1000 --output /tmp/oss-model-4s.json
python scripts/benchmark_oss_capacity.py --replica-loss --output /tmp/oss-reconnect.json
```

O teste mede uma janela de dois turnos por usuário com inferência sintética curta. Capacidade no Railway depende de CPU/memória por réplica, conexões do PostgreSQL/Redis, latência e limites do provedor e ferramentas invocadas. Ensaios de longa duração, rede do navegador e conteúdo do modelo hospedado exigem evidência própria.

Os dados incluem p50, p95, p99, máximos, falhas, fontes de relógio e o SHA-256 do arquivo do Runtime na rodada dimensionada. [Evidência JSON](aurora-runtime-capacity-2026-11-28.json)
