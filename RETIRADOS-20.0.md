# Módulos retirados de 20.0

Estos módulos **no se migran a Odoo 20.0** y se quitaron de esta rama. Siguen en las ramas
anteriores (16.0–19.0) para los clientes que los tengan instalados.

- **Antes de pasar un cliente a 20.0:** desinstalarlos en su base, sobre la versión que use
  hoy, como indica la última columna. Si quedan instalados, el upgrade los encuentra sin
  código.
- **Forward-port:** si un PR a 19.0 toca uno de estos módulos, se mergea con
  `@robbmya r+ no-fw`. Si no, el forward-port a 20.0 choca contra el borrado.
- La decisión es parte del plan de migración de módulos BMyA a 20.0 (2026-09-27).

Con este retiro, la rama 20.0 de bmya-ai queda **sin módulos**.

| Módulo | Por qué se retira | Qué usar en 20.0 | Antes del upgrade del cliente |
|---|---|---|---|
| `ai_fields_gemini` | En 20.0 la IA pasa por el servicio IAP de Odoo (`odoo_ai`, commit enterprise `5cc937531b8`): ya no hay claves propias de OpenAI/Gemini y el modelo lo elige el servidor de Odoo. Además, `ai_fields.tools` y `LLMApiService` ya no existen | Los campos IA nativos (`ai_fields`), por IAP. A futuro, el gateway IA de BMyA con el parámetro `ai.endpoint` | Desinstalar |
| `ai_perplexity_agent` | Depende de `ai_app` (en 20.0 es `ai_agentic`) y de `LLMApiService`/`llm_providers`, que ya no existen. En 19.0 además falla al importar: el `Provider` del core pide 7 campos y el módulo arma 5 | Los agentes nativos (`ai_agentic`), por IAP | Desinstalar (en bmya.cl ya está desinstalado) |
| `ai_perplexity` | Perplexity dejó su API solo en el plan Max, así que queda inviable. `crm_enrichment` y `crm_gatekeeper` (bmya-crm) se migran sin esta dependencia | El punto de conexión LLM opcional de los módulos CRM (gateway IA de BMyA) | Primero quitar la dependencia de los CRM en 19.0 y después desinstalar |
