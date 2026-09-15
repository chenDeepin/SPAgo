-- Defect round 2026-09-16: what counts as current evidence in an investigation.
--
-- Two defects share one cause: a row that exists is not the same fact as a row
-- that still holds.
--
-- 1. **Investigation scope.** `target_candidates` links a compound to the target
--    the user investigated. A retrieval may attach a measurement to a *different*
--    target row — the interaction/complex record it was retrieved through
--    (`_assay_target_row`), because a protein–protein interaction is a different
--    scientific object from the protein. Every target-scoped read, however,
--    joined measurements to candidates **by compound**, so any measurement of
--    that compound against any target (a cyclooxygenase IC50 for a compound that
--    happens to occur in the corpus, say) was counted in this target's verdict,
--    drawer, counts, AI totals and export. `target_relations` records which
--    objects a retrieval actually went through, and
--    `investigation_measurements` states the scope rule once.
--
-- 2. **Retraction.** A hand-added row could not be withdrawn, and a source
--    refresh could not retract a mapping the new release no longer contains.
--    Both are the same fact — "this row was current, it is not any more" — so
--    both use `retracted_at` / `retracted_reason`, and the current-state views
--    below exclude retracted rows. Nothing is deleted: the row keeps its
--    provenance, and the count of withdrawn rows is reported to the reader
--    instead of a row disappearing silently (AGENTS.md §9/§10).
--
-- Note for later migrations: `investigation_measurements` and
-- `current_measurements` expose `m.*`, so a new column on `measurements` does
-- **not** appear through them until the view is recreated (the same holds for
-- the mention/evidence views). `tests/test_investigation_scope.py` fails when
-- that happens, on purpose.
--
-- Forward-compatible: new table, new nullable columns, new views; no existing
-- row changes meaning.

-- --- 1. Retraction columns ----------------------------------------------------

-- A measurement the user added by hand, or a source row a refresh no longer
-- holds. The reason is mandatory at the API level: "why is this gone" is part of
-- the record, not a UI detail.
ALTER TABLE measurements
    ADD COLUMN IF NOT EXISTS retracted_at timestamptz,
    ADD COLUMN IF NOT EXISTS retracted_reason text;

-- Candidate membership is per investigation, so withdrawing the last live
-- measurement of a hand-added compound takes the candidate row out of the
-- investigation too (the compound itself stays, with its other evidence).
ALTER TABLE target_candidates
    ADD COLUMN IF NOT EXISTS retracted_at timestamptz,
    ADD COLUMN IF NOT EXISTS retracted_reason text;

ALTER TABLE target_supplement_remarks
    ADD COLUMN IF NOT EXISTS retracted_at timestamptz,
    ADD COLUMN IF NOT EXISTS retracted_reason text;

-- Patent side: a refresh of a family can drop a compound occurrence or an
-- evidence record. Retracting keeps the occurrence readable as history.
ALTER TABLE compound_mentions
    ADD COLUMN IF NOT EXISTS retracted_at timestamptz,
    ADD COLUMN IF NOT EXISTS retracted_reason text,
    ADD COLUMN IF NOT EXISTS retracted_by_dataset_version text;

ALTER TABLE evidence_records
    ADD COLUMN IF NOT EXISTS retracted_at timestamptz,
    ADD COLUMN IF NOT EXISTS retracted_reason text,
    ADD COLUMN IF NOT EXISTS retracted_by_dataset_version text;

CREATE INDEX IF NOT EXISTS idx_measurements_current
    ON measurements(compound_id) WHERE retracted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_mentions_current
    ON compound_mentions(document_id) WHERE retracted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_evidence_current
    ON evidence_records(compound_id) WHERE retracted_at IS NULL;

-- The current corpus, stated once. Reads that answer "what does the corpus hold
-- now" go through these; reads that answer "what did a release contain" or count
-- ingestion bookkeeping keep reading the base tables.
CREATE OR REPLACE VIEW current_compound_mentions AS
SELECT * FROM compound_mentions WHERE retracted_at IS NULL;

CREATE OR REPLACE VIEW current_evidence_records AS
SELECT * FROM evidence_records WHERE retracted_at IS NULL;

CREATE OR REPLACE VIEW current_measurements AS
SELECT * FROM measurements WHERE retracted_at IS NULL;

COMMENT ON VIEW current_compound_mentions IS
    'Compound occurrences the loaded corpus currently holds (retracted ones excluded).';
COMMENT ON VIEW current_evidence_records IS
    'Evidence records the loaded corpus currently holds (retracted ones excluded).';
COMMENT ON VIEW current_measurements IS
    'Measurements that still hold: a withdrawn hand-added row or a retracted source row is excluded.';

-- --- 2. Which targets one investigation retrieved measurements through ---------

CREATE TABLE IF NOT EXISTS target_relations (
    -- The target the user investigated.
    target_id         uuid NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    -- The object the source measured (an interaction/complex record, typically).
    related_target_id uuid NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    relation          text NOT NULL CHECK (relation IN ('interaction_record_of')),
    source_name       text NOT NULL,
    -- The source's own identifier for the related object, for traceability.
    source_key        text,
    note              text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (target_id, related_target_id, relation)
);

CREATE INDEX IF NOT EXISTS idx_target_relations_related
    ON target_relations(related_target_id);

COMMENT ON TABLE target_relations IS
    'Targets whose measurements belong to another target''s investigation, and why.';

-- One statement of the scope rule. A measurement is in scope for an
-- investigation when its assay belongs to the investigated target itself, or to
-- an object that investigation retrieved through (an interaction/complex record
-- of the same protein). `retracted_at` on the candidate or the measurement takes
-- the row out of the current set without deleting it.
--
-- DISTINCT matters: one compound has a candidate row per source record, so a
-- plain join would return the same measurement once per candidate row and every
-- `count(*)` through this view would over-count.
CREATE OR REPLACE VIEW investigation_measurements AS
SELECT DISTINCT tc.target_id AS investigation_target_id,
       m.*
FROM target_candidates tc
JOIN measurements m ON m.compound_id = tc.compound_id
JOIN assays a ON a.id = m.assay_id
LEFT JOIN target_relations r ON r.related_target_id = a.target_id
WHERE tc.retracted_at IS NULL
  AND m.retracted_at IS NULL
  AND (a.target_id = tc.target_id OR r.target_id = tc.target_id);

COMMENT ON VIEW investigation_measurements IS
    'Measurements in one target investigation''s scope: the investigated target plus the '
    'interaction/complex targets that investigation retrieved through, minus retracted rows.';

-- --- 3. Attribution repair: BindingDB's source-local target key -----------------

-- BindingDB labels every record with `bindingdb:<accession>`. The persistence
-- path used to turn that into its own target row, so measurements retrieved *for*
-- this accession hung off a pseudo-target and fell outside the investigation they
-- were retrieved for once the scope rule above applied. The retrieval was for the
-- investigated target, so re-point the assay. Every measurement row, its
-- provenance and its document reference are untouched; only the object it is
-- attributed to changes, to the one that actually holds the accession.
UPDATE assays
   SET target_id = fixed.primary_target_id
  FROM (
        SELECT a.id AS assay_id,
               (SELECT t2.id FROM targets t2
                 WHERE t2.uniprot_accession = split_part(t1.target_key, ':', 2)
                 ORDER BY t2.id LIMIT 1) AS primary_target_id
          FROM assays a
          JOIN targets t1 ON t1.id = a.target_id
         WHERE t1.target_key LIKE 'bindingdb:%'
           AND split_part(t1.target_key, ':', 2) <> ''
       ) fixed
 WHERE assays.id = fixed.assay_id
   AND fixed.primary_target_id IS NOT NULL
   AND assays.target_id <> fixed.primary_target_id;

-- --- 4. An import that died is a state of its own -----------------------------

-- A killed import left `running` forever, which reads as "in progress" rather
-- than "we do not know what it wrote" (AGENTS.md §22).
ALTER TABLE import_jobs DROP CONSTRAINT IF EXISTS import_jobs_status_check;
ALTER TABLE import_jobs ADD CONSTRAINT import_jobs_status_check
    CHECK (status IN ('queued','running','completed','failed','interrupted'));
