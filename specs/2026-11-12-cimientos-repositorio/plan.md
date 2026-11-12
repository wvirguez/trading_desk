# Plan — Bloque 0: Cimientos del repositorio

Grupos de tareas en orden de ejecución. Cada grupo termina en un commit verde. El contexto y las decisiones (D1–D12) están en [`requirements.md`](requirements.md).

---

## 1. Entorno de máquina (manual, con `sudo`)

1.1. Instalar uv con el instalador oficial y comprobar `uv --version`.
1.2. Añadir el repositorio apt de PostgreSQL (PGDG) e instalar `postgresql-16`.
1.3. Comprobar que el clúster `16/main` está online en el puerto **5432** (`pg_lsclusters`); véase D1.
1.4. Añadir el repositorio apt de TimescaleDB, instalar `timescaledb-2-postgresql-16` y ejecutar `timescaledb-tune` **solo sobre el clúster 16**.
1.5. Reiniciar el clúster 16 y comprobar que `shared_preload_libraries` incluye `timescaledb`.

## 2. Reestructuración a monorepo (0.1)

2.1. Mover con `git mv` a `frontend/` los archivos de la app: `app/`, `public/`, `package.json`, `package-lock.json`, `tsconfig.json`, `next.config.ts`, `next-env.d.ts`, `eslint.config.mjs` y la configuración de PostCSS/Tailwind.
2.2. Dejar en la raíz: `specs/`, `prompts/`, `README.md`, `TODO.md`, `AGENTS.md` y `.gitignore`. Añadir a `.gitignore` las entradas de Python (`.venv/`, `__pycache__/`, `.env`) y ajustar las de Node a `frontend/`.
2.3. Reinstalar dependencias en `frontend/` y comprobar `npm run build` y `npm run lint`.
2.4. Crear `backend/` con `uv init --package`, fijar Python 3.12 (`.python-version`) y crear la estructura de carpetas vacía (`app/{api/v1,core,models,schemas}` con su `__init__.py`).
2.5. Commit: `chore: reestructurar a monorepo frontend/ + backend/`.

## 3. Esqueleto FastAPI (0.2)

3.1. Añadir las dependencias `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `sqlalchemy[asyncio]`, `asyncpg` y `alembic`.
3.2. `app/core/config.py`: clase `Settings` (D7) con `APP_ENV`, `DATABASE_URL` y `TEST_DATABASE_URL`. Crear también `backend/.env.example`.
3.3. `app/schemas/health.py`: `HealthSchema` (D6). El esquema se escribe **antes** que el endpoint.
3.4. `app/api/v1/router.py` y `app/api/v1/health.py`: de momento, health solo con `status` y `version`, sin base de datos.
3.5. `app/main.py`: app FastAPI con *lifespan* y el router montado en `/api/v1`.
3.6. Comprobar que `uv run uvicorn app.main:app --reload` responde en `/api/v1/health` y que `/docs` funciona.

## 4. Base de datos local y Alembic (0.5)

4.1. `backend/scripts/setup_db.sh` (D5): script idempotente que crea `quant_admin`, `quant_terminal_db`, `quant_terminal_test` y las extensiones `uuid-ossp` y `timescaledb` en ambas bases de datos. Se ejecuta con `sudo -u postgres bash < backend/scripts/setup_db.sh` (por stdin: `postgres` no puede leer el home del usuario) contra el puerto 5432.
4.2. `app/core/db.py`: `create_async_engine`, `async_sessionmaker`, la dependencia `get_session` y `Base` declarativa (SQLAlchemy 2.0).
4.3. Ejecutar `alembic init -t async alembic` y configurar `env.py` para que lea `Settings.DATABASE_URL` y `Base.metadata`.
4.4. Migración `0001_baseline` (D4): comprueba en `pg_extension` que existen `uuid-ossp` y `timescaledb` y lanza una excepción descriptiva si falta alguna.
4.5. Ampliar `/health` con `SELECT 1` y la consulta de la versión de timescaledb. Devuelve 503 con `database: "error"` si falla.
4.6. Comprobar `uv run alembic upgrade head` sobre las dos bases de datos.

## 5. Tooling de calidad (0.3)

5.1. Backend: configurar `ruff` (lint + format), `mypy --strict` (D9), `pytest`, `pytest-asyncio`, `httpx` y el marcador `db` (D8) en `pyproject.toml`.
5.2. Tests backend:
   - `test_config.py`: carga de settings.
   - `test_health.py`: health sin base de datos con la dependencia sobrescrita, más un caso con base de datos real marcado `db`, y el caso 503 simulando el fallo de la base de datos.
5.3. Frontend: instalar Vitest + `@testing-library/react` + jsdom, crear `vitest.config.ts`, añadir los scripts `test` y `typecheck` (`tsc --noEmit`) y un test de humo de `app/page.tsx`.
5.4. Comprobar que pasan en local:
   - Backend: `uv run ruff check`, `uv run ruff format --check`, `uv run mypy app` y `uv run pytest`.
   - Frontend: `npm run lint`, `npm run typecheck`, `npm test` y `npm run build`.

## 6. CI en GitHub Actions (0.4)

6.1. `.github/workflows/ci.yml` (D10), job `backend`:
   - `astral-sh/setup-uv` → `uv sync --frozen`.
   - *Service* `timescale/timescaledb:latest-pg16`.
   - Crear las extensiones con `psql` como superusuario.
   - `alembic upgrade head`, ruff, mypy y pytest (incluidos los tests `db`).
6.2. Job `frontend`: `actions/setup-node` (Node 20, caché npm, `working-directory: frontend`) → `npm ci` → lint → typecheck → test → build.
6.3. Hacer push de la rama, abrir la PR y comprobar la CI en verde.

## 7. Documentación y cierre

7.1. README:
   - Instalación real: uv, PG16 en el puerto 5432, `setup_db.sh` y `.env.example`.
   - Comandos de calidad que existen de verdad (quitar Playwright y `gen:api` como "próximamente").
   - Estructura actualizada.
7.2. `tech-stack.md`: precisar PG16 en el puerto 5432 (local), Python 3.12 y que Playwright se incorpora en la Fase 4. Añadir entrada al changelog.
7.3. `roadmap.md`: marcar 0.1–0.5 como `[x]`.
7.4. Ejecutar el checklist de [`validation.md`](validation.md) y adjuntar el resultado a la PR.
