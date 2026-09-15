import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Compound, EvidenceRecord, Mention } from "../api/types";
import { AiPanel, type AiScopeOption } from "./AiPanel";

interface EvidencePanelProps {
  compound: Compound;
  mentions: Mention[];
  evidence: EvidenceRecord[] | undefined;
  evidenceLoading: boolean;
  evidenceError: string | null;
  familyId: string;
  familyKey: string;
  onClose: () => void;
}

const PROVENANCE_LABELS: Record<string, string> = {
  source_fact: "Source fact",
  database_curated: "Database curated",
  machine_extracted: "Machine extracted",
  llm_inferred: "LLM inferred",
  user_curated: "User curated",
};

type InspectorTab = "evidence" | "ai";

function Field({ label, value, mono = false }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd className={mono ? "mono" : undefined}>{value}</dd>
    </div>
  );
}

function NotProvided() {
  return <span className="not-provided">Not provided</span>;
}

function CopyRow({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="identity-row">
      <span style={{ color: "var(--text-2)" }}>{label}:</span>
      <span className="mono"> {value}</span>
      <button
        className="copy-btn"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          } catch {
            setCopied(false);
          }
        }}
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

/** Right-hand inspector with Evidence | AI tabs (design doc: AI reuses the
 * inspection area; no permanent fourth panel). Evidence view keeps the
 * compound/occurrence source labels; the AI view shows family scope and its
 * own analysis provenance. Missing locators are stated, never invented. */
export function EvidencePanel({
  compound,
  mentions,
  evidence,
  evidenceLoading,
  evidenceError,
  familyId,
  familyKey,
  onClose,
}: EvidencePanelProps) {
  const [occurrenceIdx, setOccurrenceIdx] = useState(0);
  const [tab, setTab] = useState<InspectorTab>("evidence");
  const [bioactivityOpen, setBioactivityOpen] = useState(false);

  useEffect(() => {
    setOccurrenceIdx(0);
    setTab("evidence");
    setBioactivityOpen(false);
  }, [compound.id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const occurrence = mentions[occurrenceIdx] ?? null;
  const occurrenceEvidence =
    evidence?.find((e) => e.compound_mention_id === occurrence?.id) ?? null;
  const fallbackEvidence = evidence?.find((e) => !e.compound_mention_id) ?? null;
  const shown = occurrenceEvidence ?? fallbackEvidence;

  const scopeNote =
    mentions.length > 0
      ? `${mentions.length} occurrence${mentions.length === 1 ? "" : "s"} in this family`
      : "no occurrence details available";

  const openCitation = (factRef: string) => {
    setTab("evidence");
    if (factRef.startsWith("measurement:")) setBioactivityOpen(true);
  };

  return (
    <aside
      className="evidence-panel"
      aria-label="Evidence inspector"
      role="dialog"
      aria-modal="false"
    >
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
        <AiTab
          familyId={familyId}
          documentId={occurrence?.document_id ?? null}
          familyKey={familyKey}
          documentLabel={occurrence?.publication_number ?? null}
          onOpenCitation={openCitation}
        />
      ) : (
        <>
          <div className="evidence-compound">
            {occurrence?.patent_label ? `${occurrence.patent_label} — ` : ""}
            <span className="mono">{compound.inchikey}</span>
          </div>
          <div style={{ fontSize: 12, color: "var(--text-2)", marginBottom: 8 }}>{scopeNote}</div>

          <span className="provenance-chip">
            <span className="dot" aria-hidden="true" style={{ background: "var(--accent)" }} />
            {shown
              ? PROVENANCE_LABELS[shown.provenance_state] ?? shown.provenance_state
              : "Provenance pending"}
          </span>

          {mentions.length > 1 && (
            <div className="occ-switcher" role="group" aria-label="Occurrence">
              {mentions.map((m, i) => (
                <button
                  key={m.id}
                  className="occ-tab"
                  aria-pressed={i === occurrenceIdx}
                  onClick={() => setOccurrenceIdx(i)}
                >
                  {m.publication_number}
                  {m.patent_label ? ` · ${m.patent_label}` : ""}
                </button>
              ))}
            </div>
          )}

          {evidenceError && (
            <div className="state-banner error" role="alert">
              <span>{evidenceError}</span>
            </div>
          )}

          {evidenceLoading ? (
            <div role="status" aria-label="Loading evidence">
              <div className="skeleton" style={{ height: 120 }} />
            </div>
          ) : shown ? (
            <>
              <dl className="field-list">
                <Field label="Document" value={shown.publication_number ?? <NotProvided />} mono />
                <Field label="Source type" value={shown.source_type} />
                <Field label="Section" value={shown.section ?? <NotProvided />} />
                <Field label="Page" value={shown.page != null ? shown.page : <NotProvided />} />
                <Field label="Table / figure" value={<NotProvided />} />
                <Field label="Patent-local ID" value={shown.compound_local_id ?? <NotProvided />} mono />
                <Field label="Extraction method" value={shown.extraction_method} />
                <Field
                  label="Provenance state"
                  value={PROVENANCE_LABELS[shown.provenance_state] ?? shown.provenance_state}
                />
                <Field label="Dataset version" value={shown.dataset_version} mono />
                <Field label="Retrieved at" value={new Date(shown.retrieved_at).toLocaleString()} />
              </dl>

              <div className="excerpt-card">
                <div className="label">Source record</div>
                {shown.raw_excerpt ?? (
                  <span className="not-provided">Original passage not provided.</span>
                )}
              </div>

              {shown.source_url ? (
                <a className="source-link" href={shown.source_url} target="_blank" rel="noreferrer">
                  Open source ↗
                </a>
              ) : (
                <span className="not-provided" style={{ fontSize: 12 }}>
                  No source link available in the current dataset — the original patent passage is
                  not attached to this record.
                </span>
              )}
            </>
          ) : (
            <div className="state-banner">
              <span>No evidence record is linked to this compound in the current dataset.</span>
            </div>
          )}

          <BioactivitySection compoundId={compound.id} open={bioactivityOpen} />

          <details className="identity-details">
            <summary>Chemical identity</summary>
            <CopyRow label="Canonical SMILES" value={compound.canonical_smiles} />
            <CopyRow label="InChIKey" value={compound.inchikey} />
            {compound.inchi && <CopyRow label="InChI" value={compound.inchi} />}
            <div className="identity-row">
              <span style={{ color: "var(--text-2)" }}>Stereochemistry:</span>{" "}
              {compound.has_stereo
                ? "stereo centres specified in the source structure; preserved on normalization"
                : "no stereochemistry specified in the source structure"}
            </div>
            {compound.is_multi_component && (
              <div className="identity-row">
                <span style={{ color: "var(--text-2)" }}>Components:</span> multi-component record
                (e.g. salt); salt/parent normalization is not applied at this milestone.
              </div>
            )}
            {compound.normalization_notes && (
              <div className="identity-row">
                <span style={{ color: "var(--text-2)" }}>Notes:</span> {compound.normalization_notes}
              </div>
            )}
          </details>
        </>
      )}
    </aside>
  );
}

function AiTab({
  familyId,
  documentId,
  familyKey,
  documentLabel,
  onOpenCitation,
}: {
  familyId: string;
  documentId: string | null;
  familyKey: string;
  documentLabel: string | null;
  onOpenCitation: (factRef: string) => void;
}) {
  // The scopes on offer are named, and the chosen one is what the request
  // states: a document summary is never presented as a family summary.
  const options: AiScopeOption[] = [];
  if (familyId) {
    options.push({
      scope: "family" as const,
      id: familyId,
      label: `Family ${familyKey}`,
      description: (
        <>
          Family scope: <span className="mono">{familyKey}</span> — generated from the family's
          stored source records only (not the open compound, not full documents).
        </>
      ),
    });
  }
  if (documentId) {
    options.push({
      scope: "document" as const,
      id: documentId,
      label: `Document ${documentLabel ?? "current"}`,
      description: (
        <>
          Document scope: <span className="mono">{documentLabel ?? "selected document"}</span> —
          this document's own compounds, measurements and evidence only. Claims text is not stored
          in this deployment, so claims are reported as not assessed.
        </>
      ),
    });
  }
  return <AiPanel options={options} onOpenCitation={onOpenCitation} />;
}

function BioactivitySection({ compoundId, open }: { compoundId: string; open: boolean }) {
  const query = useQuery({
    queryKey: ["activity", compoundId],
    queryFn: ({ signal }) => api.activity(compoundId, signal),
  });

  return (
    <details className="identity-details" open={open}>
      <summary>Bioactivity</summary>
      {query.isLoading ? (
        <div className="skeleton" style={{ height: 40, marginTop: 8 }} />
      ) : query.data && query.data.length > 0 ? (
        <div style={{ marginTop: 8 }}>
          {query.data.map((a, i) => (
            <div key={i} className="field-list" style={{ marginBottom: 8 }}>
              <div>
                <dt>Measurement</dt>
                <dd>
                  {a.standard_type} {a.relation} {a.value} {a.unit}
                </dd>
              </div>
              <div>
                <dt>Target</dt>
                <dd>{a.target_name ?? a.assay_key}</dd>
              </div>
              <div>
                <dt>Assay</dt>
                <dd>
                  {a.assay_key}
                  {a.assay_type ? ` (${a.assay_type})` : ""}
                </dd>
              </div>
              <div>
                <dt>Provenance</dt>
                <dd>
                  {PROVENANCE_LABELS[a.provenance_state] ?? a.provenance_state} ·{" "}
                  <span className="mono">{a.dataset_version}</span>
                </dd>
              </div>
            </div>
          ))}
          <p className="hint-note">
            Values from different assays are listed separately and are not ranked or combined into
            selectivity numbers.
          </p>
        </div>
      ) : (
        <p className="not-provided" style={{ marginTop: 8 }}>
          No typed measurements for this compound. Absence of a measurement is not evidence of
          inactivity.
        </p>
      )}
    </details>
  );
}
