-- ONLINE-06: patent/trial references declared by a source, per measurement.
--
-- ChEMBL's activity payload carries `document_chembl_id` only; the patent
-- number (when the document *is* a patent), DOI and PMID live on the document
-- record. Without them a discovered compound cannot be connected to a patent,
-- which is the central relation this product exists to make (AGENTS.md §1/§9).
--
-- The stored patent number is *normalized* (country + digits, kind code and
-- separators dropped) so it can be matched against a corpus value that uses a
-- different formatting. Normalization is lossy in exactly that way and is
-- documented in `spago_core/domain/patent_numbers.py`; the raw source string is
-- not rewritten anywhere, and every value here is labelled as source-declared
-- rather than corpus-verified.
--
-- Forward-compatible: nullable columns, no constraint on existing rows.

ALTER TABLE measurements ADD COLUMN IF NOT EXISTS document_patent_number text;
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS document_doi text;
ALTER TABLE measurements ADD COLUMN IF NOT EXISTS document_pmid text;

CREATE INDEX IF NOT EXISTS idx_measurements_document_patent
    ON measurements (document_patent_number);

COMMENT ON COLUMN measurements.document_patent_number IS
    'Publication number as declared by the source, normalized to country+digits. '
    'Source-declared: it is not proof that the compound occurs in that document in '
    'SPAgo''s corpus, and the UI must distinguish the two.';
COMMENT ON COLUMN measurements.document_doi IS
    'DOI of the source document, as declared by the source.';
COMMENT ON COLUMN measurements.document_pmid IS
    'PubMed identifier of the source document, as declared by the source.';
