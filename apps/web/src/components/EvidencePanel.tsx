import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import type { Compound, EvidenceRecord, Mention } from "../api/types";

interface EvidencePanelProps {
  compound: Compound;
  mentions: Mention[];
  evidence: EvidenceRecord[] | undefined;
  evidenceLoading: boolean;
  evidenceError: string | null;
  familyId: string;
  onClose: () => void;
}

type InspectorTab = "evidence" | "ai";

const PROVENANCE_LABELS: Record<string, string> = {
  source_fact: "Source fact",
  database_curated: "Database curated",
  machine_extracted: "Machine extracted",
  llm_inferred: "LLM inferred",
  user_curated: "User curated",
};

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

/** Right-hand evidence inspector. Missing locators are stated, never invented;
 * "Open source" appears only when a real source URL exists (design doc §4). */
export function EvidencePanel({
  compound,
  mentions,
  evidence,
  evidenceLoading,
  evidenceError,
  familyId,
  onClose,
}: EvidencePanelProps) {
  const [occurrenceIdx, setOccurrenceIdx] = useState(0);
  const [tab, setTab] = useState<InspectorTab>("evidence");

  useEffect(() => {
    setOccurrenceIdx(0);
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

      {tab === "ai" ? (
        <AiTab familyId={familyId} />
      ) : (
        <>
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
            <Field
              label="Document"
              value={shown.publication_number ?? <NotProvided />}
              mono
            />
            <Field label="Source type" value={shown.source_type} />
            <Field label="Section" value={shown.section ?? <NotProvided />} />
            <Field label="Page" value={shown.page != null ? shown.page : <NotProvided />} />
            <Field label="Table / figure" value={<NotProvided />} />
            <Field label="Patent-local ID" value={shown.compound_local_id ?? <NotProvided />} mono />
            <Field label="Extraction method" value={shown.extraction_method} />
            <Field label="Provenance state" value={PROVENANCE_LABELS[shown.provenance_state] ?? shown.provenance_state} />
            <Field label="Dataset version" value={shown.dataset_version} mono />
            <Field label="Retrieved at" value={new Date(shown.retrieved_at).toLocaleString()} />
          </dl>

          <div className="excerpt-card">
            <div className="label">Source record</div>
            {shown.raw_excerpt ?? <span className="not-provided">Original passage not provided.</span>}
          </div>

          {shown.source_url ? (
            <a className="source-link" href={shown.source_url} target="_blank" rel="noreferrer">
              Open source ↗
            </a>
          ) : (
            <span className="not-provided" style={{ fontSize: 12 }}>
              No source link available in the current dataset — the original patent passage is not
              attached to this record.
            </span>
          )}
        </>
      ) : (
        <div className="state-banner">
          <span>No evidence record is linked to this compound in the current dataset.</span>
        </div>
      )}

        <BioactivitySection compoundId={compound.id} />

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

function AiTab({ familyId }: { familyId: string; onClose?: () => void }) {
  const [summary, setSummary] = useState<import("../api/types").FamilySummaryResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.familySummary(familyId);
      setSummary(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Summary generation failed.");
    } finally {
      setBusy(false);
    }
  };

  if (!familyId) {
    return (
      <div className="state-banner">
        <span>AI summary is available per patent family.</span>
      </div>
    );
  }

  return (
    <div>
      <button className="btn btn-primary" onClick={generate} disabled={busy}>
        {busy ? "Generating…" : summary ? "Regenerate summary" : "Generate family summary"}
      </button>
      {error && (
        <div className="state-banner error" role="alert">
          <span>{error}</span>
        </div>
      )}
      {summary && (
        <div style={{ marginTop: 12 }}>
          <span className="provenance-chip">
            <span className="dot" aria-hidden="true" style={{ background: "var(--accent)" }} />
            {PROVENANCE_LABELS[summary.provenance_state] ?? summary.provenance_state} ·{" "}
            {summary.provider}
          </span>
          <pre className="ai-summary-text">{summary.text}</pre>
          <p className="hint-note">
            {summary.citations.length} evidence citation(s) back this summary. Interpretive
            statements from real LLM providers would be marked llm_inferred.
          </p>
        </div>
      )}
      <p className="hint-note" style={{ marginTop: 10 }}>
        No LLM provider is configured on this deployment: the summary is assembled verbatim from
        stored, evidence-linked records and is labeled machine-extracted.
      </p>
    </div>
  );
}

function BioactivitySection({ compoundId }: { compoundId: string }) {
  const query = useQuery({
    queryKey: ["activity", compoundId],
    queryFn: ({ signal }) => api.activity(compoundId, signal),
  });

  return (
    <details className="identity-details">
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
            Values from different assays are listed separately and are not ranked or combined
            into selectivity numbers.
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
