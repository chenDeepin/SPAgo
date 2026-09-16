import { useEffect, useRef, useState } from "react";
import type { Candidate, CitationRef, ResolvedTarget, TargetMeasurement } from "../api/types";
import { AiPanel, type AiScopeOption } from "./AiPanel";
import { TakeBackControl } from "./TakeBackControl";
import { activityClassLabel } from "./ReferenceStrip";
import { evidenceClassLabel, modalityLabel } from "./TargetHeader";

interface TargetEvidencePanelProps {
  candidate: Candidate;
  target: ResolvedTarget;
  measurements: TargetMeasurement[] | undefined;
  loading: boolean;
  error: string | null;
  /** The candidate table's labelled modality filter, passed to the summary. */
  includeAllModalities: boolean;
  /** B-37: record-bearing citations (candidate, measurement) are routed to the
   * app, which selects the cited compound — even when it is not the selected
   * one and not on the loaded page — and reopens this panel on it. */
  onNavigateCitation?: (citation: CitationRef) => void;
  /** B-37: the measurement a citation named, to highlight in today's rows. The
   * cited row is marked; an id that no longer exists in today's data gets an
   * explicit note instead of silence — the snapshot and the present stay
   * distinguishable. */
  focusMeasurementId?: string | null;
  /** Focus a per-source coverage chip when the summary cites `source:<name>`.
   * Without it that citation would switch tabs and go nowhere. */
  onFocusSource?: (sourceName: string) => void;
  /** Focus the potency verdict strip when the summary cites
   * `reference:<target-id>` (ONLINE-06). Same rule as `source:`. */
  onFocusReference?: () => void;
  /** Take back a row this user added by hand (ONLINE-07 / defect D3). A
   * retrieved row belongs to its source and is not withdrawable here. */
  onWithdrawSupplement?: (recordId: string, reason: string) => Promise<void>;
  withdrawing?: boolean;
  onClose: () => void;
}

type InspectorTab = "evidence" | "ai";

/** Assay evidence for one candidate.
 *
 * Values are shown as reported, grouped by assay, and never ranked into a
 * single potency list: Kd, Ki, IC50 and EC50 are different measurements, and the
 * panel says so. Records that share an original document reference are marked
 * so a duplicate cannot read as independent corroboration. */
export function TargetEvidencePanel({
  candidate,
  target,
  measurements,
  loading,
  error,
  includeAllModalities,
  onNavigateCitation,
  focusMeasurementId,
  onFocusSource,
  onFocusReference,
  onWithdrawSupplement,
  withdrawing,
  onClose,
}: TargetEvidencePanelProps) {
  const [showDuplicates, setShowDuplicates] = useState(true);
  // Evidence | AI tabs reuse the existing inspection area, so the target view
  // does not grow a second permanent panel (AGENTS.md §17/§18).
  const [tab, setTab] = useState<InspectorTab>("evidence");
  const citedRowRef = useRef<HTMLTableRowElement | null>(null);

  useEffect(() => {
    setShowDuplicates(true);
  }, [candidate.compound_id]);

  // A `source:<name>` citation is about the retrieval, not this candidate, so it
  // focuses the coverage chip in the header; `reference:<target-id>` is about the
  // verdict, so it focuses the potency strip. A `candidate`/`measurement`
  // citation names a record: it goes to the app, which selects the cited
  // compound (this one or another) and points this panel at the exact row.
  const openCitation = (citation: CitationRef) => {
    if (citation.kind === "source" && citation.source_name && onFocusSource) {
      onFocusSource(citation.source_name);
      return;
    }
    if (citation.kind === "reference" && onFocusReference) {
      onFocusReference();
      return;
    }
    if (
      (citation.kind === "candidate" || citation.kind === "measurement") &&
      onNavigateCitation
    ) {
      onNavigateCitation(citation);
      return;
    }
    setTab("evidence");
  };

  const rows = measurements ?? [];
  const citedRow = focusMeasurementId
    ? rows.find((m) => String(m.id) === focusMeasurementId)
    : undefined;
  useEffect(() => {
    if (citedRow) citedRowRef.current?.scrollIntoView({ block: "center" });
  }, [citedRow]);

  const aiOptions: AiScopeOption[] = [
    {
      scope: "target",
      id: target.id,
      label: `Target ${target.target_key}`,
      description: (
        <>
          Target scope: <span className="mono">{target.target_key}</span>
          {target.uniprot_accession ? ` (${target.uniprot_accession})` : ""} — generated from the
          stored investigation facts and the per-source coverage shown above, not from full
          documents.
        </>
      ),
    },
  ];

  const visible = showDuplicates ? rows : rows.filter((m) => !m.potential_duplicate);
  const hiddenDuplicates = rows.length - visible.length;

  const byAssay = new Map<string, TargetMeasurement[]>();
  for (const row of visible) {
    const key = `${row.target_key ?? "target"}::${row.assay_key}`;
    byAssay.set(key, [...(byAssay.get(key) ?? []), row]);
  }

  return (
    <aside className="evidence-panel" aria-label="Candidate assay evidence">
      <div className="evidence-head">
        <div role="tablist" aria-label="Inspector tabs" className="inspector-tabs">
          <button
            role="tab"
            aria-selected={tab === "evidence"}
            className="inspector-tab"
            onClick={() => setTab("evidence")}
          >
            Evidence
          </button>
          <button
            role="tab"
            aria-selected={tab === "ai"}
            className="inspector-tab"
            onClick={() => setTab("ai")}
          >
            AI
          </button>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label="Close evidence panel">
          ✕
        </button>
      </div>

      {tab === "ai" ? (
        <AiPanel
          options={aiOptions}
          includeAllModalities={includeAllModalities}
          onOpenCitation={openCitation}
        />
      ) : (
        <>
          <div className="evidence-compound">
            {modalityLabel(candidate.modality)} ·{" "}
            {evidenceClassLabel(candidate.evidence_class)} · from {candidate.source_name}
          </div>

      {candidate.patent_occurrences === 0 && (
        <div className="state-banner" role="status">
          <span>
            No patent mapping is recorded for this candidate. That is a normal state: the
            compound is retained and saveable, and the absence of a patent link is not
            evidence about patent coverage.
          </span>
        </div>
      )}

      {loading && <div className="skeleton-note">Loading measurements…</div>}
      {error && (
        <div className="state-banner error" role="alert">
          <span>{error}</span>
        </div>
      )}

      {!loading && !error && rows.length === 0 && (
        <div className="state-banner" role="status">
          <span>
            No typed measurement is stored for this candidate. Absence of a measurement is
            not evidence of inactivity.
          </span>
        </div>
      )}

      {rows.length > 0 && (
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={showDuplicates}
            onChange={(e) => setShowDuplicates(e.target.checked)}
          />
          Include records flagged as duplicates of a shared original reference
          {hiddenDuplicates > 0 && !showDuplicates ? ` (${hiddenDuplicates} hidden)` : ""}
        </label>
      )}

      {/* B-37: the cited record versus today's data. A hit is highlighted in
          place below; a miss is stated, never silently dropped — the
          measurement the summary cited came from its input snapshot, and
          today's rows may have changed since. */}
      {focusMeasurementId && !loading && !citedRow && (
        <div className="state-banner" role="status" data-testid="cited-record-missing">
          <span>
            The cited measurement <span className="mono">{focusMeasurementId}</span> is not in
            today's stored rows for this compound. The summary saw it in its input snapshot;
            the data has changed since, or the record was retracted.
          </span>
        </div>
      )}

      {[...byAssay.entries()].map(([key, group]) => {
        const first = group[0];
        return (
          <section className="assay-block" key={key}>
            <div className="assay-head">
              <strong>{first.target_name ?? first.target_key ?? "target not named"}</strong>
              {first.target_type && <span className="fineprint"> · {first.target_type}</span>}
              <div className="fineprint">
                Assay {first.assay_key}
                {first.assay_type ? ` · type ${first.assay_type}` : ""}
                {first.assay_format ? ` · ${first.assay_format}` : ""}
              </div>
              {first.assay_description && (
                <details>
                  <summary>Assay description</summary>
                  <p className="fineprint">{first.assay_description}</p>
                </details>
              )}
            </div>
            <table className="meas-table">
              <thead>
                <tr>
                  <th>Endpoint</th>
                  <th>Value</th>
                  <th>Class</th>
                  <th>Evidence class</th>
                  <th>Context</th>
                </tr>
              </thead>
              <tbody>
                {group.map((m) => (
                  <tr
                    key={m.id}
                    className={focusMeasurementId && String(m.id) === focusMeasurementId ? "cited-row" : undefined}
                    ref={
                      focusMeasurementId && String(m.id) === focusMeasurementId
                        ? citedRowRef
                        : undefined
                    }
                    data-testid={focusMeasurementId && String(m.id) === focusMeasurementId ? "cited-measurement-row" : undefined}
                  >
                    <td>{m.standard_type}</td>
                    <td className="mono">
                      {m.relation !== "=" ? `${m.relation} ` : ""}
                      {m.value} {m.unit}
                      {m.pchembl_value != null && (
                        <span className="fineprint"> (pChEMBL {m.pchembl_value})</span>
                      )}
                    </td>
                    {/* The class of this one report under the stated threshold.
                        Absent means the endpoint is not a potency (kinetic or
                        percent readout), which is a fact, not a gap. */}
                    <td title={m.activity_class_rule ?? undefined}>
                      <span className={`badge badge-activity-${m.activity_class ?? "not_applicable"}`}>
                        {activityClassLabel(m.activity_class ?? "not_applicable")}
                      </span>
                    </td>
                    <td>{evidenceClassLabel(m.evidence_class)}</td>
                    <td className="fineprint">
                      {[m.species, m.variant_mutation]
                        .filter(Boolean)
                        .join(" · ") || "context not provided"}
                      {m.document_ref && (
                        <>
                          {" · "}
                          <span className="mono">{m.document_ref}</span>
                        </>
                      )}
                      {/* Decomposed reference: what the source declared, kept
                          separate from a corpus occurrence. */}
                      {m.document_patent_number && (
                        <>
                          {" · patent declared by source "}
                          <span className="mono">{m.document_patent_number}</span>
                        </>
                      )}
                      {m.document_doi && (
                        <>
                          {" · DOI "}
                          <a
                            href={`https://doi.org/${m.document_doi}`}
                            target="_blank"
                            rel="noreferrer noopener"
                          >
                            {m.document_doi}
                          </a>
                        </>
                      )}
                      {m.document_pmid && (
                        <>
                          {" · PMID "}
                          <a
                            href={`https://pubmed.ncbi.nlm.nih.gov/${m.document_pmid}/`}
                            target="_blank"
                            rel="noreferrer noopener"
                          >
                            {m.document_pmid}
                          </a>
                        </>
                      )}
                      {m.source_url && (
                        <>
                          {" · "}
                          <a href={m.source_url} target="_blank" rel="noreferrer noopener">
                            source record
                          </a>
                        </>
                      )}
                      {m.potential_duplicate && (
                        <div className="paging-error">
                          {m.validity_comment ?? "flagged as a duplicate measurement"}
                        </div>
                      )}
                      {m.validity_comment && !m.potential_duplicate && (
                        <div className="paging-error">source note: {m.validity_comment}</div>
                      )}
                      {m.note && (
                        <div className="user-note">
                          note added with this row: {m.note}
                        </div>
                      )}
                      {m.source_name === "user_supplement" &&
                        m.source_record_id &&
                        onWithdrawSupplement && (
                          <TakeBackControl
                            label="Take back this row"
                            what="This row"
                            pending={withdrawing}
                            onWithdraw={(reason) =>
                              onWithdrawSupplement(m.source_record_id as string, reason).catch(
                                () => undefined,
                              )
                            }
                          />
                        )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        );
      })}

          <p className="fineprint">
            Values are grouped by assay and shown as reported. The class column applies the potency
            threshold stated in the reference strip above to this single report; different endpoint
            types and assay formats are not comparable, so no ranking or selectivity number is
            derived here.
          </p>
        </>
      )}
    </aside>
  );
}
