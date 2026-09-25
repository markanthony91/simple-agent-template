# Ponte de e-mail do ElevenLabs

O endpoint abaixo permite que o novo agente Fastpay e futuros agentes enviem uma
instrução simulada já criada pelo Agent Runtime. Ele não cria proposta e não aceita
valores, descontos, parcelas, credor, produto ou código de pagamento do agente de voz.

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

O novo tool do ElevenLabs deve usar este contrato. O agente legado permanece com
sua configuração atual até uma migração separada.
