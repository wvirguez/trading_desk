# Plan — Fase 2: Motor cuantitativo y núcleo de riesgo

Regla de cada grupo: **esquema → tests → implementación**, y termina en un commit verde (`ruff`, `mypy`, `pytest`). Decisiones D51–D69 en [`requirements.md`](requirements.md). Los grupos se pueden implementar por separado, en este orden. Los comandos se ejecutan en `backend/` salvo que se indique.

## 1. Dependencias y configuración

1.1. Dependencias **aprobadas** (D54): `uv add polars numpy statsmodels` y `uv add --dev hypothesis`. Override de mypy `ignore_missing_imports` para `statsmodels.*` (y `scipy.*` si hiciera falta).
1.2. Confirmar con `uv run python -c "import polars, numpy, statsmodels"` y que `pandas`/`scipy` no se importan en `app/` salvo en `yahoo.py` (`grep`).
1.3. `Settings` (`app/core/config.py`): las 9 variables de la sección 4 de `requirements.md` con sus rangos validados. Actualizar `backend/.env.example`.
1.4. Tests en `tests/test_config.py`: valores por defecto, y rechazo de `RISK_PER_TRADE_PCT=0`, `RISK_PER_TRADE_PCT=50` y `MIN_RR=0.5`.
1.5. Commit: `Feat: dependencias y configuracion de riesgo (fase 2)`.

## 2. Esquemas Pydantic

2.1. Enums nuevos en `app/schemas/enums.py`: `RegimeLabel`, `StructureEventType`, `SwingKind`, `VetoReason`. Tests en `tests/schemas/test_enums.py`.
2.2. `app/schemas/quant.py`: `SwingPoint`, `StructureEvent`, `FairValueGap`, `MarketStructureResult`, `RegimeStats`, `RegimeThresholds`, `RegimeReport`, `BacktestConfig`, `EquityPoint`, `BacktestMetricsSchema`. Todos `frozen=True`.
2.3. `app/schemas/risk.py`: `PositionSizeResult`, `KellyResult`, `OpenPosition`, `PortfolioState`, `ProposedTrade`, `GuardDecision`.
2.4. Tests (`tests/schemas/test_quant.py`, `test_risk.py`): `BacktestConfig` rechaza `exit_z ≥ entry_z`, `zscore_window` fuera de 10–500, `initial_capital ≤ 0` y `symbol` vacío; los `Decimal` viajan como cadena en JSON; `GuardDecision` con `approved=True` exige `reasons == []`; los esquemas son inmutables.
2.5. `mypy --strict` pasa. Commit: `Feat: esquemas de quant y riesgo`.

## 3. Base de datos: modelo, migración y repositorio

3.1. Modelo `app/models/strategy.py` (`Strategy`) con `CHECK` de `timeframe` (`enum_check`) y `JSONB` para `params` y `metrics`; registrarlo en `app/models/__init__.py`.
3.2. Migración `0006_strategies` (`down_revision = "0005_yahoo_5m"`, usar el id real de la última): crea la tabla, el índice `(instrument_id, created_at DESC)` y un `downgrade` que la elimina.
3.3. Tests `db` (`tests/repositories/test_strategies_repo.py`): `upgrade head` crea `strategies`; `downgrade -1` y `upgrade head` funcionan; el `CHECK` rechaza un timeframe inválido; `JSONB` hace *round-trip*. Actualizar la fixture de `TRUNCATE` (D20) para incluir `strategies`.
3.4. `app/repositories/strategies.py`: `insert_strategy(session, ...) -> Strategy` (sin `commit`, como D21).
3.5. `app/repositories/ohlcv.py`: `fetch_range(session, instrument_id, timeframe, symbol, start, end, limit) -> list[CandleSchema]`, ascendente por `ts`; test `db` con rangos abiertos y cerrados y con el tope.
3.6. Commit: `Feat: modelo strategies y consulta de rango OHLCV`.

## 4. Lógica de dominio (`quant/` y `risk/`)

Cada subgrupo es un commit independiente. En todos: tests primero, funciones puras, `mypy --strict`, sin importar FastAPI ni SQLAlchemy (D66).

### 4A. Datos y features (2.1)

4A.1. `app/quant/data.py`: `candles_to_frame(list[CandleSchema]) -> pl.DataFrame` con columnas `ts` (UTC), `open`, `high`, `low`, `close`, `volume` en `Float64` (único punto `Decimal → float`, D52). Orden ascendente validado; `ValueError` si hay `ts` duplicados.
4A.2. Tests de referencia **calculados a mano** en `tests/quant/test_features.py` (serie de ~10 velas): `log_returns` (primer valor `null`), `rolling_volatility` (`ddof=1`, ventana 3) y `atr` (Wilder, periodo 3, `TR` con cierre previo). Propiedades: ATR ≥ 0; sin look-ahead por truncado (D55).
4A.3. `app/quant/features.py`: `log_returns`, `rolling_volatility(window)`, `atr(period)` como expresiones/funciones de polars. Validan `window ≥ 2`.
4A.4. Commit: `Feat: features basicas (quant)`.

### 4B. Estadísticos de régimen (2.2)

4B.1. Generador de series sintéticas con semilla fija en `tests/quant/synthetic.py`: *random walk*, serie con reversión a la media (Ornstein–Uhlenbeck discreto, φ = 0,9) y serie con tendencia (deriva positiva + ruido).
4B.2. Tests en `tests/quant/test_regime_stats.py` (1000 puntos, semilla fija): `hurst(random_walk) ∈ [0.4, 0.6]`, `hurst(mean_reverting) < 0.4`, `hurst(trending) > 0.6`; `adf_pvalue(mean_reverting) < 0.05` y `adf_pvalue(random_walk) > 0.05`; `zscore` con valores de referencia; `nan` con menos de `min_obs` o serie constante.
4B.3. `app/quant/regime_stats.py`: `zscore(series, window)`, `hurst_exponent(x)` (D53), `adf_pvalue(x)` (envuelve `adfuller`).
4B.4. Commit: `Feat: zscore, hurst y adf`.

### 4C. Estructura de mercado (2.3)

4C.1. Fixtures de velas **pequeñas y dibujadas a mano** en `tests/fixtures/structure/*.json` (cada una con su `expected_*.json`): swings alternos; BOS alcista; CHoCH bajista tras tendencia alcista; FVG alcista y bajista; FVG mitigado y sin mitigar.
4C.2. Tests en `tests/quant/test_structure.py`: resultados exactos contra los fixtures; un swing solo aparece con `confirmed_at = ts + n velas`; el truncado no cambia lo ya confirmado (D55); sin swings si hay menos de `2n + 1` velas.
4C.3. `app/quant/structure.py`: `find_swings(df, n)`, `find_structure_events(df, swings)`, `find_fvgs(df)` y `analyze_structure(df, n=3) -> MarketStructureResult` (D68).
4C.4. Commit: `Feat: estructura de mercado (swings, BOS, CHoCH, FVG)`.

### 4D. Clasificador de régimen (2.4)

4D.1. Tests en `tests/quant/test_regime.py` con las series de 4B: *random walk* → `HIGH_VOLATILITY_NOISE` (inconcluyente), reversión → `MEAN_REVERTING`, tendencia → `TRENDING`, tramo con volatilidad multiplicada por 3 al final → `HIGH_VOLATILITY_NOISE` (D67); `n_obs < min_obs` → `ValueError`; los umbrales del resultado coinciden con los usados.
4D.2. `app/quant/regime.py`: `classify_regime(close: pl.Series, thresholds=RegimeThresholds()) -> RegimeReport`.
4D.3. Commit: `Feat: clasificador de regimen`.

### 4E. Position sizing, Kelly y riesgo de ruina (2.5, 2.6)

4E.1. Tests `example-based` en `tests/risk/test_sizing.py` con los 4 instrumentos del seed (tick y lote reales): p. ej. EUR/USD, equity 10 000, 1 %, entrada 1.08500, stop 1.08300 → 50 000 unidades; BTC/USDT con lote 0.00001; caso `SIZE_BELOW_LOT`; distancia `0` o stop del lado equivocado → `ValueError` en español.
4E.2. Tests `hypothesis` (`tests/risk/test_sizing_props.py`): para cualquier `equity > 0`, `risk_pct ∈ (0, 1]`, entrada y stop válidos, tick y lote: **`risk_amount_real ≤ equity · risk_pct`**; `units` es múltiplo de `lot_size`; `units ≥ 0`; más distancia nunca da más unidades.
4E.3. `app/risk/sizing.py`: `position_size(equity, risk_pct, entry, stop, instrument) -> PositionSizeResult` (D60).
4E.4. Tests de `tests/risk/test_kelly.py`: valores conocidos (`p=0.6, b=1` → `f*=0.2`; `p=0.5, b=1` → 0); `fraction ≤ cap`; propiedades hypothesis (`0 ≤ fraction ≤ cap`; riesgo de ruina en `[0, 1]`, no decreciente al subir `risk_pct`, no creciente al subir `p`); `ValueError` con `p=1.2` o `b ≤ 0`.
4E.5. `app/risk/kelly.py`: `kelly_fraction(p, b, fraction, cap) -> KellyResult` y `risk_of_ruin(p, b, risk_pct) -> float` (D61).
4E.6. Commit: `Feat: position sizing, kelly y riesgo de ruina`.

### 4F. Correlación y guardas de cartera (2.7)

4F.1. Tests de `tests/risk/test_correlation.py`: series idénticas → 1.0; series opuestas → −1.0; independientes (semilla fija) → `|ρ| < 0.2`; usa solo las últimas `window` velas comunes (unión interna por `ts`); menos de 20 comunes → `nan`.
4F.2. `app/risk/correlation.py`: `correlation_matrix(closes: dict[str, pl.DataFrame], window) -> dict[tuple[str, str], float]` (D63).
4F.3. Tests de `tests/risk/test_guards.py`, uno por motivo de veto y uno sin veto: R:R 1.79 → `RR_BELOW_MIN` y R:R 1.8 → aprobado (límite exacto); pérdida diaria exactamente −3 % → `DAILY_LOSS_LIMIT` y −2.99 % → aprobado; riesgo abierto 2.5 % + 1 % → `OPEN_RISK_LIMIT`; posición correlacionada del mismo sentido → `CORRELATED_RISK_LIMIT`, y del sentido contrario o `|ρ|` bajo → no; `ρ = nan` se trata como 1.0 (D63); stop del lado equivocado → `INVALID_LEVELS`; **se acumulan varios motivos**; `messages` en español con el dato incumplido.
4F.4. Test `hypothesis` (`tests/risk/test_guards_props.py`): **ninguna decisión `approved=True` tiene `size.risk_pct > RISK_PER_TRADE_PCT`, ni `R:R < MIN_RR`, ni pérdida diaria ≥ límite** (criterio de éxito de la misión).
4F.5. `app/risk/guards.py`: `risk_reward(trade)` y `evaluate_trade(...) -> GuardDecision` (D62), usando `position_size` de 4E.
4F.6. Commit: `Feat: guardas de cartera y veto determinista`.

### 4G. Backtester vectorizado y golden (2.8, 2.9)

4G.1. Tests en `tests/quant/test_backtest.py` con series pequeñas **calculadas a mano**: sin señales → capital constante, `n_trades = 0`; una operación larga con resultado conocido; la posición se aplica con `shift(1)` (D57), comprobado con un precio que salta justo tras la señal; `allow_short=False` no abre cortos; `max_drawdown ≤ 0`; `sharpe = 0.0` si `std = 0`; `periods_per_year` para `1d` cripto (365) y FX (252) y `1h` FX (252·24).
4G.2. Propiedades `hypothesis`: la curva de capital nunca es negativa para exposición 1× con retornos > −100 %; `win_rate ∈ [0, 1]`; truncar los datos al final no cambia el capital ya calculado (sin look-ahead).
4G.3. `app/quant/backtest.py`: `run_backtest(df, config, periods_per_year) -> BacktestResult` (interno, `float`) y `to_metrics_schema(...)` (redondeo a 10 decimales, D59). Posición con marcas de entrada/salida + `forward_fill` (D57), sin bucle por vela.
4G.4. `backend/scripts/make_golden.py`: genera con semilla fija 3 datasets sintéticos (reversión a la media, tendencia, *random walk*; 1500 velas `1h`) en `tests/golden/data/*.csv`. Se ejecuta **una vez** y los CSV se versionan; el script queda en el repo para documentar su origen.
4G.5. `tests/golden/expected/*.json`: métricas exactas esperadas (tras revisarlas a mano que son razonables, p. ej. que la serie con reversión tenga `total_return > 0` y la tendencia sea peor), y `tests/golden/test_backtest_golden.py`: carga el CSV, ejecuta, compara con **igualdad exacta** de los valores redondeados (D59) y verifica que **dos ejecuciones seguidas dan el mismo resultado** y el mismo `config_hash`. Un cambio en los datos o el algoritmo hace fallar el test con un mensaje que explica cómo regenerar (`make_golden.py --update`, con revisión humana obligatoria).
4G.6. Commit: `Feat: backtester vectorizado y tests golden`.

## 5. Servicio y endpoint FastAPI

5.1. `app/services/backtest.py`: `run_backtest_for_config(session, config, settings) -> BacktestMetricsSchema`: resuelve el instrumento (`InstrumentNotFoundError` → 404), lee velas con `fetch_range` (tope `BACKTEST_MAX_BARS`), valida `n_bars` (D69), ejecuta 4G, añade los `warnings` (sin costes ni *slippage*; proveedor `YAHOO` provisional; `n_trades = 0`), calcula `config_hash` e inserta en `strategies` (D64).
5.2. Tests del servicio (`tests/services/test_backtest_service.py`, `@pytest.mark.db`): con velas sintéticas insertadas en la BD de test, el resultado coincide con el de `run_backtest` directo; se persiste una fila; dos llamadas iguales dan el mismo `config_hash` y las mismas métricas; símbolo desconocido y datos insuficientes lanzan sus errores.
5.3. `app/api/v1/quant.py`: `POST /quant/backtest` con `response_model=BacktestMetricsSchema` y `tags=["quant"]`; registrar el router en `router.py`. Errores de dominio → `HTTPException` con `detail` en español (404 y 422).
5.4. Tests de la API (`tests/api/test_quant.py`, `@pytest.mark.db`): 200 con cuerpo válido y esquema completo; 404 con símbolo desconocido; 422 con `exit_z ≥ entry_z`; 422 con datos insuficientes y mensaje con las cantidades; el `Decimal` de `final_equity` viaja como cadena.
5.5. Commit: `Feat: endpoint POST /quant/backtest`.

## 6. Tipos TS generados

6.1. `uv run python scripts/export_openapi.py` → `backend/openapi.json` actualizado.
6.2. En `frontend/`: `npm run gen:api` → `frontend/types/api.ts`. No se escribe ningún tipo a mano.
6.3. `npm run typecheck` y `npm run build` pasan; no hay diff tras regenerar.
6.4. Commit: `Ud: contrato OpenAPI y tipos TS de la fase 2`.

## 7. CI, documentación y cierre del roadmap

7.1. CI (`.github/workflows/`): sin cambios estructurales; comprobar que los tests `db` y `golden` corren en el job backend y que la comprobación de `openapi.json`/`api.ts` sigue en verde. Si la CI instala dependencias con `uv sync --frozen`, verificar que `uv.lock` incluye las nuevas.
7.2. `specs/tech-stack.md`: changelog con las dependencias añadidas (`polars`, `numpy` explícita, `statsmodels`, `hypothesis` dev) y la nota de que `pandas`/`scipy` llegan como transitivas y no se importan.
7.3. README del backend: sección breve «Motor cuantitativo» (módulos, `POST /quant/backtest`, las variables de entorno nuevas, y el aviso: **backtest sin costes ni *slippage***).
7.4. Registrar en `requirements.md` las decisiones de implementación (D70 en adelante) y actualizar la tabla de riesgos.
7.5. Smoke manual (véase `validation.md`), PR y CI en verde.
7.6. Marcar **2.1–2.10** como `[x]` en `specs/roadmap.md` con una nota breve de las decisiones relevantes. Commit: `Ud: actualizacion de roadmap.md`.
