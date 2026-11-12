# Requisitos — Bloque 0: Cimientos del repositorio

- **Rama:** `feature/bloque-0-cimientos`
- **Roadmap:** pasos 0.1 – 0.5 de [`specs/roadmap.md`](../roadmap.md)
- **Referencias:** [`mission.md`](../mission.md), [`tech-stack.md`](../tech-stack.md)

## 1. Contexto

El repositorio contiene solo el scaffold de `create-next-app` (Next.js 16.4) en la raíz y la constitución en `specs/`. Antes de escribir lógica de dominio (Fase 1) hace falta un monorepo con backend y frontend que arranquen, una base de datos local operativa, herramientas de calidad y una CI que proteja `main`. Esto cumple el principio 7 de la misión: incrementos pequeños, cada uno funcionando y con tests.

### Estado actual de la máquina (2026-11-12)

| Componente | Requerido (`tech-stack.md`) | Encontrado | Acción |
| :--- | :--- | :--- | :--- |
| PostgreSQL | 16+ | 14 (clúster `14/main`, puerto 5432) | Instalar PG16. *(Resultado: PG16.16 en el 5432; PG14 movido al 5433 y apagado, véase D1.)* |
| TimescaleDB | Sí | No instalado | Instalar `timescaledb-2-postgresql-16` (repositorio apt oficial). |
| Python | 3.11+ | 3.10.12 (sistema) | Usar Python **3.12** gestionado por uv; el del sistema no se toca. |
| uv | Sí | No instalado | Instalar uv (instalador oficial, en `~/.local/bin`). |
| Node.js | 20+ | 24.16 (nvm) | OK |

## 2. Alcance

### Dentro del alcance
1. **0.1 Monorepo:** mover la app Next.js de la raíz a `frontend/` y crear `backend/` con `uv init`.
2. **0.2 Esqueleto FastAPI:** `app/main.py`, `core/config.py` (pydantic-settings), router `/api/v1` y `GET /api/v1/health`.
3. **0.3 Tooling de calidad:**
   - Backend: ruff, mypy, pytest y pytest-asyncio.
   - Frontend: ESLint (ya existe) y Vitest.
4. **0.4 CI:** workflow de GitHub Actions para backend y frontend.
5. **0.5 Base de datos:** PG16 + TimescaleDB local, sesión async de SQLAlchemy y Alembic con una migración base.
6. **Documentación:** README y `tech-stack.md` alineados con la instalación real; roadmap con los pasos 0.x marcados como hechos.

### Fuera del alcance
- Modelos de dominio (`instruments`, `ohlcv_bars`, ...): Fase 1.
- Generación de tipos con `openapi-typescript` y el script `gen:api`: paso 1.9.
- Playwright: paso 4.10.
- shadcn/ui, Zustand, TanStack Query y `lightweight-charts`: Fase 4.
- Retirar el clúster PostgreSQL 14: queda a decisión del usuario, fuera de esta rama.
- Docker para desarrollo local. En CI sí se usa un *service container*, porque no afecta al entorno local.

## 3. Decisiones

| # | Decisión | Motivo |
| :--- | :--- | :--- |
| D1 | PG16 + TimescaleDB **nativos** en el **puerto 5432**. *Revisada: inicialmente era un clúster nuevo en el 5433; el usuario intercambió los puertos y el PG14 quedó en el 5433, apagado.* | Sin Docker (`tech-stack.md`); 5432 es el puerto estándar. |
| D2 | Python **3.12** fijado en `backend/.python-version` y gestionado por uv. | Cumple 3.11+ con margen y no toca el Python del sistema. |
| D3 | Dos bases de datos: `quant_terminal_db` (desarrollo) y `quant_terminal_test` (tests). | Los tests no pueden ensuciar los datos de desarrollo. |
| D4 | Las extensiones (`uuid-ossp`, `timescaledb`) las crea el **script de setup como superusuario**. La migración Alembic `0001_baseline` solo **verifica** que existen y falla con un mensaje claro si faltan. | TimescaleDB no es una extensión *trusted*: el rol `quant_admin` no puede crearla. |
| D5 | Script idempotente `backend/scripts/setup_db.sh` para crear roles, bases de datos y extensiones. | Hace reproducible el entorno local, que es lo que se valida en el smoke test. |
| D6 | `GET /api/v1/health` devuelve `HealthSchema` (Pydantic): `status` (`ok`/`degraded`), `version`, `database` (`ok`/`error`) y `timescaledb` (versión o `null`). Responde **200** si todo está bien y **503** si la base de datos falla. | Esquemas primero: incluso el health check tiene contrato. |
| D7 | Configuración con `pydantic-settings` leída de `backend/.env`. Se versiona `.env.example`; `.env` no. | Secretos fuera del repositorio. |
| D8 | Los tests que necesitan base de datos se marcan con `@pytest.mark.db`. Los unitarios corren sin ella. | Permite iterar rápido y la CI ejecuta ambos tipos. |
| D9 | `mypy --strict` sobre todo `app/` desde el inicio. | Es más barato hacerlo ahora que adoptarlo con código ya escrito. |
| D10 | La CI se dispara en `pull_request` y en `push` a `main`, con dos jobs en paralelo (`backend`, `frontend`). Postgres corre como *service* `timescale/timescaledb:latest-pg16`. | Docker en CI no contradice la regla de no usar Docker en local. |
| D11 | El frontend usa npm y queda en `frontend/` con su propio `package-lock.json`. Sin workspaces. | Simplicidad: los dos lados no comparten paquetes JS. |
| D12 | Se crea `frontend/.env.local.example` con `NEXT_PUBLIC_API_URL`, pero la UI todavía no llama al backend. | Deja listo el contrato de entorno sin adelantar la Fase 4. |
| D13 | *(implementación)* **Node 22 LTS** como mínimo (CI y `engines`) y `@types/node@^22`. | Vitest 5 lo exige; Node 20 llegó a fin de vida en abril de 2026. |
| D14 | *(implementación)* `AGENTS.md` se mueve a `frontend/`. | `next dev` lo regenera en el directorio del proyecto Next; en la raíz quedaría duplicado. |
| D15 | *(implementación)* `/health` devuelve **503** también cuando falta TimescaleDB (`status: "degraded"`). Solo `ok` implica 200. | Sin TimescaleDB la aplicación no puede funcionar; un 200 enmascararía el problema. |
| D16 | *(implementación)* `npm run typecheck` = `next typegen && tsc --noEmit`. | `next-env.d.ts` y los tipos de rutas no se versionan; en CI hay que generarlos. |
| D17 | *(implementación)* La CI reutiliza `scripts/setup_db.sh` (vía `PGHOST`/`PGUSER`/`PGPASSWORD`) contra el *service*. | El script de setup queda probado en cada ejecución de la CI. |
| D18 | *(implementación)* `setup_db.sh` se invoca por stdin: `sudo -u postgres bash < backend/scripts/setup_db.sh`. | El usuario `postgres` no tiene acceso al home del desarrollador (`drwxr-x---`); así el archivo lo lee el usuario actual. |

## 4. Variables de entorno (backend)

```dotenv
APP_ENV=development
DATABASE_URL=postgresql+asyncpg://quant_admin:quant_secret_dev@localhost:5432/quant_terminal_db
TEST_DATABASE_URL=postgresql+asyncpg://quant_admin:quant_secret_dev@localhost:5432/quant_terminal_test
```

Las claves de Anthropic y OANDA **no** entran en este bloque. Se añadirán en las fases que las usen.

## 5. Riesgos

- **Next 16 al moverse de carpeta:** las rutas en `tsconfig.json`, `eslint.config.mjs` y `next.config.ts` pueden asumir la raíz. Mitigación: verificar `npm run build` tras el movimiento y consultar `node_modules/next/dist/docs/` (véase `AGENTS.md`).
- **Instalación de paquetes de sistema (apt):** requiere `sudo` y la ejecuta el usuario. El plan indica los comandos, pero no se automatizan.
- **Diferencias entre la CI y el entorno local** (imagen Docker frente a instalación nativa): ambas usan PG16 y TimescaleDB 2.x, y `/health` expone la versión para detectar diferencias.
