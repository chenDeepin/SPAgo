import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { CorpusSourceRow } from "../api/types";
import { Modal } from "./Modal";

interface CorpusDialogProps {
  onClose: () => void;
}

/** The loaded corpus, per dataset version (B-01).
 *
 * This is the one place that answers "does this deployment actually hold what I
 * am about to search?" — the question that decides whether an empty result means
 * "no chemistry found" or "never imported". It is deliberately read-only and
 * counts-only: loading more is an operator action (`scripts/corpus_batch.py`),
 * reported here so the operator can see the result in the same product the
 * scientists use. */
export function CorpusDialog({ onClose }: CorpusDialogProps) {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["corpus"],
    queryFn: ({ signal }) => api.corpus(signal),
    staleTime: 60_000,
  });

  const counts = (row: CorpusSourceRow) => [
    { label: "families", value: row.families },
    { label: "documents", value: row.documents },
    { label: "compounds", value: row.compounds },
    { label: "mentions", value: row.mentions },
    { label: "evidence", value: row.evidence },
    { label: "measurements", value: row.measurements },
  ];

  return (
    <Modal title="Loaded corpus" onClose={onClose} wide>
      {isError ? (
        <div className="state-banner error" role="alert">
          <span>{(error as Error).message || "The corpus overview could not be loaded."}</span>
          <button className="btn btn-quiet" onClick={() => refetch()}>
            Retry
          </button>
        </div>
      ) : isLoading ? (
        <p className="hint-note">Reading the corpus tables…</p>
      ) : !data || data.sources.length === 0 ? (
        <p className="hint-note">
          This deployment holds no corpus rows yet. Import a package
          (<code>python -m spago_core.import_package &lt;dir&gt;</code>) before searching.
        </p>
      ) : (
        <>
          <div className="corpus-list">
            {data.sources.map((row) => (
              <div className="corpus-row" key={row.dataset_version}>
                <div className="corpus-head">
                  <span className="corpus-version">{row.dataset_version}</span>
                  <span className="corpus-source">
                    {row.source_name ?? "source not recorded"}
                    {row.synthetic ? " · synthetic" : ""}
                    {row.registered ? "" : " · not an imported package"}
                  </span>
                </div>
                <div className="corpus-counts">
                  {counts(row).map((c) => (
                    <span key={c.label} className="corpus-count">
                      <strong>{c.value.toLocaleString()}</strong> {c.label}
                    </span>
                  ))}
                  {row.issues > 0 && (
                    <span className="corpus-count corpus-count-warn">
                      <strong>{row.issues.toLocaleString()}</strong> record
                      {row.issues === 1 ? "" : "s"} with ingestion issues
                    </span>
                  )}
                </div>
                <div className="hint-note">
                  {row.retrieved_at
                    ? `Retrieved ${new Date(row.retrieved_at).toLocaleString()}`
                    : "Retrieval time not recorded"}
                  {row.release_label ? ` · release ${row.release_label}` : ""}
                  {row.notes ? ` · ${row.notes}` : ""}
                </div>
              </div>
            ))}
          </div>

          <div className="corpus-totals">
            <strong>Total</strong>{" "}
            {[
              "families",
              "documents",
              "compounds",
              "mentions",
              "evidence",
              "measurements",
            ]
              .map((kind) => `${(data.totals[kind] ?? 0).toLocaleString()} ${kind}`)
              .join(" · ")}
          </div>

          <div className="hint-note">
            Imports: {data.imports.completed} completed
            {data.imports.running ? `, ${data.imports.running} running` : ""}
            {data.imports.failed ? `, ${data.imports.failed} failed` : ""}
            {data.imports.interrupted ? `, ${data.imports.interrupted} interrupted` : ""}
            {data.imports.last_finished_at
              ? ` · last finished ${new Date(data.imports.last_finished_at).toLocaleString()}`
              : ""}
          </div>
          {data.imports.last_error && (
            <div className="state-banner error" role="alert">
              <span>
                Last failed import: {data.imports.last_error.dataset_version} —{" "}
                {data.imports.last_error.error}
              </span>
            </div>
          )}
          {data.notes.map((note) => (
            <p className="hint-note" key={note}>
              {note}
            </p>
          ))}
          <p className="hint-note">
            Counts are read from the corpus tables when this dialog is opened. A
            publication that is not listed here was never imported: neither this
            view nor a search can conclude anything about its chemistry.
          </p>
        </>
      )}
    </Modal>
  );
}
