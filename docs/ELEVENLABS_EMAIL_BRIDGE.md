# Ponte de e-mail do ElevenLabs

O agente Fastpay DEMO envia o e-mail com os dados já disponíveis na ligação, sem
validar CPF e sem consultar sessão, proposta ou pagamento no Runtime:

```text
POST /integrations/elevenlabs/send-demo-email
Authorization: Bearer <ELEVENLABS_RUNTIME_API_TOKEN>
Content-Type: application/json
```

```json
{
  "session_id": "11111111-1111-4111-8111-111111111111",
  "contact_name": "Marcelo",
  "credor": "Fastpay",
  "valor_divida": "R$ 850,00",
  "valor_total": 750.00,
  "valor_parcela": 250.00,
  "forma_pagamento": "BOLETO",
  "parcelas": 3,
  "email": "cliente@example.com",
  "latest_user_message": "Envie para cliente@example.com"
}
```

Na tool Fastpay, `valor_total` é obrigatório e `valor_parcela` é opcional. A rota
aceita `valor_total` ausente como fallback técnico para `valor_divida`; sem
`valor_parcela`, divide o total pela quantidade de parcelas.
O produto é fixo em `cartao_de_credito` neste DEMO. PIX aceita uma parcela e boleto
aceita de uma a dez. O endereço precisa aparecer em `latest_user_message`.

O contrato abaixo continua reservado ao fluxo que já possui sessão e pagamento no
Runtime. Ele não foi relaxado e segue exigindo identidade validada:

```text
POST /integrations/elevenlabs/send-payment-instruction
Authorization: Bearer <ELEVENLABS_RUNTIME_API_TOKEN>
Content-Type: application/json
```

```json
{
  "session_id": "11111111-1111-4111-8111-111111111111",
  "payment_id": "PAY-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "email": "cliente@example.com",
  "latest_user_message": "Envie para cliente@example.com"
}
```

Regras:

- `session_id` precisa ser UUID e existir no Runtime;
- a identidade da sessão precisa estar validada;
- `payment_id` precisa pertencer à mesma sessão e continuar compatível com a
  política publicada;
- o e-mail precisa aparecer integralmente em `latest_user_message`;
- reenvios da mesma combinação de pagamento e destinatário reutilizam o resultado
  persistido;
- `success=true` e `sent=true` significam aceite do provedor, não entrega na caixa;
- o destinatário não é persistido e nunca aparece na resposta.

Variáveis locais:

- `ELEVENLABS_RUNTIME_API_TOKEN`: autentica somente esta entrada do agente de voz;
- `CHANNEL_CONSOLE_AGENT_RUNTIME_TOKEN`: credencial restrita usada pelo Runtime
  para catálogo e disparo de e-mail no Canais;
- `CHANNEL_CONSOLE_ENGINE_TOKEN`: fallback temporário dos fluxos existentes.

O agente legado permanece com sua configuração atual. A nova tool Fastpay usa a
rota DEMO e só deve ser vinculada ao novo agente depois da publicação do Runtime.

## Usedigi no Runtime OSS

O agente de voz Usedigi usa um webhook separado no Playground. Esse webhook
exige `DEMO_VOICE_TOOL_TOKEN`, uma sessão de voz emitida para a carteira e
destinatário em `DEMO_VOICE_ALLOWED_EMAILS` (inicialmente apenas Marcelo). O
Playground encaminha pela rede privada para o Runtime OSS com `X-Api-Key`:

```text
POST /integrations/elevenlabs/send-demo-email
X-Api-Key: <OSS_RUNTIME_API_TOKEN>
```

O corpo inclui o `scope_id` e o produto daquela carteira, além dos termos da
simulação. O Runtime OSS usa `CHANNEL_CONSOLE_RUNTIME_TOKEN_SCOPE_<id>` para
consultar o template e solicitar o disparo no Canais; não usa o vínculo de
Resend nem o token da carteira principal. A tool global antiga do ElevenLabs
não deve ser editada nem vinculada ao agente Usedigi.
