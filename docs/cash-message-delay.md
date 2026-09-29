# Pausa na entrega das mensagens

Escopo confirmado pelo operador: somente separar a frase existente de verificação
e a continuação por cinco segundos. Não adiciona tool, instrução, consulta, cálculo,
proposta ou transição de negociação. Workflow, AGENTS.md e manifesto permanecem
iguais à base 0.14.6.

O middleware HTTP atua somente no POST de runs/stream com mensagens identificadas.
Quando um evento AI do turno atual contém a abertura existente
`Entendi, <nome>. Vou verificar internamente se consigo uma condição especial para pagamento à vista hoje.`,
libera esse trecho imediatamente e espera cinco segundos antes de liberar os
bytes originais e a continuação do stream. A espera é assíncrona e acontece somente
uma vez por resposta HTTP. Eventos values e messages/partial/complete são suportados.
Nenhum histórico/checkpoint é reescrito; o marcador de entrega existe somente no
stream. Não muda as respostas de runs/wait, leituras de histórico ou outros endpoints.

Canais 0.29.1 reconhece o marcador, usa os mesmos blocos persistidos/retries e
não reenvia o prefixo já aceito. Preserva a espera mínima após aceite da primeira
mensagem pelo provedor. Playground consome os eventos nativos existentes; não
exige deploy de frontend.

O restante do texto não é gerado por este middleware. Se a resposta original
contiver somente o anúncio, somente ele será exibido; não há continuação artificial,
segunda chamada LLM ou tool adicional. Se a frase não corresponder à abertura
existente, o stream segue sem pausa. Essa detecção é de texto de saída, não de
intenção nem condição comercial. Latência da rede pode alterar o intervalo percebido.

O buffer adicional por evento SSE é limitado a 8 MiB; não retém séries de snapshots.
Snapshots históricos não acionam a pausa de values. Canais mantém seu worker serial.

A implantação inicial 0.15.0, que continha uma tool adicional, foi retirada após
a correção de escopo. Nenhuma instrução preparada para o Assistant foi aplicada.
O runtime anterior 0.14.6 foi restaurado antes desta versão 0.14.7.
