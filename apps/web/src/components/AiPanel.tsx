import { useEffect, useRef, useState } from "react";
import type React from "react";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import type { CitationRef, FamilySummaryResponse } from "../api/types";

export interface AiScopeOption {
  /** Passed to the API and shown to the user; never inferred. */
  scope: "family" | "document" | "target";
  id: string;
  label: string;
  /** What the summary is generated from, stated in the UI. */
  description: React.ReactNode;
}

interface AiPanelProps {
  options: AiScopeOption[];
  /** B-37: the whole typed citation, not just its ref string — navigating to
   * the exact record needs the compound/document ids the ref alone does not
   * carry. Kinds with no ownable record (a family or target scope) still arrive
   * here; the owner decides what they mean. */
  onOpenCitation: (citation: CitationRef) => void;
  /** Optional modifier for the request (target scope only). */
  includeAllModalities?: boolean;
}

const PROVENANCE_LABELS: Record<string, string> = {
  source_fact: "Source fact",
  database_curated: "Database curated",
  machine_extracted: "Machine extracted",
  llm_inferred: "LLM inferred",
  user_curated: "User curated",
};

/** AI inspector shared by the patent and target surfaces.
 *
 * The scope is an explicit choice with the available scopes named, so a
 * document or target analysis is never presented as a family analysis. Failure
 * states are distinguished (not configured, busy, timeout, rate limited,
 * invalid output) and stopping the wait is described honestly. */
export function AiPanel({ options, onOpenCitation, includeAllModalities = false }: AiPanelProps) {
  const statusQuery = useQuery({
    queryKey: ["ai-status"],
    queryFn: ({ signal }) => api.aiStatus(signal),
    staleTime: 30_000,
  });
  const status = statusQuery.data;
  const llmConfigured = status?.state === "configured";

  const [scopeIndex, setScopeIndex] = useState(0);
  const [mode, setMode] = useState<"offline" | "llm">("offline");
  const [summary, setSummary] = useState<FamilySummaryResponse | null>(null);
  const [summaryKey, setSummaryKey] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const closedRef = useRef(false);

  const option = options[Math.min(scopeIndex, options.length - 1)] ?? null;
  const requestKey = option ? `${option.scope}:${option.id}` : null;

  // A summary of another scope never shows here.
  useEffect(() => {
    setSummary(null);
    setSummaryKey(null);
    setError(null);
    abortRef.current?.abort();
    setBusy(false);
  }, [requestKey]);

  useEffect(
    () => () => {
      closedRef.current = true;
      abortRef.current?.abort();
    },
    [],
  );

  const effectiveMode: "offline" | "llm" = mode === "llm" && llmConfigured ? "llm" : "offline";

  const generate = async () => {
    if (!option) return;
    setError(null);
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    try {
      const res =
        option.scope === "target"
          ? await api.targetSummary(option.id, effectiveMode, includeAllModalities, controller.signal)
          : option.scope === "document"
            ? await api.documentSummary(option.id, effectiveMode, controller.signal)
            : await api.familySummary(option.id, effectiveMode, controller.signal);
      if (controller.signal.aborted || closedRef.current) return;
      setSummary(res);
      setSummaryKey(`${option.scope}:${option.id}`);
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof ApiError ? err.message : "Summary generation failed.");
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  };

  if (options.length === 0) {
    return (
      <div className="state-banner">
        <span>No summary scope is available in this view.</span>
      </div>
    );
  }

  const shown = summary && summaryKey === requestKey ? summary : null;

  return (
    <div>
      <div className="ai-scope-line">
        <span>
          {option?.description}
        </span>
      </div>

      {options.length > 1 && (
        <>
          <div className="input-label">Scope</div>
          <div role="radiogroup" aria-label="Summary scope" className="radio-col">
            {options.map((opt, index) => (
              <label className="radio-row" key={requestKey === `${opt.scope}:${opt.id}` ? opt.label : `${opt.scope}:${opt.id}`}>
                <input
                  type="radio"
                  name="ai-scope"
                  checked={index === scopeIndex}
                  onChange={() => setScopeIndex(index)}
                />
                <span>{opt.label}</span>
              </label>
            ))}
          </div>
        </>
      )}

      <div className="input-label">Summary mode</div>
      <div role="radiogroup" aria-label="Summary mode" className="radio-col">
        <label className="radio-row">
          <input
            type="radio"
            name="ai-mode"
            checked={effectiveMode === "offline"}
            onChange={() => setMode("offline")}
          />
          <span>Offline summary (extractive, no model)</span>
        </label>
        <label className="radio-row">
          <input
            type="radio"
            name="ai-mode"
            checked={effectiveMode === "llm"}
            disabled={!llmConfigured}
            onChange={() => setMode("llm")}
          />
          <span>
            LLM summary{" "}
            {status?.state === "configured"
              ? `(model: ${status.model})`
              : status
                ? "(not configured)"
                : ""}
          </span>
        </label>
      </div>
      {status?.state === "config_invalid" && (
        <p className="hint-note">LLM configuration is invalid: {status.reason}</p>
      )}
      {effectiveMode === "llm" && (
        <p className="hint-note">
          The stored facts for this scope are sent to the configured model endpoint
          {status?.target ? ` (${status.target})` : ""}. LLM output is labeled llm_inferred and must
          be checked against the cited records. Reference text is treated as data, not as
          instructions.
        </p>
      )}

      {busy ? (
        <>
          <button className="btn btn-quiet" onClick={() => { abortRef.current?.abort(); setBusy(false); }}>
            Stop waiting
          </button>
          <p className="hint-note">
            Waiting for the summary… a request that was already sent may still be billed by the
            provider; stopping only stops waiting for it.
          </p>
        </>
      ) : (
        !shown && (
          <button className="btn btn-primary" onClick={generate}>
            Generate summary
          </button>
        )
      )}

      {error && (
        <div className="state-banner error" role="alert">
          <span>{error}</span>
          <span className="spacer" />
          <button className="btn btn-quiet" onClick={generate}>
            Retry
          </button>
        </div>
      )}

      {shown && (
        <div style={{ marginTop: 12 }}>
          <span className="provenance-chip">
            <span className="dot" aria-hidden="true" style={{ background: "var(--accent)" }} />
            {PROVENANCE_LABELS[shown.provenance_state] ?? shown.provenance_state} ·{" "}
            {shown.provider}
            {shown.model ? ` · ${shown.model}` : ""}
            {shown.cached ? " · cached" : ""}
            {shown.scope ? ` · ${shown.scope} scope` : ""}
          </span>
          <pre className="ai-summary-text">{shown.text}</pre>
          <div className="input-label" style={{ marginTop: 10 }}>
            Citations ({shown.citations.length})
          </div>
          <ul className="citation-list">
            {shown.citations.map((c) => (
              <li key={c.fact_ref}>
                <button className="citation-link" onClick={() => onOpenCitation(c)}>
                  <span className="citation-kind">{c.kind}</span> {c.label ?? c.fact_ref}
                </button>
              </li>
            ))}
          </ul>
          <p className="hint-note">
            LLM conclusions are inferences (llm_inferred): check them against the cited records.
            Measurement citations link to database records, not patent text.
          </p>
        </div>
      )}

      {!shown && !busy && (
        <p className="hint-note" style={{ marginTop: 10 }}>
          Cached summaries are reused automatically; the same scope data always yields the same
          summary.
        </p>
      )}
    </div>
  );
}
