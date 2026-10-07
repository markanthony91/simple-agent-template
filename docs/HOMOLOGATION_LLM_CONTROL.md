# LLM por carteira na homologação

Com `CHANNELS_LLM_CONTROL_ENABLED=true`, cada execução do grafo `agent` no
Runtime OSS consulta Canais usando `CHANNELS_LLM_RESOLVER_URL` (HTTPS) e o
Bearer privado `CHANNELS_LLM_RESOLVER_TOKEN`. A consulta informa scope, tenant
e Assistant da execução; Canais confere essa associação antes de retornar
endpoint, modelo, proxy e credencial. O Runtime mantém esses dados somente no
contexto transitório da execução, sem incluí-los em checkpoint ou resposta do
chat. Um erro de consulta interrompe a execução, sem recorrer silenciosamente
às credenciais locais.

O Runtime Principal usa `langgraph dev` e não importa `oss_runtime.py`; portanto
essa opção não o afeta. O recurso deve ser habilitado somente no serviço de
Homologação, depois de configurar as integrações e os vínculos das carteiras em
Canais. Os valores LLM existentes em homologação permanecem como rollback:
desabilitar `CHANNELS_LLM_CONTROL_ENABLED` restaura a seleção local sem
migrar sessões ou alterar bancos.
