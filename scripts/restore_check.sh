#!/usr/bin/env bash
# Restore rehearsal for the operator gate (docs/online-capability.md §6 criterion 6,
# docs/runbook.md §H7).
#
# What it does, in order:
#   1. reads the running db container for the deployment's own role/database names
#      (so the rehearsal cannot drift from the deployment it checks);
#   2. records the source counts *before* the dump;
#   3. dumps the source database in custom format;
#   4. creates a scratch database and restores the dump into it as the app role;
#   5. restores the rdkit extension first (a non-superuser app role cannot create it);
#   6. compares users, projects (owned/unowned), analyses, saved project items and
#      compounds-with-structure, plus the per-user project split, and exits non-zero on
#      any mismatch.
#
# The scratch database is dropped at the end unless --keep is given. The dump file is
# removed unless --dump is given, so no server dump is left behind by accident.
#
# Assumptions this rehearsal states rather than hides:
#   - Counts are read from the source before the dump. If the deployment receives
#     writes during the rehearsal, source and restore legitimately differ; stop the
#     app container (docker compose stop app) and re-run.
#   - The same PostgreSQL server hosts the scratch database. A rehearsal that needs a
#     second host is the operator's own procedure; the comparisons below still apply.
#
# Usage:
#   scripts/restore_check.sh [--project spago] [--env-file .env] [--db spago]
#                            [--scratch spago_restore_check] [--superuser postgres]
#                            [--dump <path>] [--keep] [--reuse-scratch] [--quiet]

set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT=spago
ENV_FILE=""
DB=""
SCRATCH="spago_restore_check"
SUPERUSER=""
DUMP=""
KEEP=0
REUSE=0
QUIET=0

while [ $# -gt 0 ]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --env-file) ENV_FILE="$2"; shift 2 ;;
    --db) DB="$2"; shift 2 ;;
    --scratch) SCRATCH="$2"; shift 2 ;;
    --superuser) SUPERUSER="$2"; shift 2 ;;
    --dump) DUMP="$2"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    --reuse-scratch) REUSE=1; shift ;;
    --quiet) QUIET=1; shift ;;
    -h|--help) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

COMPOSE=(docker compose -p "${PROJECT}")
[ -n "${ENV_FILE}" ] && COMPOSE+=(--env-file "${ENV_FILE}")

say() { [ "${QUIET}" -eq 1 ] || echo "$@"; }

fail() { echo "RESTORE CHECK FAILED: $*" >&2; exit 1; }

# One place where SQL is executed inside the db container. `-t -A -q` gives stable,
# unaligned output for comparison; errors abort the script (set -e).
db_psql() { "${COMPOSE[@]}" exec -T db psql -v ON_ERROR_STOP=1 -t -A -q -U "$1" -d "$2" -c "$3"; }

container_var() { "${COMPOSE[@]}" exec -T db sh -c "printf '%s' \"\${$1:-}\""; }

"${COMPOSE[@]}" ps --services --status running 2>/dev/null | grep -qx db \
  || fail "the db service of compose project '${PROJECT}' is not running"

[ -n "${DB}" ] || DB="$(container_var POSTGRES_DB)"
ROLE="$(container_var POSTGRES_USER)"
[ -n "${DB}" ] || fail "cannot determine the source database name; pass --db"

say "== restore rehearsal: project=${PROJECT} role=${ROLE} database=${DB} scratch=${SCRATCH} =="

# --- the metrics, in one place, so source and restore cannot drift apart ------------
# Each entry is "label|SQL", ordered. Counts only: a rehearsal compares the documented
# ownership/integrity counts, not row contents.
METRICS=(
  "users|SELECT count(*) FROM users"
  "projects_total|SELECT count(*) FROM projects"
  "projects_unowned|SELECT count(*) FROM projects WHERE owner_id IS NULL"
  "analyses_total|SELECT count(*) FROM ai_analyses"
  "analyses_unowned|SELECT count(*) FROM ai_analyses WHERE owner_id IS NULL"
  "project_items|SELECT count(*) FROM project_items"
  "compounds_with_structure|SELECT count(*) FROM compounds WHERE m IS NOT NULL"
  # The per-user split is compared as one string: a restore that reassigns owners
  # could still match the totals above.
  "projects_per_user|SELECT coalesce(string_agg(x, '|' ORDER BY x), '') FROM (SELECT u.email || ':' || count(p.id) AS x FROM users u LEFT JOIN projects p ON p.owner_id = u.id GROUP BY u.email) s"
)

collect() { # collect <role> <database>  -> "label=value" lines on stdout
  local role="$1" database="$2" entry label sql
  for entry in "${METRICS[@]}"; do
    label="${entry%%|*}"
    sql="${entry#*|}"
    printf '%s=%s\n' "${label}" "$(db_psql "${role}" "${database}" "${sql}")"
  done
}

SOURCE_COUNTS=""
if [ "${REUSE}" -eq 0 ]; then
  say "-- source counts (before the dump)"
  SOURCE_COUNTS="$(collect "${ROLE}" "${DB}")"
  [ "${QUIET}" -eq 1 ] || echo "${SOURCE_COUNTS}" | sed 's/^/   /'

  DUMP_WAS_TEMPORARY=0
  if [ -z "${DUMP}" ]; then
    DUMP="$(mktemp -t spago-restore-check-XXXXXX.dump)"
    DUMP_WAS_TEMPORARY=1
  fi
  say "-- dumping ${DB} -> ${DUMP}"
  "${COMPOSE[@]}" exec -T db pg_dump -U "${ROLE}" -d "${DB}" -Fc > "${DUMP}"
  [ -s "${DUMP}" ] || fail "the dump is empty"

  say "-- creating scratch database ${SCRATCH}"
  # The app role may lack CREATEDB on a managed host; then the superuser does it.
  db_psql "${ROLE}" postgres "DROP DATABASE IF EXISTS ${SCRATCH}" \
    || db_psql "${SUPERUSER:-postgres}" postgres "DROP DATABASE IF EXISTS ${SCRATCH}"
  db_psql "${ROLE}" postgres "CREATE DATABASE ${SCRATCH}" \
    || db_psql "${SUPERUSER:-postgres}" postgres "CREATE DATABASE ${SCRATCH}" \
    || fail "cannot create ${SCRATCH}: neither ${ROLE} nor ${SUPERUSER:-postgres} has CREATEDB"

  # The rdkit extension needs superuser rights in most deployments; a fresh database
  # created by the app role cannot install it (runbook §H7 records this failure).
  say "-- creating the rdkit extension in ${SCRATCH}"
  if ! db_psql "${ROLE}" "${SCRATCH}" "CREATE EXTENSION IF NOT EXISTS rdkit" 2>/dev/null; then
    db_psql "${SUPERUSER:-postgres}" "${SCRATCH}" "CREATE EXTENSION IF NOT EXISTS rdkit" \
      || fail "cannot create extension rdkit in ${SCRATCH}; pass --superuser <role>"
    say "   (created as ${SUPERUSER:-postgres}: the app role is not a superuser)"
  fi

  say "-- restoring"
  # --no-owner: the restore runs as one role; --no-comments: COMMENT ON EXTENSION is
  # not permitted for a role that does not own it (both recorded in §H7).
  docker cp "${DUMP}" "$("${COMPOSE[@]}" ps -q db):/tmp/restore-check.dump" >/dev/null
  "${COMPOSE[@]}" exec -T db pg_restore -U "${ROLE}" -d "${SCRATCH}" \
    --no-owner --no-comments --exit-on-error /tmp/restore-check.dump \
    || fail "pg_restore reported an error"
  "${COMPOSE[@]}" exec -T db rm -f /tmp/restore-check.dump
else
  say "-- reusing the existing scratch database ${SCRATCH} (counts re-compared only)"
  SOURCE_COUNTS="$(collect "${ROLE}" "${DB}")"
  DUMP_WAS_TEMPORARY=0
fi

say "-- restored counts"
RESTORE_COUNTS="$(collect "${ROLE}" "${SCRATCH}")"
[ "${QUIET}" -eq 1 ] || echo "${RESTORE_COUNTS}" | sed 's/^/   /'

# --- compare ------------------------------------------------------------------------
mismatch=0
while IFS='=' read -r label value; do
  restored="$(echo "${RESTORE_COUNTS}" | awk -F= -v k="${label}" '$1 == k { sub(/^[^=]*=/, ""); print }')"
  if [ "${value}" != "${restored}" ]; then
    echo "MISMATCH ${label}: source='${value}' restored='${restored}'" >&2
    mismatch=1
  fi
done <<< "${SOURCE_COUNTS}"

# RDKit has to work in the restored database, not only hold the column values.
chemistry="$(db_psql "${ROLE}" "${SCRATCH}" "SELECT count(*) FROM compounds WHERE m @> 'c1ccccc1'::mol")"
say "-- RDKit substructure query in the restored database returned ${chemistry} row(s)"

if [ "${mismatch}" -ne 0 ]; then
  if [ "${KEEP}" -eq 0 ] && [ "${REUSE}" -eq 0 ]; then
    echo "   (scratch database ${SCRATCH} kept for inspection because the check failed)" >&2
    KEEP=1
  fi
  [ "${REUSE}" -eq 1 ] || say ""
  fail "ownership or integrity counts differ between source and restore"
fi

if [ "${KEEP}" -eq 1 ]; then
  say "-- keeping scratch database ${SCRATCH}${DUMP:+, dump ${DUMP}}"
else
  db_psql "${ROLE}" postgres "DROP DATABASE IF EXISTS ${SCRATCH}" \
    || db_psql "${SUPERUSER:-postgres}" postgres "DROP DATABASE IF EXISTS ${SCRATCH}"
  if [ -n "${DUMP}" ] && [ "${DUMP_WAS_TEMPORARY:-0}" -eq 1 ]; then rm -f "${DUMP}"; DUMP=""; fi
  say "-- scratch database dropped${DUMP:+, dump kept at ${DUMP}}"
fi

say "== restore rehearsal passed: ownership and integrity counts match =="
