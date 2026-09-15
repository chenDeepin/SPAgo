# SPAgo operations runbook (local single-user deployment)

Scope: the supported deployment shape — one machine, one user, one app worker
(`docker compose`), loopback-bound ports. Multi-user/LAN hosting additionally
requires PROD-08 (authentication, project authorization) and is **not** covered
by this runbook.

## 1. Clean install

```bash
git clone <repository> && cd spago
docker compose up -d --build
# app: http://127.0.0.1:8000 (loopback by default)
```

- The app container applies migrations and (with the default
  `SPAGO_SEED_MODE=demo`) loads the synthetic demo fixture so the UI works
  immediately. Demo data is labeled as demo everywhere.
- Default port bindings are loopback-only: app `127.0.0.1:8000`, database
  `127.0.0.1:5432` (`SPAGO_APP_BIND` / `SPAGO_DB_BIND` / ports in `.env`).
  Exposing either to a LAN is an explicit operator decision; change the demo
  `POSTGRES_PASSWORD` first (see §6).
- Verify: `curl -s localhost:8000/healthz` → `"status":"ok"`; the top bar shows
  the loaded dataset.

## 2. Loading real patent data (SureChEMBL extract)

Real chemistry comes from the official SureChEMBL bulk data (EMBL-EBI FTP,
CC BY 4.0, Parquet). SPAgo extracts only the rows of the patent families you
name using remote Parquet range reads. Transfer cost depends on row-group
statistics and network performance; this is not a fixed download-size guarantee.

```bash
# 1) Extract a family package (run once per case; needs network, ~5–15 min).
#    Uses the app container; no host Python/RDKit/DuckDB setup is needed.
mkdir -p local
docker compose run --rm --no-deps -v "$PWD/local:/import" app \
    python /app/scripts/extract_surechembl.py \
    --release 2026-09-08 --patent US-5153197-A --out /import/pkg-losartan

# 2) Import it (idempotent; records a durable import job with checksums):
docker compose run --rm -v "$PWD/local:/import" app \
    python -m spago_core.import_package /import/pkg-losartan
```

Practical notes:

- Use an explicit dated release and a new, empty output directory. Extraction
  and package validation cap each table at 100,000 rows. A failed extraction
  does not publish a manifest; retry into a fresh directory.
- Source refresh currently upserts records; it does not retract mappings that
  disappear or become invalid. Do not treat it as a complete release replacement.
  Interrupted imports can remain `running`; automatic cancellation/recovery is
  not implemented. Retain packages and inspect job/error records before retrying.

- `--patent` takes the SureChEMBL number format (`US-5153197-A`). All family
  documents are included automatically. Numbers not covered by the release
  fail loudly — "not covered" is never served as "no chemistry".
- Real-source deployments should set `SPAGO_SEED_MODE=none` in `.env` so the
  demo fixture is never mixed into a real dataset at restart.
- Re-importing the same package updates rows in place (identity is
  InChIKey/family-key based) and never duplicates. Import state, file
  checksums, and issues are queryable in `import_jobs` / `ingestion_issues`.
- The bulk extract has no page numbers and no patent-local labels; SPAgo
  shows "not provided" for those instead of inventing positions. Every
  evidence record links to the Espacenet publication page for manual
  verification (SPAgo never automates or scrapes Espacenet).

## 3. Backup

Backs up everything scientific: projects, saved items, evidence, source
versions, import jobs, analyses. Depiction SVGs are a rebuildable cache and
are not backed up.

```bash
set -euo pipefail
umask 077
mkdir -p backups
SPAGO_BACKUP_FILE="backups/spago-$(date +%Y%m%d-%H%M%S).dump"
docker compose exec -T db sh -c \
    'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
    > "${SPAGO_BACKUP_FILE}.partial"
docker compose exec -T db pg_restore --list < "${SPAGO_BACKUP_FILE}.partial" > /dev/null
mv "${SPAGO_BACKUP_FILE}.partial" "$SPAGO_BACKUP_FILE"
```

Only a successful dump with a readable archive listing receives the `.dump`
name. This checks the archive format; a restore drill is still required to
prove recovery. Keep failed `.partial` files separate from usable backups.
The database name and role come from the container configuration, including
custom `POSTGRES_DB` / `POSTGRES_USER` values.

Keep a copy of any imported source packages (`local/pkg-*`) next to the
backup: they are the re-importable external evidence files, with checksums
recorded in `import_jobs.files`.

## 4. Restore

Restore into a **new database**, keeping the original database and volume.
Use the same `POSTGRES_USER` as when the backup was taken: the archive retains
its original object owners. The container's local `postgres` superuser restores
the RDKit extension and object ownership; no host sudo or password output is
needed. Do not restore an archive from an untrusted source as a superuser.

```bash
set -euo pipefail
SPAGO_BACKUP_FILE='backups/replace-with-your-backup.dump'
SPAGO_RESTORE_DB="spago_restore_$(date +%Y%m%d_%H%M%S)"
test -s "$SPAGO_BACKUP_FILE"
docker compose up -d --wait db
docker compose exec -T db pg_restore --list < "$SPAGO_BACKUP_FILE" > /dev/null
docker compose stop app
docker compose exec -T -e SPAGO_RESTORE_DB="$SPAGO_RESTORE_DB" db sh -c \
    'exec psql -X -v ON_ERROR_STOP=1 -U postgres -d postgres \
      -v restore_db="$SPAGO_RESTORE_DB" -v app_role="$POSTGRES_USER"' <<'SQL'
CREATE DATABASE :"restore_db" OWNER :"app_role";
SQL
docker compose exec -T -e SPAGO_RESTORE_DB="$SPAGO_RESTORE_DB" db sh -c \
    'exec pg_restore --exit-on-error --single-transaction -U postgres -d "$SPAGO_RESTORE_DB"' \
    < "$SPAGO_BACKUP_FILE"
docker compose exec -T -e SPAGO_RESTORE_DB="$SPAGO_RESTORE_DB" db sh -c \
    'exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$SPAGO_RESTORE_DB"' <<'SQL'
SELECT extname, extversion FROM pg_extension WHERE extname = 'rdkit';
SELECT version FROM schema_migrations ORDER BY version;
SELECT count(*) AS projects FROM projects;
SELECT count(*) AS saved_items FROM project_items;
SELECT count(*) AS evidence_records FROM evidence_records;
SELECT count(*) AS analyses FROM ai_analyses;
SQL
printf 'Restored database: %s\n' "$SPAGO_RESTORE_DB"
```

If any command fails, leave the app stopped and investigate; do not treat
restore errors as benign. The original database remains available. Compare
the restored counts and representative project items, evidence references,
source versions and analyses with the backup's recorded pre-restore state.
Older backups must be inspected against their own schema version.

Only after those checks pass, set `POSTGRES_DB` in `.env` to the printed
restored database name, preserving `POSTGRES_USER`, password and the intended
`SPAGO_SEED_MODE` (`none` for real-only data). Ensure an exported `POSTGRES_DB`
does not override `.env`. Then switch the containers to that database:

```bash
docker compose up -d --force-recreate --wait db app
curl -fsS localhost:8000/healthz     # status ok, rdkit_cartridge installed
```

Reopen the saved project in the browser and verify its expected items and
evidence before retiring the original database. If switching fails, restore
the previous `POSTGRES_DB` configuration and recreate the containers; the
original database has not been deleted.

To rebuild from scratch instead (⚠ deletes all projects/analyses):

```bash
docker compose down -v && docker compose up -d --build
```

## 5. Upgrade

Take and validate a backup (§3) before changing versions; retain the previous
version and configuration so §4 can be used for rollback.

```bash
git fetch && git checkout <new version>
docker compose build
docker compose up -d          # app applies forward migrations at startup
```

- Migrations are forward-only. A supported upgrade path was drilled by
  starting a stack on the previous release with data, then switching to the
  new image: projects and saved items survived, schema advanced
  (see the plan record for the drill log).
- Rollback = restore the backup taken before upgrading (§3/§4). There is no
  automatic downgrade.

## 6. Security boundaries of this deployment shape

- Both published ports bind to loopback by default. The database is a private
  component; do not expose it without changing the demo credentials
  (`POSTGRES_PASSWORD` in `.env`). Recreate the db/app **containers while
  preserving the volume** with `docker compose up -d --force-recreate --wait db app`:
  the database entrypoint updates the application role's password on startup.
  Check both container health and `curl -fsS localhost:8000/healthz` afterwards.
  Do not use `docker compose down -v` to change a password; it deletes stored data.
- No authentication exists in the app. Anyone who can reach the app port can
  read/write projects and (if configured) trigger paid model calls. Keep the
  loopback binding when an LLM key is configured.
- LLM keys live in `.env` (never committed); the app never returns them.
