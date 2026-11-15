# Validación — Fase 3: Orquestación multiagente

## 1. Automatizado (CI y PR)

- Backend (en `backend/`): `uv run ruff check`, `uv run ruff format --check`, `uv run mypy app`, `uv run pytest` (incluidos `@pytest.mark.db`, `tests/golden` y los de propiedades, con la BD de test migrada a `head`: `DATABASE_URL="$TEST_DATABASE_URL" uv run alembic upgrade head`, que ahora aplica `0007`, `0008` y `0009`).
- Frontend (en `frontend/`): `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`.
- `uv run python scripts/export_openapi.py` y `npm run gen:api` no dejan diff (`backend/openapi.json` y `frontend/types/api.ts` versionados y al día).
- **Ningún test llama a la red ni a un LLM real:** `ALLOW_MODEL_REQUESTS = False` global (D84) y la CI no define `ANTHROPIC_API_KEY`.
- `hypothesis` con semilla/derandomización fija en CI, como en la Fase 2.

### Afirmaciones concretas que deben existir en los tests

| Afirmación | Dónde |
| :--- | :--- |
| `Settings` no muestra `ANTHROPIC_API_KEY` en `repr`; rechaza `PROPOSAL_TARGET_RR < MIN_RR`, tope de coste sin precios y `ANALYSIS_LOOKBACK_BARS=10`. | `tests/test_config.py` |
| La suite tiene `ALLOW_MODEL_REQUESTS = False`; un agente sin *override* no sale a la red. | `tests/conftest.py`, `tests/agents/test_echo.py` |
| `app/quant/` y `app/risk/` no importan `pydantic_ai`, `anthropic`, `fastapi`, `sqlalchemy` ni `httpx`. | `tests/test_architecture.py` |
| Los esquemas de agentes rechazan campos desconocidos (`extra="forbid"`), `timeframes` con < 2 marcos o repetidos, y son inmutables. | `tests/schemas/test_agents.py` |
| `TradeSignalSchema`: LONG ⇒ `stop_loss < entry < take_profit` (SHORT al revés); `APPROVED` ⇒ `size` presente y sin `veto_reasons`; los `Decimal` viajan como cadena. | `tests/schemas/test_signals.py` |
| `AnalyzeRequest` exige que `timeframe` esté en `timeframes`; `AnalysisEvent` discrimina por `event` y hace ida y vuelta JSON. | `tests/schemas/test_analysis.py` |
| `agent_analyses` existe tras `upgrade head`; `downgrade`/`upgrade` funcionan; los `CHECK` rechazan valores inválidos; **`UPDATE` y `DELETE` lanzan error** y `INSERT` sigue funcionando; `JSONB` hace *round-trip*. | `tests/repositories/test_agent_analyses_repo.py` |
| `trade_signals` ampliada: columnas nuevas, `CHECK` de `regime`, filas antiguas válidas; `list_active` solo devuelve `APPROVED`, filtra por clase de activo, ordena y respeta `limit`. | `tests/repositories/test_trade_signals_repo.py` |
| `build_proposal`: entrada en el borde del FVG sin mitigar o en el último cierre; SL = invalidación ∓ 0,5·ATR redondeado al tick en contra; TP a 2,0 R; `NO_TRADE` ⇒ sin propuesta con motivo. | `tests/quant/test_proposal.py` |
| **Propiedad:** toda propuesta tiene el SL del lado correcto, niveles múltiplos del tick y R:R ≥ objetivo (salvo redondeo documentado). | `tests/quant/test_proposal_props.py` |
| `build_model` sin clave ⇒ `AgentsNotConfiguredError` en español; el auditor usa `AGENT_AUDITOR_MODEL` si está definido. | `tests/agents/test_models.py` |
| El runner devuelve tokens, latencia y traza con `prompt_version`; `cost_usd` es `null` sin precios; un `FunctionModel` que excede el tope de tokens falla con el consumo. | `tests/agents/test_echo.py`, `tests/agents/test_runner.py` |
| Las herramientas de cada agente devuelven **exactamente** lo de las funciones de la Fase 2; un informe con niveles, FVG o régimen que no coinciden se rechaza con `ModelRetry`. | `tests/agents/test_structure_agent.py`, `test_quant_agent.py` |
| Kelly lo calcula la herramienta, nunca el LLM, y no interviene en el tamaño. | `tests/agents/test_quant_agent.py`, `tests/services/test_analysis_service.py` |
| **Si las guardas vetan, `RiskAuditorAgent` no se invoca; un `APPROVE` del modelo no puede aprobar lo vetado; un `VETO` del modelo rechaza lo aprobado.** | `tests/agents/test_risk_auditor.py` |
| **Propiedad:** `final_status` devuelve `APPROVED` solo si el veto determinista y el auditor aprueban. | `tests/agents/test_final_status_props.py` |
| Camino feliz: 5 filas en `agent_analyses` con el mismo `analysis_id`, en orden, y una `trade_signals` `APPROVED` enlazada. | `tests/services/test_analysis_service.py` |
| Veto determinista (R:R 1,5) ⇒ `SIGNAL_REJECTED`, sin fila `RISK_AUDIT`, con `veto_reasons` y señal `REJECTED` persistida. | `tests/services/test_analysis_service.py` |
| `NO_TRADE` ⇒ sin señal y con motivo; fallo de agente ⇒ fila `ERROR` y `analysis_failed`; tope de tokens ⇒ fallo que nombra el tope. | `tests/services/test_analysis_service.py` |
| Marcos sin datos (p. ej. NAS100 `1h`/`4h`) se omiten con aviso; con < 2 marcos o sin el marco de entrada ⇒ 422 con cantidades. | `tests/services/test_analysis_service.py`, `tests/api/test_agents.py` |
| **Propiedad:** ninguna señal `APPROVED` supera `RISK_PER_TRADE_PCT`, tiene R:R < `MIN_RR` ni se aprueba con pérdida diaria ≥ límite. | `tests/services/test_signals_props.py` |
| `POST /agents/analyze`: `text/event-stream`; eventos en orden; cada `data:` valida contra `AnalysisEvent`; el último contiene un `AgentReportSchema` válido. | `tests/api/test_agents.py` |
| `POST /agents/analyze`: 404 símbolo desconocido, 422 datos insuficientes o `timeframe` fuera de `timeframes`, **503 sin `ANTHROPIC_API_KEY`**; un fallo a mitad produce `analysis_failed`; un cliente que corta el *stream* no deja filas a medias. | `tests/api/test_agents.py` |
| `GET /signals/active`: solo `APPROVED`, filtro `asset_class`, `limit` fuera de 1–200 ⇒ 422, más recientes primero. | `tests/api/test_signals.py` |
| Ni la clave ni su valor aparecen en `trace`, `input`, logs ni mensajes de error. | `tests/services/test_analysis_service.py` |

## 2. Manual (smoke local)

Requisitos: Postgres local en marcha y datos ingeridos (Fase 1) para, al menos, `BTC/USDT` en `15m`, `1h`, `4h` y `1d` (≥ 100 velas cada uno).

1. `uv run alembic upgrade head` → aplica `0007_agent_analyses` y `0008_trade_signals_analysis`. `psql -d <db> -c "\d agent_analyses"` muestra `input`, `output` y `trace` en `jsonb`; `\d trade_signals` muestra las columnas nuevas.
2. **Solo inserción:** `psql -d <db> -c "UPDATE agent_analyses SET status='OK'"` y `DELETE FROM agent_analyses` fallan con `agent_analyses es de solo inserción` (con la tabla vacía, insertar una fila de prueba primero y borrarla con `TRUNCATE`).
3. Arrancar `uv run uvicorn app.main:app` **sin** `ANTHROPIC_API_KEY` y abrir `http://localhost:8000/docs`: aparecen `POST /api/v1/agents/analyze` (con `AnalyzeRequest` y la respuesta `text/event-stream`) y `GET /api/v1/signals/active`.
4. Sin clave:
   ```bash
   curl -i -N -X POST localhost:8000/api/v1/agents/analyze \
     -H 'content-type: application/json' -d '{"symbol":"BTC/USDT","timeframe":"1h"}'
   ```
   Esperado: **503** con `detail` «El análisis con agentes no está configurado: falta ANTHROPIC_API_KEY.» y ninguna fila nueva en `agent_analyses`.
5. Símbolo desconocido (`"symbol":"XYZ"`) → 404 `Instrumento desconocido: XYZ`. `"timeframe":"5m"` fuera de `timeframes` por defecto → 422.
6. `GET /api/v1/signals/active` (BD sin señales) → `200 []`; con `?limit=0` → 422; con `?asset_class=CRYPTO` → 200.
7. NAS100: `"symbol":"NAS100","timeframe":"1d"` (clave configurada o no) → o bien 503 si no hay clave, o bien el análisis con aviso «marcos omitidos: 1h, 4h (sin datos)».
8. Cliente de pruebas sin modelo real: ejecutar la suite de integración `uv run pytest tests/api/test_agents.py -v` y confirmar que el *stream* completo pasa con `FunctionModel`.
9. **Opcional, con clave real (D92):** poner `ANTHROPIC_API_KEY` en `backend/.env`, repetir el paso 4 y comprobar:
   - Salen en orden `analysis_started`, `step_started/step_completed` de `STRUCTURE`, `QUANT`, `PROPOSAL`, `GUARDS` y, si las guardas aprueban, `RISK_AUDIT`, y un `analysis_completed` con `outcome` y `usage`.
   - `SELECT step, model, input_tokens, output_tokens, cost_usd, latency_ms, status FROM agent_analyses WHERE analysis_id = '<id>' ORDER BY created_at;` muestra un paso por fila con tokens y latencia (y `cost_usd` nulo si no hay precios).
   - `SELECT trace->>'prompt_version', jsonb_array_length(trace->'messages') FROM agent_analyses WHERE step='STRUCTURE' ...` muestra la versión del prompt y las llamadas a herramientas.
   - Si hay señal: `SELECT status, rr, units, risk_amount FROM trade_signals ORDER BY created_at DESC LIMIT 1;` — `risk_amount ≤ equity · 1 %`, `rr ≥ 1.8`.
   - `GET /signals/active` la devuelve si es `APPROVED`.
   - Con `AGENT_MAX_TOKENS_PER_ANALYSIS=500`: el análisis termina con `analysis_failed` que nombra el tope y el consumo, y queda la fila `ERROR`.
   - Anotar en la PR el coste y la latencia de una ejecución, y los problemas de prompt vistos.
10. `npm run gen:api` en `frontend/` y `git status`: sin cambios.

### Casos límite

- Análisis dos veces seguidas con los mismos datos: dos `analysis_id` distintos; las filas de cada uno son independientes y las anteriores no cambian.
- Régimen `HIGH_VOLATILITY_NOISE` o `playbook=NO_TRADE` → `outcome = NO_TRADE`, sin señal y con motivo en español; sí hay filas en `agent_analyses`.
- Propuesta con R:R < 1,8 forzada en un test → `SIGNAL_REJECTED` con `RR_BELOW_MIN`, sin llamada al auditor.
- Un modelo que alucina un nivel o un FVG inexistente → reintento de validación y, si persiste, `step_failed` con el dato incorrecto nombrado.
- Un modelo que devuelve un `APPROVE` ante un veto determinista → la señal sigue `REJECTED`.
- Sin datos de otros instrumentos para la correlación → el par se trata como correlación desconocida (ρ = 1, D63) y el aviso lo dice.
- Cliente que corta el *stream* en el paso `QUANT` → el análisis se cancela, `STRUCTURE` queda persistido, no hay filas parciales de `QUANT` ni señal.

## 3. Tono

- `detail` de la API, `warnings`, `reasoning`, `concerns`, `rationale` y mensajes de evento: **español**, técnicos, con el dato problemático. Ejemplos: «Datos insuficientes para NAS100 1h: 0 velas, se necesitan al menos 100.», «Tope de tokens excedido: 61 240 de 60 000 en el paso QUANT.», «R:R 1.42 por debajo del mínimo 1.8», «Marcos omitidos por falta de datos: 1h, 4h.».
- Los prompts piden español técnico, sin lenguaje promocional ni garantías, y que el informe distinga hechos de las herramientas e hipótesis.
- Ninguna señal se presenta como predicción de rentabilidad; un veto se explica sin suavizarlo.
- No se expone ningún secreto en logs, trazas, eventos ni mensajes.

## 4. Terminado cuando

- Todo lo automatizado está en verde en la PR y en `main`, incluidos los tests `db`, los *golden* y los de propiedades, sin llamadas a la red.
- El smoke manual (pasos 1–8 y 10) pasa. El paso 9 con clave real se ejecuta cuando haya clave y, si no, queda anotado como pendiente en la PR y en el roadmap (D92), sin bloquear el cierre.
- 2.1–2.10 y 3.1–3.10 marcados como `[x]` en `roadmap.md`; `tech-stack.md` (changelog), el README y `requirements.md` (decisiones D98+) actualizados.
- Los tipos TS (incluido `AnalysisEvent`) están regenerados y sin diff.

**Se rechaza si:** el LLM calcula o escribe un precio, un tamaño de posición, un Kelly aplicado o cualquier métrica de riesgo; el auditor puede aprobar algo que el código vetó; `agent_analyses` admite `UPDATE` o `DELETE`; un test llama a la red o la CI necesita `ANTHROPIC_API_KEY`; una dependencia distinta de la aprobada se añadió sin preguntar; `quant/` o `risk/` importan `pydantic_ai`, FastAPI, SQLAlchemy o `httpx`; la clave aparece en un log, traza, evento o mensaje; un fallo de agente se esconde (sin fila `ERROR` ni evento `analysis_failed`); o hay `float` en importes de las señales (`entry`, `stop_loss`, `take_profit`, `size`).
