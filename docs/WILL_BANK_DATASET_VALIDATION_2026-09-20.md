# Validação do dataset ativo — Will Bank

Data da validação: 2026-09-20.

Esta análise foi executada em modo somente leitura no serviço Railway
`langgraph-simple-agent-clean`. Nenhum documento, ponteiro de bundle, simulador ou
configuração do agente foi alterado.

## Estado atual

O snapshot ativo é:

```text
Bundle: okf_wiki_2026-09-18_paths-corrigidos-yaml-corrigido
OKF: 0.2
Documentos Markdown: 467
Publicado em: 2026-09-18T22:21:13.889468+00:00
```

Resultado da validação executada pelo próprio runtime:

| Verificação | Resultado |
|---|---:|
| Erros estruturais | 0 |
| Avisos `broken_relative_link` | 128 |
| Documentos `draft` | 403 |
| Documentos `stable` | 1 |
| Documentos sem `status` | 63 |
| Documentos com placeholder operacional | 307 |
| Documentos com frontmatter `negotiation` | 0 |

O bundle está ativo e pode ser consultado. Ele ainda não contém política
executável para negociação.

## Estado específico do Will Bank

Foram encontrados 33 arquivos sob:

```text
COMPANIES/fastpay/INSTITUTIONS/will-bank/
```

Problemas que afetam o teste de negociação:

1. As políticas estão em `draft`.
2. O campo `institution` alterna entre `Will Bank` e `will-bank`.
3. O campo `product` usa `Cartão de crédito`, enquanto a sessão do simulador usa
   `cartao_de_credito`.
4. Nenhum documento possui o bloco declarativo `negotiation`.
5. Elegibilidade, descontos, juros, alçadas e exceções ainda possuem
   `A DEFINIR PELA OPERAÇÃO`.
6. O índice lista várias políticas concorrentes sem identificar uma fonte
   executável canônica.
7. `parcelamento.md` declara entrada obrigatória, mas o simulador atual não
   suporta entrada separada.
8. Os prazos numéricos não informam unidade. Por exemplo, `Validade da proposta:
   3` e `Prazo de baixa: 3` não dizem se o valor representa dias úteis, dias
   corridos ou outra unidade.
9. O texto sobre comprovante descreve uma futura automação de conciliação que não
   existe nas tools atuais.

As políticas abaixo foram verificadas diretamente com o contrato de
`generate_offer` e todas retornaram `policy_not_published`:

```text
policies/negociacao-parametros.md
policies/parcelamento.md
policies/limites-desconto.md
```

Trocar somente `status: draft` por `stable` não resolve. A próxima falha seria
`policy_scope_mismatch` por causa dos IDs; depois dos IDs, ocorreria
`policy_terms_undefined` pela ausência de `negotiation`.

## Relação com o simulador

A sessão sintética atual usa:

```yaml
institution: Will Bank
product: cartao_de_credito
identity_policy:
  cpf_mode: first4
  secondary: full_name
  max_attempts: 3
eligibility:
  can_negotiate: true
  max_installments: 10
  max_discount_percentage: "20"
```

`eligibility` é apenas o teto transacional do cliente sintético. Esses números
não são política comercial e não devem ser copiados automaticamente para o OKF.
A política pode restringir esse teto, mas nunca ampliá-lo.

## Alterações estruturais seguras

Estas alterações não definem condição comercial e podem ser aplicadas ao draft:

1. Padronizar `institution: Will Bank` em todos os conceitos Will Bank.
2. Padronizar `product: cartao_de_credito` nos conceitos específicos de cartão.
3. Manter `product: null` somente nos conceitos realmente institucionais.
4. Escolher `policies/negociacao-parametros.md` como única política executável de
   negociação para o piloto.
5. Colocar essa política em primeiro lugar no `policies/index.md`, identificada
   como fonte executável.
6. Marcar os demais documentos comerciais como material complementar e apontar
   para a política canônica, sem duplicar o bloco `negotiation`.
7. Informar unidades em todos os prazos.
8. Remover promessas de conciliação, envio, retorno ou escalonamento que não
   possuam tool implementada.
9. Manter todos os documentos em `draft` até a revisão do conteúdo final.

## Decisões que exigem aprovação operacional

O gerador ou a LLM não devem decidir estes valores:

- modalidades permitidas: `cash`, `installment` ou ambas;
- máximo de parcelas;
- desconto máximo;
- juros e encargos;
- valor mínimo negociável e valor mínimo da parcela;
- entrada, caso uma tool futura passe a suportá-la;
- validade da proposta e sua unidade;
- vencimento da primeira parcela;
- alçadas e exceções;
- meios e prazos de pagamento;
- regras de reabertura e escalonamento.

## Piloto mínimo recomendado

Para testar o protocolo atual sem inventar uma política ampla, criar uma cópia
isolada do bundle e aprovar uma política sintética temporária com estas premissas:

- somente dados e dívida sintéticos;
- pagamento à vista e parcelado;
- no máximo 3 parcelas, conforme o valor já preenchido no onboarding;
- desconto máximo de 0% nesta primeira rodada;
- sem entrada separada;
- sem juros calculados pela LLM;
- vigência curta e explícita;
- uso exclusivo no ambiente de teste.

O valor de 3 parcelas ainda precisa ser confirmado como condição de teste por uma
pessoa responsável. O desconto 0% permite validar oferta e acordo sem criar uma
concessão comercial fictícia.

Exemplo do frontmatter a ser revisado antes da publicação:

```yaml
---
type: Policy
title: Política sintética de negociação — Will Bank
status: stable
okf_version: "0.2"
scope: institution
institution: Will Bank
product: cartao_de_credito
effective_from: "<data ISO-8601 aprovada>"
effective_until: "<data ISO-8601 aprovada>"
negotiation:
  payment_types:
    - cash
    - installment
  max_installments: 3
  max_discount_percentage: "0"
  offer_discount_percentage: "0"
verified:
  - by: "human:<responsável>"
    at: "<data ISO-8601 da aprovação>"
---
```

Os placeholders entre `<...>` precisam ser substituídos. O arquivo não deve ser
publicado contendo esses placeholders.

No corpo de `negociacao-parametros.md`, registrar de forma consistente:

```markdown
## Escopo do piloto

- Ambiente: teste com dados sintéticos.
- Formas de oferta: à vista ou parcelada.
- Máximo de parcelas: 3.
- Desconto: não disponível neste piloto.
- Entrada separada: não suportada pelo simulador atual.
- Juros e encargos: não calculados pelo agente.
- Formalização: somente após confirmação expressa da oferta retornada pela tool.
```

Atualizar `policies/index.md` para orientar a navegação:

```markdown
## Política executável do piloto

- [Política sintética de negociação — Will Bank](negociacao-parametros.md) —
  fonte canônica para gerar ofertas no ambiente de teste.

## Material complementar

- Os demais documentos desta pasta não autorizam ofertas e não substituem a
  política executável acima.
```

## Testes de aceite do piloto

Executar cada cenário em uma conversa nova:

| Cenário | Resultado esperado |
|---|---|
| Consulta institucional, sem dados pessoais | Resposta via OKF, sem identificação |
| Consulta de dívida | Identificação antes de `get_customer` |
| Oferta à vista com 0% | `generate_offer` retorna oferta disponível |
| Oferta em 3 parcelas com 0% | Oferta disponível e cronograma soma o total exato |
| Pedido de 4 parcelas | Bloqueio por limite da política |
| Pedido de qualquer desconto | Bloqueio por limite da política |
| Política `draft` ou path diferente | Nenhuma oferta gerada |
| Confirmação sem ID exato da oferta | Nenhum acordo criado |
| Confirmação expressa com ID exato | Acordo sintético criado |
| Pedido de entrada separada | Limitação informada, sem cálculo manual |

O frontmatter sintético proposto foi validado localmente em armazenamento
temporário, usando o mesmo contrato do runtime:

```text
cash, 1 parcela, 0%: permitido
installment, 3 parcelas, 0%: permitido
installment, 4 parcelas, 0%: policy_terms_exceeded
cash, 1 parcela, 1%: policy_terms_exceeded
```

Esse teste comprova o contrato declarativo e os limites do exemplo. Ele não
aprova esses valores como política comercial nem valida o comportamento
probabilístico da LLM.

## Caminho de publicação seguro

1. Criar um novo draft a partir do snapshot ativo.
2. Aplicar somente as alterações Will Bank do piloto.
3. Revisar o diff e registrar a aprovação humana.
4. Validar paths, YAML, links, vigência e contrato `negotiation`.
5. Publicar como novo bundle imutável.
6. Testar em conversas novas com dados sintéticos.
7. Manter o bundle anterior disponível para rollback.

Não editar arquivos diretamente dentro do snapshot ativo. Não promover todos os
403 drafts em massa.
