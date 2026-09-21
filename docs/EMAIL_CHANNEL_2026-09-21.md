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
