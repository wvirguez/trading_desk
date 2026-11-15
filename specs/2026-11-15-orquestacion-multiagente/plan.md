# Plan — Fase 3: Orquestación multiagente

Regla de cada grupo: **esquema → tests → implementación**, y termina en un commit verde (`ruff`, `mypy`, `pytest`). Decisiones D81–D97 en [`requirements.md`](requirements.md). Los grupos se pueden implementar por separado, en este orden. Los comandos se ejecutan en `backend/` salvo que se indique. Ningún test llama a la red ni a un LLM real (D84).

## 1. Dependencias y configuración

1.1. Dependencia **aprobada** (D82): `uv add "pydantic-ai-slim[anthropic]"`. Si no basta `slim`, preguntar antes de cambiar. Confirmar con `uv run python -c "import pydantic_ai, anthropic"` y que `uv.lock` queda actualizado.
1.2. `Settings` (`app/core/config.py`): las 12 variables de la sección 4 de `requirements.md`; `anthropic_api_key` como `SecretStr | None`; validadores de rango y de coherencia (`PROPOSAL_TARGET_RR ≥ MIN_RR`; tope de coste solo con ambos precios). Actualizar `backend/.env.example`.
1.3. Tests en `tests/test_config.py`: valores por defecto; `repr(settings)` no contiene la clave; rechazo de `PROPOSAL_TARGET_RR=1.0` (con `MIN_RR=1.8`), `AGENT_MAX_COST_USD_PER_ANALYSIS` sin precios y `ANALYSIS_LOOKBACK_BARS=10`.
1.4. `tests/conftest.py`: fijar `pydantic_ai.models.ALLOW_MODEL_REQUESTS = False` para toda la suite (D84) y un test que lo verifica.
1.5. Test de arquitectura (`tests/test_architecture.py`): `app/quant/` y `app/risk/` no importan `pydantic_ai` ni `anthropic` (ampliación de D66 → D97).
1.6. Commit: `Feat: dependencias y configuracion de agentes (fase 3)`.

## 2. Esquemas Pydantic

2.1. Enums nuevos en `app/schemas/enums.py`: `Bias`, `Playbook`, `AuditDecision`, `AnalysisStep`, `AnalysisOutcome`. Tests en `tests/schemas/test_enums.py`.
2.2. `app/schemas/agents.py`: `TimeframeStructure`, `MarketStructureReport`, `QuantAlphaReport`, `RiskVerdict` (`frozen=True`, `extra="forbid"`; `reasoning` acotado en longitud; `timeframes` con ≥ 2 elementos y sin marcos repetidos).
2.3. `app/schemas/signals.py`: `ProposedSignal` y `TradeSignalSchema` (invariantes: LONG ⇒ `stop_loss < entry < take_profit`, SHORT al revés; `status = APPROVED` ⇒ `size` presente y `veto_reasons == []`; `REJECTED` ⇒ `veto_reasons` no vacío **o** un rechazo del auditor registrado en `rationale`).
2.4. `app/schemas/analysis.py`: `AnalyzeRequest` (`timeframe` debe estar en `timeframes`; `symbol` no vacío; sin marcos repetidos), `StepUsage`, `AgentReportSchema` y la unión discriminada `AnalysisEvent` (con `seq`).
2.5. Tests (`tests/schemas/test_agents.py`, `test_signals.py`, `test_analysis.py`): cada invariante de arriba; los `Decimal` viajan como cadena en JSON; `extra="forbid"` rechaza campos desconocidos (un LLM que añade campos falla la validación); inmutabilidad; `AnalysisEvent` discrimina bien por `event`; ida y vuelta JSON de `AgentReportSchema`.
2.6. `mypy --strict` pasa. Commit: `Feat: esquemas de agentes, señales y analisis`.

## 3. Base de datos: modelos, migraciones y repositorios

3.1. Modelo `app/models/agent_analysis.py` (`AgentAnalysis`) con `CHECK` de `step`, `timeframe` y `status` (`enum_check`), `JSONB` en `input`/`output`/`trace` e índices `(analysis_id)` y `(instrument_id, created_at DESC)`. Registrarlo en `app/models/__init__.py`.
3.2. Migración `0007_agent_analyses`: crea la tabla, los índices y el *trigger* `BEFORE UPDATE OR DELETE` que lanza `RAISE EXCEPTION 'agent_analyses es de solo inserción'` (D88); `downgrade` los elimina.
3.3. Ampliar `app/models/trade_signal.py` y migración `0008_trade_signals_analysis`: columnas `analysis_id`, `rr`, `units`, `risk_amount`, `regime` (con `CHECK`), `rationale` y `veto_reasons JSONB NOT NULL DEFAULT '[]'` (todas nulables salvo la última); `downgrade` las elimina. Índice `(analysis_id)`.
3.4. Tests `db` (`tests/repositories/test_agent_analyses_repo.py`, `test_trade_signals_repo.py`): `upgrade head` crea ambas; `downgrade -1` y `upgrade head` funcionan; los `CHECK` rechazan `step`/`timeframe`/`status`/`regime` inválidos; `JSONB` hace *round-trip*; **`UPDATE` y `DELETE` sobre `agent_analyses` lanzan error** y un `INSERT` posterior sigue funcionando; las filas antiguas de `trade_signals` siguen siendo válidas. Actualizar la fixture de `TRUNCATE` para incluir `agent_analyses`.
3.5. `app/repositories/agent_analyses.py`: `insert_step(session, ...) -> AgentAnalysis` (único método de escritura; sin `commit`) y `list_by_analysis(session, analysis_id)`. `app/repositories/trade_signals.py`: `insert_signal`, `list_active(session, asset_class, limit) -> list[TradeSignalSchema]` y `to_schema`.
3.6. Tests `db` de los repositorios: orden de `list_by_analysis` por `created_at`; `list_active` solo devuelve `APPROVED`, filtra por `asset_class`, ordena por más reciente y respeta `limit`.
3.7. Commit: `Feat: modelos agent_analyses y ampliacion de trade_signals`.

## 4. Lógica de dominio (`quant/` y `agents/`)

Cada subgrupo es un commit independiente. Las herramientas de agente son envoltorios finos sobre las funciones puras de la Fase 2: no contienen cálculo propio.

### 4A. Propuesta determinista (3.6)

4A.1. Tests de ejemplo en `tests/quant/test_proposal.py` con series/estructuras construidas a mano: `TREND_FOLLOWING` con sesgo alcista y FVG sin mitigar → `LONG` con entrada en el borde de la zona; sin zona → entrada en el último cierre; SL = invalidación ∓ 0,5·ATR redondeado al tick **en contra**; TP = entrada ± 2,0·distancia; `NO_TRADE` o sesgo incompatible → sin propuesta con motivo; los 4 instrumentos del seed (tick y lote reales).
4A.2. Propiedades `hypothesis` (`tests/quant/test_proposal_props.py`): para cualquier propuesta devuelta, el SL queda del lado correcto de la entrada, `rr ≥ PROPOSAL_TARGET_RR` salvo el redondeo a tick documentado, y todos los niveles son múltiplos del tick.
4A.3. `app/quant/proposal.py`: `build_proposal(structure, quant, last_close, atr, instrument, params) -> ProposedSignal | NoTradeReason` (D93), en `Decimal`, sin importar agentes.
4A.4. Commit: `Feat: construccion determinista de la senal propuesta`.

### 4B. Infraestructura de agentes y agente «eco» (3.3)

4B.1. Tests `tests/agents/test_models.py`: `build_model(settings, role)` sin clave → `AgentsNotConfiguredError` con mensaje en español; con clave, devuelve el modelo con el nombre configurado (el auditor usa `AGENT_AUDITOR_MODEL` si existe) sin hacer ninguna llamada; la clave no aparece en el `repr`.
4B.2. `app/agents/models.py` (`build_model`, `AgentsNotConfiguredError`), `app/agents/deps.py` (`AgentDeps`: velas por marco, instrumento, ajustes y estado de cartera, solo datos ya cargados, sin acceso a la BD) y `app/agents/prompts.py` (`PROMPT_VERSION`, esqueleto).
4B.3. Tests `tests/agents/test_echo.py`: un agente «eco» con salida tipada (`EchoReport`) y `TestModel` pasa; con `FunctionModel` que devuelve una salida inválida se reintenta y falla tras el máximo; un agente sin *override* falla en lugar de salir a la red (D84).
4B.4. `app/agents/echo.py` y `app/agents/runner.py`: `run_agent(agent, prompt, deps, limits) -> AgentRun` que devuelve `(output, StepUsage, trace)` con latencia medida, tokens, `cost_usd` (D95) y la traza serializada (D89). Tests del cálculo de coste (con y sin precios) y de `UsageLimits` (un `FunctionModel` que excede el tope lanza el error con el consumo).
4B.5. Commit: `Feat: cliente PydanticAI, runner y agente eco`.

### 4C. `MarketStructureAgent` (3.4)

4C.1. Tests `tests/agents/test_structure_agent.py` con `FunctionModel` guionizado (llama a las herramientas y devuelve el informe): las herramientas devuelven exactamente lo de `analyze_structure` por marco temporal; un informe que cita un nivel o un FVG inexistente es rechazado por el `output_validator` (`ModelRetry`) y, si el modelo lo corrige, pasa; un informe con < 2 marcos o con marcos no pedidos falla; el prompt contiene `PROMPT_VERSION` en la traza.
4C.2. `app/agents/structure.py`: `structure_agent` con `output_type=MarketStructureReport`, herramientas `get_structure(timeframe)` y `get_last_close(timeframe)`, y su `output_validator` (D86). Prompt en español en `prompts.py`.
4C.3. Commit: `Feat: MarketStructureAgent`.

### 4D. `QuantAlphaAgent` (3.5)

4D.1. Tests `tests/agents/test_quant_agent.py` (`FunctionModel`): las herramientas devuelven lo de `log_returns`, `rolling_volatility`, `atr`, `zscore`, `hurst`, `adf` y `classify_regime` (comparación exacta); un informe cuyo `regime` no coincide con el clasificador, o cuyo `stats` difiere, se rechaza; `playbook=MEAN_REVERSION` con régimen `TRENDING` se acepta pero queda anotado en `concerns`/`reasoning` (el informe lo permite; lo veta la propuesta o el auditor); `kelly` se calcula por la herramienta, nunca por el LLM.
4D.2. `app/agents/quant.py`: `quant_agent` con `output_type=QuantAlphaReport`, herramientas `get_features`, `get_regime_stats`, `classify` y `kelly(p, b)` (D86), y su `output_validator`.
4D.3. Commit: `Feat: QuantAlphaAgent`.

### 4E. Veto determinista y `RiskAuditorAgent` (3.7)

4E.1. Tests `tests/agents/test_risk_auditor.py` (`FunctionModel`): el auditor recibe `GuardDecision` y la propuesta; si la decisión determinista **no** estaba aprobada, el agente no se invoca (se comprueba con un modelo que falla si se llama); **un `APPROVE` del modelo no puede aprobar lo vetado** (propiedad de D94); un `VETO` del modelo sobre una propuesta aprobada deja `REJECTED`; `RiskVerdict.deterministic` es el de las guardas y no el que escriba el LLM.
4E.2. `app/agents/risk_auditor.py`: `risk_auditor_agent` con `output_type` reducido (`decision`, `concerns`, `rationale`); el orquestador ensambla el `RiskVerdict` completo. Función pura `final_status(guard, verdict) -> SignalStatus` (único lugar donde se decide aprobar).
4E.3. Test `hypothesis` (`tests/agents/test_final_status_props.py`): para cualquier combinación de `GuardDecision` y `AuditDecision`, `APPROVED` solo si ambas aprueban.
4E.4. Commit: `Feat: veto determinista y RiskAuditorAgent`.

### 4F. Orquestador (3.8)

4F.1. Tests `db` en `tests/services/test_analysis_service.py` con velas sintéticas en la BD de test y `FunctionModel` guionizados para los tres agentes: **camino feliz** (`SIGNAL_APPROVED`): 5 filas en `agent_analyses` (`STRUCTURE`, `QUANT`, `PROPOSAL`, `GUARDS`, `RISK_AUDIT`) con el mismo `analysis_id`, orden correcto, tokens y latencia > 0, y una fila `APPROVED` en `trade_signals` con `analysis_id`; **veto determinista** (R:R forzado a 1,5 o pérdida diaria simulada) → `SIGNAL_REJECTED`, sin fila `RISK_AUDIT` y con `veto_reasons`; **`NO_TRADE`** → sin señal y con motivo; **veto del auditor**; **fallo de un agente** → fila `ERROR` y `analysis_failed`, sin señal; **tope de tokens excedido** → fallo que nombra el tope; marcos sin datos omitidos con aviso (D91) y 422 si quedan < 2; el estado de cartera usa la correlación real de los cierres de la BD.
4F.2. `app/services/portfolio.py` (`load_portfolio_state`, D90) y `app/services/signals.py` (construcción de `TradeSignalSchema`, persistencia).
4F.3. `app/services/analysis.py`: `analyze(session, request, settings) -> AsyncIterator[AnalysisEvent]` — valida instrumento/datos/configuración (errores de dominio `InstrumentNotFoundError`, `InsufficientDataError`, `AgentsNotConfiguredError` antes de emitir nada), ejecuta los pasos (D85), persiste cada uno **antes** de emitir su evento, hace `commit` por paso y cierra con `analysis_completed`. Logging `structlog` con `analysis_id`.
4F.4. Propiedad `hypothesis` (`tests/services/test_signals_props.py`): ninguna `TradeSignalSchema` con `status = APPROVED` supera `RISK_PER_TRADE_PCT`, tiene R:R < `MIN_RR` ni existe con pérdida diaria ≥ límite.
4F.5. Commit: `Feat: orquestador de analisis con persistencia por paso`.

## 5. Servicios y endpoints FastAPI

5.1. Tests de la API (`tests/api/test_agents.py`, `@pytest.mark.db`; el modelo se inyecta con una dependencia sobreescrita, sin red): el *stream* devuelve `Content-Type: text/event-stream`, los eventos llegan en orden (`analysis_started`, pares `step_started`/`step_completed`, `analysis_completed`), cada `data:` es JSON que valida contra `AnalysisEvent`, y el último evento contiene un `AgentReportSchema` válido; 404 con símbolo desconocido; 422 con datos insuficientes (mensaje con cantidades) y con `timeframe` fuera de `timeframes`; **503** sin `ANTHROPIC_API_KEY` y con mensaje en español; un fallo de agente a mitad produce `analysis_failed` (HTTP 200 ya enviado) y la fila `ERROR`; un cliente que corta el *stream* cancela el análisis sin dejar filas a medias.
5.2. Tests de `GET /signals/active` (`tests/api/test_signals.py`): solo `APPROVED`; filtro `asset_class`; `limit` fuera de 1–200 → 422; ordenadas por más recientes; `Decimal` como cadena.
5.3. `app/api/v1/agents.py` (`POST /agents/analyze`, `StreamingResponse`, `tags=["agents"]`, dependencia `get_model_factory` sustituible en tests) y `app/api/v1/signals.py` (`GET /signals/active`); registrar ambos en `router.py`. Publicar `AnalysisEvent` en `components` de OpenAPI y declarar la respuesta `text/event-stream` (D87); registrar el mecanismo elegido como decisión de implementación. Errores de dominio → `HTTPException` con `detail` en español.
5.4. Commit: `Feat: POST /agents/analyze (SSE) y GET /signals/active`.

## 6. Tipos TS generados

6.1. `uv run python scripts/export_openapi.py` → `backend/openapi.json` actualizado (incluye `AnalysisEvent`, `AgentReportSchema`, `TradeSignalSchema`, `AnalyzeRequest`).
6.2. En `frontend/`: `npm run gen:api` → `frontend/types/api.ts`. Ningún tipo escrito a mano. Comprobar que el tipo de los eventos SSE aparece en `components["schemas"]`.
6.3. `npm run typecheck` y `npm run build` pasan; sin diff tras regenerar.
6.4. Commit: `Ud: contrato OpenAPI y tipos TS de la fase 3`.

## 7. CI, documentación y cierre del roadmap

7.1. CI (`.github/workflows/`): comprobar que `uv sync --frozen` instala `pydantic-ai-slim` y que **no** existe `ANTHROPIC_API_KEY` en los secretos del job de backend (los tests no deben necesitarla). Verificar que `openapi.json`/`api.ts` siguen en la comprobación.
7.2. `specs/tech-stack.md`: changelog con la dependencia (`pydantic-ai-slim[anthropic]`; `anthropic` como transitiva), las 12 variables nuevas, `AGENT_MODEL=claude-sonnet-5-5`, el estado de cartera simulado (D90) y que el SSE usa `StreamingResponse` (sin `sse-starlette`).
7.3. `README.md`: sección «Agentes» con el flujo `Structure → Quant → veto → Auditor`, `POST /agents/analyze` con un `curl -N` de ejemplo, `GET /signals/active`, las variables de entorno y los avisos (señales no caducan; propuesta sin calibrar; sin clave = 503).
7.4. Registrar en `requirements.md` las decisiones de implementación (D98 en adelante) y actualizar la tabla de riesgos.
7.5. Smoke manual (véase `validation.md`), PR y CI en verde.
7.6. Marcar **2.1–2.10** y **3.1–3.10** como `[x]` en `specs/roadmap.md` con una nota breve de las decisiones relevantes (incluida la 1.7 ya cerrada). Si el *smoke* real con Claude no se ha hecho (D92), dejarlo anotado como pendiente en la 3.x, no como bloqueo. Commit: `Ud: actualizacion de roadmap.md`.
