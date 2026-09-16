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

### 2.1 Loading many families at once (B-01)

A screening set or a competitor's portfolio is a list, not a single case.
`scripts/corpus_batch.py` chunks that list, extracts and imports each chunk, and
keeps a resumable state file, so an interrupted run continues where it stopped
instead of re-downloading:

```bash
# my-patents.txt: one publication number per line (`#` comments allowed), or a
# CSV/TSV export with --column naming the field.
services/core/.venv/bin/python scripts/corpus_batch.py \
    --patents my-patents.txt --release 2026-09-08 \
    --workdir var/batch-2026-09-16 --per-package 20
```

What it guarantees, and what it does not:

- A chunk counts as done only when its import job reports `completed` against the
  database. A package written to disk is not chemistry in the corpus.
- At the end the **database** is asked which requested publications it holds
  (`spago_core.corpus_status` asks the same question): the run exits non-zero and
  prints every number that is not loaded, so a partial corpus cannot be mistaken
  for a complete one. `STATE.json` carries the same list under `missing`, plus
  `unfinished_chunks` and the captured error per failed chunk.
- A failed chunk can be re-run with `--retry-failed`; completed chunks are always
  skipped. `--dry-run` prints the plan without touching the network.
- It is sequential on purpose: SureChEMBL extraction is bandwidth-bound and the
  release index is the shared bottleneck. Run two workdirs in parallel only if the
  network is not the constraint.

### 2.2 What is loaded, and whether a list is covered

```bash
docker compose exec app python -m spago_core.corpus_status          # per-version table
docker compose exec app python -m spago_core.corpus_status --json > corpus-2026-09-16.json
docker compose exec app python -m spago_core.corpus_status --patents my-patents.txt
#   → exits 1 and prints every number that is NOT in the corpus
```

The same numbers are in the product: the top-bar dataset badge opens **Loaded
corpus** (`GET /api/v1/corpus`), which lists each dataset version with its counts,
its retrieval time, failed and interrupted import jobs, and which versions were
recorded per row by a source lookup rather than imported as a package. Counts are
read from the corpus tables on the request (measured 5.8–6.5 ms on the local
database, 1,907 bytes), so the view cannot disagree with the data it describes.

### 2.3 How far a source's data can be linked to a patent

Each target investigation records, per source, how every kept record's
source-declared document reference resolved — a patent number, a DOI, a PubMed id,
or one of the reasons none was attached (the document declares no identifier, the
source does not know the cited document, the lookup bound was reached, the lookup
failed, the record cites no document). The target header's **Source notes and
reference coverage** disclosure renders it next to the retrieval's own notes.

To measure it live on a deployed build, without writing anything to the database:

```bash
docker compose run --rm -v "$PWD/scripts:/app/scripts:ro" app \
    python /app/scripts/cohort_coverage.py TSLP CD40LG IL6 IL6R EGFR \
    --declarations --out - > benchmarks/reference-declarations-<date>.md
```

It reads the ChEMBL target ids each stored investigation used (so the measurement
covers the scope this deployment actually retrieved, not a freshly planned one),
calls the source, and reports per target: records returned, excluded, kept, and the
per-bucket counts. `--json` emits the machine record; `--max-activities` lowers the
per-target bound. It refuses to run together with `--investigate`, because a caller
must not be left thinking rows were written.

A bucket of `document_not_retrieved_bound` or `document_not_retrieved_failure` is a
fact about *this retrieval*: those compounds may well be patented, the lookup stopped
before it could say. Never read it as "no patent", and never add
`reference_counts` to `rejection_counts` — the first covers kept records, the second
covers records the source returned without a usable structure or value.

### 2.4 What a source declares for a publication (patent-led lookup)

`POST /api/v1/patents/{publication_number}/source-compounds` (the patent view's
**Ask ChEMBL what it declares** control) asks one source what it declares under a
publication number, whether or not the corpus holds that family. It writes only to
`patent_source_lookups` / `patent_source_compounds`; it never writes a
`compound_mentions` row, so it cannot change a family's compound count or appear as
evidence.

To run it without a browser and record the result:

```bash
SPAGO_DATABASE_URL=postgresql+psycopg://spago:spago@127.0.0.1:5432/spago \
services/core/.venv/bin/python scripts/patent_source_lookup.py \
    --patents US10508115 --json > benchmarks/patent-source-<number>-<date>.json
```

Read the exit code and the status word, not just the counts:

| Status | Means | What to do |
| --- | --- | --- |
| `complete` | The set was read whole. | Use it; the rule and the retrieval time are on the response. |
| `partial` | A document or activity bound was reached (20 documents / 500 records). | The set is the first slice, and the warning says which bound. Raise `--max-activities` if the document is bigger than the bound and the whole set is needed. |
| `empty` | The source was asked and knows no document under that number **for this rule**. | Nothing is wrong. It is a statement about this source, not about the patent. |
| `failed` | The source could not be asked. | Retry; the previously stored rows are still shown, with the time they came from. |
| `not_queried` | Nobody asked. | Not an answer. |

`--quiet` prints one line per publication (status, counts, rule) and the notes on
stderr, for a list of numbers in a batch: `--patents-file my-patents.txt`.

Two things to keep straight when reporting a set: a declared compound is **not** an
occurrence in this corpus, and the `N declared, M not usable` split is the honest
headline — the not-usable records were returned by the source and could not be
compared with a potency threshold (kinetic constants, values without a numeric
field, rows without a structure), which is different from "the source has nothing".

### 2.5 A set of literature rows as one bundle (B-25)

When an agent, a colleague or a script has produced a set of literature rows for a
target (a paper's table, a patent example, a supplementary file), they are handed
over as one `supplement-bundle-v1` JSON file and imported with:

```bash
curl -s -X POST "$SPAGO_BASE/api/v1/targets/$TARGET_ID/supplements/bundle" \
    -H 'Content-Type: application/json' \
    --data-binary @paper-rows.json | python3 -m json.tool
```

The file must state who produced it and what was searched:

```json
{
  "bundle_version": 1,
  "produced_by": "literature agent (web search, 2026-09-16)",
  "produced_by_kind": "agent",
  "searched": "PubMed 'CDK4 inhibitor IC50' + the paper's Table 2/3",
  "generated_at": "2026-09-16T09:00:00Z",
  "uniprot": "P11802",
  "records": [
    { "name": "compound 7", "smiles": "Nc1ncnc(Nc2ccccc2)c1", "ic50_nm": 10,
      "note": "Table 2, CDK4/cyclin D1 IC50; read 2026-09-16",
      "doi": "10.1016/s0960-894x(03)00203-8" }
  ]
}
```

What to expect, and what to check:

| `produced_by_kind` | Stored as | In the investigation? |
| --- | --- | --- |
| `human` | `user_curated` | yes, on arrival — identical to the one-row path |
| `agent` | `llm_inferred` | no — counted as `unreviewed_supplements` until confirmed |
| `external` | `machine_extracted` | no — as above |

- The reply's `report.outcomes` answers **every** record, including the refused ones
  with their reasons. `rejected > 0` is not a failure of the import: the rest of the
  file was stored. Fix the refused record and re-submit — a re-post updates the row,
  it does not duplicate it.
- Confirm a proposal only after reading the rows:
  `POST /api/v1/targets/{id}/supplement-imports/{import_id}/confirm`. That is the act
  that makes the rows part of the investigation (`user_curated` plus the candidates);
  it records who and when. Confirming twice answers "already confirmed" and changes
  nothing.
- `GET …/supplement-imports` reads the runs back, with each row's current state — so
  a row withdrawn since the import shows as withdrawn here too.
- A record with no `note`, with a contradictory value
  (`value` and `ic50_nm` disagreeing), or with an `inchikey` that disagrees with the
  structure SPAgo computed is refused rather than repaired. A stated `uniprot` that
  does not match the target refuses the whole file — that is the guard against
  importing an agent's file into the wrong investigation.
- Do not present an imported set as a literature review of the target: it is what
  this file claimed, with this producer, after this search string (`AGENTS.md` §11
  and §12). The verdict's `unreviewed_supplements` count is the honest state of the
  proposal before a person confirms it.

### 2.6 What is stored for a publication, and what nobody asked (B-26)

Four paths can contribute chemistry to one publication — the imported corpus, a
per-publication source lookup (B-24), target-led source rows (B-02) and hand-added
rows (B-25). The audit puts them side by side per publication and names what is
missing:

```bash
SPAGO_DATABASE_URL=postgresql+psycopg://spago:spago@127.0.0.1:5432/spago \
services/core/.venv/bin/python scripts/patent_coverage.py \
    --patents-file portfolio.txt --json > benchmarks/patent-coverage-<date>.json
```

It runs against the database directly (no HTTP) and **calls no source**: every leg is
a read of stored rows, so it costs no rate limit and needs no user action. Read the
per-row status and the `unqueried` list, not just the counts:

| Status | Means | What to do |
| --- | --- | --- |
| `corpus` | The imported corpus holds live mentions. | Nothing; open the document and read the table. |
| `declared` | A stored source lookup declares compounds for the number. | Check the retrieval time; re-ask if it is old or `failed`. |
| `supplement` | Confirmed hand-added rows cite it. | Nothing to fetch; read the rows in the target investigation. |
| `proposed` | Only unconfirmed proposals (a B-25 bundle) cite it. | Review the bundle and confirm it, or the row is not part of any investigation. |
| `empty` | No leg holds records, and at least one applicable leg **was** asked. | A stored answer, not a verdict that the patent has no compounds. |
| `failed` | Nothing found, and an asked leg did not complete. | Re-run that lookup; the row is not the whole picture. |
| `not_queried` | No applicable leg was ever asked. | Ask: `Ask ChEMBL what it declares` in the patent view, or a target-led retrieval. |

Exit code `1` means the operator has something to do: a publication nobody asked
about, or an ask that did not complete. A leg deliberately never asked on a row that
already holds records is a gap the report names, not a failure.

Two things the report says about itself, and neither should be dropped when quoting
it: the corpus leg can only report documents SPAgo *imported* (the true sibling set
needs a bibliographic source, B-22), and `not_queried` is never an absent verdict
(`AGENTS.md` §11). The UI surface is the *Coverage* strip in the patent view,
collapsed to one line; the same report is exported as Markdown or CSV from it.

### 2.7 Retrying one source without touching the others (B-06)

When one source of a target investigation failed or stopped at a bound, re-run **that
source alone**. It is the same endpoint as a full retrieval, with the source named:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/targets/discover \
  -H 'content-type: application/json' \
  -d '{"target_id": "<uuid>", "sources": ["bindingdb"]}' | jq '.sources[] | {source_name, status, records_kept, requested_in_run, retrieved_at}'
```

What it does: asks only the named source, writes only that source's retrieval row,
candidate rows and measurements. What it leaves alone: the other sources' stored
retrieval — status, counts and the `retrieved_at` that says *when those rows were
retrieved* — so a healthy source's rate limit is not spent and its rows are not
re-dated. Every row in the response carries `requested_in_run`, and a source that has
never been asked still reads `not_queried` (a fact, not an empty result). Naming no
source is refused with 422.

What it does **not** do, and must not be read as: retracting rows a source no longer
returns. A failed or bound-limited ask establishes no absence, so nothing is
retracted; whether a *complete* ask should retract the rows it no longer contains is
register item B-30, not implemented. A stored analysis is a snapshot and stays as it
is; the potency verdict is recomputed from the stored rows, so it does reflect the
retry. In the UI the control appears on the target header's failed/partial chip, with
that source's own last-run cost beside it.

### 2.8 Answering a target from a local BindingDB release (B-23)

On a workstation that holds a BindingDB dump, answer one target from the **whole
release** instead of the endpoint's bounded answer. This is operator work against
the database directly; there is no browser path to it (a multi-gigabyte scan inside
a request would violate `AGENTS.md` §21), and no source is contacted:

```bash
SPAGO_DATABASE_URL=postgresql+psycopg://spago:spago@127.0.0.1:5432/spago \
services/core/.venv/bin/python scripts/bindingdb_snapshot.py \
    --target IL6 \
    --file /path/to/BindingDB_All_2609.tsv \
    --json benchmarks/bindingdb-snapshot-<date>.json
```

What it spends: one pass over the file (≈113 s / 3.24 M rows / 8.98 GB on the
reference machine, ≈29 k rows/s), CPU and disk read only — no rate limit, no
network, no HTTP request. `--dry-run` does the same scan and writes nothing. The
target must already be stored (resolve it in the app first); the script never
resolves or invents one.

What it writes: ordinary measurement rows for that target, through the same
service the REST path uses, one source at a time — so ChEMBL and PubChem rows are
not re-asked or re-dated (B-06). Each row carries
`source_version=bindingdb-snapshot-tsv` and `dataset_version=bindingdb-snapshot:<release>`;
the retrieval row carries the search it actually ran (file name, release, sha256,
bytes, rows scanned, match mode) and is re-labelled by a snapshot run even when it
previously held the REST outcome. A re-run updates rows by the release's own record
ids instead of duplicating them.

What it decides, and the honest bounds:

- **Matching** is the reviewed UniProt accession first (every
  `UniProt … of Target Chain N` column), then `Target Name` exactly. `--name-mode
  auto` accepts a substring and is how a related protein's rows ("Interleukin-6
  receptor subunit alpha") enter the requested target's set — opt-in for that reason.
- **Organism** comes from the target's own row and rows stating another one are
  excluded and counted (`--all-organisms` keeps them, `--organism` overrides).
  A row whose organism cannot be compared is kept and reported as unverified.
- **Bounds** `--max-rows` / `--max-seconds` stop the scan; the result is stored as
  `partial`, says how far it read, and records **no** file digest, because a prefix
  is not a snapshot. Only a scan that reached the end records the digest and
  `complete`.
- A snapshot row is a `DATABASE_CURATED` fact about that file, not evidence that a
  compound occurs in a patent, and not a corpus occurrence (`AGENTS.md` §7/§10/§11).
  Exit codes: `0` completed or matched nothing (`empty`), `1` `failed`/`partial`,
  `2` refused before any scan (no such stored target, no such file, unknown mode).
- The measured shape and what it does not prove:
  `benchmarks/bindingdb-snapshot-2026-09-16.md`.

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

---

# Hosted deployment runbook (invited beta)

Scope: the ONLINE-03/04 shape — one app worker, HTTPS ingress, invitation-only
accounts, PostgreSQL private, bounded model usage. This section is separate from
the local runbook above because the security model is different: in local mode
there is one trusted user, and here there are several mutually untrusted ones.

Do not follow this section for a local install, and do not run the local shape
on a public interface.

## H1. Prerequisites and decisions to make first

| Decision | Why it must be made before deployment |
| --- | --- |
| Host and domain | Cookie `Secure` behaviour, CORS origins and the invitation link all depend on the public URL. |
| Model endpoint and model id | Recorded with every analysis; must be an endpoint you are authorized to bill. |
| Monthly token budget | The service refuses paid calls past `SPAGO_LLM_DEPLOYMENT_TOKEN_LIMIT`; the provider bill is not bounded by *that* number alone. |
| Invited cohort | Invitations are per-address; there is no signup. |
| Data privacy/retention | What may be sent to the model provider and how long usage rows are kept. |

Record the answers in the active plan before admitting users. Purchasing
infrastructure and public deployment are separate, explicit decisions.

## H2. Configuration

```bash
# Required for hosted mode
SPAGO_AUTH_MODE=required
SPAGO_COOKIE_SECURE=true                # HTTPS only
SPAGO_SEED_MODE=none                    # never ship the demo fixture to users
SPAGO_DATABASE_URL=postgresql+psycopg://<user>:<password>@<private-host>:5432/spago
SPAGO_CORS_ORIGINS=https://<your-domain>   # explicit origins, never "*"

# Model usage bounds (ONLINE-04)
SPAGO_LLM_BASE_URL=https://<endpoint-prefix>
SPAGO_LLM_MODEL=<model-id>
SPAGO_LLM_API_KEY=<secret>
SPAGO_LLM_USER_TOKEN_LIMIT=200000
SPAGO_LLM_DEPLOYMENT_TOKEN_LIMIT=2000000
SPAGO_LLM_QUOTA_WINDOW=month
# Optional: only if you know the price. Unset reports tokens without a currency figure.
#SPAGO_LLM_PRICE_PER_MILLION_TOKENS=
```

- Secrets are injected by the platform's secret mechanism, never baked into an
  image or committed. `.env` is for local development.
- `SPAGO_AUTH_MODE=required` plus `SPAGO_COOKIE_SECURE=false` is reported by
  `/api/v1/readyz` as a note; fix it before inviting anyone.
- The database must not have a public listener. Verify from outside: a
  connection attempt to the database port must fail.

### What the app does not do — the ingress duties

The app container is one worker behind whatever terminates HTTPS. These duties are the
proxy's or the platform's, and none of them is optional for a beta that will be used by
someone other than the operator:

| Duty | Why the app cannot cover it | What to configure |
| --- | --- | --- |
| TLS termination and certificate renewal | The app sets `Secure` cookies and never serves a certificate. | Your proxy or platform ingress, with a chain your users' browsers accept. |
| **Compression** | The app compresses its own responses (gzip, level 6, in the container), so this is no longer a blocking duty: the editor's first open transfers 5.2 MB instead of 20.3 MB (`benchmarks/asset-compression-2026-09-16.md`). | Optional further win: brotli at the proxy for `text/*`, `application/javascript`, `application/json` and the `.wasm`/`.data` editor assets. Do not double-encode — the app passes through a response that already carries `content-encoding`. |
| Connection and request limits, sign-in throttling | The service enforces model **token quotas** and nothing else; there is no per-IP or per-account rate limiting, and no sign-in attempt lockout. | Put a request rate limit in front. For a small invited cohort, record the decision not to and why. |
| Log retention and access control | The app writes operational logs to stdout. | Your platform's log pipeline. Never log cookies, API keys or model payloads. |
| Backup schedule | §H7 rehearses a restore; it does not schedule one. | A periodic `pg_dump` (or the platform's snapshot) plus the §H7 rehearsal after any change to the database shape. |

## H3. First deployment

```bash
docker compose build            # or your platform's equivalent
docker compose up -d
curl -fsS https://<domain>/healthz          # public, reveals nothing sensitive
```

Create the first administrator and an invitation (these are operator commands):

```bash
docker compose exec app python -m spago_core.admin invite you@example.org --base-url https://<domain>
# redeem the printed link once, then grant admin deliberately in SQL if needed:
#   UPDATE users SET is_admin = true WHERE email = 'you@example.org';
docker compose exec app python -m spago_core.admin users
```

`/api/v1/readyz` is the operational readiness check. It sits behind the session
gate because it reports configuration detail, so an operator account is needed:

```bash
curl -fsS -b cookies.txt https://<domain>/api/v1/readyz | jq
```

Expect `"status":"ready"` with `database`, `chemistry`, `migrations_applied`,
`rdkit_cartridge`, `model_quota_configured` all true, and read the `notes` array.

## H4. Inviting users, and revoking access

```bash
# Invite (prints the redeem link once; only the hash is stored afterwards)
docker compose exec app python -m spago_core.admin invite ada@example.org --base-url https://<domain>
# Cancel a pending invitation
docker compose exec app python -m spago_core.admin revoke-invitation <invitation-id>
# Sign a user out everywhere (lost laptop, offboarding)
docker compose exec app python -m spago_core.admin revoke-sessions ada@example.org
# Disable an account entirely
docker compose exec db psql -U spago -d spago -c \
  "UPDATE users SET disabled_at = now() WHERE email = 'ada@example.org';"
```

Session expiry is `SPAGO_SESSION_TTL_HOURS` (default 12). There is no refresh
token: an expired session means signing in again with a new invitation.

## H5. Migrating an existing local installation

Local projects have `owner_id IS NULL`, which hosted users **cannot** see. This
is deliberate: they must not be handed to whoever signs in first.

```bash
docker compose exec app python -m spago_core.admin legacy-projects
docker compose exec app python -m spago_core.admin assign-project <project-id> you@example.org
```

The command refuses to reassign a project that already has an owner. Review each
project individually; do not bulk-assign.

## H6. Model usage, cost and quotas

- Every paid call reserves budget before it is sent and records its real usage
  afterwards. A call that never settles keeps its reservation, so an interrupted
  request cannot silently free budget.
- `/api/v1/usage` shows the caller their own window and the deployment total.
  `/api/v1/usage/events` is administrator-only and lists operational rows:
  provider, model, scope, outcome, tokens, truncated error text. No provider
  payload and no credential is stored.
- What a user paid for stays readable: the **Analyses** button in the top bar
  lists their stored analyses (`GET /api/v1/analyses`), each with the model, the
  prompt version, the data version and the billed tokens. Opening one is a plain
  read — it never calls the provider — and each export carries that header with
  the text. A summary generated before the data or the potency policy moved is
  shown as out of date rather than silently re-served.
- If `SPAGO_LLM_PRICE_PER_MILLION_TOKENS` is unset, the report says no price is
  configured and reports tokens only. The provider invoice is authoritative in
  every case.
- Lowering a limit takes effect for the next request; it does not cancel a call
  already in flight.

## H7. Backup and restore

Same shape as the local runbook §3, with one addition: owned rows must survive a
restore *with their ownership*.

**The rehearsal is scripted.** `scripts/restore_check.sh` performs the whole procedure
below against the running compose stack and **fails loudly on any count mismatch** — it
is what §6 criterion 6 should be closed with:

```bash
scripts/restore_check.sh --project spago --env-file .env      # exits non-zero on mismatch
scripts/restore_check.sh ... --keep                            # keep the scratch DB + dump to inspect
```

It reads the role and database names from the running db container (so the rehearsal
cannot check a deployment different from the one that is up), records the source counts
before dumping, restores into a scratch database, compares users, projects
(owned/unowned), analyses, saved project items, compounds-with-structure and the per-user
project split, runs an RDKit substructure query in the restored database, and drops the
scratch database unless `--keep` is given. Stop the app container first (`docker compose
stop app`) if the deployment may receive writes while it runs: the comparison is honest
only for a source that is not changing.

The manual procedure below stays for a host where the database is not a compose service;
it is the same two pitfalls and the same counts.

```bash
docker compose exec db pg_dump -U spago -d spago -Fc > spago-$(date +%F).dump

# Restore into a fresh, isolated database and verify ownership survived.
# Two steps matter and are easy to get wrong (both found by a drill, see below):
#   1. the rdkit extension needs superuser rights, so create it first;
#   2. restoring as the non-superuser app role needs --no-comments, because
#      COMMENT ON EXTENSION is not permitted for a role that does not own it.
createdb -h <host> spago_restore
psql -h <host> -d spago_restore -c "CREATE EXTENSION IF NOT EXISTS rdkit;"   # as a superuser role
pg_restore -h <host> -U spago -d spago_restore --no-owner --no-comments spago-<date>.dump

# Ownership must match the source. Count both sides of the split:
psql -h <host> -d spago_restore -c \
  "SELECT count(*) FILTER (WHERE owner_id IS NULL) AS unowned, count(*) AS projects FROM projects;"
psql -h <host> -d spago_restore -c \
  "SELECT count(*) FILTER (WHERE owner_id IS NULL) AS unowned, count(*) AS analyses FROM ai_analyses;"
psql -h <host> -d spago_restore -c \
  "SELECT u.email, count(p.id) FROM users u LEFT JOIN projects p ON p.owner_id = u.id
   GROUP BY u.email ORDER BY u.email;"

# Chemistry must survive too. The RDKit column is named `m` (type `mol`), not
# `mol` — a query written against the wrong name fails, it does not silently
# pass. Counting non-NULL values proves the structures came across; a search
# proves RDKit itself works in the restored database:
psql -h <host> -d spago_restore -c \
  "SELECT count(*) AS with_structure, count(*) FILTER (WHERE m IS NULL) AS without FROM compounds;"
psql -h <host> -d spago_restore -c \
  "SELECT count(*) FROM compounds WHERE m @> 'c1ccccc1'::mol LIMIT 1;"
```

A restore that loses ownership would either hide everyone's work (all rows
unowned) or, worse, expose it. Never point a restored database at the production
app until the counts and the per-user split match the source.

### Drill log (2026-09-15; script re-run 2026-09-16)

Executed on the verification stack: two users, one project each with the same
name plus one unowned legacy project, one analysis per user, and the seeded
compound structures. Re-run on 2026-09-16 by `scripts/restore_check.sh` against the
hosted-shape rehearsal stack (3 users, 3 projects, 8 analyses, 2,639 structures), which
also verified the deliberate-mismatch path: after deleting one restored project the
script reported `MISMATCH projects_total: source='3' restored='2'` and the per-user
split, and exited 1.

| Check after restore | Result |
| --- | --- |
| `pg_restore` completion (app role, `--no-owner --no-comments`) | clean, no errors |
| projects | 3 total: 1 unowned (legacy) + 1 Ada + 1 Bob |
| analyses | 2 total, 0 unowned, 2 distinct owners |
| saved project items | 2 |
| compound rows with a non-NULL RDKit `m` value | 10 (chemistry intact; re-verified 2026-09-16 on the acceptance rehearsal's 2,639-row database) |

Findings from the drill, now reflected above:

- With `--exit-on-error` and without `--no-comments`, the restore aborts on
  `COMMENT ON EXTENSION rdkit` when run as the non-superuser app role. Piping
  `pg_restore` output through a tool that closes the pipe early can also make a
  partial restore look successful — check the exit status, not just the tail.
- The `rdkit` extension must exist before the restore; a fresh database created
  by the app role cannot create it.

## H8. Failure drills and what "healthy" means

| Failure | Expected behaviour | How to verify |
| --- | --- | --- |
| Model endpoint down | Search, evidence and target discovery keep working; summaries report a provider failure (502/504), never an empty success. The usage row is `failed` (transport), not `invalid_output` — no answer was read, so nothing was refused and nothing was billed. | `curl` the summary route with the endpoint pointed at a black hole. |
| Provider rate limit | 429 with `Retry-After` only when the endpoint supplied a usable value; never re-sampled automatically. | Point the endpoint at a stub returning 429. |
| Model answer rejected by validation (bad JSON, unknown fact ref) | One automatic re-sample of the identical request; if the second answer is rejected too, 502 with the validation reason and a usage row at outcome `invalid_output`. Token accounting sums both billed attempts. | Point the endpoint at `scripts/mock_llm_endpoint.py` with the model set to `mock-reject-twice` (the first two requests are refused on purpose). When SPAgo runs in a container, start the mock with `--host 0.0.0.0`; a loopback-only mock is unreachable from the container even though it answers `curl` on the host — that difference is itself the transport case above. |
| Database unavailable | `/healthz` reports `database: down`; API calls fail with 5xx rather than returning empty data. | Stop the db container. |
| External source down | The affected source's coverage row says `failed`; the rest of the investigation still returns. | Block the source's host. |
| Session expired mid-use | 401 on the next request; the UI returns to the sign-in view. | Delete the session row. |
| Container restart | Sessions survive (they are rows); in-flight model calls do not. | Restart the app container and reload. |

## H9. Latency and cost budget, before the beta

The last gate item in `docs/online-capability.md` §6 is "latency and cost targets for
the chosen host and model **defined, then measured**". This section is the worksheet:
the components that are already measured on this build, the two formulas, and the
blank table the operator fills in with the numbers their host and their provider
produce. Nothing here is a target until the operator writes one down; an unfilled row
is an open gate item, not a pass.

### What is already measured (this build)

| Component | Measured value | Where it comes from |
| --- | --- | --- |
| Patent lookup (stored corpus) | p50 2.1 ms, p95 2.7 ms | `benchmarks/online-baseline-2026-09-15.md` |
| Compounds page, evidence, depictions | p50 1.4–5.5 ms | same |
| Target reads (stored investigation) | p50 4.3 ms candidates, 5.4 ms measurements (200) | same |
| A live target investigation, five acceptance targets | 4.2 s (TSLP) · 4.5 s (IL-6R) · 6.4 s (CD40LG) · 20.0 s (IL-6) · 66.0 s (EGFR) — upstream request time, summed per source | `benchmarks/cohort-coverage-2026-09-16.json` |
| One ChEMBL activity page (200 records) | ~1.7–3 s, per page, and the page count is set by `max_activities` | `benchmarks/online00-chembl-projection-2026-09-16.md` |
| Scoped summary, model `deepseek-flash` | median call 3.6 s, 4,347 tokens for 2 calls (4,096-token output cap) | `benchmarks/online01-llm-eval-2026-09-16-sparse.md` |
| Structure editor, first open | ~7.7 MB dialog chunk + ~11.8 MB `.wasm`, fetched once per session; application bundle ~320 KB | `benchmarks/online08-structure-editor-2026-09-16.md` |

### Formula 1 — investigation wall time

An investigation is **not** an interactive read: it fans out to the live sources and
writes what it retrieves. Its wall time on the operator's host is

```
T_investigation ≈ T_resolve + T_bindingdb + T_chembl + T_pubchem + T_write
```

`T_resolve` is one UniProt lookup (sub-second when the accession resolves); the three
source terms are upstream and dominate; `T_write` is tens of milliseconds at the
cohort scale above. Each source term is a property of *that source's* load at that
moment, not of SPAgo — the recorded range for the same five targets across two runs on
two days was 0.7–50.9 s per source. Later reads of the same target are the stored-read
numbers above (milliseconds), because the investigation is persisted.

### Formula 2 — model cost and usage

The shipped accounting (`services/core/spago_core/services/usage.py`) is the only
cost formula this deployment has:

```
cost = deployment_tokens / 1_000_000 × SPAGO_LLM_PRICE_PER_MILLION_TOKENS
```

- `deployment_tokens` is measured: a request reserves an estimate before the call and
  records the provider's real usage after it. An interrupted call keeps its
  reservation, so the estimate errs upward, never downward.
- With no price configured, the report says so and reports tokens only. Do not put a
  price in this document — the operator's invoice is authoritative.
- Both limits (`SPAGO_LLM_USER_TOKEN_LIMIT`, `SPAGO_LLM_DEPLOYMENT_TOKEN_LIMIT`) must
  be non-zero before invitations go out; a refusal is a 429 that names the limit and
  the window. Check the spend with `curl -s <base>/api/v1/usage` (own window) and
  `curl -s <base>/api/v1/usage/events` (admin, per-call rows) — measured, not estimated.
- Summary scopes are cached separately, so a repeated summary of the same scope costs
  one call. A rejected model answer is re-sampled once, and both attempts are billed
  and counted.

### The operator's worksheet (fill in before the beta, keep with the acceptance run)

| Quantity | Target (operator) | Measured (operator) | How to measure |
| --- | --- | --- | --- |
| Patent lookup p95 | | | `benchmarks/run_benchmarks.py` against the deployed build |
| Compounds page p95 at the real corpus size | | | same, or the browser's own timings on a family of realistic size |
| A target investigation wall time, worst acceptance target | | | run `scripts/cohort_coverage.py <target> --investigate --yes` once and read `latency_ms` per source |
| First open of the structure dialog on a slow connection | | | devtools network tab, throttle to the target connection profile |
| Model calls per user session | | | count rows in `/api/v1/usage/events` for a rehearsal run |
| Tokens per session, and per month for the invited cohort | | | sum `total_tokens` over the same window; multiply by the expected number of sessions |
| Monthly spend | | | Formula 2 with the provider's price; compare with the deployment limit |
| Summary latency p95 | | | `/api/v1/usage/events` timestamps, or the browser's network tab |

Go/no-go: a target above the measured value is a decision to widen the host, lower
`max_activities` (knowing it narrows coverage), or change the model — written down
before the beta, not discovered during it. Record the filled table next to the
acceptance run (`docs/online-capability.md` §6) so the numbers belong to a build.

## H10. Explicit limits of this beta

- Single app worker. Multi-worker safety for the in-flight model-call registry is
  not claimed; use one worker.
- No password reset, no self-service signup, no team sharing, no SSO.
- A long-lived session is a long-lived session: there is no sliding refresh.
- `/api/v1/readyz` and the usage log are operator surfaces, not user features.
