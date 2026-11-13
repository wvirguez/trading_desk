# Validación — Fase 2: Motor cuantitativo y núcleo de riesgo

## 1. Automatizado (CI y PR)

- Backend (en `backend/`): `uv run ruff check`, `uv run ruff format --check`, `uv run mypy app`, `uv run pytest` (incluidos `@pytest.mark.db` y `tests/golden`, con la BD de test migrada a `head`: `DATABASE_URL="$TEST_DATABASE_URL" uv run alembic upgrade head`).
- Frontend (en `frontend/`): `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`.
- `npm run gen:api` y `uv run python scripts/export_openapi.py` no dejan diff (`backend/openapi.json` y `frontend/types/api.ts` versionados y al día).
- Ningún test llama a la red ni a un LLM.
- `hypothesis` corre con semilla/derandomización fija en CI (`@settings(derandomize=True)` o perfil `ci`), para no tener fallos intermitentes.

### Afirmaciones concretas que deben existir en los tests

| Afirmación | Dónde |
| :--- | :--- |
| `log_returns`, `rolling_volatility` y `atr` coinciden con valores calculados a mano; el primer log-retorno es `null`. | `tests/quant/test_features.py` |
| Ningún feature ni estructura usa datos futuros: calcular sobre `df[:k]` iguala las primeras `k` filas de calcular sobre `df`. | `tests/quant/test_features.py`, `test_structure.py` |
| Hurst: *random walk* ∈ [0,4; 0,6]; reversión < 0,4; tendencia > 0,6. ADF: p < 0,05 en reversión y p > 0,05 en *random walk*. | `tests/quant/test_regime_stats.py` |
| Hurst/ADF devuelven `nan` con menos de `min_obs` datos o serie constante. | `tests/quant/test_regime_stats.py` |
| Swings, BOS, CHoCH y FVG (alcista/bajista, mitigado y no) coinciden exactamente con los fixtures; un swing se confirma `n` velas después. | `tests/quant/test_structure.py` |
| El clasificador devuelve `TRENDING`, `MEAN_REVERTING` y `HIGH_VOLATILITY_NOISE` en las series sintéticas correspondientes; `n_obs < min_obs` lanza `ValueError`. | `tests/quant/test_regime.py` |
| **El riesgo real de `position_size` nunca supera `equity · risk_pct`**, `units` es múltiplo de `lot_size` y la distancia se redondea al alza al tick (propiedad). | `tests/risk/test_sizing_props.py` |
| `units < lot_size` → 0 unidades (las guardas emiten `SIZE_BELOW_LOT`); entrada igual al stop o valores ≤ 0 → `ValueError`; el sizing usa `|entry − stop|` (no conoce la dirección), y el **stop del lado equivocado lo veta `INVALID_LEVELS`** en las guardas (D76). Hay tests con los 4 instrumentos del seed. | `tests/risk/test_sizing.py`, `tests/risk/test_guards.py` |
| Kelly: `p=0,6, b=1` → 0,2; `p=0,5, b=1` → 0; `0 ≤ fracción ≤ cap`; riesgo de ruina en [0, 1], monótono en `risk_pct` y en `p`; entradas inválidas → `ValueError`. | `tests/risk/test_kelly.py` |
| La correlación de series idénticas es 1,0 y la de opuestas −1,0; usa solo las últimas `window` velas comunes; con < 20 comunes devuelve `nan` y las guardas lo tratan como 1,0. | `tests/risk/test_correlation.py`, `test_guards.py` |
| **R:R 1,79 → veto `RR_BELOW_MIN`; R:R 1,8 → aprobado.** Pérdida diaria de −3 % → `DAILY_LOSS_LIMIT`; −2,99 % → aprobado. | `tests/risk/test_guards.py` |
| Las guardas acumulan varios motivos y los `messages` están en español y nombran el dato. | `tests/risk/test_guards.py` |
| **Ninguna decisión aprobada incumple** riesgo por operación, R:R mínimo ni límite de pérdida diaria (propiedad). | `tests/risk/test_guards_props.py` |
| El backtester aplica la posición con `shift(1)` (sin *look-ahead*); sin señales → capital constante y `n_trades = 0`; `max_drawdown ≤ 0`; `sharpe = 0.0` si `std = 0`. | `tests/quant/test_backtest.py` |
| **Golden:** para cada dataset versionado, las métricas coinciden exactamente con `expected/*.json`, y dos ejecuciones seguidas dan lo mismo y el mismo `config_hash`. | `tests/golden/test_backtest_golden.py` |
| `strategies` existe tras `upgrade head`, `downgrade`/`upgrade` funcionan, el `CHECK` rechaza un timeframe inválido y `JSONB` hace *round-trip*. | `tests/repositories/test_strategies_repo.py` |
| El servicio persiste una fila por backtest y el resultado coincide con el de la función pura. | `tests/services/test_backtest_service.py` |
| `POST /quant/backtest`: 200 con esquema completo; 404 con símbolo desconocido; 422 con `exit_z ≥ entry_z`; 422 con datos insuficientes (mensaje con las cantidades). | `tests/api/test_quant.py` |
| `Settings` rechaza `RISK_PER_TRADE_PCT=0` y `MIN_RR=0.5`. | `tests/test_config.py` |
| `app/quant/` y `app/risk/` no importan `fastapi`, `sqlalchemy` ni `httpx`. | test de arquitectura (`tests/test_architecture.py`, inspección de imports con `ast`) |

## 2. Manual (smoke local)

Requisitos: Postgres local en marcha y datos ingeridos (Fase 1).

1. `uv run alembic upgrade head` → aplica `0006_strategies`. `psql -d <db> -c "\d strategies"` muestra la tabla con `params` y `metrics` en `jsonb`.
2. Con datos (p. ej. `uv run python -m app.cli.ingest backfill --symbol BTC/USDT --tf 1h`), arrancar `uv run uvicorn app.main:app` y abrir `http://localhost:8000/docs`: aparece `POST /api/v1/quant/backtest` con el esquema `BacktestConfig` y sus ejemplos.
3. Backtest con los valores por defecto:
   ```bash
   curl -s -X POST localhost:8000/api/v1/quant/backtest \
     -H 'content-type: application/json' \
     -d '{"symbol":"BTC/USDT","timeframe":"1h"}' | jq '{strategy_id, n_bars, n_trades, sharpe, max_drawdown, win_rate, expectancy, final_equity, warnings}'
   ```
   Esperado: 200, métricas numéricas finitas, `max_drawdown ≤ 0`, `win_rate ∈ [0,1]` y `warnings` con el aviso de que no hay costes ni *slippage*.
4. **Determinismo:** repetir la llamada 2 veces y comparar con `diff <(…) <(…)` (excluyendo `strategy_id`): idénticas. En `psql`, `SELECT config_hash, count(*) FROM strategies GROUP BY 1;` muestra el mismo hash con 2 filas.
5. Símbolo desconocido (`"symbol":"XYZ"`) → 404 `Instrumento desconocido: XYZ`.
6. `"exit_z": 3, "entry_z": 2` → 422 (validación).
7. Rango sin datos suficientes (`"start"` y `"end"` con pocas velas) → 422 con `detail` tipo «Datos insuficientes para BTC/USDT 1h: N velas, se necesitan al menos M.».
8. `"symbol":"EUR/USD","timeframe":"1h"` → el resultado incluye el aviso de datos provisionales de Yahoo.
9. Rendimiento: backtest sobre ~50 000 velas (p. ej. `5m` de BTC/USDT con `since` amplio, si hay datos) termina en pocos segundos; anotar el tiempo en la PR.
10. Funciones puras desde una consola (`uv run python`): `position_size`, `evaluate_trade` con un R:R de 1,5 y `classify_regime` sobre velas leídas de la BD; la salida es coherente con los umbrales.
11. `npm run gen:api` en `frontend/` y `git status`: sin cambios.

### Casos límite

- Serie constante (todas las velas iguales): backtest con `n_trades = 0`, `sharpe = 0.0` y sin excepciones; Hurst/ADF → `nan`.
- Stop a una distancia menor que un tick, o entrada igual al stop → error claro (español), no división por cero.
- Equity muy pequeña que da `units < lot_size` → veto `SIZE_BELOW_LOT`, no una posición de tamaño 0 aprobada.
- Dos posiciones abiertas correlacionadas del mismo sentido que, juntas, superan `MAX_CORRELATED_RISK_PCT` → veto; una del sentido contrario → no.
- Pérdida diaria justo en el límite (−3 %) → veto; el día siguiente (`day_start_equity` nuevo) vuelve a permitir.
- Velas `YAHOO` en `5m`/`15m` con poca historia → 422 de datos insuficientes, no un resultado con 3 operaciones.

## 3. Tono

- `detail` de la API y `messages` de las guardas: **español**, técnicos y con el dato problemático (cifras y límites). Ejemplos: «R:R 1.42 por debajo del mínimo 1.8», «Riesgo por operación 1.20 % supera el máximo 1.00 %», «Datos insuficientes para EUR/USD 15m: 38 velas, se necesitan al menos 52.».
- Nunca se presenta un backtest como predicción de rentabilidad: los `warnings` dicen siempre que no incluye costes y, cuando aplica, que el dato es provisional.
- No se expone ningún secreto en logs ni mensajes.

## 4. Terminado cuando

- Todo lo automatizado está en verde en la PR y en `main`, incluidos los tests `db`, los *golden* y los de propiedades.
- El smoke manual pasa, incluida la repetición determinista (pasos 3–4).
- 2.1–2.10 marcados como `[x]` en `roadmap.md`; `tech-stack.md` (changelog), el README y `requirements.md` (decisiones de implementación D70+) actualizados.
- Los tipos TS están regenerados y sin diff.

**Se rechaza si:** el LLM o cualquier dependencia de agentes interviene en un cálculo de riesgo; una dependencia se añadió sin aprobación; un test llama a la red; las métricas del backtest no son idénticas entre dos ejecuciones; hay `float` en sizing, límites o importes de los esquemas de riesgo; `quant/` o `risk/` importan FastAPI, SQLAlchemy o `httpx`; o `pandas`/`scipy` se usan fuera de `yahoo.py` y de las librerías que los exigen.
