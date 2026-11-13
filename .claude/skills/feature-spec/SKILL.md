---
name: feature-spec
description: Inicia una nueva función de este proyecto al encontrar la siguiente fase incompleta en specs/roadmap.md, crea una rama de Git, entrevista al usuario sobre el alcance, las decisiones y el contexto, y escribe un directorio con fecha en specs/ que contiene plan.md, requirements.md y validation.md. Se activa cuando el usuario dice "especificación de la función", "siguiente fase", "iniciar la siguiente función" o invoca /feature-spec.
---

# Especificación de la función

## Flujo de trabajo

### 1. Encontrar la siguiente fase

Lee `specs/roadmap.md`. La siguiente fase es la primera sección (Bloque o Fase) con algún elemento `[ ]`. Si ese elemento ya está implementado y solo falta verificarlo (por ejemplo, la CI en verde), díselo al usuario y pasa a la siguiente sección. El cierre del elemento pendiente se incluye en la nueva spec. Anota el nombre de la sección: de él salen el nombre de la rama y el del directorio.

### 2. Crea la rama

```
git checkout -b phase-N-<kebab-name>
```

### 3. Entrevista al usuario ANTES de escribir cualquier archivo

Usa `AskUserQuestion` con exactamente **3 preguntas en una sola llamada**:

| Encabezado | Enfoque de la pregunta |
|--------|---------------|
| **Alcance** | Qué ítems del roadmap cubre la spec y qué expone o hace: esquemas Pydantic, tablas, endpoints, vistas del terminal. |
| **Decisiones** | Opciones clave de implementación: almacenamiento (tablas, hypertables, JSONB), dependencias nuevas, estrategia de tests (fixtures, `TestModel`, red), contrato de la API. |
| **Contexto** | Restricciones y preguntas abiertas: precisión numérica, credenciales pendientes, límites de riesgo, pasos del roadmap que hay que cerrar. |

No escribas ningún archivo hasta que el usuario haya respondido las tres preguntas.

### 4. Lee los archivos de guía

Lee `specs/mission.md` y `specs/tech-stack.md` antes de redactar. Revisa también la spec más reciente de `specs/` para mantener el formato y la numeración de las decisiones.

### 5. Crea el directorio de especificaciones

Nombre: `specs/AAAA-MM-DD-<nombre-de-la-característica>/`, con la fecha de hoy.

#### `requirements.md`
- **Contexto:** por qué hace falta la fase y qué principios de la misión cumple.
- **Alcance:** qué entra y qué no. Si aplica, tablas de esquemas, tablas de base de datos y endpoints.
- **Decisiones:** tabla numerada (D1, D2, …) con la decisión y su motivo, basada en las respuestas del usuario.
- **Variables de entorno nuevas**, si las hay.
- **Contexto, tono y patrones existentes** a seguir, con enlaces a los archivos.
- **Preguntas abiertas y riesgos.**

#### `plan.md`
- Grupos de tareas numerados, en este orden y omitiendo los que no apliquen:
  1. Dependencias y configuración.
  2. Esquemas Pydantic.
  3. Base de datos: modelos, migraciones de Alembic y repositorios.
  4. Lógica de dominio: `quant/`, `risk/`, adaptadores o agentes.
  5. Servicios y endpoints FastAPI.
  6. Tipos TS generados.
  7. UI de Next.js.
  8. CI, documentación y cierre del roadmap.
- Cada grupo sigue el orden **esquema → tests → implementación**, tiene subtareas numeradas y termina en un commit verde. Los grupos se pueden implementar por separado.

#### `validation.md`
- **Automatizado, en CI y en la PR:**
  - Backend: `uv run ruff check`, `uv run ruff format --check`, `uv run mypy app` y `uv run pytest`, incluidos los tests `@pytest.mark.db`.
  - Frontend: `npm run lint`, `npm run typecheck`, `npm test` y `npm run build`.
  - Si la fase toca la API, los tipos regenerados (`npm run gen:api`) no dejan diff.
  - Además, una tabla de **afirmaciones concretas** que deben existir en los tests.
- **Manual:** smoke test local con comandos y resultados esperados (`alembic`, CLI, `curl` a `/api/v1/...`, `/docs` y, si hay UI, recorrido en el navegador), más los casos límite.
- **Tono** de los textos visibles: `detail` de la API, salida de la CLI y UI, si la hay.
- **Definición de "terminado"** y criterio de rechazo.

## Restricciones de la pila

Fuente de verdad: `specs/tech-stack.md`. Si la especificación contradice ese archivo, gana el archivo. Si una decisión cambia la pila, se actualiza `tech-stack.md` y su changelog.

- **Monorepo:** `backend/` (FastAPI), `frontend/` (Next.js), `specs/` (fuente de verdad SDD) y `.github/` (CI).
- **Backend:**
  - Python 3.12 gestionado con **uv** (`pyproject.toml` + `uv.lock`).
  - FastAPI + Pydantic v2, con prefijo `/api/v1`. REST, SSE y WebSocket.
  - Configuración con `pydantic-settings` en `app/core/config.py` (`get_settings()`). Secretos solo en `backend/.env` (fuera de git), documentados en `.env.example` y como `SecretStr` cuando son credenciales.
  - Logging con `structlog` en JSON.
- **Base de datos:**
  - PostgreSQL 16 local y nativo (puerto 5432, sin Docker) con TimescaleDB y `uuid-ossp`. En CI, *service* `timescale/timescaledb:latest-pg16`.
  - SQLAlchemy 2.0 async + asyncpg; sesión con `get_session` de `app/core/db.py`.
  - Migraciones versionadas con **Alembic** en `backend/alembic/versions/`.
  - `ohlcv_bars` es hypertable. `agent_analyses` es solo inserción (JSONB).
- **Contratos (SDD):**
  - Esquemas Pydantic primero: ningún endpoint, herramienta de agente ni componente se implementa sin su contrato.
  - Los tipos TS se **generan** con `openapi-typescript` desde el OpenAPI de FastAPI; nunca se escriben a mano.
  - La validación vive en los esquemas Pydantic, en los límites del sistema.
- **Núcleo cuantitativo:**
  - polars, numpy, scipy y statsmodels.
  - Backtester vectorizado propio y determinista.
  - El riesgo, el *sizing*, Kelly, Sharpe, el drawdown y el R:R se calculan **siempre en Python puro, nunca con el LLM**.
  - Veto determinista con R:R < 1,8, 1 % de riesgo por operación y 3 % de pérdida diaria.
- **Agentes:**
  - Anthropic Claude con **PydanticAI** (`output_type` tipado y herramientas deterministas).
  - Orquestador propio async.
  - En CI se usan `TestModel`/`FunctionModel`: los tests nunca llaman a la API real.
- **Frontend:**
  - Next.js 16 (App Router) con React 19, TypeScript estricto y sin `any`. Tailwind CSS 4 + shadcn/ui + Lucide.
  - Zustand y TanStack Query; `lightweight-charts`.
  - Esta versión de Next tiene cambios incompatibles: antes de proponer APIs o convenciones, lee la guía relevante en `frontend/node_modules/next/dist/docs/`.
  - Por defecto, Server Components; `"use client"` solo cuando haga falta interactividad.
- **Pruebas:**
  - Backend: pytest + pytest-asyncio, con `hypothesis` para las propiedades de riesgo, tests *golden* de determinismo y `@pytest.mark.db` para los tests con base de datos.
  - Frontend: Vitest + Testing Library; Playwright desde la fase 4.
  - Todo código nuevo lleva pruebas. La CI no hace llamadas de red a proveedores externos: se usan fixtures grabados.
- **Calidad:** `ruff`, `mypy --strict` sobre `app/`, ESLint y `tsc --noEmit`.
- **Dependencias:** no se añaden nuevas sin la aprobación del usuario.
- **Público y estilo:**
  - Herramienta personal de un único usuario (trader-desarrollador), local y sin autenticación ni multiusuario.
  - Interfaz oscura, densa y técnica, solo en español. Se prioriza la trazabilidad sobre el acabado visual.
  - Fuera del alcance del MVP: ejecución real (solo paper trading), despliegue en la nube y Docker en local.
- **Tono:** técnico, honesto y concreto. Los errores nombran el dato problemático y no esconden fallos. Nunca se exponen secretos en logs ni en mensajes (ver `specs/mission.md`).
