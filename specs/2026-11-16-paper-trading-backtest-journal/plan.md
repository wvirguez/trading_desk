# Plan — Fase 4 (parte 2): paper trading, backtest, journal y E2E completo

Regla de cada grupo: **esquema → tests → implementación**, y termina en un commit verde (backend: `ruff check`, `ruff format --check`, `mypy app`, `pytest`; frontend: `lint`, `typecheck`, `test`, `build`). Decisiones D132–D146 en [`requirements.md`](requirements.md). Los grupos se pueden implementar por separado, en este orden. Los comandos del backend se ejecutan en `backend/` y los del frontend en `frontend/`. Cada tarea lleva su casilla `[ ]`: se marca `[x]` al implementarla y comprobarla.

**Antes de cualquier tarea de UI (grupo 7)** hay que leer la guía relevante en `frontend/node_modules/next/dist/docs/01-app/`: Next 16 tiene cambios incompatibles y `cacheComponents` está activo.

## 1. Dependencias y configuración

- [x] 1.1. Confirmar que **no hay dependencias nuevas** (D132): `git diff main -- backend/pyproject.toml backend/uv.lock frontend/package.json frontend/package-lock.json` queda vacío al final de la spec. Si una tarea necesita un paquete, se detiene y se pregunta al usuario.
- [x] 1.2. Corregir el roadmap: `4.6` y `4.7` pasan de `[x]` a `[ ]` con la nota «reabiertas (2026-11-16): marcadas sin código».
- [x] 1.3. Commit: `Ud: reabrir 4.6 y 4.7 en el roadmap (sin codigo)`.

## 2. Esquemas Pydantic

- [x] 2.1. `app/schemas/enums.py`: `OrderStatus` (`PENDING_FILL`, `OPEN`, `CLOSED_TP`, `CLOSED_SL`) y `JournalOutcome` (`NOT_EXECUTED`, `PENDING_FILL`, `OPEN`, `WIN`, `LOSS`).
- [x] 2.2. `app/schemas/paper.py`: `OrderReceiptSchema`, `PaperOrderSchema`, `BlotterSchema`, `PaperRefreshResult` (`frozen=True`, `extra="forbid"`; `simulated: Literal[True]`; invariantes de estado ↔ campos).
- [x] 2.3. `app/schemas/journal.py`: `JournalEntrySchema`, `JournalSummarySchema`, `JournalSchema`.
- [x] 2.4. Tests en `tests/schemas/test_paper.py` y `tests/schemas/test_journal.py`: precios y PnL viajan como cadena en JSON; `OPEN`/`CLOSED_*` sin `fill_price` falla; `CLOSED_*` sin `exit_price`/`closed_at`/`realized_pnl` falla; `PENDING_FILL` con `fill_price` falla; `realized_pnl` en una orden no cerrada falla; `simulated` solo admite `True`; `extra="forbid"`; inmutabilidad; ida y vuelta JSON; `win_rate`/`expectancy_r` admiten `None`.
- [x] 2.5. `mypy --strict` pasa. Commit: `Feat: esquemas de paper trading y journal`.

## 3. Base de datos: modelo, migración y repositorios

- [x] 3.1. Tests `db` de la migración (`tests/db/test_paper_orders_migration.py`, patrón de las migraciones anteriores): `alembic upgrade head` crea `paper_orders` con sus `CHECK`, el índice y `UNIQUE(signal_id)`; `downgrade` la elimina; los `CHECK` rechazan un estado inconsistente (p. ej. `CLOSED_SL` sin `exit_price`) y un `status` inválido.
- [x] 3.2. `app/models/paper_order.py` (modelo ORM, `enum_check`) y migración `alembic/versions/0010_paper_orders.py`. Registrar el modelo en `app/models/__init__.py`.
- [x] 3.3. Tests `db` de repositorios (`tests/repositories/test_paper_orders_repo.py`): `insert_order` copia niveles y tamaño de la señal; una segunda inserción para la misma señal lanza el error de unicidad; `list_open_orders` devuelve solo `PENDING_FILL`/`OPEN` con símbolo e instrumento; `list_orders(status, limit)` ordena por `executed_at` descendente; `sum_realized_pnl(session)` y `sum_realized_pnl_between(session, start, end)` usan `Decimal`; `update_order_state` solo cambia las columnas de estado (nunca `signal_entry`, `units`, `stop_loss`, `take_profit`, `risk_amount`).
- [x] 3.4. `app/repositories/paper_orders.py` (inserción, listados, sumas, actualización de estado, conversión a esquema) y, en `app/repositories/trade_signals.py`, `get_signal_for_update(session, signal_id)` (bloqueo `FOR UPDATE`), `mark_executed(session, signal_id)` y `list_for_journal(session, symbol, limit)` (todos los estados con `analysis_id`, con su orden si existe, por `LEFT JOIN`). Reescribir `list_executed` para que lea `paper_orders` (D138).
- [x] 3.5. Tests actualizados de `list_executed` (ahora desde `paper_orders`) y de `list_for_journal` (incluye `REJECTED`, `APPROVED` sin orden y `EXECUTED` con orden; excluye filas sin `analysis_id`; filtra por símbolo).
- [ ] 3.6. Commit: `Feat: modelo paper_orders, migracion 0010 y repositorios`.

## 4. Lógica de dominio

### 4A. Simulador de fills (4.6)

- [x] 4A.1. Dataset golden versionado `tests/golden/paper_fills.json` (velas fijas y órdenes LONG/SHORT) con salidas esperadas exactas en `Decimal` (D145): TP; SL; SL y TP en la misma vela (gana SL); hueco por encima del SL / del TP (salida al `open`); fill con la orden ya fuera de rango en la vela de fill; sin velas posteriores (`PENDING_FILL`); varias velas hasta la salida; vela de fill sin tocar niveles (`OPEN`).
- [x] 4A.2. Tests en `tests/paper/test_simulator.py`: el golden; **idempotencia** (procesar dos veces las mismas velas deja el mismo estado y `last_processed_ts`); procesar en dos tandas da lo mismo que en una; propiedades con `hypothesis` (PnL = `±(exit − fill) × units`; con fill = entry de la señal y salida en SL, `pnl = −risk_amount` salvo redondeo; nunca `float` en el resultado; un LONG nunca sale por TP por debajo del TP); aviso cuando el riesgo real tras el fill supera `risk_amount`; velas anteriores a `executed_at` se ignoran.
- [x] 4A.3. `app/paper/__init__.py` y `app/paper/simulator.py`: función pura `advance_order(order, candles) -> OrderAdvance` (nuevo estado, fill, salida, PnL, `last_processed_ts`, avisos) con las reglas de D134. Sin importar SQLAlchemy ni FastAPI (`tests/test_architecture.py` lo comprobará).
- [x] 4A.4. `mypy --strict` pasa. Commit: `Feat: simulador de fills de paper trading`.

### 4B. Estado de cartera real y resumen del journal (4.6, 4.9)

- [x] 4B.1. Tests `db` de `app/services/portfolio.py` (`tests/services/test_portfolio_service.py`, actualizado): sin órdenes, `equity = ACCOUNT_EQUITY_USD` y `realized_pnl_today = 0`; con una orden cerrada hoy en pérdida, `realized_pnl_today` es negativo y `equity` baja; una orden cerrada **ayer** (UTC) entra en `equity` pero no en `realized_pnl_today`; `day_start_equity = equity − realized_pnl_today`; las órdenes `PENDING_FILL`/`OPEN` aparecen en `open_positions` con su `risk_amount`; el PnL no realizado **no** entra en `equity`; el aviso `SIMULATED_PORTFOLIO_WARNING` ya no existe.
- [x] 4B.2. Implementar el cambio en `app/services/portfolio.py` (D138) y actualizar `tests/services/test_analysis_service.py` (el aviso desaparece; un análisis sin órdenes se comporta igual que antes). Un análisis llama primero a `refresh_orders` (D135).
- [x] 4B.3. Tests puros de `app/paper/journal.py` (`tests/paper/test_journal.py`): `build_journal(rows)` calcula `n_*`, `win_rate`, `total_pnl`, `expectancy_r`, `avg_rr_emitted` y `avg_r_realized` con valores calculados a mano; con 0 cerradas los campos son `None`; con < 30 cerradas hay aviso de muestra pequeña y con ≥ 30 no; `outcome` mapea `CLOSED_TP → WIN`, `CLOSED_SL → LOSS`, rechazadas y sin orden → `NOT_EXECUTED`; el resultado es idéntico con las mismas entradas (determinismo).
- [x] 4B.4. `app/paper/journal.py`: `build_journal` en Python puro (principio 2).
- [ ] 4B.5. Commit: `Feat: estado de cartera real y resumen del journal`.

## 5. Servicios y endpoints FastAPI

- [x] 5.1. Tests de servicio `db` (`tests/services/test_paper_service.py`): `execute_signal` crea la orden con `units`, niveles y `risk_amount` de la señal y pasa la señal a `EXECUTED`; **el `units` de la orden es el de la señal, no recalculado** (D137); señal `REJECTED`/`PENDING` o ya `EXECUTED` → `SignalNotExecutableError` con el estado; señal inexistente → `SignalNotFoundError`; veto de cartera (`DAILY_LOSS_LIMIT` con pérdida del día ≥ 3 %, `OPEN_RISK_LIMIT`, `CORRELATED_RISK_LIMIT`) → `ExecutionVetoedError` con motivos y mensajes, sin crear orden y con la señal aún `APPROVED`; ejecución con velas posteriores ya ingeridas deja la orden `OPEN` o cerrada; dos ejecuciones concurrentes de la misma señal producen una orden y un error; `refresh_orders` es idempotente y devuelve los contadores; `get_blotter` calcula `mark_price` con el último cierre, `unrealized_pnl`, `r_multiple`, `open_risk` y `daily_loss_limit_reached`; `get_journal` coincide con `build_journal`.
- [x] 5.2. Tests de la API (`tests/api/test_paper.py`, `tests/api/test_journal.py`, `@pytest.mark.db`): `POST /signals/{id}/execute` → 201 con `OrderReceiptSchema` y `simulated = true`; 404 `Señal desconocida: <id>`; 409 por estado y por veto (mensajes en español con el dato); 409 en la segunda ejecución; 422 con UUID inválido; `POST /paper/refresh` → 200 con contadores; `GET /paper/blotter` → 200, filtra por `status`, no modifica datos (dos `GET` seguidos idénticos y sin escrituras) y rechaza `limit` fuera de 1–500; `GET /journal` → 200, filtra por `symbol`, 404 con símbolo desconocido; `GET /signals/active` ya no devuelve la señal tras ejecutarla; decimales como cadena.
- [x] 5.3. `app/services/paper.py` (`execute_signal`, `refresh_orders`, `get_blotter`, `get_journal`; errores de dominio) y los routers: `POST /signals/{signal_id}/execute` en `app/api/v1/signals.py`, nuevos `app/api/v1/paper.py` (`/paper/refresh`, `/paper/blotter`) y `app/api/v1/journal.py` (`/journal`), registrados en `router.py`. Errores de dominio → `HTTPException` con `detail` en español (D146). El «día» es UTC.
- [x] 5.4. Registrar como decisión de implementación (D147 en adelante) el mecanismo elegido para reutilizar las guardas sin recalcular el tamaño (D137).
- [ ] 5.5. Commit: `Feat: ejecucion simulada, blotter y journal (API)`.

## 6. Tipos TS generados

- [x] 6.1. `uv run python scripts/export_openapi.py` → `backend/openapi.json` actualizado.
- [x] 6.2. En `frontend/`: `npm run gen:api` → `frontend/types/api.ts`. Comprobar que existen `OrderReceiptSchema`, `PaperOrderSchema`, `BlotterSchema`, `PaperRefreshResult`, `JournalSchema`, `JournalEntrySchema`, `JournalSummarySchema`, `OrderStatus` y las rutas `execute`, `paper/refresh`, `paper/blotter` y `journal`. No se escribe ningún tipo de API a mano.
- [x] 6.3. `npm run typecheck` y `npm run build` pasan; sin diff al regenerar por segunda vez.
- [ ] 6.4. Commit: `Ud: contrato OpenAPI y tipos TS de paper trading y journal`.

## 7. UI de Next.js

Cada subgrupo es un commit independiente. En todos: leer antes la guía de Next relevante; tipos generados → tests → implementación; Server Components por defecto y `"use client"` solo donde haga falta (D123); TypeScript estricto y **sin `any`**; texto solo en español; sin `fetch` de datos en servidor; sin aritmética de riesgo, PnL ni R en la UI (D139).

### 7A. Ejecución y blotter (4.6 UI, 4.7)

- [x] 7A.1. Tests de hooks con `fetch` simulado: `useExecuteSignal` (`POST /api/v1/signals/{id}/execute`; éxito invalida `signals/active` y `paper/blotter`; 404/409/422 devuelven el `detail` exacto del backend como `ApiError`); `useBlotter(status?)` (`GET /api/v1/paper/blotter`); `useRefreshOrders` (`POST /paper/refresh`, invalida el blotter). Añadir `apiPost` a `lib/api.ts` si no existe (con tests: cuerpo, errores 4xx/5xx con `detail`, error de red en español).
- [x] 7A.2. Tests de componentes: `SignalList` muestra el botón «Ejecutar (paper)» solo para señales `APPROVED`; el primer clic cambia a «Confirmar ejecución simulada» y el segundo ejecuta (no ejecuta con un solo clic); mientras corre, el botón se deshabilita (sin doble envío); un 409 muestra el `detail` tal cual (incluido el veto con motivos) y la señal sigue visible; `Blotter` muestra la tabla (símbolo, dirección, unidades, estado, fill, salida, PnL, R, con formato de `tick_size`), el resumen (equity, PnL del día, PnL no realizado, riesgo abierto), el aviso «Paper trading simulado: sin costes ni slippage» y «PnL no realizado = vs. último cierre ingerido (no es tiempo real)», `PENDING_FILL` con su explicación, el aviso de límite diario alcanzado (`daily_loss_limit_reached`), el estado vacío («Sin órdenes simuladas. Ejecuta una señal aprobada.») y «—» para valores nulos; el botón «Actualizar» llama a `POST /paper/refresh`; error 5xx visible con reintento.
- [x] 7A.3. Implementar `hooks/{use-execute-signal,use-blotter,use-refresh-orders}.ts`, `components/blotter/{blotter,orders-table,account-summary}.tsx`, el botón en `components/signals/signal-list.tsx`, y el panel inferior de `/desk` con pestañas «Señales» y «Blotter» (D140; componente `tabs` ya copiado). Tabla con `<table>` y Tailwind (sin paquetes nuevos).
- [ ] 7A.4. `lint`, `typecheck`, `test`, `build` en verde. Commit: `Feat: ejecucion en paper y blotter en el terminal`.

### 7B. Vista de backtest (4.8)

- [x] 7B.1. Tests de lógica pura `lib/chart-data.ts` (`equityToSeries`: convierte `EquityPoint[]` a segundos UTC y `number`, ordena, descarta duplicados) y de `lib/format.ts` (formato de porcentaje y de importe sin notación científica, `—` para nulos).
- [x] 7B.2. Tests de `hooks/use-backtest.ts` (`useMutation` con `fetch` simulado: `POST /api/v1/quant/backtest` con el cuerpo `BacktestConfig`; éxito entrega `BacktestMetricsSchema`; 404 y 422 devuelven el `detail` exacto) y de componentes: `BacktestForm` (símbolo y timeframe desde el store, valores por defecto de `BacktestConfig`, «Ejecutar backtest» deshabilitado mientras corre, no hace validación de negocio propia), `BacktestMetrics` (todas las métricas con formato; `warnings` visibles; «El backtest no modela costes ni slippage»), `EquityChart` (con `lightweight-charts` simulado: crea una serie de línea con los puntos y se limpia al desmontar) y la página `/backtest` (ya no muestra «Pendiente: paso 4.8»); un 422 se muestra y el formulario sigue usable.
- [x] 7B.3. Implementar `lib/chart-data.ts` (`equityToSeries`), `hooks/use-backtest.ts`, `components/backtest/{backtest-form,backtest-metrics,equity-chart}.tsx` (`"use client"`; gráfico con `next/dynamic` `ssr: false` dentro de un componente cliente, como `CandleChart`) y `app/backtest/page.tsx`. Actualizar el test del sidebar/páginas marcadoras (solo queda `/journal` hasta 7C).
- [ ] 7B.4. Verificación manual con datos ingeridos (véase `validation.md`). Commit: `Feat: vista de backtest con curva de capital y metricas`.

### 7C. Journal (4.9)

- [x] 7C.1. Tests de `hooks/use-journal.ts` (`GET /api/v1/journal?symbol=&limit=`; 404 con `detail`) y de componentes: `JournalSummary` (métricas con `—` si son `null`, comparación «R:R emitido» vs «R realizado», aviso de muestra pequeña, aviso de que el diario es una ayuda de análisis y no una promesa de rentabilidad), `JournalTable` (una fila por señal con estado de la señal y `outcome`, niveles con `tick_size`, R:R emitido y R realizado, motivos de veto de las rechazadas, `rationale` con la etiqueta «Texto del modelo, no verificado» en una fila desplegable), filtro por símbolo (store o selector propio), estado vacío («Sin señales registradas. Lanza un análisis en /agents.») y `/journal` (ya no muestra «Pendiente»).
- [x] 7C.2. Implementar `hooks/use-journal.ts`, `components/journal/{journal-summary,journal-table}.tsx` y `app/journal/page.tsx`. Eliminar la última página marcadora y actualizar sus tests.
- [ ] 7C.3. Verificación manual (véase `validation.md`). Commit: `Feat: journal de senales y resultado simulado`.

### 7D. E2E con Playwright (4.10)

- [x] 7D.1. Ampliar `e2e/support/` con un **estado en memoria por prueba** (D144): `POST /signals/{id}/execute` cambia la señal a `EXECUTED` y crea una orden; `GET /paper/blotter` y `GET /journal` reflejan ese estado; `POST /paper/refresh` cierra la orden (por TP) en una segunda fase de la prueba; `POST /quant/backtest` devuelve un fixture con curva de capital. Los fixtures JSON se versionan junto a los demás.
- [x] 7D.2. `e2e/paper-flow.spec.ts` (flujo completo de 4.10): `/agents` → «Analizar» con SSE simulado → `SIGNAL_APPROVED` → `/desk` → la señal y sus overlays (entrada, SL, TP) están en el gráfico → «Ejecutar (paper)» → «Confirmar ejecución simulada» → pestaña «Blotter» con la orden `PENDING_FILL`/`OPEN` → «Actualizar» → la orden aparece cerrada con su PnL → la señal ya no está en «Señales» activas → `/journal` muestra la entrada con resultado `WIN` y su R realizado. Casos: ejecutar dos veces (409 visible, sin duplicados) y veto por pérdida diaria (409 con el motivo visible y la señal sigue aprobada).
- [x] 7D.3. `e2e/backtest.spec.ts`: `/backtest` → ejecutar con los valores por defecto → métricas y curva de capital visibles; un 422 simulado muestra su mensaje y deja el formulario usable. Actualizar `e2e/desk.spec.ts`/`agents.spec.ts` (las páginas ya no son marcadoras).
- [x] 7D.4. `npm run test:e2e` en verde en local (Chromium). Commit: `Feat: E2E del flujo completo con paper trading, backtest y journal`.

## 8. CI, documentación y cierre del roadmap

- [ ] 8.1. CI (`.github/workflows/ci.yml`): confirmar que el job de backend aplica la migración 0010 a la BD de test y ejecuta los tests `db`; que `export_openapi.py` y `gen:api` siguen comprobando el contrato sin diff; que el job `e2e` ejecuta los nuevos flujos; y que no hay claves de LLM en el entorno.
- [ ] 8.2. `specs/tech-stack.md`: changelog «2026-11-16 (Fase 4.2)»: migración `0010_paper_orders`; estado de cartera **real** desde órdenes simuladas (cierra D90); simulador de fills con sus supuestos (D134: fill al open de la siguiente vela, SL antes que TP, hueco, sin costes ni slippage); circuit breaker de −3 % diario aplicado al ejecutar (D137); **sin dependencias nuevas**; sin variables de entorno nuevas. Actualizar las secciones que cambien (p. ej. §7: `paper_orders` modificable frente a `agent_analyses` de solo inserción).
- [ ] 8.3. `README.md`: secciones «Paper trading», «Backtest» y «Journal» (cómo ejecutar una señal, qué significa cada estado, supuestos del simulador, el día UTC, qué es provisional, cómo ejecutar `npm run test:e2e`).
- [ ] 8.4. Registrar en `requirements.md` las decisiones de implementación (D147 en adelante) y actualizar la tabla de riesgos. Corregir en el roadmap las notas de 4.10 de la parte 1.
- [ ] 8.5. Smoke manual (véase `validation.md`), PR y CI en verde. En la PR, indicar cómo se marcaron 4.6/4.7 sin código.
- [ ] 8.6. Marcar **4.6–4.10** como `[x]` en `specs/roadmap.md`. Esta tarea la hace el usuario o el flujo principal tras validar con `/spec-validation`. Commit: `Ud: actualizacion de roadmap.md`.
