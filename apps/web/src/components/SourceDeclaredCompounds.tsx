import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { PatentSourceResponse, PatentSourceRow } from "../api/types";
import { canonicalPublicationNumber } from "../state/url";
import { MoleculeImage } from "./MoleculeImage";
import { activityClassLabel } from "./ReferenceStrip";

interface SourceDeclaredCompoundsProps {
  /** The publication to ask about — a corpus document's number, or the query
   * the reader typed when the corpus holds nothing under it. */
  publicationNumber: string | null;
  /** Set when the corpus itself has no family for this number, so the panel is
   * framed as "the corpus cannot answer" rather than as a supplement. */
  notHeldByCorpus?: boolean;
  /** How many compounds the corpus holds for this publication, when it does. */
  corpusCompoundCount?: number | null;
}

const PAGE_SIZE = 50;

/** What a public source *declares* for a publication (B-24).
 *
 * The product's first promise — enter a patent, see its compounds — used to stop
 * at the loaded corpus: a publication that was never imported showed nothing,
 * even when a public source indexes compounds under it. This panel closes that
 * gap by asking ChEMBL what it declares for the publication number, independent
 * of the corpus.
 *
 * It is deliberately a *separate* surface with its own vocabulary. A declared
 * record is not an occurrence in a patent (AGENTS.md §11): `document_patent_number`
 * is the reference the source itself recorded, and it is never merged into the
 * compound table above, never counted in the family's compound total, and never
 * presented as evidence. Nothing is fetched until the reader asks, and an empty
 * answer is shown with the match rule that produced it, so "the source declares
 * no compounds" cannot be read as "this patent has no compounds".
 */
export function SourceDeclaredCompounds({
  publicationNumber,
  notHeldByCorpus = false,
  corpusCompoundCount = null,
}: SourceDeclaredCompoundsProps) {
  const queryClient = useQueryClient();
  // This panel's identity is the *publication*, not the way it is spelled on the way
  // in. A "/" cannot be a path segment, so the request carries the canonical form and
  // `requested_number` comes back canonical for exactly those inputs (state/url.ts);
  // comparing raw strings would then throw away a successful lookup (observed on the
  // local stack, 2026-09-16 — the same defect class the B-24 browser check found in the
  // other direction). `canonicalPublicationNumber` is the mirrored deterministic rule
  // and only drops separators and case, so two different publications never share it.
  const identity = publicationNumber ? canonicalPublicationNumber(publicationNumber) : null;
  const key = ["patent-source-compounds", identity] as const;
  const [open, setOpen] = useState(false);
  const [extraRows, setExtraRows] = useState<PatentSourceRow[]>([]);
  const [paging, setPaging] = useState(false);
  const [pagingError, setPagingError] = useState<string | null>(null);

  // Reading the stored answer is free and never calls the external source, so
  // it can run as soon as the panel has a number to look up.
  const stored = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => api.patentSourceCompounds(publicationNumber as string, {}, signal),
    enabled: Boolean(publicationNumber),
    staleTime: 30_000,
  });

  const lookup = useMutation({
    mutationFn: () => api.lookupPatentSourceCompounds(publicationNumber as string),
    onSuccess: (data) => {
      // A response that lands after the reader moved to another publication must
      // not be shown or cached under this panel. The comparison is canonical on
      // both sides, so a number written differently still lands here while a
      // different publication does not.
      if (canonicalPublicationNumber(data.requested_number ?? "") !== identity) return;
      setExtraRows([]);
      setPagingError(null);
      queryClient.setQueryData(key, data);
      // The stored read for the canonical number is served by the same endpoint;
      // refresh it so a later visit to that number sees the new set.
      void queryClient.invalidateQueries({ queryKey: ["patent-source-compounds"] });
    },
  });

  const answerBelongsToThisPanel = Boolean(
    lookup.data && canonicalPublicationNumber(lookup.data.requested_number ?? "") === identity,
  );
  const view: PatentSourceResponse | undefined = answerBelongsToThisPanel
    ? lookup.data
    : stored.data;

  // A stored set that the reader only asked to see expanded is what opens the
  // panel; a publication the corpus cannot answer for opens it too, because the
  // empty state above is then the only thing on screen.
  useEffect(() => {
    setExtraRows([]);
    setPagingError(null);
    setOpen(false);
  }, [publicationNumber]);

  const hasStoredRows = Boolean(view && view.row_count > 0);
  useEffect(() => {
    if (hasStoredRows) setOpen(true);
  }, [hasStoredRows]);

  if (!publicationNumber) return null;

  const queried = view && view.status !== "not_queried";
  const rows = [...(view?.rows ?? []), ...extraRows];
  const hasMore = Boolean(view && rows.length < view.row_count);
  const failedLookupIsStaleSet = Boolean(
    view && view.status === "failed" && view.row_count > 0 &&
      view.rows_retrieved_at &&
      view.rows_retrieved_at !== view.retrieved_at,
  );

  async function loadMore() {
    if (!view) return;
    setPaging(true);
    setPagingError(null);
    try {
      const page = await api.patentSourceCompounds(publicationNumber as string, {
        offset: rows.length,
        limit: PAGE_SIZE,
      });
      setExtraRows((current) => [...current, ...page.rows]);
    } catch (error) {
      setPagingError((error as Error).message);
    } finally {
      setPaging(false);
    }
  }

  return (
    <section className="declared-strip" aria-label="Source-declared compounds">
      <div className="declared-head">
        <button
          className="declared-toggle"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          <strong>ChEMBL declares</strong>{" "}
          {stored.isError
            ? "— the stored lookup could not be read"
            : view === undefined
              ? "— checking whether a lookup is stored…"
              : view.status === "not_queried"
                ? "— nothing asked about this publication yet"
                : view.status === "failed"
                  ? "— the last lookup failed"
                  : view.status === "empty"
                    ? "no compounds for this publication"
                    : `${view.row_count} record${view.row_count === 1 ? "" : "s"} for ${
                        view.compound_count
                      } compound${view.compound_count === 1 ? "" : "s"}`}
          {view && view.status === "partial" && " (partial)"}
          <span className="declared-caret">{open ? "▾" : "▸"}</span>
        </button>
        <span className="spacer" />
        <button
          className={queried ? "btn btn-quiet" : "btn btn-primary"}
          onClick={() => lookup.mutate()}
          disabled={lookup.isPending}
        >
          {lookup.isPending
            ? "Asking ChEMBL…"
            : queried
              ? "Ask ChEMBL again"
              : "Ask ChEMBL what it declares"}
        </button>
      </div>

      <p className="fineprint">
        {notHeldByCorpus
          ? "This publication is not held by the loaded corpus. "
          : corpusCompoundCount === 0
            ? "The loaded corpus holds no compound for this publication. "
            : ""}
        A declared record is the source's own statement about a publication — not an
        occurrence in SPAgo's corpus, not evidence, and not counted in the table above.
      </p>

      {lookup.error && (
        <div className="state-banner error" role="alert">
          <span>{(lookup.error as Error).message}</span>
        </div>
      )}

      {open && view && (
        <div className="declared-body">
          <div className="coverage-strip" role="list" aria-label="Declared-set status">
            <span className={`coverage-chip coverage-${view.status}`} role="listitem">
              <strong>{view.source_name}</strong> {view.status.replace("_", " ")}
              {view.retrieved_at && ` · asked ${new Date(view.retrieved_at).toLocaleString()}`}
            </span>
            <span className="coverage-chip" role="listitem">
              {view.records_seen} record{view.records_seen === 1 ? "" : "s"} seen
              {view.records_excluded > 0 && ` · ${view.records_excluded} not usable`}
            </span>
            {view.compound_count > 0 && (
              <span className="coverage-chip" role="listitem">
                {view.activity_class_counts.active ?? 0} at or below{" "}
                {view.reference_threshold_label} under {view.reference_policy_version}
              </span>
            )}
            {view.rows_retrieved_at && view.rows_retrieved_at !== view.retrieved_at && (
              <span className="coverage-chip coverage-partial" role="listitem">
                shown set retrieved {new Date(view.rows_retrieved_at).toLocaleString()}
              </span>
            )}
          </div>

          {view.status === "failed" && (
            <p className="hint-note">
              The lookup did not complete: {view.warnings.join(" ")}{" "}
              {failedLookupIsStaleSet
                ? "The set below is from the last successful retrieval and may be out of date."
                : "No set is stored for this publication, and this is not an empty result."}
            </p>
          )}

          {view.status === "empty" && (
            <p className="hint-note">
              ChEMBL's patent <code>{view.match_rule}</code> matched no document for{" "}
              <span className="mono">{view.publication_number}</span>. That is a statement
              about this source and this rule, not about the patent.
            </p>
          )}

          {view.status === "partial" && view.warnings.length > 0 && (
            <details className="declared-notes">
              <summary>Why this set is partial</summary>
              <ul>
                {view.warnings.map((warning, index) => (
                  <li key={index}>{warning}</li>
                ))}
              </ul>
            </details>
          )}

          {view.near_matches.length > 0 && (
            <details className="declared-notes">
              <summary>
                {view.near_matches.length} document
                {view.near_matches.length === 1 ? "" : "s"} whose recorded number is not
                this publication
              </summary>
              <ul>
                {view.near_matches.map((match) => (
                  <li key={match.document_chembl_id ?? match.patent_id ?? "unknown"}>
                    <span className="mono">{match.patent_id ?? "no number"}</span> ·{" "}
                    {match.document_chembl_id}
                    {match.year ? ` · ${match.year}` : ""} — {match.reason}. Excluded rather
                    than merged.
                  </li>
                ))}
              </ul>
            </details>
          )}

          {rows.length > 0 && (
            <div className="declared-table-wrap">
              <table className="declared-table">
                <thead>
                  <tr>
                    <th scope="col">Structure</th>
                    <th scope="col">Compound</th>
                    <th scope="col">Declared activity</th>
                    <th scope="col">Class</th>
                    <th scope="col">Target / assay</th>
                    <th scope="col">Source record</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.row_id}>
                      <td>
                        <MoleculeImage compoundId={row.compound_id} />
                      </td>
                      <td>
                        <div>{row.source_molecule_name ?? "unnamed"}</div>
                        <div className="mono fineprint">{row.inchikey}</div>
                        {row.modality && row.modality !== "small_molecule" && (
                          <span className="badge">{row.modality.replace("_", " ")}</span>
                        )}
                        {row.potential_duplicate && (
                          <span className="badge" title="The source flags a possible duplicate">
                            source-flagged duplicate
                          </span>
                        )}
                      </td>
                      <td title={row.activity_class_rule}>
                        {row.potency_label}
                        {row.pchembl_value !== null && (
                          <div className="fineprint">pChEMBL {row.pchembl_value}</div>
                        )}
                      </td>
                      <td>
                        <span className={`badge badge-activity-${row.activity_class}`}>
                          {activityClassLabel(row.activity_class)}
                        </span>
                      </td>
                      <td>
                        <div>{row.target_name ?? row.target_key ?? "no target"}</div>
                        <div className="fineprint">
                          {[row.assay_type, row.species, row.variant_mutation]
                            .filter(Boolean)
                            .join(" · ")}
                        </div>
                      </td>
                      <td>
                        {row.source_url ? (
                          <a
                            className="evidence-link"
                            href={row.source_url}
                            target="_blank"
                            rel="noreferrer noopener"
                          >
                            {row.source_record_id}
                          </a>
                        ) : (
                          <span className="mono">{row.source_record_id}</span>
                        )}
                        <div className="fineprint">
                          declares{" "}
                          <span className="mono">
                            {row.document_patent_number ?? row.document_ref ?? "—"}
                          </span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {hasMore && (
            <div className="declared-actions">
              <button className="btn btn-quiet" onClick={() => void loadMore()} disabled={paging}>
                {paging
                  ? "Loading…"
                  : `Load more (${rows.length} of ${view?.row_count ?? 0} shown)`}
              </button>
              {pagingError && (
                <span className="paging-error" role="alert">
                  {pagingError}
                </span>
              )}
            </div>
          )}

          <details className="declared-notes">
            <summary>Match rule, rejected records and export</summary>
            <p className="fineprint">
              Match rule <code>{view.match_rule}</code>: {view.match_rule_text}
            </p>
            <p className="fineprint">
              {view.records_excluded > 0
                ? `${view.records_excluded} of ${view.records_seen} records were not usable: ` +
                  Object.entries(view.rejection_counts)
                    .map(([reason, count]) => `${count} ${reason.replace(/_/g, " ")}`)
                    .join(", ") +
                  "."
                : `${view.records_seen} records were read and all of them were usable.`}{" "}
              {view.bounds?.max_activities
                ? `The lookup reads at most ${view.bounds.max_documents ?? "—"} documents and ${view.bounds.max_activities} activity records.`
                : ""}
            </p>
            {view.documents.length > 0 && (
              <p className="fineprint">
                Documents the source matched:{" "}
                {view.documents
                  .map((document) => document.patent_id ?? document.document_chembl_id ?? "—")
                  .join(", ")}
              </p>
            )}
            <div className="declared-actions">
              <button
                className="btn btn-quiet"
                onClick={() => void api.exportPatentSourceCompounds(view.publication_number, "csv")}
                disabled={view.row_count === 0}
              >
                Export CSV
              </button>
              <button
                className="btn btn-quiet"
                onClick={() => void api.exportPatentSourceCompounds(view.publication_number, "sdf")}
                disabled={view.row_count === 0}
              >
                Export SDF
              </button>
              <span className="fineprint">
                {view.row_count === 0
                  ? "Nothing declared, so there is no file to write."
                  : "The file states the source, the match rule and the potency policy."}
              </span>
            </div>
          </details>
        </div>
      )}

      {!open && view && view.status !== "not_queried" && (
        <p className="fineprint">
          {view.status === "failed"
            ? "The last lookup failed; open to see what it stored."
            : view.status === "empty"
              ? "Open for the match rule behind that answer."
              : "Open for the declared records, their rule and export."}
        </p>
      )}

      {!queried && view && view.status === "not_queried" && (
        <p className="hint-note">{view.not_queried_reason}</p>
      )}
    </section>
  );
}
