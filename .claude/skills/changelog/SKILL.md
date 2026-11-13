---
name: changelog
description: Mantiene CHANGELOG.md en la raíz del proyecto con un encabezado por fecha y viñetas por cambio. Si el archivo no existe, lo crea a partir del historial de Git; si existe, agrega solo las confirmaciones nuevas. Se invoca manualmente (/changelog) antes de fusionar una rama.
disable-model-invocation: true
---

# Changelog

Mantiene `CHANGELOG.md` en la raíz del proyecto. Un encabezado `##` por fecha (más reciente primero) y una viñeta por cambio relevante, en español.

## Formato

```markdown
# Changelog

## 2026-11-05

- Feat: Hub de productos en la portada
- Fix: Ajuste en la imagen del Hero

## 2026-07-29

- Nuevas modificaciones
```

- Fecha en formato `YYYY-MM-DD` (fecha del commit, `--date=short`).
- Fechas en orden descendente; dentro de una fecha, orden cronológico.
- Conserva el prefijo `Feat:` / `Fix:` si el commit lo tiene.

## Flujo de trabajo

### 1. Reunir las confirmaciones

Excluye merges (`--no-merges`).

- **Si `CHANGELOG.md` NO existe** → historial completo:
  ```
  git log --no-merges --reverse --date=short --pretty='%ad|%h|%s'
  ```
- **Si existe** → lee el encabezado de fecha más reciente (`D`) y obtén lo que pueda faltar desde esa fecha:
  ```
  git log --no-merges --reverse --since="D 00:00" --date=short --pretty='%ad|%h|%s'
  ```
  Si la rama actual no es la principal, limita a lo que se va a fusionar: `git log main..HEAD ...`.

### 2. Descartar lo ya registrado

Compara cada commit con las viñetas existentes en la misma fecha (por significado, no solo texto exacto). No dupliques. Si no queda nada nuevo, dilo y termina sin tocar el archivo.

### 3. Redactar las viñetas

- Una viñeta por cambio, no necesariamente por commit: agrupa commits triviales o repetidos de la misma fecha.
- Reescribe el asunto del commit para que lo entienda alguien que no vio el código (qué cambió, no cómo). Corrige errores ortográficos evidentes.
- Si el asunto es ambiguo (p. ej. "Nuevas Modificaciones"), mira `git show --stat <hash>` para describirlo con precisión.
- Omite ruido puro (commits de formato, "wip", revertidos y rehechos).

### 4. Escribir el archivo

- Archivo nuevo: crea `# Changelog` seguido de todas las fechas.
- Archivo existente: agrega viñetas bajo la fecha correspondiente o inserta el encabezado nuevo en su posición. No reescribas entradas anteriores.

### 5. Reportar

Muestra un resumen breve de lo agregado (fechas y número de viñetas). No hagas commit ni push: el usuario decide cuándo incluir el changelog en la rama.

## Notas

- Los cambios sin confirmar (working tree) no se registran; avisa si hay cambios pendientes que quedarían fuera.
- Nunca inventes cambios que no estén respaldados por el historial de Git.
