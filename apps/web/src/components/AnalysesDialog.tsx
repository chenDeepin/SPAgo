import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { AnalysisDetail, AnalysisEntry, CitationRef } from "../api/types";
import { Modal } from "./Modal";

interface AnalysesDialogProps {
  onClose: () => void;
  /** Submit a query to reopen a scope (family publication number or target
   * key). Omitted when the surrounding view cannot navigate. */
  onOpenScope?: (query: string) => void;
  /** B-37: open a citation of a stored analysis at its exact record. The entry
   * carries the scope context (scope id and reopen query); the citation names
   * the record. Offered only when the scope still exists — a citation whose
   * scope is gone stays readable text with the scope's own "gone" note. */
  onOpenCitation?: (citation: CitationRef, entry: AnalysisEntry) => void;
}

const SCOPE_LABELS: Record<string, string> = {
  family: "patent family",
  document: "document",
  target: "target",
};

const PROVENANCE_LABELS: Record<string, string> = {
  source_fact: "Source fact",
  database_curated: "Database curated",
  machine_extracted: "Machine extracted",
  llm_inferred: "LLM inferred",
  user_curated: "User curated",
};

/** What this owner has already generated (B-10).
 *
 * The AI panel answers "summarize this view"; this dialog answers "what did I
 * already summarize, and can I read it again without paying for it twice?".
 * Opening one is a pure read — no provider is called — and the entry says
 * whether the data behind it has moved since, instead of presenting an old
 * analysis as current. */
export function AnalysesDialog({ onClose, onOpenScope, onOpenCitation }: AnalysesDialogProps) {
  const [scope, setScope] = useState<string>("");
  const [search, setSearch] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const listQuery = useQuery({
    queryKey: ["analyses", scope, search],
    queryFn: ({ signal }) =>
      api.analyses({ scope: scope || null, search: search.trim() || null, limit: 50 }, signal),
    staleTime: 15_000,
  });

  const detailQuery = useQuery({
    queryKey: ["analysis", openId],
    queryFn: ({ signal }) => api.analysis(openId as string, signal),
    enabled: openId !== null,
    staleTime: 60_000,
  });

  const exportOne = async (entry: AnalysisEntry) => {
    setActionError(null);
    setBusyId(entry.analysis_id);
    try {
      await api.exportAnalysis(entry);
    } catch (err) {
      setActionError((err as Error).message || "The export failed.");
    } finally {
      setBusyId(null);
    }
  };

  const detail: AnalysisDetail | undefined = detailQuery.data;
  const items = listQuery.data?.items ?? [];

  return (
    <Modal title="My analyses" onClose={onClose} wide>
      <div className="analyses-filters">
        <label className="analyses-filter">
          <span>Scope</span>
          <select value={scope} onChange={(e) => setScope(e.target.value)} aria-label="Scope">
            <option value="">All scopes</option>
            <option value="family">Patent family</option>
            <option value="document">Document</option>
            <option value="target">Target</option>
          </select>
        </label>
        <label className="analyses-filter analyses-filter-search">
          <span>Find</span>
          <input
            type="search"
            value={search}
            placeholder="family key, publication number or target"
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Find a stored analysis"
          />
        </label>
      </div>

      {actionError && (
        <div className="state-banner error" role="alert">
          <span>{actionError}</span>
        </div>
      )}

      {listQuery.isError ? (
        <div className="state-banner error" role="alert">
          <span>{(listQuery.error as Error).message || "Stored analyses could not be loaded."}</span>
          <button className="btn btn-quiet" onClick={() => listQuery.refetch()}>
            Retry
          </button>
        </div>
      ) : listQuery.isLoading ? (
        <p className="hint-note">Reading stored analyses…</p>
      ) : items.length === 0 ? (
        <p className="hint-note">
          {search || scope
            ? "No stored analysis matches this filter."
            : "No analysis has been generated yet. Generate one from the AI tab of a patent or target view; it is stored and appears here."}
        </p>
      ) : (
        <>
          <div className="analyses-count">
            {listQuery.data?.total} stored {listQuery.data?.total === 1 ? "analysis" : "analyses"}
            {listQuery.data?.current_dataset_version
              ? ` · this deployment serves ${listQuery.data.current_dataset_version}`
              : ""}
          </div>
          <ul className="analyses-list">
            {items.map((entry) => (
              <li className="analyses-item" key={entry.analysis_id}>
                <div className="analyses-head">
                  <button
                    className="analyses-open"
                    aria-expanded={openId === entry.analysis_id}
                    onClick={() =>
                      setOpenId(openId === entry.analysis_id ? null : entry.analysis_id)
                    }
                  >
                    <span className="analyses-scope">{SCOPE_LABELS[entry.scope] ?? entry.scope}</span>{" "}
                    <span className="mono">{entry.scope_label}</span>
                  </button>
                  <span className="analyses-meta">
                    {new Date(entry.created_at).toLocaleString()} ·{" "}
                    {entry.model ?? "offline, no model"} ·{" "}
                    {PROVENANCE_LABELS[entry.provenance_state] ?? entry.provenance_state} ·{" "}
                    {entry.citation_count} citation{entry.citation_count === 1 ? "" : "s"}
                  </span>
                </div>
                {entry.stale && (
                  <div className="analyses-stale" role="status">
                    <strong>May be out of date.</strong>{" "}
                    {entry.stale_reasons.join(" ")}
                  </div>
                )}
                <div className="analyses-actions">
                  <button
                    className="btn btn-quiet"
                    onClick={() => exportOne(entry)}
                    disabled={busyId === entry.analysis_id}
                  >
                    {busyId === entry.analysis_id ? "Exporting…" : "Export .md"}
                  </button>
                  {onOpenScope && entry.scope_query && (
                    <button
                      className="btn btn-quiet"
                      onClick={() => {
                        onOpenScope(entry.scope_query as string);
                        onClose();
                      }}
                    >
                      Open {SCOPE_LABELS[entry.scope] ?? entry.scope}
                    </button>
                  )}
                  {!entry.scope_query && (
                    <span className="hint-note">
                      The {SCOPE_LABELS[entry.scope] ?? entry.scope} this covers is gone; the
                      stored text is still readable.
                    </span>
                  )}
                </div>

                {openId === entry.analysis_id && (
                  <div className="analyses-detail">
                    {detailQuery.isLoading ? (
                      <p className="hint-note">Reading the stored analysis…</p>
                    ) : detailQuery.isError ? (
                      <div className="state-banner error" role="alert">
                        <span>
                          {(detailQuery.error as Error).message ||
                            "The stored analysis could not be read."}
                        </span>
                      </div>
                    ) : detail ? (
                      <>
                        <p className="hint-note">
                          Prompt {detail.prompt_version ?? "not recorded"} · data{" "}
                          {detail.dataset_version}
                          {detail.exact_check?.same_inputs === true
                            ? " · the inputs are unchanged, so this is what the same request returns now"
                            : detail.exact_check?.same_inputs === false
                              ? " · the inputs have changed since; this text is the stored one, not a fresh answer"
                              : detail.exact_check?.note
                                ? ` · ${detail.exact_check.note}`
                                : ""}
                        </p>
                        <pre className="ai-summary-text">{detail.text}</pre>
                        <div className="input-label">
                          Citations ({detail.citations.length}) — records inside the scope
                        </div>
                        <ul className="citation-list">
                          {detail.citations.map((c) => {
                            const canOpen = !!onOpenCitation && !!entry.scope_id;
                            return (
                              <li key={c.fact_ref}>
                                {canOpen ? (
                                  <button
                                    className="citation-link"
                                    onClick={() => {
                                      if (!onOpenCitation) return;
                                      onOpenCitation(c, entry);
                                      onClose();
                                    }}
                                  >
                                    <span className="citation-kind">{c.kind}</span>{" "}
                                    {c.label ?? c.fact_ref}{" "}
                                    <span className="mono">{c.fact_ref}</span>
                                  </button>
                                ) : (
                                  <>
                                    <span className="citation-kind">{c.kind}</span>{" "}
                                    {c.label ?? c.fact_ref}{" "}
                                    <span className="mono">{c.fact_ref}</span>
                                  </>
                                )}
                              </li>
                            );
                          })}
                        </ul>
                        <p className="hint-note">
                          This is the stored analysis, unchanged. LLM output is an inference
                          (llm_inferred) to be checked against the cited records; export keeps the
                          scope, model and version header with it.
                        </p>
                      </>
                    ) : null}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </Modal>
  );
}
