# Especificação para o Lovable — gerador de bundle OKF apto à negociação

## Solicitação

Corrigir o gerador/exportador de bundles OKF 0.2 do projeto Lovable para produzir
um ZIP estruturalmente válido e informar, de forma explícita, se o resultado está:

1. **Apto à consulta**: pode ser navegado e lido pelas tools OKF.
2. **Apto à negociação**: contém política comercial aprovada e pode autorizar a
   geração determinística de ofertas.

Não considerar um ZIP apto à negociação apenas porque foi criado, importado ou
ativado. Ativar o bundle seleciona o snapshot consultado; não aprova documentos.

## Fonte única desta análise

Use somente este arquivo como fixture de regressão:

```text
C:\Users\Marcelo Silva\Downloads\okf_wiki_2026-09-18.zip
```

Não use versões corrigidas anteriormente para implementar ou validar esta tarefa.
O gerador deve corrigir os problemas a partir do ZIP original e das regras abaixo.

## Diagnóstico do ZIP original

| Verificação | Resultado |
|---|---:|
| Arquivos Markdown | 475 |
| Erros de validação | 1 |
| Avisos de links quebrados | 128 |
| Documentos `draft` | 403 |
| Documentos `stable` | 1 |
| Documentos sem `status` | 71 |
| Documentos com `A DEFINIR PELA OPERAÇÃO` | 307 |
| Documentos com frontmatter `negotiation` | 0 |

O ZIP original está reprovado para importação por YAML inválido. Mesmo após a
correção estrutural, continuará inapto à negociação enquanto não existirem
políticas executáveis e aprovadas.

## Estrutura esperada

O ZIP deve abrir diretamente na raiz OKF, sem uma pasta externa envolvendo o
conteúdo:

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
  zerai/
    index.md
    INSTITUTIONS/
      index.md
      usedigi/
        index.md
        institution.md
        agente/
        knowledge/
        policies/
PRODUCTS/
  ...
```

Regras obrigatórias:

- Usar `/` como separador dentro do ZIP.
- Não aceitar path absoluto, `..`, barra invertida ou componente vazio.
- Escrever `GLOBAL`, `COMPANIES` e `PRODUCTS` no máximo uma vez em cada path.
- Usar `will-bank` de forma consistente; não alternar com `will_bank`.
- Gerar cada `index.md` a partir do manifesto final de arquivos.
- Reprovar colisões em vez de sobrescrever silenciosamente um arquivo.
- Manter paths como identidades bundle-relative; não concatenar um path já
  completo ao diretório atual.

## Correção 1 — árvore `COMPANIES` repetida

O ZIP original contém 70 paths sob duas áreas problemáticas:

| Prefixo | Total | Com raiz `COMPANIES` repetida | Índice local |
|---|---:|---:|---:|
| `COMPANIES/fastpay/INSTITUTIONS/will_bank/` | 37 | 36 | 1 |
| `COMPANIES/zerai/INSTITUTIONS/usedigi/` | 33 | 32 | 1 |

São 68 arquivos em que uma segunda árvore `COMPANIES/...` foi gravada dentro da
instituição.

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

Ao remover o prefixo repetido dos 68 arquivos, surgem 67 destinos canônicos:

- 61 destinos ainda não existem no ZIP original;
- 7 arquivos de origem convergem para 6 destinos que já existem;
- dois arquivos diferentes convergem para `COMPANIES/index.md`.

Destinos com colisão:

```text
COMPANIES/index.md
COMPANIES/fastpay/index.md
COMPANIES/fastpay/INSTITUTIONS/index.md
COMPANIES/zerai/index.md
COMPANIES/zerai/INSTITUTIONS/index.md
COMPANIES/zerai/INSTITUTIONS/usedigi/index.md
```

Não escolher uma versão arbitrariamente. Para todos esses destinos, reconstruir
o `index.md` usando os filhos existentes no manifesto final.

Tratamento dos dois índices locais:

- remover `COMPANIES/fastpay/INSTITUTIONS/will_bank/index.md`, pois ele representa
  o wrapper incorreto `will_bank`;
- manter e reconstruir `COMPANIES/zerai/INSTITUTIONS/usedigi/index.md`, pois esse é
  o path canônico da UseDigi, mas seu conteúdo atual aponta para `COMPANIES/` como
  filho e não para os conceitos reais da instituição.

O índice `COMPANIES/fastpay/INSTITUTIONS/index.md` deve apontar para `will-bank/`,
sem underscore.

## Correção 2 — YAML inválido

O erro está neste path do ZIP original:

```text
COMPANIES/fastpay/INSTITUTIONS/will_bank/COMPANIES/fastpay/INSTITUTIONS/will-bank/CARTAO_DE_CREDITO/policies/negativacao-spc.md
```

Conteúdo incorreto:

```yaml
description: - A DEFINIR PELA OPERAÇÃO
```

Conteúdo válido:

```yaml
description: "A DEFINIR PELA OPERAÇÃO"
```

Implementação exigida no Lovable:

- usar um serializador YAML para produzir o frontmatter;
- validar novamente o YAML serializado;
- rejeitar aliases e chaves duplicadas;
- não montar frontmatter por concatenação manual de strings.

## Correção 3 — links do `log.md`

O `log.md` possui 128 links locais iniciados por `/`. Todos os destinos existem
no ZIP original quando essa barra inicial é removida. Como os paths OKF são
bundle-relative, a barra inicial deve ser eliminada na geração.

```markdown
<!-- Incorreto -->
[Desconto](/GLOBAL/04_NEGOCIACAO/desconto.md)

<!-- Correto no log.md da raiz -->
[Desconto](GLOBAL/04_NEGOCIACAO/desconto.md)
```

Para arquivos localizados em subdiretórios, calcular o link relativo a partir do
arquivo de origem. Validar todos os destinos contra o manifesto final antes de
gerar o ZIP.

## Política executável de negociação

Texto livre sobre desconto, entrada ou parcelamento não autoriza uma oferta. Uma
política executável precisa de frontmatter declarativo, completo e aprovado.

Exemplo exclusivamente sintético:

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

Os nomes e valores desse exemplo não representam condições aprovadas para Will
Bank, UseDigi ou qualquer operação real.

Uma política só pode ser classificada como executável quando:

- `status` for `published`, `stable` ou `active`;
- `institution` for exatamente igual ao ID retornado pela fonte transacional;
- `product` for exatamente igual ao ID retornado pela fonte transacional;
- a política estiver vigente;
- `negotiation.payment_types` for uma lista de modalidades suportadas;
- `negotiation.max_installments` for um inteiro entre 1 e 360;
- `negotiation.max_discount_percentage` for um decimal entre 0 e 100;
- não houver `A DEFINIR PELA OPERAÇÃO` em nenhum termo necessário;
- houver aprovação humana registrada.

O path e os IDs do frontmatter são contratos diferentes. Por exemplo, o diretório
pode continuar como `CARTAO_DE_CREDITO`, enquanto o produto transacional pode ser
`cartao_de_credito`. O gerador não deve deduzir um ID a partir do nome de exibição.

## Conteúdo ainda não aprovado

Quando faltar qualquer condição comercial, manter o documento como `draft` e não
gerar um bloco `negotiation` parcial:

```yaml
---
type: Policy
title: Política de negociação — Will Bank
status: draft
institution: Will Bank
product: cartao_de_credito
---
```

Nunca converter `A DEFINIR PELA OPERAÇÃO` em zero, lista vazia, valor padrão ou
estimativa. O Lovable deve mostrar que a política não está pronta para negociação
e quais campos ainda precisam de definição.

## Fluxo esperado no Lovable

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
Gerar documentos e índices pelo manifesto final
            |
            v
Serializar e validar o YAML
            |
            v
Classificar consulta e negociação separadamente
            |
            v
Revisão humana das condições comerciais
            |
            v
Promover somente as políticas aprovadas
            |
            v
Validar o artefato final e gerar o ZIP imutável
```

Na interface do gerador, apresentar antes do download:

- quantidade de arquivos;
- erros e avisos de validação;
- colisões de paths;
- links sem destino;
- políticas em `draft`;
- políticas executáveis;
- placeholders pendentes;
- resultado separado: `Apto à consulta` e `Apto à negociação`.

O botão que declara o bundle apto à negociação deve ficar indisponível enquanto
houver erro comercial ou ausência de aprovação. A exportação de um bundle apenas
consultivo pode continuar disponível, desde que essa limitação esteja visível.

## Critérios de aceite

Usando somente `okf_wiki_2026-09-18.zip` como entrada de regressão:

- [ ] A saída possui `index.md` diretamente na raiz.
- [ ] A saída possui 467 arquivos Markdown após a normalização descrita.
- [ ] Nenhum path contém uma segunda raiz `COMPANIES`.
- [ ] Não existe o wrapper `will_bank`; a instituição usa `will-bank`.
- [ ] Os seis índices com colisão foram reconstruídos pelo manifesto final.
- [ ] `COMPANIES/zerai/INSTITUTIONS/usedigi/index.md` lista seus filhos reais.
- [ ] O YAML de `negativacao-spc.md` é válido.
- [ ] Nenhum link do `log.md` começa com `/`.
- [ ] Todos os links locais resolvem para arquivos presentes no ZIP.
- [ ] O validador final retorna zero erros e zero `broken_relative_link`.
- [ ] O relatório informa que o bundle está apto à consulta.
- [ ] O relatório não informa aptidão à negociação enquanto não houver política
      executável e aprovação humana.
- [ ] Políticas publicadas possuem `negotiation` completo e IDs transacionais
      exatos.
- [ ] A validação é executada sobre o ZIP final, não apenas sobre objetos
      intermediários da interface.

## Fora do escopo desta correção

- Definir percentuais, parcelas, juros, entrada ou alçada da operação.
- Aprovar automaticamente documentos `draft`.
- Alterar tools de consulta, geração de oferta ou formalização de acordo.
- Usar valores do simulador como substitutos para política aprovada.

