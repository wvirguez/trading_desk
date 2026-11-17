# Validación — Fase 4 (parte 2): paper trading, backtest, journal y E2E completo

## 1. Automatizado (CI y PR)

- Backend (en `backend/`): `uv run ruff check`, `uv run ruff format --check`, `uv run mypy app`, `uv run pytest` (incluidos `@pytest.mark.db`, golden y propiedades, con la BD de test migrada a `head`, **ahora con la migración 0010**: `DATABASE_URL="$TEST_DATABASE_URL" uv run alembic upgrade head`).
- Frontend (en `frontend/`): `npm run lint`, `npm run typecheck`, `npm test` y `npm run build`.
- E2E (en `frontend/`): `npm run test:e2e` (Playwright, Chromium, red simulada, D124/D144).
- `uv run python scripts/export_openapi.py` y `npm run gen:api` no dejan diff (`backend/openapi.json` y `frontend/types/api.ts` al día).
- **Sin dependencias nuevas:** `git diff main -- backend/pyproject.toml backend/uv.lock frontend/package.json frontend/package-lock.json` vacío (D132).
- **Ningún test llama a la red, a un proveedor de mercado ni a un LLM real**, y la CI no define `ANTHROPIC_API_KEY` ni `GEMINI_API_KEY`.
- TypeScript estricto: **cero `any`** en `frontend/` fuera de `types/api.ts` generado (`grep` y ESLint).
- `app/paper/` no importa SQLAlchemy ni FastAPI (`tests/test_architecture.py`).

### Afirmaciones concretas que deben existir en los tests

| Afirmación | Dónde |
| :--- | :--- |
| Los esquemas de paper trading rechazan estados incoherentes (`OPEN` sin `fill_price`, `CLOSED_*` sin salida o PnL, `PENDING_FILL` con fill, `realized_pnl` en una orden no cerrada); `simulated` solo es `True`; precios y PnL viajan como cadena; `extra="forbid"`. | `backend/tests/schemas/test_paper.py` |
| `JournalSummarySchema` admite `None` en `win_rate`, `expectancy_r` y `avg_r_realized`. | `backend/tests/schemas/test_journal.py` |
| La migración 0010 crea `paper_orders` con `UNIQUE(signal_id)` y los `CHECK`; `downgrade` la elimina; un estado inconsistente se rechaza en BD. | `backend/tests/db/test_paper_orders_migration.py` |
| El repositorio copia niveles y tamaño de la señal, impide dos órdenes por señal, nunca modifica los campos inmutables y `list_for_journal` incluye `REJECTED` y excluye filas sin `analysis_id`. | `backend/tests/repositories/test_paper_orders_repo.py`, `test_trade_signals_repo.py` |
| **Golden del simulador:** TP; SL; SL y TP en la misma vela → SL; hueco → salida al `open`; sin velas posteriores → `PENDING_FILL`; PnL exacto en `Decimal`. | `backend/tests/paper/test_simulator.py` + `tests/golden/paper_fills.json` |
| El simulador es idempotente y procesar en dos tandas equivale a una sola; ignora velas anteriores a `executed_at`. | `backend/tests/paper/test_simulator.py` |
| Propiedad (`hypothesis`): con fill = entry de la señal y salida en SL, `pnl = −risk_amount` (± redondeo); el PnL es `±(exit − fill) × units` y nunca `float`. | `backend/tests/paper/test_simulator.py` |
| Aviso en la orden cuando el riesgo real tras el fill supera `risk_amount`. | `backend/tests/paper/test_simulator.py` |
| `build_journal` calcula `win_rate`, `expectancy_r`, `avg_rr_emitted`, `avg_r_realized` y `total_pnl` con valores calculados a mano; `None` con 0 cerradas; aviso de muestra pequeña con < 30 cerradas; es determinista. | `backend/tests/paper/test_journal.py` |
| El estado de cartera es real: sin órdenes `equity = ACCOUNT_EQUITY_USD`; una pérdida de hoy reduce `equity` y fija `realized_pnl_today`; una cerrada ayer (UTC) no cuenta en el día; el PnL no realizado no entra en `equity`; las órdenes abiertas son `open_positions`; el aviso de simulación ya no existe. | `backend/tests/services/test_portfolio_service.py`, `test_analysis_service.py` |
| `execute_signal`: crea la orden con **el `units` de la señal** (no recalculado), pasa la señal a `EXECUTED`; `REJECTED`/`PENDING`/ya ejecutada → error con estado; veto por `DAILY_LOSS_LIMIT` (≥ 3 % de pérdida hoy), `OPEN_RISK_LIMIT` y `CORRELATED_RISK_LIMIT` sin crear orden y con la señal aún `APPROVED`; dos ejecuciones concurrentes → una orden y un error. | `backend/tests/services/test_paper_service.py` |
| `refresh_orders` es idempotente y devuelve contadores; `get_blotter` calcula `mark_price`, `unrealized_pnl`, `r_multiple`, `open_risk` y `daily_loss_limit_reached`; `get_journal` coincide con `build_journal`. | `backend/tests/services/test_paper_service.py` |
| API: `POST /signals/{id}/execute` → 201 / 404 / 409 (estado, doble ejecución y veto) / 422; `POST /paper/refresh` → 200; `GET /paper/blotter` filtra por `status`, valida `limit` y **no escribe**; `GET /journal` filtra por `symbol` y da 404 si no existe; `GET /signals/active` no devuelve la señal ejecutada; mensajes en español con el dato. | `backend/tests/api/test_paper.py`, `test_journal.py` |
| `openapi.json` contiene `OrderReceiptSchema`, `PaperOrderSchema`, `BlotterSchema`, `PaperRefreshResult` y `JournalSchema`. | `backend/tests/api/test_paper.py` |
| `apiPost` envía el cuerpo, convierte 4xx/5xx en `ApiError` con el `detail` y los fallos de red en un mensaje en español. | `frontend/lib/api.test.ts` |
| `equityToSeries` ordena, deduplica y usa segundos UTC; **la conversión `Decimal → number` sigue ocurriendo solo en `lib/chart-data.ts`**. | `frontend/lib/chart-data.test.ts` |
| «Ejecutar (paper)» solo en señales `APPROVED`; exige confirmación en dos pasos; se deshabilita al enviar (sin doble envío); un 409 muestra el `detail` tal cual y la señal sigue visible. | `frontend/components/signals/signal-list.test.tsx` |
| El blotter muestra la tabla, el resumen, los avisos de simulación y de dato provisional, `PENDING_FILL` explicado, el aviso de límite diario, el estado vacío y «—» para nulos; «Actualizar» llama a `POST /paper/refresh`. | `frontend/components/blotter/*.test.tsx` |
| `useBacktest` hace `POST /quant/backtest` con `BacktestConfig` y muestra el `detail` de 404/422; el formulario se deshabilita mientras corre; las métricas y `warnings` se muestran; el aviso «no modela costes ni slippage» está presente. | `frontend/hooks/use-backtest.test.tsx`, `frontend/components/backtest/*.test.tsx` |
| `EquityChart` crea la serie con los puntos y se limpia al desmontar (con `lightweight-charts` simulado). | `frontend/components/backtest/equity-chart.test.tsx` |
| El journal muestra el resumen (`—` si `null`), la comparación R:R emitido vs. R realizado, el aviso de muestra pequeña, las filas con `outcome`, los motivos de veto y el `rationale` con la etiqueta «Texto del modelo, no verificado». | `frontend/components/journal/*.test.tsx` |
| Ninguna página es ya marcadora: `/backtest` y `/journal` no contienen «Pendiente». | `frontend/app/*/page.test.tsx`, `frontend/components/shell/sidebar.test.tsx` |
| **E2E 4.10:** analizar → señal con overlays → ejecutar (confirmación en dos pasos) → blotter → «Actualizar» y orden cerrada con PnL → señal fuera de activas → entrada en el journal; doble ejecución (409) y veto diario (409) visibles sin duplicar. | `frontend/e2e/paper-flow.spec.ts` |
| E2E del backtest: métricas y curva visibles; un 422 simulado se muestra y el formulario sigue usable. | `frontend/e2e/backtest.spec.ts` |

## 2. Manual (smoke local)

Requisitos: Postgres local en marcha, `DATABASE_URL` apuntando a la BD de desarrollo, datos ingeridos (Fase 1) para `BTC/USDT` en `1h` y `1d` (≥ 500 velas de `1h`), backend (`uv run uvicorn app.main:app --reload` en `backend/`) y `frontend/.env.local` con las dos URL. Para tener una señal `APPROVED`: un análisis real (opcional, con clave de LLM, D92) o una fila sembrada a mano en `trade_signals` con `analysis_id`, `rr`, `units`, `risk_amount` y `regime`.

1. Migración: `uv run alembic upgrade head` → termina en `0010_paper_orders`; `psql -c '\d paper_orders'` muestra `UNIQUE(signal_id)` y los `CHECK`. `uv run alembic downgrade -1` y `upgrade head` funcionan.
2. Ejecutar una señal: `curl -s -X POST localhost:8000/api/v1/signals/<id>/execute | jq '{status, simulated, units, signal_entry}'` → **201**, `"simulated": true`, `status` `PENDING_FILL` u `OPEN`, `units` igual al de la señal.
3. Doble ejecución: repetir el comando → **409** «La señal <id> ya fue ejecutada.». `curl -s -X POST localhost:8000/api/v1/signals/<uuid-inexistente>/execute` → **404** «Señal desconocida: …». Con un id que no es UUID → **422**.
4. Señal rechazada: ejecutar una `REJECTED` → **409** «La señal … no está aprobada (estado: REJECTED).».
5. Blotter: `curl -s localhost:8000/api/v1/paper/blotter | jq '{equity, open_risk, orders: (.orders|length), daily_loss_limit_reached}'` → conteos coherentes; dos `GET` seguidos dan lo mismo (no avanzan órdenes).
6. Avance: ingerir una vela nueva (`uv run python -m app.cli.ingest ...`) y `curl -s -X POST localhost:8000/api/v1/paper/refresh | jq` → `orders_checked ≥ 1`; una segunda llamada seguida devuelve `orders_filled: 0` y `orders_closed: 0` (idempotente). El `fill_price` de la orden es el `open` de la primera vela posterior a la ejecución (comprobar con `GET /market/ohlcv`).
7. Circuit breaker: sembrar en `paper_orders` una orden cerrada hoy (UTC) con `realized_pnl` ≤ −3 % de `ACCOUNT_EQUITY_USD` y ejecutar otra señal → **409** con motivo `DAILY_LOSS_LIMIT` y mensaje en español; `GET /paper/blotter` muestra `daily_loss_limit_reached: true`. Limpiar la fila sembrada después.
8. Journal: `curl -s "localhost:8000/api/v1/journal?symbol=BTC/USDT" | jq '.summary'` → conteos coherentes; con 0 cerradas, `win_rate`, `expectancy_r` y `avg_r_realized` son `null`; `?symbol=XYZ` → 404.
9. UI `/desk`: la señal `APPROVED` aparece en la pestaña «Señales» con «Ejecutar (paper)»; un solo clic **no** ejecuta (pide «Confirmar ejecución simulada»); al confirmar, la señal desaparece de las activas y la pestaña «Blotter» muestra la orden con el aviso «Paper trading simulado: sin costes ni slippage». «Actualizar» tras ingerir una vela cambia el estado.
10. UI `/backtest`: con `BTC/USDT 1h` y los valores por defecto, «Ejecutar backtest» muestra métricas, `warnings` y la curva de capital; el aviso «El backtest no modela costes ni slippage» es visible. Un rango sin datos muestra el 422 del backend tal cual y el formulario sigue usable. El mismo backtest dos veces da **exactamente** las mismas métricas (principio 6).
11. UI `/journal`: la señal ejecutada aparece con su resultado y R realizado; las rechazadas muestran sus motivos de veto; el resumen muestra el aviso de muestra pequeña (< 30 cerradas) y «—» donde no hay datos.
12. `npx playwright install chromium` y `npm run test:e2e` pasan en local.
13. `npm run gen:api` en `frontend/` y `git status`: sin cambios.
14. **Opcional, con clave real (D92):** `/agents` → «Analizar» → señal aprobada → ejecutar → blotter → journal, de extremo a extremo. Anotar cualquier problema en la PR.

### Casos límite

- **Sin velas posteriores:** la orden queda `PENDING_FILL` con la explicación «PENDING_FILL: orden ejecutada que aún espera una vela posterior para rellenarse.»; no se rellena con una vela anterior.
- **SL y TP en la misma vela:** gana SL (`CLOSED_SL`); documentado en la UI.
- **Hueco** que supera el SL o el TP al `open`: la salida es al `open`, no al nivel; el PnL lo refleja.
- **Fill que empeora el riesgo:** si `|fill − SL| × units` > `risk_amount`, la orden lleva el aviso; el tamaño no se recalcula.
- **Doble clic / reintento** en «Ejecutar»: una sola orden (409 en la segunda).
- **Dos pestañas ejecutando la misma señal a la vez:** una orden y un 409.
- **Cambio de día (UTC) con órdenes cerradas:** el PnL del día se reinicia a las 00:00 UTC; el equity conserva lo realizado.
- **Orden de otro instrumento sin velas:** `mark_price` y `unrealized_pnl` son `null` y la UI muestra «—», sin romperse.
- **Instrumento con precios de muchos decimales (EUR/USD) y de pocos (BTC/USDT):** formato según `tick_size`, nunca notación científica.
- **Backtest con `BACKTEST_MAX_BARS` superado o datos insuficientes:** 422 visible, sin reintento automático.
- **Cero señales / cero órdenes:** estados vacíos en español, sin `NaN` ni pantalla en blanco.
- **Error 5xx o red caída** en cualquier consulta o mutación: mensaje visible con reintento manual; la UI no queda en blanco ni en «cargando» para siempre.
- **Ancho de ventana estrecho:** la tabla del blotter y la del journal desplazan dentro de su contenedor; la página no desplaza en horizontal.

## 3. Tono

- Todo el texto visible está en **español**, técnico y denso; sin lenguaje promocional ni promesas de rentabilidad. Ejemplos: «Paper trading simulado: sin costes ni slippage», «PnL no realizado = vs. último cierre ingerido (no es tiempo real)», «Confirmar ejecución simulada», «Sin órdenes simuladas. Ejecuta una señal aprobada.», «Muestra pequeña: 7 operaciones cerradas (< 30); las métricas no son concluyentes.», «El backtest no modela costes ni slippage».
- Los errores nombran el dato problemático y se muestran tal cual (`detail`): «Señal desconocida: <id>», «La señal <id> ya fue ejecutada.», «La señal <id> no está aprobada (estado: REJECTED).», y el veto con sus motivos y mensajes de las guardas. No se suavizan ni se ocultan.
- Un dato provisional (último cierre ingerido, proveedor Yahoo) y todo supuesto del simulador se rotulan en la propia UI.
- La UI nunca presenta un PnL, un R o una métrica que no haya calculado el backend; el texto del modelo lleva «Texto del modelo, no verificado».
- No se expone ningún secreto en logs, mensajes ni variables `NEXT_PUBLIC_*`.

## 4. Terminado cuando

- Todo lo automatizado está en verde en la PR y en `main`, incluidos los tests `db` con la migración 0010, los golden del simulador, los E2E y el contrato sin diff.
- El smoke manual (pasos 1–13) pasa. El paso 14 con clave real se ejecuta cuando haya clave; si no, queda anotado como pendiente en la PR y no bloquea el cierre (D92).
- **4.6–4.10** marcados `[x]` en `specs/roadmap.md` (tras `/spec-validation`); `tech-stack.md` (changelog «2026-11-16 (Fase 4.2)»), el README y `requirements.md` (decisiones D147+) actualizados.
- Los tipos TS de paper trading y journal están regenerados y sin diff; no hay dependencias nuevas.
- El criterio de éxito de la misión «Hay un diario (journal) que permite comparar las señales emitidas con su resultado simulado» es verificable en la UI y con tests.

**Se rechaza si:** la UI calcula PnL, R, equity, riesgo, win rate o expectancy en lugar de mostrar lo del backend; un LLM interviene en el fill, el PnL o el tamaño; el `units` de la orden se recalcula en vez de usar el de la señal; se puede ejecutar una señal no `APPROVED`, dos veces, o con el límite diario del 3 % alcanzado; el simulador no es determinista o idempotente, o gana TP cuando SL y TP caben en la misma vela; los importes pasan por `float` en el backend o a `number` fuera de `lib/chart-data.ts`; hay un tipo de API escrito a mano o `any` fuera de `types/api.ts`; se añadió una dependencia; un test llama a la red, a un proveedor o a un LLM, o la CI necesita una clave; un `GET` modifica datos; un error se oculta o la UI queda en blanco; una página sigue siendo marcadora; los supuestos del simulador (sin costes ni slippage, día UTC, precio provisional) no se rotulan; hay texto de interfaz fuera del español; o 4.6/4.7 se vuelven a marcar `[x]` sin código y sin tests que lo respalden.
