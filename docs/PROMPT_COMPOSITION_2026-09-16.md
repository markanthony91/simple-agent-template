# Composição das instruções: comparação na LLM em 2026-09-16

O System Prompt visível na interface não é toda a instrução recebida pelo modelo.
O código monta uma única mensagem de sistema nesta ordem:

1. `context.system_prompt`, ou `config/system_prompt.md` como fallback.
2. `context.agent_instructions`, ou `config/AGENTS.md` como fallback.
3. `context.active_workflow`, ou `config/WORKFLOW.md` quando ausente.
4. Contrato de identificação acrescentado pelo middleware a cada chamada.

Fontes: `src/simple_agent/prompt_loader.py`, `managed_graph.py`,
`tool_middleware.py` e `services/identity_policy.py`.

Na leitura atual, o Assistant versão 7 tinha somente `system_prompt` no contexto;
portanto AGENTS.md e WORKFLOW.md vinham dos arquivos do backend. Limpar o campo
AGENTS.md não elimina suas instruções: texto vazio aciona o fallback. Já workflow
explicitamente vazio desabilita apenas esse bloco. Nenhuma dessas configurações
foi alterada nesta avaliação.

Os títulos “Operational Instructions” e “Active Workflow” não criam níveis de
prioridade distintos na API: são trechos concatenados na mesma mensagem. O contrato
de identificação declara em texto sua precedência, e as ferramentas também aplicam
os bloqueios no backend. O carregador não interpola os placeholders do prompt.

## Comparação controlada

26 chamadas novas ao `Qwen/Qwen3-30B-A3B-Instruct-2507-FP8`, pelo adaptador do
próprio serviço: 20 comparando atual/v3, sozinhos/compostos, em cinco entradas;
e 6 isolando cada bloco adicional nas duas saudações. Mesmo catálogo de 11 tools
em todas as condições, sem histórico e sem executar chamadas de ferramenta.
O contrato composto usou fixture sintética first4 + full_name. Credenciais ficaram
no serviço; nenhum prompt ou dado de produção foi escrito.

O modelo recebeu mensagens SystemMessage/HumanMessage diretamente, preservando
schemas das ferramentas. Este experimento mede a primeira resposta ou decisão de
chamar ferramenta; não executa o ciclo inteiro do grafo. As configurações de
amostragem foram as mesmas do adaptador/provedor, sem impor temperatura ou seed.
Cada entrada foi executada uma vez por condição: os números não medem estabilidade
estatística, nem reproduzem a configuração desconhecida do aplicativo do celular.

Prompt atual, SHA256:
`d550ccc5c7daee2b3b185c6f1ce5688c8bc69fa6f5a260ecf15eee4ea27a67f3`.
Candidata v3, SHA256:
`b77c62fc1c84deb806233c5a015132d2b9fb40d789f2ffdc848231d77e569972`.

| Composição | “boa tarde” | “boaa tarde” |
|---|---|---|
| Atual sozinho | Apresentou-se usando `[Nome da Empresa]` | Apresentou-se usando `[Nome da Empresa]` |
| Atual + AGENTS.md | Apresentou-se como assistente “da sua instituição” | Mesmo comportamento |
| Atual + WORKFLOW.md | Sem apresentação | Sem apresentação |
| Atual + contrato de identificação | Apresentou-se como “atendente virtual” | Sem apresentação |
| Atual + todos os blocos | Sem apresentação | Sem apresentação |
| V3 sozinha | Apresentou-se como assistente virtual Zerai | Apresentou-se como assistente virtual Zerai |
| V3 + todos os blocos | Apresentou-se como assistente virtual Zerai | Apresentou-se como assistente virtual Zerai |

Exemplo com o prompt atual sozinho:

> Boa tarde! Sou o assistente de atendimento da [Nome da Empresa]. Como posso ajudar você hoje?

Com o mesmo prompt e todos os blocos:

> Boa tarde! Como posso ajudar você hoje?

O workflow contém “Saudação: responda naturalmente, sem consultar dados” e um roteiro
próprio de negociação. Essa frase não proíbe se apresentar, mas o teste com apenas
essa camada adicional reproduziu a omissão em ambas as saudações. É evidência de
interferência da composição, não prova de que uma frase seja a única causa.
O contrato de identificação também alterou uma das respostas.

## Outros resultados e limites da candidata v3

- Pedido completo de consulta: v3 sozinha pediu nascimento sem ter recebido contrato
  que o exigisse. Com todos os blocos, chamou verify_customer_identity com os fatores
  corretos. Portanto remover todas as instruções complementares também pode piorar
  o comportamento. As ferramentas não foram executadas neste experimento.
- Opt-out/número errado: v3 sozinha e composta informaram que não conseguem remover
  telefone, sem prometer remoção. Não incluíram a apresentação inicial nesse caso.
- Humano/agendamento: v3 sozinha e composta negaram corretamente essas capacidades,
  mas também omitiram a apresentação inicial.
- No pedido de consulta, v3 composta acrescentou “Boa tarde” sem saudação ou horário
  fornecido. Ainda há comportamento a ajustar; não considerar a candidata aprovada.
- Nenhum teste novo validou negociação, acordo ou envio completos com esta v3.

## Interpretação e próximo ajuste recomendado

Há sobreposição real: o System Prompt descreve oito etapas, enquanto o workflow
acrescenta outro roteiro. O atual pede fechamento após envio, mas o workflow descreve
acordo simulado sem envio. O System Prompt manda seguir validação pela Wiki; o
backend impõe seu próprio contrato. Orientações para “oferecer revisão humana”
precisam distinguir sugestão de atendimento de uma transferência executável.

Ajuste recomendado: alinhar responsabilidades entre os blocos, deixando identidade,
tom e apresentação no System Prompt; contratos operacionais no AGENTS.md; sequência
no workflow; fatores de identificação e bloqueios de segurança no backend.
Depois, repetir a comparação alterando uma camada por vez. Não remover os controles
de identidade, escopo e consentimento para reproduzir um chat direto.

A observação no celular é compatível com estes resultados. Para uma comparação
exata entre aplicativos, ainda faltam o modelo/quantização, template, contexto,
schemas de tools e parâmetros usados lá. “Qwen” sozinho não identifica tudo isso.
