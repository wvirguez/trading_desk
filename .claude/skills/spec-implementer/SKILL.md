----
name: spec-implemeter
description: Implementa el plan de una especificación de este proyecto. Recibe la ruta de un plan.md (o del directorio de la spec en specs/), lee la misión, el stack y el roadmap, implementa los grupos de tareas uno a uno con subagentes y, al terminar, hace una revisión y entrega una lista de errores críticos sin corregirlos. Se invoca manualmente (/spec-implemeter specs/AAAA-MM-DD-nombre/plan.md).
disable-model-invocation: true
argument-hint: specs/AAAA-MM-DD-<nombre>/plan.md
----

# Implementador de especificaciones

Implementa el `plan.md` indicado por el usuario. El argumento es la ruta a un `plan.md` o al directorio de la spec (en ese caso, usa `plan.md` dentro de él). Si no se indica ruta, pregunta cuál spec implementar; no adivines.

## Flujo de trabajo

### 1. Contexto del proyecto

Lee, antes de tocar código:
- `specs/mission.md` y `specs/tech-stack.md` (detalles del proyecto; si una spec los contradice, ganan estos archivos).
- `specs/roadmap.md` (fases del proyecto; identifica a cuál pertenece la spec).
- `AGENTS.md`: Next.js 16 tiene cambios incompatibles; lee la guía relevante en `node_modules/next/dist/docs/` antes de escribir código de framework.
- Los hermanos del `plan.md` indicado: `requirements.md` y `validation.md`.

Confirma que estás en la rama de la fase (`phase-N-...`); si estás en `main`, avisa al usuario antes de continuar.

### 2. Implementar los grupos de tareas, uno a la vez

Los grupos del `plan.md` (Base de datos → Componentes → Página y ruta → Navegación → Pruebas, etc.) se implementan **secuencialmente, de uno en uno**:

1. Lanza un subagente (herramienta `Agent`, tipo `general-purpose`) por grupo. En el prompt incluye: la ruta de la spec, el texto exacto del grupo y sus subtareas, las restricciones de la pila (abajo) y qué grupos ya están hechos. No lances grupos en paralelo.
2. Al volver el subagente, comprueba brevemente que realizó lo pedido (`git status`/`git diff --stat`) y pasa al siguiente grupo. No corrijas nada a mano entre grupos salvo que el siguiente grupo no pueda avanzar sin ello; si ocurre, repórtalo.
3. Un grupo sin cambios ("Ninguno", "Sin cambios") se omite y se anota.

Restricciones de la pila para cada subagente:
- Next.js 16 (App Router), React 19, Tailwind 4, TypeScript estricto y **sin `any`**.
- Prisma 7 con adaptador MariaDB; cliente desde `lib/db.ts`; variables validadas en `lib/env.ts`; `.env*` fuera de git. Usa el MySQL local, no Docker.
- Zod en los límites del sistema. Server Components por defecto; `"use client"` solo si hace falta.
- Todo código nuevo lleva pruebas (Vitest + Testing Library).
- **No añadir dependencias** sin aprobación del usuario.
- Interfaz solo en español, tono honesto y sin falsas urgencias (ver `specs/mission.md`).
- No hacer commit ni push.

### 3. Revisión (sin arreglar)

Una vez implementados todos los grupos:
1. Ejecuta `npm test`, `npm run lint` y `npx tsc --noEmit` (y `npm run build` si el plan toca rutas o esquema). Registra los fallos tal cual.
2. Lanza un subagente revisor (solo lectura: no edita archivos) que compare el `git diff` contra `plan.md`, `requirements.md` y `validation.md`, y busque: tareas del plan sin implementar, incumplimientos de la pila, `any`, dependencias nuevas, secretos en código, código sin pruebas, errores de lógica y desvíos del tono de la misión.

**No arregles nada después de esta revisión.** Ni los fallos de las pruebas ni los hallazgos del revisor.

### 4. Reporte

Entrega al usuario:
- Resumen por grupo: implementado / omitido.
- Resultado de `npm test`, `npm run lint`, `npx tsc --noEmit` (y build si aplica).
- **Lista de errores críticos**: cada uno con archivo y línea (`ruta:línea`), qué falla y por qué importa. Si no hay, dilo explícitamente. Separa los críticos de las observaciones menores (máximo unas pocas líneas).
- Pasos de `validation.md` que requieren verificación manual.

Pregunta al usuario si quiere que corrijas los errores; no los corrijas por tu cuenta ni marques la fase como `[x]` en el roadmap (eso ocurre solo tras validarla).

## Notas

- Nunca declares algo implementado o verificado sin haberlo comprobado en el diff o en la salida de los comandos.
- Si el plan contradice `specs/tech-stack.md` o la misión, detente en ese grupo y consulta al usuario.
