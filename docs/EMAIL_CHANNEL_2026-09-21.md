# Envio de instruções por e-mail

`send_payment_instruction` envia a instrução de pagamento simulada pelo perfil
`email` do Zerai Channel Console. O endereço precisa aparecer integralmente na
última mensagem humana. Identidade, pagamento e política são revalidados antes da
consulta ao catálogo.

## Configuração

O Runtime usa as variáveis já existentes:

- `CHANNEL_CONSOLE_URL` ou `RAILWAY_SERVICE_ZERAI_CHANNEL_CONSOLE_URL`;
- `CHANNEL_CONSOLE_ENGINE_TOKEN`, com o mesmo valor de `ENGINE_API_TOKEN` no
  Zerai Channel Console.

O Console precisa publicar um perfil `email` em `ENGINE_CHANNELS_CSV`, com
`template_id` e um endereço padrão válido em `to`. A tool pode substituir somente
o destinatário desse canal. O template pode usar:

- `nome`, `credor`, `produto`;
- `forma_pagamento`, `valor`, `codigo_pagamento`;
- `payment_id`, `agreement_id`, `numero_parcela`, `parcelas`;
- `aviso_simulacao`, `is_simulation`.

Variável desconhecida bloqueia o envio. O template recomendado deve incluir
`{{aviso_simulacao}}`, pois PIX e boleto continuam deliberadamente inválidos.

## Resultado

O Runtime reserva um request ID antes do POST, não persiste o endereço e não
repete resultado incerto. `sent=true` significa somente que o Resend aceitou o
pedido. Uma resposta determinística informa essa condição sem afirmar entrega.
Webhook de entrega/bounce permanece fora desta versão.

## Publicação inativa

PR [#31](https://github.com/markanthony91/simple-agent-template/pull/31)
mesclado no commit `69efe8f0c4d30038c90ace1fe446d64bd9cf0ca9`. Runtime 0.12.0
publicado no Railway no deployment `6da9eb39-14af-4f45-9f68-27815d488050`.

Antes do deploy, o backup `/data/backups/pre-email-20260921` passou no
`integrity_check`. Depois do deploy, as seis tabelas mantiveram as mesmas contagens:
160 sessões, 12 clientes, 12 dívidas, 12 contextos, uma carteira e um tenant. A
consulta Runtime → Console funcionou e confirmou `email_active=false`; nenhum
provedor foi acionado.
