-- B-02: what happened to each kept record's document reference, per retrieval.
--
-- A measurement only links a compound to a patent if its source document was
-- resolved (`measurements.document_patent_number`, migration 0013). Whether that
-- resolution succeeded is a property of the *retrieval*, not of the measurement,
-- so the tally lives on `source_retrievals` next to `rejection_counts`:
--
--   patent_declared                the document declares a patent number
--   doi_only                       the document declares a DOI, no patent
--   pmid_only                      the document declares a PubMed id only
--   no_reference_on_document       the document was retrieved and declares none
--   no_reference_from_source       the source row carried no reference at all
--   document_unknown_to_source     the source does not know the cited document id
--   document_not_retrieved_bound   the configured lookup bound was reached first
--   document_not_retrieved_failure the lookup failed before this document
--   activity_without_document      the record cites no document
--
-- The buckets are disjoint over the *kept* records (the ones with a structure and
-- a numeric value), so `sum(reference_counts) = records_kept`. Records excluded for
-- a missing structure or value never reach document resolution and are counted in
-- `rejection_counts` instead; the two tallies describe different sets and must not
-- be added together. `{}` means "not recorded for this run" (a row written before
-- this migration), which is a third state and must never render as zero.
--
-- `source_declared_patents` is a *source declaration*; it is not evidence that the
-- compound occurs in that document in SPAgo's corpus (AGENTS.md §10/§11).
--
-- Forward-compatible: a defaulted column, no constraint on existing rows.

ALTER TABLE source_retrievals
    ADD COLUMN IF NOT EXISTS reference_counts jsonb NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN source_retrievals.reference_counts IS
    'Per-retrieval tally of how the source-declared document reference resolved, '
    'over the kept records: disjoint buckets (patent_declared, doi_only, pmid_only, '
    'no_reference_on_document, no_reference_from_source, document_unknown_to_source, '
    'document_not_retrieved_bound, document_not_retrieved_failure, '
    'activity_without_document). sum() = records_kept. Empty means not recorded.';
