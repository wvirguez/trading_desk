---
name: spec-implementer
description: Implementa el plan de una especificación de este proyecto. Recibe la ruta de un plan.md (o del directorio de la spec en specs/), lee la misión, el stack y el roadmap, implementa los grupos de tareas uno a uno con subagentes y, al terminar, hace una revisión y entrega una lista de errores críticos sin corregirlos. Se invoca manualmente (/spec-implementer specs/AAAA-MM-DD-nombre/plan.md).
disable-model-invocation: true
argument-hint: specs/AAAA-MM-DD-<nombre>/plan.md
---

# Implementador de especificaciones

Implementa el `plan.md` indicado por el usuario. El argumento es la ruta a un `plan.md` o al directorio de la spec (en ese caso, usa `plan.md` dentro de él). Si no se indica ruta, pregunta cuál spec implementar; no adivines.

## Flujo de trabajo

### 1. Contexto del proyecto

Lee, antes de tocar código:
- `specs/mission.md` y `specs/tech-stack.md` (detalles del proyecto; si una spec los contradice, ganan estos archivos).
- `specs/roadmap.md` (fases del proyecto; identifica a cuál pertenece la spec).
- `frontend/AGENTS.md`, solo si el plan toca el frontend: Next.js 16 tiene cambios incompatibles; lee la guía relevante en `frontend/node_modules/next/dist/docs/` antes de escribir código de framework.
- Los hermanos del `plan.md` indicado: `requirements.md` y `validation.md`.

Confirma que estás en la rama de la fase (`phase-N-...`); si estás en `main`, avisa al usuario antes de continuar.

### 2. Implementar los grupos de tareas, uno a la vez

Los grupos del `plan.md` (Dependencias y configuración → Esquemas → Base de datos → Lógica de dominio → Servicios y endpoints → Tipos TS → UI → CI y documentación) se implementan **secuencialmente, de uno en uno**. Si un grupo se divide en subgrupos (4A, 4B…), cada subgrupo cuenta como un grupo.

1. Lanza un subagente (herramienta `Agent`, tipo `general-purpose`) por grupo. En el prompt incluye: la ruta de la spec, el texto exacto del grupo y sus subtareas, las restricciones de la pila (abajo) y qué grupos ya están hechos. No lances grupos en paralelo.
2. Al volver el subagente, comprueba brevemente que realizó lo pedido (`git status`/`git diff --stat` y, si procede, un comando de verificación) y pasa al siguiente grupo. No corrijas nada a mano entre grupos salvo que el siguiente grupo no pueda avanzar sin ello; si ocurre, repórtalo.
3. Un grupo sin cambios ("Ninguno", "Sin cambios") se omite y se anota.
4. Tareas del plan que no se pueden hacer sin el usuario (aprobar dependencias, smoke manual, PR, CI, marcar el roadmap) se omiten y se anotan en el reporte.

Restricciones de la pila para cada subagente:
- **Backend:** Python 3.12 con **uv** (comandos en `backend/`: `uv run ...`), FastAPI + Pydantic v2 con prefijo `/api/v1`, SQLAlchemy 2.0 async + asyncpg, Alembic (migraciones en `backend/alembic/versions/`), PostgreSQL 16 local con TimescaleDB (sin Docker). Configuración con `get_settings()`; secretos solo en `backend/.env` (fuera de git), documentados en `.env.example`.
- **Contratos (SDD):** esquemas Pydantic primero, después tests, después implementación. Los tipos TS se **generan** (`npm run gen:api`), nunca se escriben a mano. Dinero y precios en `Decimal`.
- **Núcleo cuantitativo y riesgo:** polars/numpy/statsmodels; el riesgo, el sizing, Kelly, Sharpe, drawdown y R:R se calculan en Python puro, nunca con el LLM. `quant/` y `risk/` no importan FastAPI ni SQLAlchemy.
- **Agentes:** PydanticAI; en tests, `TestModel`/`FunctionModel`, nunca la API real.
- **Frontend (solo si el plan lo toca):** Next.js 16 (App Router), React 19, Tailwind 4, TypeScript estricto y **sin `any`**, Server Components por defecto (`"use client"` solo si hace falta), Vitest + Testing Library.
- **Calidad:** `ruff` (línea 100), `mypy --strict` sobre `app/`, tests con `pytest`; los tests con base de datos llevan `@pytest.mark.db` y la BD de test debe estar migrada a `head`. Todo código nuevo lleva pruebas, y ninguna llama a la red.
- **No añadir dependencias** sin aprobación del usuario; si el plan las lista como aprobadas, comprueba que la aprobación está registrada en la spec.
- Interfaz y mensajes solo en español, técnicos y honestos (ver `specs/mission.md`). Nunca secretos en logs ni mensajes.
- No hacer commit ni push.

### 3. Revisión (sin arreglar)

Una vez implementados todos los grupos:
1. Ejecuta las comprobaciones de `validation.md` que sean automáticas y reproducibles en local. Backend (en `backend/`): `uv run ruff check`, `uv run ruff format --check`, `uv run mypy app`, `uv run pytest`. Frontend (en `frontend/`, si el plan lo toca o regeneró tipos): `npm run lint`, `npm run typecheck`, `npm test` y `npm run build`. Registra los fallos tal cual.
2. Lanza un subagente revisor (solo lectura: no edita archivos) que compare el `git diff` (incluidos los archivos nuevos sin seguimiento) contra `plan.md`, `requirements.md` y `validation.md`, y busque: tareas del plan sin implementar, incumplimientos de la pila, `any`, `float` donde la spec exige `Decimal`, dependencias nuevas sin aprobar, secretos en código, código sin pruebas, afirmaciones de `validation.md` sin test, errores de lógica y desvíos del tono de la misión.

**No arregles nada después de esta revisión.** Ni los fallos de las pruebas ni los hallazgos del revisor.

### 4. Reporte

Entrega al usuario:
- Resumen por grupo: implementado / omitido.
- Resultado de las comprobaciones del paso 3 (lint, formato, tipos, tests y, si aplica, build).
- **Lista de errores críticos**: cada uno con archivo y línea (`ruta:línea`), qué falla y por qué importa. Si no hay, dilo explícitamente. Separa los críticos de las afirmaciones de `validation.md` sin test y de las observaciones menores (máximo unas pocas líneas).
- Desviaciones respecto a la spec que decidieron los subagentes.
- Pasos de `validation.md` que requieren verificación manual.

Pregunta al usuario si quiere que corrijas los errores; no los corrijas por tu cuenta ni marques la fase como `[x]` en el roadmap (eso ocurre solo tras validarla).

## Notas

- Nunca declares algo implementado o verificado sin haberlo comprobado en el diff o en la salida de los comandos.
- Si el plan contradice `specs/tech-stack.md` o la misión, detente en ese grupo y consulta al usuario.
- Este skill solo se activa con `/spec-implementer` tecleado por el usuario (`disable-model-invocation`): no se invoca con la herramienta Skill.
