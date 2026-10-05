# Railway service labels

Project `agent-runtime-console` (`511a294c-8d6a-4906-bd26-e8e33011eac5`),
environment `production` (`8830dd97-8668-467d-b2f5-6ebcb8807969`).

The labels below were verified on 2026-10-05. Use service IDs in CLI operations;
the text in parentheses is an operator-facing description, not a new deployment
or a new traffic route.

| Railway label | Service ID |
| --- | --- |
| `langgraph-simple-agent-clean (Agente Principal)` | `861cf8e9-935f-4673-baf0-6bb438eac5fb` |
| `agent-chat-ui-fork (Chat e Configurações)` | `1266d27e-78be-4b48-98a7-e62bb7bb6855` |
| `zerai-channel-console (Canais e Disparos)` | `f1705dea-fcf1-44a2-9f2c-65dbcb393626` |
| `zerai-portfolio-playground (Chat por Carteira)` | `efb21236-bdc2-4d74-94e1-bc60de92f9a6` |
| `zerai-okf-service (Base de Conhecimento)` | `c4f2c04a-286a-41f5-8c3f-b3d3eee3e848` |
| `llm-tailscale-bridge (Conexão com Modelos)` | `1f0bc1c2-523b-46ee-a27c-b82a45c67f4a` |
| `Postgres (Dados Operacionais)` | `ae65fc8d-cc4f-4acf-92a9-24f1c3a10452` |
| `Redis (Dados Temporários)` | `ff085d88-75c3-474d-bce5-1322efec3a20` |
| `agent-runtime-console (Console Legado)` | `5071894b-f1d3-4e1d-a199-966ad6c57cf9` |
| `postgres-runtime-testes (Dados de Migração)` | `e1d98011-cd52-4005-866d-f863a99871a5` |
| `Agente de Homologação` | `accedeb1-4a8d-455e-a7ed-f4d2d7d92dec` |
| `Dados de Homologação` | `4fe1fa72-c700-44fe-9132-6c8240d9e556` |

The purpose of `postgres-runtime-testes` still needs confirmation before any
retirement or data change. Its descriptive label is provisional.

After the label changes, all 12 existing deployments remained `SUCCESS`, their
private-network hostnames were unchanged, and the five public HTTP endpoints
still returned 200. No service was restarted or redeployed for this naming pass.
