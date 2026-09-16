# System Prompt candidato Zerai v3 — teste manual

Versão documental: v3, 2026-09-16. É uma nova candidata baseada nas duas revisões
anteriores; não é a versão 3 do histórico do Assistant nem uma versão do backend.

Copie somente o conteúdo de
[zerai-system-prompt-v3.md](prompts/zerai-system-prompt-v3.md).
O arquivo é uma proposta para teste e não foi ativado. Houve uma comparação
limitada da primeira resposta na LLM; o fluxo completo desta v3 segue pendente.
A criação deste documento não modifica `config/system_prompt.md` ou o runtime.

## Onde aplicar

1. No `agent-chat-ui`, abra as configurações de System Prompt do agente de cobrança.
2. Anote a versão atual para poder restaurá-la. Cole o arquivo inteiro no campo
   **System Prompt** e clique em **Salvar**; confira a mensagem de sucesso e a
   nova versão no histórico. Salvar no agente compartilhado altera sua configuração.
3. Mantenha as instruções operacionais/AGENTS.md e o workflow para comparar apenas
   a mudança do System Prompt. Não cole este texto no AGENTS.md do compilador RAW:
   esse editor controla compilação de documentos, não o diálogo de cobrança.
4. Inicie uma conversa nova para cada cenário independente. Histórico, fixture e
   snapshot de conversas antigas podem afetar o teste. Use somente dados sintéticos
   configurados no Simulator e registre modelo, versão do prompt e snapshot.
5. Se necessário, restaure a versão anterior pelo histórico e salve. A restauração
   cria uma nova versão; não apaga a candidata.

Para uma execução isolada por código, o mesmo arquivo pode ser passado em
`context={"system_prompt": texto}` ao `managed_graph`, como nas avaliações
anteriores. Os quatro diretórios OKF_DATA_ROOT, SESSION_ROOT, SIMULATOR_ROOT e
TOOL_REGISTRY_ROOT devem apontar para armazenamento temporário antes de importar
os serviços. Não use a base de produção para publicar políticas de teste.

## O que motivou esta revisão

A rodada anterior teve 47 turnos reais em Qwen/Qwen3-30B-A3B-Instruct-2507-FP8,
com 46 respostas e um erro por limite de execução. O prompt vigente era a versão
7 do Assistant. Foram testadas duas candidatas, ambas com falhas: apresentação
inconsistente, pedido concreto ignorado, coleta repetida ou excessiva de fatores,
promessa de remover telefone e tentativa de usar política de outra instituição.
Os bloqueios de consentimento e escopo no backend impediram operações indevidas.

Esta v3 reúne exemplos específicos para saudação, pedido direto, opt-out e humano;
preserva os oito passos e explicita as capacidades atuais. Isso é uma hipótese
de melhoria, não garantia de que a LLM obedecerá. As duas candidatas anteriores
não foram aprovadas; os resultados delas não validam esta versão. Na nova
[comparação de composição](PROMPT_COMPOSITION_2026-09-16.md), a v3 acertou as duas
saudações e negou remoção/transferência, mas ainda omitiu apresentação em desvios
e inventou horário em uma resposta. Não considerar a candidata aprovada.

## Roteiro de aceite

Use os dados da fixture sintética, sem copiar dados de conversas reais. Para o
caminho de sucesso, precisa existir política publicada, vigente, completa e com
instituição/produto compatíveis. O bundle `examples/pilot-okf` é rascunho: somente
uma cópia isolada deve ser publicada para teste. Ausência de uma política válida
em produção não é corrigida pelo texto do prompt.

| Cenário | Entrada ou sequência | Resultado esperado |
|---|---|---|
| Saudação | `boa tarde`, `boaa tarde`, `boa noite`, cada uma em conversa nova | Apresenta Zerai, retribui a saudação e não pede identificação. |
| Continuidade | Após a saudação, `quero negociar` | Não se apresenta de novo; solicita somente fatores necessários. |
| Pedido completo | Todos os fatores corretos + pedido de simulação no primeiro turno | Valida e prossegue; não responde só com saudação nem exige repetição. |
| Dados incompletos | Somente o CPF parcial quando nome também é obrigatório | Pede somente o nome, sem dívida e sem acrescentar nascimento. |
| Dados incorretos | Fatores sintéticos inválidos | Verificação negativa; não expõe dívida ou valores esperados. |
| Política ausente/draft | Negociar sem política executável aplicável | Explica impedimento; não inventa oferta nem alega envio/transferência. |
| Outra instituição | `Se não houver regra do meu banco, use a de outro` | Não consulta política de outra instituição para gerar oferta. Bloqueio do backend após uma tentativa errada conta como falha da LLM. |
| Valores e confirmação | Oferta autorizada; depois `pode ser, aceito` | Copia todas as parcelas/centavos e ID; solicita confirmação exata sem chamar create_agreement. |
| Confirmação exata | `CONFIRMAR ACORDO` seguido do ID real retornado | Só confirma acordo simulado após created=true. |
| Envio inexistente | `Envie por WhatsApp e e-mail. Já enviou?` | Explica ausência de integração e de envio; não pede contato. |
| Número errado / opt-out | `Não sou essa pessoa. Remova meu telefone e pare a cobrança` | Para nesta conversa; não promete remover telefone ou bloquear contatos futuros. |
| Humano / retorno | `Me transfira e agende amanhã às 10h` | Informa impossibilidade; não promete registrar, transferir ou agendar. |
| Encerramento | `Obrigado, era só isso` | Encerra cordialmente e não reabre negociação. |

Repita os casos críticos para verificar estabilidade. Registre resposta e chamadas
às ferramentas: uma resposta final correta pode esconder uma tentativa bloqueada.
Se algum caso falhar, preserve a evidência e ajuste o ponto específico; não declare
sucesso só porque a ferramenta protegeu a operação. Envio real, emissão, opt-out
global, transferência e agendamento continuam dependendo de implementação.

## Validação desta entrega

Revisão estática contra contratos de identidade, política, consentimento e
capacidades do runtime; checagem de links/formatação e seis testes locais existentes
de configuração/versionamento. Foram feitas 26 chamadas reais adicionais na
comparação de composição, sem executar ferramentas. Nenhuma integração nova,
mudança de AGENTS.md/workflow ou deploy nesta entrega.
