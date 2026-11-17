# Requisitos — Fase 4 (parte 2): paper trading, backtest, journal y E2E completo

- **Rama:** `phase-4-backtest-journal-e2e`
- **Roadmap:** pasos **4.6 – 4.10** de [`specs/roadmap.md`](../roadmap.md). Continúa la spec [`2026-11-15-terminal-ui-lectura`](../2026-11-15-terminal-ui-lectura/requirements.md) (decisiones D115–D131); aquí las decisiones siguen en **D132**.
- **Referencias:** [`mission.md`](../mission.md), [`tech-stack.md`](../tech-stack.md).

> **Corrección del roadmap (hallazgo al abrir esta spec).** Los pasos **4.6** (paper trading backend) y **4.7** (blotter) figuraban como `[x]`, pero el código no contiene `POST /signals/{id}/execute`, ni `OrderReceiptSchema`, ni tabla de órdenes, ni UI de blotter (D115 los asignaba a esta segunda spec). Se reabren a `[ ]` en el roadmap y se especifican aquí.

## 1. Contexto

La parte 1 de la Fase 4 dejó el terminal de **lectura**: gráfico, overlays, WebSocket y feed de agentes. Faltan los tres criterios de éxito de la misión que dependen de la ejecución simulada:

- *«El terminal muestra … el blotter de paper trading»* (§5) → 4.6 y 4.7.
- *«Hay un diario (journal) que permite comparar las señales emitidas con su resultado simulado»* (§5) → 4.9. Responde la pregunta central del MVP: *¿producen los agentes señales con valor esperado positivo?*
- El backtester (Fase 2) existe como API pero no tiene UI → 4.8.
- El flujo E2E completo *analizar → ver señal → ejecutar en paper → verla en el blotter* → 4.10.

Además, las guardas de cartera de la Fase 3 trabajan hoy con un estado **simulado** (D90: sin PnL real, sin posiciones). Con el paper trading el estado de cartera pasa a ser **real** (equity, PnL del día, posiciones abiertas) y el circuito de pérdida diaria del 3 % deja de ser decorativo.

Principios de la misión que cumple: **1** (esquemas Pydantic y tipos generados antes de endpoints y UI), **2** (PnL, R-múltiplos, equity, win rate y expectancy se calculan en Python puro; la UI solo muestra), **3 y 4** (el veto y el circuit breaker de −3 % diario se aplican también al ejecutar), **5** (cada orden enlaza a su señal y a su análisis), **6** (el simulador de fills es una función pura y determinista, con tests golden) y **7** (cada grupo del plan termina en un commit verde).

## 2. Alcance

### Dentro del alcance

1. **4.6 Paper trading: backend.** `POST /signals/{id}/execute` (simulado), `OrderReceiptSchema`, tabla `paper_orders`, simulador de fills contra OHLCV y estado de cartera real para las guardas.
2. **4.7 Blotter.** `GET /paper/blotter` y `POST /paper/refresh` en el backend; tabla de órdenes y posiciones con PnL en `/desk` (panel inferior).
3. **4.8 Vista de backtest.** Formulario `BacktestConfig` en `/backtest`, curva de capital (`lightweight-charts`) y métricas. Consume el endpoint ya existente `POST /quant/backtest`; **sin cambios de backend**.
4. **4.9 Journal.** `GET /journal` (consulta derivada de solo lectura, sin tabla propia) y la vista `/journal` con la comparación señal emitida ↔ resultado simulado y su resumen.
5. **4.10 E2E con Playwright.** Flujo completo con red simulada (D124): analizar → señal en el gráfico → ejecutar → blotter; más los flujos de backtest y journal.
6. Cierre: tipos TS regenerados, CI, `tech-stack.md`, README y roadmap.

### Fuera del alcance

- Ejecución real, testnet y HITL (misión §3). Solo paper trading.
- **Slippage, comisiones, financiación (swap) y rechazos de orden.** El simulador no los modela; se documenta y se rotula en la UI («Simulación sin costes ni slippage»).
- Cancelar o modificar una orden, órdenes límite/parciales, cierre manual de una posición, trailing stop. Una orden solo termina por SL o TP.
- Feed de precios en vivo: el PnL no realizado usa el **último cierre ingerido** (mismo criterio que D120).
- Refresco automático en segundo plano: el avance de órdenes ocurre al pulsar «Actualizar» (`POST /paper/refresh`) y al ejecutar (D135).
- Persistir backtests en la UI como historial; guardar o comparar configuraciones. (El backend ya registra cada backtest en `strategies`.)
- Tabla de journal propia o notas manuales del usuario sobre cada trade.
- Dependencias nuevas, en backend y en frontend (D132).

### Esquemas Pydantic (backend)

Todos inmutables (`frozen=True`, `extra="forbid"`). Dinero y precios en `Decimal` (en JSON viajan como cadena).

**`app/schemas/enums.py`** (ampliado):

| Enum | Valores |
| :--- | :--- |
| `OrderStatus` | `PENDING_FILL` (ejecutada, aún sin vela posterior), `OPEN` (rellenada, sin tocar SL/TP), `CLOSED_TP`, `CLOSED_SL` |
| `JournalOutcome` | `NOT_EXECUTED`, `PENDING_FILL`, `OPEN`, `WIN`, `LOSS` |

**`app/schemas/paper.py`** (nuevo):

| Esquema | Campos |
| :--- | :--- |
| `OrderReceiptSchema` | `order_id: UUID`, `signal_id: UUID`, `symbol`, `timeframe`, `direction`, `units: Decimal`, `signal_entry: Decimal`, `stop_loss`, `take_profit`, `risk_amount: Decimal`, `status: OrderStatus`, `executed_at: datetime`, `fill_price: Decimal \| None`, `filled_at: datetime \| None`, `simulated: Literal[True]`, `warnings: list[str]` |
| `PaperOrderSchema` | Todo lo de `OrderReceiptSchema` más `closed_at: datetime \| None`, `exit_price: Decimal \| None`, `realized_pnl: Decimal \| None` (solo cerradas), `mark_price: Decimal \| None` y `unrealized_pnl: Decimal \| None` (solo `OPEN`), `pnl: Decimal \| None` (realizado o no realizado), `r_multiple: Decimal \| None` (`pnl / risk_amount`) |
| `BlotterSchema` | `equity`, `day_start_equity`, `realized_pnl_today`, `realized_pnl_total`, `unrealized_pnl_total`, `open_risk` (suma de `risk_amount` de órdenes `PENDING_FILL`/`OPEN`), `daily_loss_limit_reached: bool`, `orders: list[PaperOrderSchema]`, `warnings: list[str]` |
| `PaperRefreshResult` | `orders_checked: int`, `orders_filled: int`, `orders_closed: int`, `warnings: list[str]` |

Invariantes: `OPEN`/`CLOSED_*` exigen `fill_price` y `filled_at`; `CLOSED_*` exigen `exit_price`, `closed_at` y `realized_pnl`; `PENDING_FILL` no tiene precios de fill ni de salida; `realized_pnl` nunca aparece en una orden no cerrada.

**`app/schemas/journal.py`** (nuevo):

| Esquema | Campos |
| :--- | :--- |
| `JournalEntrySchema` | `signal_id`, `analysis_id`, `created_at`, `symbol`, `timeframe`, `direction`, `signal_status: SignalStatus`, `regime`, `entry`, `stop_loss`, `take_profit`, `rr: Decimal` (R:R **emitido**), `risk_amount: Decimal \| None`, `veto_reasons`, `rationale` (texto del modelo, D128), `outcome: JournalOutcome`, `order_id: UUID \| None`, `fill_price`, `exit_price`, `realized_pnl`, `r_multiple: Decimal \| None` (R **realizado**), `closed_at` |
| `JournalSummarySchema` | `n_signals`, `n_approved`, `n_rejected`, `n_executed`, `n_closed`, `n_wins`, `n_losses`, `win_rate: float \| None`, `total_pnl: Decimal`, `expectancy_r: float \| None` (media de `r_multiple` de las cerradas), `avg_rr_emitted: float \| None`, `avg_r_realized: float \| None`, `warnings: list[str]` |
| `JournalSchema` | `summary: JournalSummarySchema`, `entries: list[JournalEntrySchema]` (más recientes primero) |

`win_rate`, `expectancy_r` y `avg_r_realized` son `null` con 0 operaciones cerradas (no `0`, no `NaN`). Con menos de 30 cerradas, `warnings` incluye «Muestra pequeña: N operaciones cerradas (< 30); las métricas no son concluyentes.» (honestidad estadística).

**Sin esquemas nuevos para el backtest:** se reutilizan `BacktestConfig` y `BacktestMetricsSchema` (Fase 2).

### Tablas

**`paper_orders`** (migración `0010_paper_orders`; **modificable**, a diferencia de `agent_analyses`):

| Columna | Tipo | Notas |
| :--- | :--- | :--- |
| `id` | `UUID` PK | `uuid_generate_v4()` |
| `signal_id` | `UUID` FK → `trade_signals.id`, **UNIQUE** | una señal se ejecuta como máximo una vez (idempotencia, D136) |
| `instrument_id` | `SMALLINT` FK → `instruments.id` | |
| `timeframe`, `direction` | `TEXT` + `CHECK` | enums existentes |
| `units`, `signal_entry`, `stop_loss`, `take_profit`, `risk_amount` | `NUMERIC(24,10)` | copiados de la señal en el momento de ejecutar (inmutables) |
| `status` | `TEXT` + `CHECK` (`OrderStatus`) | `PENDING_FILL` por defecto |
| `executed_at` | `TIMESTAMPTZ` | momento de la ejecución |
| `fill_price`, `exit_price`, `realized_pnl` | `NUMERIC(24,10)` nulos | |
| `filled_at`, `closed_at` | `TIMESTAMPTZ` nulos | apertura de la vela de fill y de salida |
| `last_processed_ts` | `TIMESTAMPTZ` nulo | última vela ya evaluada (hace el refresco incremental e idempotente) |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | |

Índices: `(status)` y `(closed_at)`. `CHECK`: coherencia de estado ↔ columnas (como las invariantes del esquema).

### Endpoints (backend)

| Método y ruta | Cuerpo / parámetros | Respuesta |
| :--- | :--- | :--- |
| `POST /api/v1/signals/{signal_id}/execute` | — | **201** `OrderReceiptSchema`. **404** `Señal desconocida: <id>`. **409** `La señal <id> no está aprobada (estado: REJECTED).` / `La señal <id> ya fue ejecutada.` / veto de cartera al ejecutar (motivos y mensajes de las guardas, D137). **422** UUID inválido. |
| `POST /api/v1/paper/refresh` | — | **200** `PaperRefreshResult`: avanza todas las órdenes `PENDING_FILL`/`OPEN` con las velas ingeridas desde `last_processed_ts` (D135). |
| `GET /api/v1/paper/blotter` | `status: OrderStatus \| None`, `limit` (1–500, 100 por defecto) | **200** `BlotterSchema` (solo lectura, no avanza órdenes). |
| `GET /api/v1/journal` | `symbol: str \| None`, `limit` (1–500, 100 por defecto) | **200** `JournalSchema`. **404** `Instrumento desconocido: XYZ` si `symbol` no existe. |
| `POST /api/v1/quant/backtest` | `BacktestConfig` | Existente (sin cambios). La UI muestra 404/422 tal cual. |

## 3. Decisiones

| # | Decisión | Motivo |
| :--- | :--- | :--- |
| D132 | **Esta spec cubre 4.6 a 4.10** y reabre 4.6/4.7 a `[ ]` en el roadmap (estaban marcados sin código). **Sin dependencias nuevas** (backend ni frontend): `lightweight-charts` ya sirve para la curva de capital. | Elegido por el usuario («Alcance»). Coherencia roadmap ↔ código; regla de dependencias del proyecto. |
| D133 | **Tabla `paper_orders` y journal derivado.** Las órdenes se guardan en `paper_orders` (migración 0010). El journal es una consulta de solo lectura que une `trade_signals` y `paper_orders`; **no** tiene tabla propia. | Elegido por el usuario («Decisiones»). Una sola fuente de verdad: un journal materializado se podría desincronizar de las órdenes. |
| D134 | **Reglas del simulador de fills** (función pura y determinista, `app/paper/simulator.py`, sin BD ni red): (1) *fill* al **open de la primera vela del timeframe de la señal cuya apertura sea ≥ `executed_at`**; (2) a partir de la vela de fill se evalúa vela a vela: LONG sale por SL si `low ≤ SL` y por TP si `high ≥ TP` (SHORT al revés); (3) **si SL y TP caben en la misma vela, gana SL** (conservador); (4) **hueco**: si el `open` de una vela posterior ya supera SL (o TP), la salida es al `open`, no al nivel; (5) en la vela de fill solo se evalúan SL/TP posteriores al open (el open es el fill); (6) PnL = `±(exit − fill) × units`, en `Decimal`; (7) sin slippage, comisiones ni swap, documentado y rotulado en la UI. Si el *fill* deja el riesgo real (`|fill − SL| × units`) por encima de `risk_amount`, se añade un aviso en `warnings` (el tamaño no se recalcula: lo fijó la señal). | Elegido por el usuario («Contexto»). Conservador y reproducible (principio 6); el hueco evita subestimar pérdidas. |
| D135 | **Avance de órdenes explícito, no en segundo plano.** `POST /paper/refresh` evalúa cada orden abierta con las velas ya ingeridas desde `last_processed_ts` (idempotente: dos llamadas seguidas no cambian nada). También se llama internamente al ejecutar (por si ya hay velas posteriores) y antes de calcular el estado de cartera de un análisis. `GET /paper/blotter` **no** modifica datos. La UI tiene el botón «Actualizar» y avisa de la fecha de la última vela ingerida. | Sin tareas en segundo plano ni Redis/Celery (`tech-stack.md` §9); `GET` puro. Los datos solo cambian cuando se ingiere una vela (CLI). |
| D136 | **Ejecutar una señal es idempotente y transaccional.** En una sola transacción: bloquear la fila de la señal, comprobar `APPROVED`, re-evaluar guardas (D137), insertar la orden (`UNIQUE(signal_id)`), pasar la señal a `EXECUTED` y avanzar con las velas disponibles. Una segunda llamada devuelve **409** sin crear otra orden. | Evita doble ejecución por doble clic o reintento; `trade_signals.status = EXECUTED` ya existe en el enum desde la Fase 1. |
| D137 | **Veto de cartera al ejecutar.** Antes de crear la orden se evalúan con el estado de cartera **real** las guardas de cartera (`DAILY_LOSS_LIMIT`, `OPEN_RISK_LIMIT`, `CORRELATED_RISK_LIMIT`) con `evaluate_trade` (Fase 2); **el tamaño de la orden es el `units` de la señal, no se recalcula**. Un veto devuelve 409 con los motivos y mensajes en español; la señal permanece `APPROVED`. Al alcanzarse −3 % de pérdida diaria no se puede ejecutar ninguna señal más ese día (UTC). El mecanismo exacto (cómo reutilizar `evaluate_trade` sin recalcular el tamaño) se fija en la tarea 4.6 y se registra como decisión de implementación. | Principios 3 y 4: el circuit breaker se aplica en el momento de **ejecutar**, no solo al proponer. Varias señales aprobadas a la vez podrían superar el riesgo abierto si solo se miraran al aprobarlas. |
| D138 | **Estado de cartera real.** `load_portfolio_state` deja de ser simulado: `equity = ACCOUNT_EQUITY_USD + Σ realized_pnl` (órdenes cerradas), `day_start_equity` = equity a las 00:00 UTC del día en curso, `realized_pnl_today` = Σ `realized_pnl` de órdenes con `closed_at` de hoy (UTC) y `open_positions` = órdenes `PENDING_FILL`/`OPEN` (con su `risk_amount`). Se elimina `SIMULATED_PORTFOLIO_WARNING` y `list_executed` pasa a leer `paper_orders`. **El PnL no realizado no entra en `equity`** (se muestra aparte). Los tests de la Fase 3 que usaban el aviso se actualizan. | Cierra D90 («simulado hasta el paper trading»). Equity de cierre = decisión conservadora y reproducible; el PnL no realizado depende de un precio provisional. |
| D139 | **Sin cálculo de riesgo ni PnL en la UI** (extiende D125). PnL, R-múltiplo, equity, win rate, expectancy y open risk los calcula el backend en `Decimal`/Python puro; la UI solo formatea. La curva de capital y los precios se convierten a `number` **solo en `lib/chart-data.ts`** (se añade `equityToSeries`); los importes se muestran con el formato de `lib/format.ts`. | Principio 2. |
| D140 | **Blotter como panel de `/desk`.** Panel inferior con pestañas «Señales» (la `SignalList` actual con el botón «Ejecutar (paper)») y «Blotter» (órdenes y posiciones con PnL, resumen de equity, aviso de simulación). No se añade ruta nueva: la navegación sigue siendo `/desk`, `/backtest`, `/agents`, `/journal`. «Ejecutar» pide una confirmación en dos pasos («Confirmar ejecución simulada»). | Roadmap 4.7; `tech-stack.md` §2 fija las cuatro rutas. Evita ejecuciones accidentales. |
| D141 | **Vista de backtest sin estado servidor propio.** `/backtest` tiene el formulario (símbolo y timeframe del store, rango opcional, capital inicial, `zscore_window`, `entry_z`, `exit_z`, `allow_short`) y llama a `POST /quant/backtest` con `useMutation` (TanStack Query). Muestra métricas (`n_bars`, `n_trades`, retorno, Sharpe, max drawdown, win rate, expectancy, equity final), `warnings` y la curva de capital. La validación vive en `BacktestConfig` (la UI solo aplica límites HTML básicos y muestra el `detail` del 422/404 tal cual). Rótulo permanente: «El backtest no modela costes ni slippage» (limitación registrada en el changelog de `tech-stack.md`, Fase 2). | Roadmap 4.8; principio 1 (validación en el esquema) y tono de errores honestos. |
| D142 | **Journal: resultado y R realizado.** `JournalOutcome`: `NOT_EXECUTED` (aprobada sin ejecutar, o rechazada), `PENDING_FILL`, `OPEN`, `WIN` (`CLOSED_TP`) y `LOSS` (`CLOSED_SL`). Se listan señales de **todos los estados** (incluidas `REJECTED`, para ver qué se vetó y por qué). `r_multiple = realized_pnl / risk_amount`. El resumen compara el **R:R emitido** (`avg_rr_emitted`) con el **R realizado** (`avg_r_realized`) y calcula la expectancy en R sobre las cerradas. Solo cuentan las señales con `analysis_id` (posteriores a la Fase 3). | Es la base del criterio de éxito del MVP (misión §5). El R:R emitido es un objetivo; el realizado es el resultado: ver la diferencia es el objetivo del diario. |
| D143 | **Honestidad estadística.** Con < 30 operaciones cerradas, el resumen lleva el aviso de muestra pequeña, y la UI lo muestra junto a las métricas. Sin cerradas, las métricas son `null` y la UI muestra «—» (no 0 %). | Tono de la misión (honesto); evitar conclusiones con muestra insuficiente. |
| D144 | **E2E con red simulada y estado en el *mock*** (continúa D124). Los E2E nuevos usan `page.route` con un **estado en memoria por prueba** (la señal pasa de `APPROVED` a `EXECUTED` al ejecutar; el blotter y el journal reflejan la orden creada). Flujo 4.10: abrir `/agents` → analizar (SSE simulado) → ir a `/desk` → ver la señal y sus overlays → «Ejecutar (paper)» → confirmar → pestaña «Blotter» con la orden → «Actualizar» y ver la orden cerrada con su PnL → `/journal` con la entrada. Además un E2E de `/backtest`. La CI no necesita backend, BD ni clave de LLM. | Elegido por el usuario («Contexto»). Determinista y sin red. Las reglas reales del simulador se prueban en el backend (golden). |
| D145 | **Tests golden del simulador.** Un dataset de velas fijo y versionado (`tests/golden/`, como los golden del backtester de la Fase 2) con órdenes LONG/SHORT y casos de TP, SL, SL y TP en la misma vela, hueco y sin velas posteriores, con PnL exactos esperados en `Decimal`. Propiedades con `hypothesis`: el PnL de una orden cerrada en SL con salida en el nivel es `−risk_amount` (± redondeo) cuando el fill es el entry de la señal; el resultado no depende de cuántas veces se procese (idempotencia). | Principio 6; lógica de dinero. |
| D146 | **Mensajes y códigos de error de `execute`.** 404 señal desconocida; 409 por estado (`REJECTED`, `PENDING`, ya `EXECUTED`) o veto de cartera; `detail` en español y con el dato problemático. El `detail` del veto incluye los motivos (`DAILY_LOSS_LIMIT`, …) y los mensajes de las guardas. | Tono de la misión; la UI muestra el `detail` tal cual (D127). |
| D147 | **Guardas de cartera reutilizadas sin recalcular tamaño (implementación de D137).** Se extrae de `evaluate_trade` la función pura `portfolio_limit_vetoes(symbol, direction, new_risk, state, correlations, settings)` en `app/risk/guards.py` (junto a `daily_loss_limit_reached`), que evalúa `DAILY_LOSS_LIMIT`, `OPEN_RISK_LIMIT` y `CORRELATED_RISK_LIMIT` con un `new_risk` **dado**. `evaluate_trade` la llama con el riesgo del tamaño que acaba de calcular (comportamiento y orden de motivos intactos, tests de la Fase 3 en verde) y `execute_signal` la llama con el `risk_amount` de la señal, sin tocar `position_size`. Se descartó comparar `evaluate_trade` con el `size` de la señal: recalcularía el tamaño con el equity actual y podría vetar por `SIZE_BELOW_LOT` o por un tamaño distinto algo que ya estaba aprobado. | D137 pedía fijar el mecanismo. La extracción evita duplicar las guardas y garantiza que el `units` de la orden es el de la señal (test `test_execute_units_no_se_recalcula_aunque_el_equity_cambie`). |
| D148 | **Detalles de `execute_signal`.** Orden: bloqueo `FOR UPDATE` -> estado -> `refresh_orders` (cartera al día) -> guardas -> orden + señal `EXECUTED` -> avance de **esa** orden con las velas ya ingeridas (sus avisos del simulador van en `warnings` del recibo). El servicio no confirma: ante un error de dominio (404/409) el endpoint no hace `commit` y la sesión se descarta, de modo que el veto deja la señal `APPROVED` y sin orden. `GET /paper/blotter` calcula `mark_price` con el último cierre ingerido; `open_risk`, `unrealized_pnl_total` y `daily_loss_limit_reached` cubren todas las órdenes abiertas aunque `status`/`limit` recorten la lista. `get_journal` ignora filas sin `analysis_id` y lanza `InstrumentNotFoundError` (404) con un símbolo desconocido. | Transaccionalidad (D136) y lectura pura del blotter (D135). |
| D149 | **Precisión de D134.5 en la implementación.** En la vela de fill se evalúan también su `low` y su `high` completos (el `open` es el fill y los extremos de la vela ocurren por definición después de él); si el propio `open` ya está más allá del SL (o del TP), la orden cierra en la vela de fill a ese precio (regla de hueco). `filled_at` y `closed_at` son la **apertura (`ts`) de la vela** donde ocurre el evento, no la hora real: la precisión temporal es la del timeframe. El aviso de riesgo real > `risk_amount` se emite una sola vez, en el avance que produce el fill. | La redacción de D134.5 («solo SL/TP posteriores al open») era ambigua; el código y los golden (`tests/golden/paper_fills.json`) fijan este comportamiento conservador. |
| D150 | **Cliente HTTP y refresco del blotter en la UI.** `lib/api.ts` pasa a una función interna `request` con `apiGet` y `apiPost` (cuerpo JSON opcional); `ApiError.detail` solo toma el `detail` si es una cadena (un 422 de FastAPI trae una lista y se muestra un mensaje genérico). `useBlotter` consulta `GET /paper/blotter` con `refetchInterval` de 15 s (solo lectura: **no** avanza órdenes, D135); `useExecuteSignal` invalida `active-signals` y `blotter`, y `useRefreshOrders` invalida `blotter`. El botón «Actualizar» es la única vía que avanza órdenes. | D135 (GET puro) exige que el avance sea explícito; el sondeo solo refleja cambios ya guardados. |
| D151 | **Formato de importes en `lib/format.ts`.** `formatAmount` (decimales fijos, sin notación científica, redondeo sobre la cadena del backend cuando es un decimal plano) y `formatPercent` (fracción → «x.xx %»); ambos devuelven «—» para nulo o no finito (D143). La única conversión `Decimal → number` sigue siendo `lib/chart-data.ts` (`equityToSeries`, que ordena por tiempo y deduplica marcas repetidas). | Extiende D139; evita que `null` se muestre como 0. |
| D152 | **Tipos y estado de las vistas nuevas.** `/backtest` usa el esquema generado `BacktestConfig-Input` (nombre que publica OpenAPI para la entrada) con `useMutation`; `/journal` usa `useJournal(symbol?, limit=100)`. Ninguna guarda estado en el servidor ni en el store de Zustand. | Principio 1 (tipos generados) y D141. |
| D153 | **Estado del *mock* E2E.** `e2e/support/mock-state.ts` guarda en memoria, por prueba, señales, orden, blotter y journal; `e2e/fixtures/paper-scenario.json` define el escenario (la orden se rellena y cierra por TP al pulsar «Actualizar») y `backtest-metrics.json` / `backtest-422.json` los casos de backtest. Specs: `paper-flow.spec.ts` y `backtest.spec.ts` (nuevos) y `desk.spec.ts` (ampliado). Los resultados del escenario son datos del *mock*, no calculados por el simulador real. | Continúa D144. |

## 4. Variables de entorno nuevas

**Ninguna.** Se reutilizan `ACCOUNT_EQUITY_USD`, `MAX_DAILY_LOSS_PCT`, `MAX_OPEN_RISK_PCT`, `MAX_CORRELATED_RISK_PCT` y las de correlación (Fases 2 y 3). El *tick size* y el *lot size* siguen viniendo del instrumento. Las variables del frontend (`NEXT_PUBLIC_*`) no cambian.

## 5. Contexto, tono y patrones a seguir

- **Next.js 16 no es el que conoces** ([`frontend/AGENTS.md`](../../frontend/AGENTS.md)): antes de cada tarea de UI se lee la guía relevante de `frontend/node_modules/next/dist/docs/01-app/` (`cacheComponents` activo; Server Components por defecto; todo el dato de mercado/paper se obtiene en cliente con TanStack Query, D123).
- **Texto de la UI:** español técnico y denso; rótulos de simulación visibles («Paper trading simulado: sin costes ni slippage», «PnL no realizado = vs. último cierre ingerido (no es tiempo real)»); sin promesas de rentabilidad; el texto del modelo (`rationale`) con la etiqueta «Texto del modelo, no verificado» (D128).
- **Esquemas primero:** `schemas/paper.py` y `schemas/journal.py` (grupo 2) → tests → modelo y repositorios → simulador → servicios → endpoints → `export_openapi.py` + `npm run gen:api` → UI.
- **Patrones existentes del backend:** modelo y checks en [`models/trade_signal.py`](../../backend/app/models/trade_signal.py) y [`models/checks.py`](../../backend/app/models/checks.py); repositorio de referencia [`repositories/trade_signals.py`](../../backend/app/repositories/trade_signals.py) (`list_executed`, `to_schema`); estado de cartera en [`services/portfolio.py`](../../backend/app/services/portfolio.py); guardas en [`risk/guards.py`](../../backend/app/risk/guards.py) (`evaluate_trade`); endpoint de señales [`api/v1/signals.py`](../../backend/app/api/v1/signals.py); endpoint de backtest [`api/v1/quant.py`](../../backend/app/api/v1/quant.py); errores de dominio de [`services/backtest.py`](../../backend/app/services/backtest.py); tests `db` con `@pytest.mark.db` y [`tests/conftest.py`](../../backend/tests/conftest.py); datasets golden en [`tests/golden/`](../../backend/tests/golden); `get_settings()` de [`core/config.py`](../../backend/app/core/config.py).
- **Patrones existentes del frontend:** `lib/api.ts` (`apiGet`, `ApiError`), `lib/format.ts`, `lib/chart-data.ts` (único punto `Decimal → number`), `lib/overlays.ts`, hooks en `hooks/`, store en `store/terminal.ts`, componentes `components/signals/signal-list.tsx` y `components/chart/`, shadcn/ui ya copiados (D131; **no** se añaden más paquetes `@radix-ui` sin aprobación: si hace falta una tabla, se escribe con `<table>` y Tailwind), E2E con `e2e/support/` (REST, SSE y WebSocket simulados) y `playwright.config.ts`.
- **Tipos de API:** solo de [`frontend/types/api.ts`](../../frontend/types/api.ts) generado; cero `any` y ningún tipo de API a mano.
- **Backend sin red:** los tests no llaman a proveedores ni a LLM; el simulador es una función pura.
- **Fuente de verdad:** si esta spec contradice `tech-stack.md`, prevalece `tech-stack.md`; su changelog recogerá la migración 0010, el paso a estado de cartera real y la ausencia de dependencias nuevas.

## 6. Preguntas abiertas y riesgos

| Tema | Estado | Qué hacer |
| :--- | :--- | :--- |
| Roadmap inconsistente (4.6/4.7 `[x]` sin código) | Detectado y corregido en esta spec (4.6–4.10 siguen `[ ]` hasta `/spec-validation`). | Reabrir 4.6/4.7 en el roadmap al crear la spec; cerrar los cinco ítems solo tras `/spec-validation`. Revisar en la PR por qué se marcaron sin código. |
| Reutilizar `evaluate_trade` sin recalcular tamaño (D137) | **Decidida (D147):** se extrajeron las guardas de cartera a `portfolio_limit_vetoes` (puro, en `risk/`). | Hecho: tests en `tests/risk/test_guards.py` y `tests/services/test_paper_service.py` (el `units` de la orden es el de la señal). |
| Cambio de comportamiento de la Fase 3 (D138) | Riesgo medio: al pasar el estado de cartera a real cambian tests y avisos del análisis. | Actualizar `test_portfolio_service.py` y `test_analysis_service.py`; test de regresión de que un análisis sin órdenes se comporta igual que antes (equity = `ACCOUNT_EQUITY_USD`). |
| Fill sin vela posterior (D134/D135) | Aceptado: la orden queda `PENDING_FILL` hasta ingerir una vela nueva. | La UI explica el estado («Esperando la siguiente vela de 1h; ingiere datos con la CLI»). |
| Día en UTC | Aceptado. | El «día» del circuit breaker es UTC; documentado en el `detail` y en el README. |
| Salida por hueco y SL/TP en la misma vela (D134) | Aceptado como supuesto conservador. | Tests golden; rótulo visible de supuestos. |
| Riesgo real > `risk_amount` tras el fill | Aceptado, con aviso. | `warnings` en la orden y en el recibo; test de propiedad. |
| Concurrencia (dos «Ejecutar» simultáneos) | Riesgo bajo. | `UNIQUE(signal_id)` y bloqueo de la fila (D136); test que lanza dos ejecuciones y espera un 201 y un 409. |
| Muestra pequeña en el journal (D143) | Aceptado. | Aviso visible; no hay criterio de aprobación del MVP basado en una muestra de < 30. |
| Backtest costoso (`BACKTEST_MAX_BARS`) | Riesgo bajo: ya lo limita el backend (422). | La UI muestra el 422 y no reintenta solo; el botón se deshabilita mientras corre. |
| Curva de capital con muchos puntos | Riesgo bajo. | Tope del backend (`BACKTEST_MAX_BARS`); el gráfico de línea maneja miles de puntos. |
| E2E con estado en el *mock* (D144, D153) | Riesgo bajo: el *mock* podría divergir del backend (los PnL del escenario son datos fijos, no salida del simulador). | Los fixtures se generan a partir de las respuestas de los esquemas reales (mismos tipos generados); el contrato se verifica con `gen:api` sin diff. |
| Tamaño de la spec (5 ítems) | Aceptado por el usuario. | Grupos independientes del plan, cada uno con commit verde; el backend (grupos 2–5) se puede entregar antes que la UI. |
| Sondeo del blotter cada 15 s (D150) | Riesgo bajo: carga extra de lecturas al backend. | Es un `GET` sin efectos ni escrituras; el avance de órdenes sigue siendo manual (D135). |
| Fill y salida a la resolución del timeframe (D149) | Aceptado: `filled_at`/`closed_at` son la apertura de la vela y el orden intravela se resuelve con SL antes que TP. | Rótulo de supuestos en la UI y en el README; no se infiere nada intravela. |
| Sin costes ni slippage: el PnL simulado puede sobrestimar el resultado real | Aceptado (fuera de alcance). | Rótulo permanente en blotter, backtest y journal; el journal no es evidencia de rentabilidad con < 30 cerradas (D143). |
