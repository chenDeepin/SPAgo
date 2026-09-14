#!/bin/bash
# Initialize (first run) and run PostgreSQL 15 with the RDKit cartridge, in the foreground.
#
# The cluster lives entirely in /var/lib/postgresql/data (a named volume), so
# config and data survive container recreation together. Role/database/extension
# provisioning is idempotent and runs on every start.
set -euo pipefail

: "${POSTGRES_DB:=spago}"
: "${POSTGRES_USER:=spago}"
: "${POSTGRES_PASSWORD:=spago}"

DATA_DIR=/var/lib/postgresql/data
PG_BIN=/usr/lib/postgresql/15/bin

mkdir -p "$DATA_DIR"
chown -R postgres:postgres /var/lib/postgresql

if [ ! -s "$DATA_DIR/PG_VERSION" ]; then
  echo "[spago-db] initializing cluster in $DATA_DIR"
  printf '%s\n' "$POSTGRES_PASSWORD" > /tmp/spago-pwfile
  chown postgres:postgres /tmp/spago-pwfile
  chmod 600 /tmp/spago-pwfile
  runuser -u postgres -- "$PG_BIN/initdb" -D "$DATA_DIR" -U postgres \
    --pwfile=/tmp/spago-pwfile --auth-host=scram-sha-256 --auth-local=trust \
    --encoding=UTF8 --locale=C.UTF-8
  rm -f /tmp/spago-pwfile
  {
    echo ""
    echo "# SPAgo container settings"
    echo "listen_addresses = '*'"
  } >> "$DATA_DIR/postgresql.conf"
  {
    echo ""
    echo "# SPAgo container access"
    echo "host all all all scram-sha-256"
  } >> "$DATA_DIR/pg_hba.conf"
  chown postgres:postgres "$DATA_DIR/postgresql.conf" "$DATA_DIR/pg_hba.conf"
fi

echo "[spago-db] starting temporary postgres for provisioning"
runuser -u postgres -- "$PG_BIN/pg_ctl" -D "$DATA_DIR" -w -t 60 start

PSQL() { runuser -u postgres -- "$PG_BIN/psql" "$@"; }

if [ "$(PSQL -tAc "SELECT 1 FROM pg_roles WHERE rolname = '${POSTGRES_USER}'")" != "1" ]; then
  echo "[spago-db] creating role ${POSTGRES_USER}"
  PSQL -v ON_ERROR_STOP=1 -c \
    "CREATE ROLE \"${POSTGRES_USER}\" LOGIN CREATEDB PASSWORD '${POSTGRES_PASSWORD}';"
else
  # Keep credentials and attributes in sync with the environment.
  PSQL -v ON_ERROR_STOP=1 -c \
    "ALTER ROLE \"${POSTGRES_USER}\" LOGIN CREATEDB PASSWORD '${POSTGRES_PASSWORD}';"
fi

if [ "$(PSQL -tAc "SELECT 1 FROM pg_database WHERE datname = '${POSTGRES_DB}'")" != "1" ]; then
  echo "[spago-db] creating database ${POSTGRES_DB}"
  PSQL -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"${POSTGRES_DB}\" OWNER \"${POSTGRES_USER}\";"
fi

if [ "$(PSQL -d "${POSTGRES_DB}" -tAc "SELECT 1 FROM pg_extension WHERE extname = 'rdkit'")" != "1" ]; then
  echo "[spago-db] enabling rdkit extension in ${POSTGRES_DB}"
  PSQL -d "${POSTGRES_DB}" -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS rdkit;"
fi

echo "[spago-db] stopping temporary postgres"
runuser -u postgres -- "$PG_BIN/pg_ctl" -D "$DATA_DIR" -m fast -w stop

echo "[spago-db] starting postgresql 15 in foreground"
exec setpriv --reuid=postgres --regid=postgres --init-groups \
  "$PG_BIN/postgres" -D "$DATA_DIR"
