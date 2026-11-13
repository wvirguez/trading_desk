# Plan — Proveedor provisional Yahoo Finance

Regla de cada grupo: **esquema o protocolo → tests → implementación**. Decisiones D28–D35 en [`requirements.md`](requirements.md).

## 1. Dependencias y configuración

1.1. `uv add yfinance`; `override` de mypy para `yfinance.*` (D28).
1.2. Comprobar con una llamada real de prueba (fuera de los tests, anotando el resultado) los límites de historia de `15m` y `1h`, y si `XAUUSD=X` devuelve datos. Ajustar D30 si difieren.
1.3. `Settings`: horizontes de Yahoo y de Binance para `5m` (D30). Actualizar `backend/.env.example`.
1.4. Tests de `test_config.py` con los valores por defecto nuevos.

## 2. Esquema y base de datos

2.1. `Provider.YAHOO` y `Timeframe.M5` (`duration` 5 min, `floor` alineado a :00/:05/…) en `app/schemas/enums.py`. Tests de enums y de `CandleSchema` con `5m` (D36).
2.2. Migración `0005_yahoo_5m`: reemplaza los `CHECK` de `provider` (`instruments`) y de `timeframe` (`ohlcv_bars` y `trade_signals`) para admitir `YAHOO` y `5m`, y actualiza `provider`/`provider_symbol` de los 3 instrumentos (D29). El `downgrade` los devuelve a OANDA.
2.3. Tests `db`: tras `upgrade head`, los 3 instrumentos tienen `YAHOO` y los tickers esperados; `downgrade` y `upgrade` funcionan; Binance no cambia. Actualizar el test del seed existente.

## 3. Adaptador Yahoo

3.1. `app/market_data/yahoo.py`: `YahooAdapter(downloader, now)` con descargador inyectable (D34, D35). Mapeo de timeframe (`5m`, `15m`, `1h`, `1d`); conversión a `Decimal(str(x))`, zona horaria a UTC, solo velas cerradas (`drop_open_candle`), deduplicación y orden ascendente.
3.2. Remuestreo `4h` desde `1h` con bloques parciales avisados (D31, D49), rechazo de NAS100 1h/4h (D48) y normalización diaria (D32).
3.3. Aviso explícito cuando se devuelve menos historia de la pedida (D30).
3.4. `registry.py`: `adapter_for` devuelve `YahooAdapter` para `Provider.YAHOO`.
3.5. Fixtures en `tests/fixtures/` (1h con hueco de fin de semana, 1d, 15m, 5m) y tests sin red: mapeo, `Decimal` exacto, remuestreo 4h con bloques parciales avisados, NAS100 1h/4h no soportado, alineación diaria, error de red y respuesta vacía → `MarketDataError`.

## 4. Ingesta y documentación

4.0. Adaptadores existentes: `ccxt` y `OANDA` aceptan `5m` (`5m` / `M5`); tests con fixtures.
4.1. El servicio usa los horizontes de Yahoo para instrumentos `YAHOO` y dice en la salida de la CLI si recibió menos historia de la pedida.
4.2. Test `db` con un descargador falso: backfill de los 5 timeframes de un instrumento Yahoo.
4.3. README (aviso de proveedor provisional y limitaciones) y `tech-stack.md` (tabla de datos de mercado y changelog con `yfinance`).
4.4. Registrar decisiones de implementación (D36 en adelante) en `requirements.md`.

## 5. Cierre

5.1. `ruff`, `mypy`, `pytest`, y `npm run gen:api` sin diff (no debería cambiar el contrato).
5.2. Smoke manual (véase `validation.md`).
5.3. PR y CI en verde.
