#!/usr/bin/env bash
# Crea (de forma idempotente) el rol, las bases de datos y las extensiones del MVP.
#
# Uso:   sudo -u postgres bash < backend/scripts/setup_db.sh
# Vars:  PGPORT (por defecto 5432, clúster PostgreSQL 16)
#        DB_USER / DB_PASSWORD (credenciales SOLO de desarrollo local)
set -euo pipefail

export PGPORT="${PGPORT:-5432}"
DB_USER="${DB_USER:-quant_admin}"
DB_PASSWORD="${DB_PASSWORD:-quant_secret_dev}"
DATABASES=(quant_terminal_db quant_terminal_test)

psql_su() { psql -v ON_ERROR_STOP=1 -qtA "$@"; }

echo "→ Servidor: $(psql_su -c 'SHOW server_version;') en el puerto ${PGPORT}"

if [[ "$(psql_su -c "SELECT 1 FROM pg_roles WHERE rolname = '${DB_USER}'")" != "1" ]]; then
  psql_su -c "CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}';"
  echo "→ Rol ${DB_USER} creado"
else
  echo "→ Rol ${DB_USER} ya existe"
fi

for db in "${DATABASES[@]}"; do
  if [[ "$(psql_su -c "SELECT 1 FROM pg_database WHERE datname = '${db}'")" != "1" ]]; then
    psql_su -c "CREATE DATABASE ${db} OWNER ${DB_USER};"
    echo "→ Base de datos ${db} creada"
  else
    echo "→ Base de datos ${db} ya existe"
  fi
  psql_su -d "${db}" -c 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'
  psql_su -d "${db}" -c 'CREATE EXTENSION IF NOT EXISTS timescaledb;'
  echo "→ ${db}: timescaledb $(psql_su -d "${db}" -c "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")"
done

echo "✓ Setup completado"
