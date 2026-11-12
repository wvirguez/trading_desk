# Validación — Bloque 0: Cimientos del repositorio

La rama `feature/bloque-0-cimientos` puede integrarse en `main` **solo si se cumplen todos** los puntos siguientes. Cada punto indica cómo verificarlo.

## 1. CI en verde en la PR

- [ ] El job `backend` pasa: `uv sync --frozen`, `alembic upgrade head`, `ruff check`, `ruff format --check`, `mypy app` (strict) y `pytest`, **incluidos** los tests marcados `db`.
- [ ] El job `frontend` pasa: `npm ci`, `npm run lint`, `npm run typecheck`, `npm test` y `npm run build`.
- [ ] La CI se ejecuta en la PR. No vale con ejecutarla solo en local.

## 2. Smoke test local manual

Se ejecuta en la máquina de desarrollo, partiendo de una base de datos recién creada.

| # | Paso | Resultado esperado |
| :--- | :--- | :--- |
| S1 | `pg_lsclusters` | `16/main` *online* en el puerto 5432 (el 14 queda en el 5433, apagado). |
| S2 | `sudo -u postgres bash < backend/scripts/setup_db.sh` (dos veces seguidas) | Termina sin errores las dos veces (idempotente). |
| S3 | `cd backend && uv sync && uv run alembic upgrade head` | Se aplica `0001_baseline` sin errores. |
| S4 | Repetir S3 sobre una base de datos **sin** la extensión timescaledb | La migración falla con un mensaje que nombra la extensión que falta. |
| S5 | `uv run uvicorn app.main:app --reload` y `curl -i localhost:8000/api/v1/health` | `200` y un cuerpo con `status: "ok"`, `database: "ok"` y `timescaledb` con una versión 2.x. |
| S6 | Detener el clúster 16 y repetir el `curl` | `503`, `status: "degraded"`, `database: "error"`. El servidor no se cae. |
| S7 | `localhost:8000/docs` | Swagger muestra `/api/v1/health` con `HealthSchema`. |
| S8 | `cd frontend && npm run dev` y abrir `localhost:3000` | La página carga sin errores en consola ni en terminal. |

## 3. `/health` comprueba la base de datos

- [ ] `HealthSchema` existe en `app/schemas/health.py` y es el `response_model` del endpoint.
- [ ] El endpoint ejecuta `SELECT 1` y consulta `extversion` de `timescaledb` en `pg_extension`.
- [ ] Tests automáticos cubren los tres casos: OK (base de datos real, marcado `db`), base de datos caída (503) y extensión ausente (`timescaledb: null`, `status: "degraded"`).

## 4. Estructura y calidad del código

- [ ] La raíz del repositorio contiene solo `specs/`, `prompts/`, `frontend/`, `backend/`, `.github/` y los documentos de primer nivel. No queda código de Next en la raíz.
- [ ] El historial de git conserva los archivos movidos (`git log --follow frontend/app/page.tsx` muestra el commit inicial).
- [ ] `.env` no está versionado; `.env.example` y `.env.local.example` sí.
- [ ] Ningún secreto ni contraseña de producción aparece en el repositorio. Las credenciales de desarrollo de `setup_db.sh` son aceptables.

## 5. README y specs actualizados

- [ ] Siguiendo **solo** el README, se puede reproducir el entorno local. Esto se verifica de hecho al ejecutar la sección 2.
- [ ] El README no menciona comandos que no existen (`gen:api` y Playwright aparecen como "próximamente" o no aparecen).
- [ ] `tech-stack.md` refleja PG16 en el puerto 5432, Python 3.12 y el changelog actualizado.
- [ ] `roadmap.md` tiene los pasos 0.1–0.5 marcados `[x]`.

## Criterio de rechazo

Si cualquier punto falla, la PR no se integra. Si un punto resulta inviable, por ejemplo por diferencias entre la CI y el entorno local, la decisión se registra en `requirements.md` antes de integrar. **No se hace merge sin dejar constancia.**
