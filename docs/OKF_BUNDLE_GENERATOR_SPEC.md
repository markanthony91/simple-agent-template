# Instruções para geração de bundles OKF aptos à negociação

Este documento define como o gerador deve montar, validar e publicar um ZIP OKF
0.2 que possa ser consultado pelo agente e, quando houver aprovação operacional,
autorizar a geração determinística de ofertas.

## Escopo e evidência analisada

A auditoria comparou estes arquivos, sem alterá-los:

- `C:\Users\Marcelo Silva\Downloads\okf_wiki_2026-09-18.zip`
- `C:\Users\Marcelo Silva\Downloads\okf_wiki_2026-09-18_paths-corrigidos.zip`
- `C:\Users\Marcelo Silva\Downloads\okf_wiki_2026-09-18_paths-corrigidos-yaml-corrigido.zip`

Resultado do validador usado pelo runtime:

| Arquivo | Markdown | Erros | Avisos | Resultado |
|---|---:|---:|---:|---|
| Original | 475 | 1 | 128 | Reprovado |
| Paths corrigidos | 467 | 1 | 128 | Reprovado |
| Paths e YAML corrigidos | 467 | 0 | 128 | Válido com avisos |

O último ZIP pode ser importado porque não possui erro estrutural. Os 128 avisos
continuam relevantes e devem ser eliminados pelo gerador.

## Dois níveis de prontidão

O gerador deve distinguir explicitamente estes resultados:

1. **Apto à consulta**: estrutura, YAML, índices e links válidos. Documentos
   `draft` podem ser pesquisados como conhecimento não aprovado.
2. **Apto à negociação**: além de apto à consulta, possui política executável,
   aprovada, vigente e compatível com a instituição e o produto da sessão.

Ativar um bundle apenas seleciona o snapshot consultado pelas tools. Essa ação
não promove documentos `draft` e não aprova condições comerciais.

## Estrutura canônica do ZIP

O ZIP deve abrir diretamente nesta estrutura, sem uma pasta externa envolvendo
o conteúdo:

```text
index.md
log.md
GLOBAL/
  ...
COMPANIES/
  index.md
  fastpay/
    index.md
    INSTITUTIONS/
      index.md
      will-bank/
        index.md
        institution.md
        agente/
        knowledge/
        policies/
        CARTAO_DE_CREDITO/
          index.md
          agente/
          knowledge/
          policies/
PRODUCTS/
  ...
```

Regras obrigatórias para paths:

- Usar `/` como separador dentro do ZIP.
- Não usar path absoluto, `..`, barra invertida ou componente vazio.
- Escrever cada raiz lógica (`GLOBAL`, `COMPANIES`, `PRODUCTS`) uma única vez.
- Usar `will-bank` de forma consistente; não alternar com `will_bank`.
- Tratar o path do arquivo e os IDs do frontmatter como contratos diferentes.
  Por exemplo, o diretório pode ser `CARTAO_DE_CREDITO`, enquanto o identificador
  consumido pelo simulador é `cartao_de_credito`.
- Gerar cada `index.md` a partir do manifesto final de arquivos. Não copiar um
  índice intermediário de uma árvore aninhada.
- Reprovar colisões. O gerador não pode escolher silenciosamente qual conteúdo
  manter quando dois arquivos resultam no mesmo path canônico.

## Correções exigidas para os defeitos encontrados

### 1. Raiz `COMPANIES` repetida

O ZIP original inseriu uma segunda árvore completa dentro de diretórios de
instituição. Foram encontrados 69 paths removidos na correção:

- 37 sob `COMPANIES/fastpay/INSTITUTIONS/will_bank/`;
- 32 sob `COMPANIES/zerai/INSTITUTIONS/usedigi/`.

Exemplo Will Bank:

```text
# Incorreto
COMPANIES/fastpay/INSTITUTIONS/will_bank/COMPANIES/fastpay/INSTITUTIONS/will-bank/CARTAO_DE_CREDITO/policies/parcelamento.md

# Correto
COMPANIES/fastpay/INSTITUTIONS/will-bank/CARTAO_DE_CREDITO/policies/parcelamento.md
```

Exemplo UseDigi:

```text
# Incorreto
COMPANIES/zerai/INSTITUTIONS/usedigi/COMPANIES/zerai/INSTITUTIONS/usedigi/policies/parcelamento.md

# Correto
COMPANIES/zerai/INSTITUTIONS/usedigi/policies/parcelamento.md
```

A transformação recuperou 61 novos paths canônicos. Sete arquivos aninhados
apontavam para seis destinos que já existiam, portanto uma remoção automática de
prefixo teria causado colisões. Os destinos foram:

```text
COMPANIES/index.md
COMPANIES/fastpay/index.md
COMPANIES/fastpay/INSTITUTIONS/index.md
COMPANIES/zerai/index.md
COMPANIES/zerai/INSTITUTIONS/index.md
COMPANIES/zerai/INSTITUTIONS/usedigi/index.md
```

Nesses casos, o gerador deve reconstruir o índice a partir dos filhos reais. Não
deve sobrescrever o arquivo existente. A correção observada também precisou:

- trocar o link `will_bank/` por `will-bank/` em
  `COMPANIES/fastpay/INSTITUTIONS/index.md`;
- reconstruir `COMPANIES/zerai/INSTITUTIONS/usedigi/index.md` para apontar para
  `agente/`, `knowledge/`, `policies/` e `institution.md`;
- remover o índice intermediário órfão
  `COMPANIES/fastpay/INSTITUTIONS/will_bank/index.md`.

### 2. YAML inválido

O arquivo quebrado era:

```text
COMPANIES/fastpay/INSTITUTIONS/will-bank/CARTAO_DE_CREDITO/policies/negativacao-spc.md
```

Correção:

```yaml
# Incorreto: o valor iniciado por hífen é interpretado como estrutura YAML.
description: - A DEFINIR PELA OPERAÇÃO

# Correto
description: "A DEFINIR PELA OPERAÇÃO"
```

O gerador deve serializar frontmatter com uma biblioteca YAML e validar o texto
serializado. Não deve montar YAML por concatenação de strings.

### 3. Links quebrados no `log.md`

Os três ZIPs possuem 128 links iniciados por `/` no `log.md`. Os arquivos de
destino existem, mas o validador OKF interpreta esses links como paths relativos
ao bundle e reporta `broken_relative_link`.

```markdown
<!-- Incorreto -->
[Desconto](/GLOBAL/04_NEGOCIACAO/desconto.md)

<!-- Correto no log.md da raiz -->
[Desconto](GLOBAL/04_NEGOCIACAO/desconto.md)
```

O gerador deve criar links relativos ao arquivo de origem, sem `/` inicial, e
validar cada destino contra o manifesto final antes de fechar o ZIP.

## Política executável de negociação

Texto explicativo sobre desconto ou parcelamento não autoriza uma oferta. A tool
`generate_offer` exige frontmatter declarativo no documento de política lido.

Exemplo sintético completo:

```yaml
---
type: Policy
title: Política de negociação — Banco Exemplo
status: stable
okf_version: "0.2"
scope: institution
institution: Banco Exemplo
product: cartao_teste
effective_from: "2026-09-20T00:00:00Z"
effective_until: "2027-09-20T00:00:00Z"
negotiation:
  payment_types:
    - cash
    - installment
  max_installments: 6
  max_discount_percentage: "10.00"
verified:
  - by: "human:responsavel-operacional"
    at: "2026-09-20T00:00:00Z"
---
```

Os nomes e valores acima são apenas exemplos sintéticos. Não representam uma
política aprovada para Will Bank, UseDigi ou qualquer operação real.

Para ser executável, a política deve cumprir todos estes requisitos:

- `status` igual a `published`, `stable` ou `active`;
- `institution` exatamente igual ao valor retornado pela tool transacional;
- `product` exatamente igual ao valor retornado pela tool transacional;
- vigência válida quando `effective_from`, `effective_until` ou `stale_after`
  forem informados;
- `negotiation.payment_types` como lista contendo somente modalidades suportadas;
- `negotiation.max_installments` como inteiro entre 1 e 360;
- `negotiation.max_discount_percentage` como decimal entre 0 e 100;
- revisão humana registrada antes da promoção de status.

O ZIP analisado ainda não atende a esse contrato:

- não há nenhum bloco `negotiation:` nos 467 documentos do ZIP corrigido;
- 403 documentos estão em `draft`, 63 não declaram status e apenas um está
  `stable`;
- 307 documentos ainda contêm `A DEFINIR PELA OPERAÇÃO`;
- documentos da Will Bank alternam `Will Bank` e `will-bank`;
- o produto aparece como `Cartão de crédito`, enquanto o simulador atual usa
  `cartao_de_credito`.

Alguns números aparecem no corpo dos documentos, mas texto livre não substitui o
contrato declarativo nem a aprovação humana.

## Como representar conteúdo ainda não aprovado

Enquanto houver qualquer condição comercial pendente, o documento deve permanecer
em `draft` e não deve conter um bloco `negotiation` parcialmente preenchido:

```yaml
---
type: Policy
title: Política de negociação — Will Bank
status: draft
institution: Will Bank
product: cartao_de_credito
---
```

O corpo pode registrar pendências para revisão, mas a interface e o relatório de
build devem classificar essa política como não executável. Nunca converter
`A DEFINIR PELA OPERAÇÃO` em zero, lista vazia ou valor presumido.

## Fluxo obrigatório do gerador

```text
Dados de origem e onboarding
            |
            v
Normalizar IDs e paths em memória
            |
            v
Detectar colisões e referências ausentes
            |
            v
Gerar documentos e índices a partir do manifesto final
            |
            v
Serializar e validar YAML
            |
            v
Classificar políticas como draft ou executáveis
            |
            v
Revisão e aprovação humana das condições comerciais
            |
            v
Promover somente as políticas aprovadas
            |
            v
Validar novamente e criar o ZIP imutável
```

O gerador deve interromper a criação de um bundle declarado como apto à negociação
quando ocorrer qualquer uma destas condições:

- erro ou aviso `broken_relative_link`;
- path duplicado ou raiz lógica repetida;
- YAML inválido, aliases ou chaves duplicadas;
- índice ausente ou apontando para destino inexistente;
- política publicada com placeholder pendente;
- política publicada sem `negotiation` completo;
- instituição ou produto sem correspondência com os IDs transacionais;
- ausência de revisão humana.

Um bundle apenas consultivo pode conter drafts, mas o relatório de build deve
informar claramente que ele não está apto a gerar ofertas.

## Checklist de aceite

Antes de disponibilizar o ZIP:

- [ ] O ZIP possui `index.md` na raiz.
- [ ] Existem somente as raízes esperadas e nenhum prefixo repetido.
- [ ] Todos os paths são únicos e bundle-relative.
- [ ] Todos os `index.md` foram reconstruídos do manifesto final.
- [ ] Todo frontmatter é YAML válido e possui `type` quando exigido.
- [ ] Todos os links relativos resolvem para arquivos presentes no ZIP.
- [ ] Não existem placeholders em políticas publicadas.
- [ ] Toda política executável possui `negotiation` completo.
- [ ] Instituição e produto usam os IDs exatos do runtime.
- [ ] Toda política executável possui aprovação e vigência verificáveis.
- [ ] O relatório separa “apto à consulta” de “apto à negociação”.
- [ ] Uma validação final foi executada sobre o ZIP pronto, não apenas sobre os
      arquivos intermediários.

