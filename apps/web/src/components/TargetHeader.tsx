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
}: TargetHeaderProps) {
  if (!target) return null;
  const resolution = target.resolution;
  // Only reviewed ligand/receptor/signalling membership counts as a related
  // member; structural annotations stay out of this list.
  const related = target.components.filter(
    (c) => c.role && RELATED_MEMBER_ROLES.includes(c.role) && (c.gene_symbol || c.accession),
  );
  const queried = coverage.filter((c) => c.status !== "not_queried");
  const modality = discovery?.modality_counts ?? {};
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
        {queried.length > 0 && (
          <button className="btn btn-quiet" onClick={onDiscover} disabled={discovering}>
            {discovering ? "Refreshing…" : "Refresh sources"}
          </button>
        )}
        {coverage.length === 0 && (
          <button className="btn btn-primary" onClick={onDiscover} disabled={discovering}>
            {discovering ? "Querying open sources…" : "Query open sources"}
          </button>
        )}
      </div>

      {discoverError && (
        <div className="state-banner error" role="alert">
          <span>{discoverError}</span>
        </div>
      )}

      {discovery && (
        <p className="hint-note">
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
    </div>
  );
}

export function evidenceClassLabel(value: string): string {
  return EVIDENCE_LABEL[value] ?? value;
}

export function modalityLabel(value: string): string {
  return MODALITY_LABEL[value] ?? value;
}
