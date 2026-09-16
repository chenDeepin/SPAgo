import type { DiscoverResponse, ResolvedTarget, SourceRetrieval } from "../api/types";

const STATUS_LABEL: Record<SourceRetrieval["status"], string> = {
  complete: "complete",
  partial: "partial",
  empty: "no records",
  failed: "source failed",
  not_queried: "not queried",
};

const STATUS_TITLE: Record<SourceRetrieval["status"], string> = {
  complete: "The source answered and every record it returned was processed.",
  partial:
    "The source answered but retrieval stopped at a configured bound, or part of it failed. The counts below cover what was retrieved.",
  empty:
    "The source answered and returned nothing for this scope. This is not evidence that no inhibitors exist.",
  failed:
    "The source did not answer. Nothing can be concluded about its coverage — this is not an empty result.",
  not_queried: "This source was not queried for this investigation.",
};

const RELATED_MEMBER_ROLES = ["ligand", "receptor", "signalling_component", "pathway"];

/** B-02: why a kept record does or does not carry a source-declared document
 * reference. The codes are the server's shared vocabulary
 * (`spago_core/domain/document_refs.py`); the labels are the reader's. */
const REFERENCE_STATUS_ORDER = [
  "patent_declared",
  "doi_only",
  "pmid_only",
  "no_reference_on_document",
  "no_reference_from_source",
  "document_unknown_to_source",
  "document_not_retrieved_bound",
  "document_not_retrieved_failure",
  "activity_without_document",
] as const;

const REFERENCE_STATUS_LABEL: Record<string, string> = {
  patent_declared: "with a source-declared patent",
  doi_only: "DOI only, no patent",
  pmid_only: "PubMed id only",
  no_reference_on_document: "the document declares no identifier",
  no_reference_from_source: "the source row carried no reference",
  document_unknown_to_source: "the source does not know the cited document",
  document_not_retrieved_bound: "the lookup bound was reached first",
  document_not_retrieved_failure: "the lookup failed before this document",
  activity_without_document: "the record cites no document",
};

/** The three buckets that mean "a reference was attached". */
const REFERENCE_FOUND = ["patent_declared", "doi_only", "pmid_only"];


/** DOM id of the coverage chip for one source. A `source:<name>` citation and
 * the chip share this one convention, so the citation click can focus the
 * record it refers to without a second lookup table. */
export function coverageChipId(sourceName: string): string {
  return `coverage-source-${sourceName}`;
}

/** DOM id of the potency reference verdict strip. A `reference:<target-id>`
 * citation (ONLINE-06) points here: the verdict is what that citation supports,
 * so the click scrolls to the strip and flashes it rather than switching tabs. */
export const REFERENCE_VERDICT_ID = "target-reference-verdict";

const EVIDENCE_LABEL: Record<string, string> = {
  measured_direct_binding: "measured binding",
  interaction_disruption: "interaction disruption",
  functional_effect: "functional effect",
  screening_assay: "screening assay",
  computational_prediction: "predicted",
  unspecified: "class unspecified",
};

const MODALITY_LABEL: Record<string, string> = {
  small_molecule: "small molecule",
  peptide: "peptide",
  oligonucleotide: "oligonucleotide",
  biologic: "biologic",
  unclassified: "unclassified",
  unparseable: "unparseable",
};

interface TargetHeaderProps {
  target: ResolvedTarget | null;
  coverage: SourceRetrieval[];
  discovery: DiscoverResponse | null;
  discovering: boolean;
  discoverError: string | null;
  onDiscover: () => void;
  onOpenRelated: (query: string) => void;
  /** Source whose coverage chip an AI citation asked for. The chip is focused
   * (scrolled to and flashed) so a `source:` citation lands on the record it
   * refers to instead of a dead control. */
  focusedSource?: string | null;
  /** B-06: re-run one source. Offered only for a chip whose stored outcome is a
   * recovery case (`failed` / `partial`), because there the all-source refresh
   * re-spends the healthy sources for nothing. */
  onRetrySource?: (sourceName: string) => void;
  /** The source a retry is running for right now, so the strip shows which one
   * and stays inert for the others. */
  retryingSource?: string | null;
  /** What the last run did, when it asked a subset — the run's own numbers, so a
   * partial run is never read as a full one. */
  discoverNote?: string | null;
}

/** B-06: the last run's own cost for one source. Stored facts, not an estimate:
 * the reader is deciding what a retry will spend, and the only honest number for
 * that is what it spent last time. */
function lastRunCost(entry: SourceRetrieval): string {
  const pages = entry.pages_fetched === 1 ? "1 page" : `${entry.pages_fetched} pages`;
  const seen = `${entry.records_seen} record${entry.records_seen === 1 ? "" : "s"} seen`;
  const wall = entry.latency_ms == null ? "wall time not recorded" : `${(entry.latency_ms / 1000).toFixed(1)} s`;
  const when = entry.retrieved_at ? new Date(entry.retrieved_at).toLocaleString() : "time not recorded";
  return `last run ${when} · ${pages} · ${seen} · ${wall}`;
}

/** Target scope header: what was resolved, which related partners exist, and
 * per-source retrieval outcomes.
 *
 * The coverage strip is the honest part of this surface: an empty source and a
 * failed source are labelled differently, and no count is presented as proof
 * that inhibitors do or do not exist. */
export function TargetHeader({
  target,
  coverage,
  discovery,
  discovering,
  discoverError,
  onDiscover,
  onOpenRelated,
  focusedSource = null,
  onRetrySource,
  retryingSource = null,
  discoverNote = null,
}: TargetHeaderProps) {
  if (!target) return null;
  const resolution = target.resolution;
  // Only reviewed ligand/receptor/signalling membership counts as a related
  // member; structural annotations stay out of this list.
  const related = target.components.filter(
    (c) => c.role && RELATED_MEMBER_ROLES.includes(c.role) && (c.gene_symbol || c.accession),
  );
  const queried = coverage.filter((c) => c.status !== "not_queried");
  // B-06: a source whose own ask failed (or stopped at a bound) is the case a
  // scoped re-run exists for; the others have nothing to recover.
  const retryable = onRetrySource
    ? coverage.filter((c) => c.status === "failed" || c.status === "partial")
    : [];
  const busiest = retryingSource !== null;
  const modality = discovery?.modality_counts ?? {};
  // B-06: a run that asked a subset reports that run's own numbers. The line says
  // which sources it speaks for, so a one-source retry cannot be read as the
  // target's totals.
  const runScope = (discovery?.sources ?? [])
    .filter((entry) => entry.requested_in_run !== false)
    .map((entry) => entry.source_name);
  const partialRun = (discovery?.sources ?? []).some((entry) => entry.requested_in_run === false);
  const small = (modality.small_molecule ?? 0) + (modality.unclassified ?? 0);
  const otherModalities = Object.entries(modality).filter(
    ([key]) => key !== "small_molecule" && key !== "unclassified",
  );

  return (
    <div className="target-header">
      <div className="target-title">
        <h2>
          {target.name ?? target.target_key}{" "}
          <span className="mono target-accession">{target.uniprot_accession ?? "no accession"}</span>
        </h2>
        <span className="scope-note">
          {[target.organism, target.target_key, target.scope_kind, target.target_type]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </div>

      {related.length > 0 && (
        <p className="hint-note">
          Related members of the same system are offered explicitly and kept distinct from the
          requested target:{" "}
          {related.map((c, index) => (
            <span key={c.accession ?? index}>
              {index > 0 && ", "}
              <button
                className="evidence-link"
                onClick={() => onOpenRelated(c.gene_symbol ?? c.accession ?? "")}
                title={c.name ?? ""}
              >
                {c.gene_symbol ?? c.accession} ({c.role})
              </button>
            </span>
          ))}
          .
        </p>
      )}

      {resolution && resolution.notes.length > 0 && (
        <details className="target-notes">
          <summary>Resolution provenance ({resolution.notes.length} notes)</summary>
          <ul>
            {resolution.notes.map((note, index) => (
              <li key={index}>{note}</li>
            ))}
          </ul>
          <p className="fineprint">
            Source {resolution.source_name}
            {resolution.source_version ? ` · ${resolution.source_version}` : ""} ·{" "}
            {resolution.retrieved_at
              ? `retrieved ${new Date(resolution.retrieved_at).toLocaleString()}`
              : "retrieval time not recorded"}
            . Excluded alternatives are recorded with the resolution, not discarded.
          </p>
          {resolution.excluded.length > 0 && (
            <ul>
              {resolution.excluded.map((candidate) => (
                <li key={candidate.identifier}>
                  excluded {candidate.identifier} {candidate.name ?? ""} — {candidate.reason}
                </li>
              ))}
            </ul>
          )}
        </details>
      )}

      <div className="coverage-strip" role="list" aria-label="Source coverage">
        {coverage.length === 0 && (
          <span className="not-provided">No retrieval has been run for this target yet.</span>
        )}
        {coverage.map((entry) => (
          <span
            key={entry.source_name}
            id={coverageChipId(entry.source_name)}
            role="listitem"
            className={
              `coverage-chip coverage-${entry.status}` +
              (focusedSource === entry.source_name ? " coverage-chip-focused" : "")
            }
            title={STATUS_TITLE[entry.status]}
          >
            <strong>{entry.source_name}</strong> {STATUS_LABEL[entry.status]}
            {entry.records_kept > 0 && ` · ${entry.records_kept} kept`}
            {entry.records_excluded > 0 && ` · ${entry.records_excluded} not qualifying`}
            {entry.records_seen === 0 && entry.status === "complete" && " · 0 records"}
          </span>
        ))}
        {retryable.map((entry) => (
          <button
            key={`retry-${entry.source_name}`}
            className="btn btn-quiet coverage-retry"
            onClick={() => onRetrySource?.(entry.source_name)}
            disabled={busiest || discovering}
            title={
              `Ask ${entry.source_name} again, and only ${entry.source_name}: the other ` +
              `sources' stored outcomes are left as they are. ${lastRunCost(entry)}.`
            }
          >
            {retryingSource === entry.source_name
              ? `Retrying ${entry.source_name}…`
              : `Retry ${entry.source_name}`}
          </button>
        ))}
        {queried.length > 0 && (
          <button className="btn btn-quiet" onClick={onDiscover} disabled={discovering || busiest}>
            {discovering ? "Refreshing…" : "Refresh sources"}
          </button>
        )}
        {coverage.length === 0 && (
          <button className="btn btn-primary" onClick={onDiscover} disabled={discovering}>
            {discovering ? "Querying open sources…" : "Query open sources"}
          </button>
        )}
      </div>

      {retryable.length > 0 && (
        <p className="fineprint coverage-cost">
          A retry asks only that source and rewrites only its stored outcome; the others are not
          asked again and their rows keep their own retrieval time. What it will spend, from that
          source's own last run:{" "}
          {retryable.map((entry) => `${entry.source_name} — ${lastRunCost(entry)}`).join(" · ")}.
        </p>
      )}

      {discoverNote && <p className="fineprint coverage-note" role="status">{discoverNote}</p>}

      {discoverError && (
        <div className="state-banner error" role="alert">
          <span>{discoverError}</span>
        </div>
      )}

      {discovery && (
        <p className="hint-note">
          {partialRun && (
            <>
              Last run asked {runScope.join(", ") || "no source"} only, so these are that run's
              numbers.{" "}
            </>
          )}
          Candidate focus: <strong>{small}</strong> small-molecule / unclassified
          {otherModalities.length > 0 && (
            <>
              {" · labelled separately: "}
              {otherModalities.map(([key, count], index) => (
                <span key={key}>
                  {index > 0 && ", "}
                  {count} {MODALITY_LABEL[key] ?? key}
                </span>
              ))}
            </>
          )}
          {". "}
          {discovery.coverage_note}
        </p>
      )}

      {/* B-02: what the retrieval could and could not link to a document, and the
          source notes that used to be stored and never shown. A retrieval whose
          lookup bound was reached says so here instead of leaving the reader to
          read "no patent mapping" as a fact about the compound. */}
      {(coverage.some((entry) => Object.keys(entry.reference_counts ?? {}).length > 0) ||
        coverage.some((entry) => (entry.warnings ?? []).length > 0)) && (
        <details className="target-notes">
          <summary>Source notes and reference coverage</summary>
          {coverage.map((entry) => {
            const counts = entry.reference_counts ?? {};
            const recorded = Object.keys(counts).length > 0;
            const linked = REFERENCE_FOUND.reduce((total, key) => total + (counts[key] ?? 0), 0);
            // Three different states, said differently: records were tallied,
            // there were no records to tally, or the run predates the tally (a
            // stored row from before migration 0016). None of them is "zero
            // references declared".
            const coverageLine = recorded
              ? `${linked} linked to a document`
              : entry.records_kept === 0
                ? "no kept record to resolve a reference for"
                : "reference coverage not recorded for this run (it predates the tally; that is not zero)";
            return (
              <div key={entry.source_name} className="reference-coverage">
                <p className="fineprint">
                  <strong>{entry.source_name}</strong> · {entry.records_kept} kept record
                  {entry.records_kept === 1 ? "" : "s"} · {coverageLine}
                </p>
                {recorded && (
                  <ul>
                    {REFERENCE_STATUS_ORDER.filter((status) => (counts[status] ?? 0) > 0).map(
                      (status) => (
                        <li key={status}>
                          {counts[status]} {REFERENCE_STATUS_LABEL[status] ?? status}
                        </li>
                      ),
                    )}
                  </ul>
                )}
                {(entry.warnings ?? []).length > 0 && (
                  <details>
                    <summary>{entry.warnings.length} source note(s)</summary>
                    <ul>
                      {entry.warnings.map((warning, index) => (
                        <li key={index}>{warning}</li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            );
          })}
          <p className="fineprint">
            A document reference is what the source declared, not proof that the compound occurs
            in that document; the candidate table keeps the two apart.
          </p>
        </details>
      )}
    </div>
  );
}

export function evidenceClassLabel(value: string): string {
  return EVIDENCE_LABEL[value] ?? value;
}

export function modalityLabel(value: string): string {
  return MODALITY_LABEL[value] ?? value;
}
