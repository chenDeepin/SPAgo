import { useState } from "react";
import { looksLikePublicationNumber } from "../state/url";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type {
  CoverageLeg,
  CoverageLegName,
  CoverageLegState,
  CoverageStatus,
  PublicationCoverage,
} from "../api/types";

interface PublicationCoverageProps {
  /** The publications to audit: a family's stored documents, or the one number the
   * reader typed when the corpus holds nothing under it. */
  publications: string[];
  /** Set when the corpus itself has no family for these numbers, so the strip is
   * framed as "what else is stored for this number" rather than as a summary. */
  notHeldByCorpus?: boolean;
  /** Opens the document a row belongs to (family view only). */
  onSelectPublication?: (number: string) => void;
}

const STATUS_LABEL: Record<CoverageStatus, string> = {
  corpus: "corpus occurrence",
  declared: "source-declared",
  supplement: "hand-added",
  proposed: "awaiting review",
  empty: "asked, none found",
  failed: "an ask failed",
  not_queried: "never asked",
};

const LEG_LABEL: Record<CoverageLegName, string> = {
  corpus: "corpus",
  declared: "source",
  supplement: "by hand",
};

const LEG_STATE_LABEL: Record<CoverageLegState, string> = {
  has_records: "holds records",
  unconfirmed: "proposed only",
  asked_empty: "asked · none",
  failed: "ask failed",
  not_queried: "never asked",
};

const ANSWER_LABEL: Record<string, string> = {
  corpus: "stored corpus document",
  patent_source_lookup: "per-publication lookup",
  target_led_source: "target-led rows",
  hand_added: "hand-added rows",
};

/** What is stored for a publication, from where, and what nobody asked (B-26).
 *
 * Four paths can contribute chemistry to one publication — the imported corpus, a
 * per-publication source lookup (B-24), target-led source rows (B-02) and a person's
 * hand-added rows (ONLINE-07/B-25) — and nothing put them side by side. This strip
 * reads them as *legs* and never sums them: a corpus occurrence, a source-declared
 * compound and a hand-added row are three different facts (AGENTS.md §10/§11).
 *
 * The one thing it must never do is let "we never asked" read as "this publication
 * has no compounds": a leg nobody asked is reported as never asked, the `unqueried`
 * legs are named on the row, and the notes state what the audit cannot see. Nothing
 * is fetched from an external source and nothing is written — the audit reads stored
 * rows, so it can run on its own without a user action and without spending a rate
 * limit (AGENTS.md §16).
 */
export function PublicationCoverage({
  publications,
  notHeldByCorpus = false,
  onSelectPublication,
}: PublicationCoverageProps) {
  const [open, setOpen] = useState(false);
  // The notes/export block is DOM-owned by default (`<details>`), and a React
  // re-render of an ancestor can leave the node replaced with the marker the
  // browser first rendered — observed on the local stack 2026-09-16: the block
  // snapped shut between opening it and clicking export. Holding the state here
  // keeps the reader's open/closed intent across any re-render, which is the same
  // reason the B-24 panel owns its own expansion state.
  const [notesOpen, setNotesOpen] = useState(false);
  // The audit is a *publication-number* audit, and the service refuses a list in
  // which no value carries one. Filtering here (with the mirrored client rule, the
  // same literal the server's `patent_tokens` accepts) keeps a synthetic fixture's
  // non-number identifiers — `DEMO-PATENT-A` — from turning into a refusal banner
  // and a pointless request: there is no publication to report on.
  const numbers = publications.filter((number) => looksLikePublicationNumber(number));
  // One audit request per distinct set of publications. The key is built from the
  // sorted numbers, so a family that renders its documents in another order does not
  // re-ask, and a response for another set can never be shown under this one.
  const identity = [...numbers].sort().join(" ");
  const report = useQuery({
    queryKey: ["patent-coverage", identity],
    queryFn: ({ signal }) => api.patentCoverage(numbers, signal),
    enabled: numbers.length > 0,
    staleTime: 60_000,
  });

  if (numbers.length === 0) return null;

  const data = report.data;
  const rows = data?.publications ?? [];
  // The count the service computed under its own headline rule: the statuses that
  // name a leg holding records. The surface reads it rather than re-deriving which
  // statuses "hold compounds", so the summary line and the rows cannot disagree.
  const holding = data?.totals?.holds_records ?? 0;
  const neverAsked = data?.totals?.not_fully_asked ?? 0;
  const failedLegs = data?.totals?.failed_legs ?? 0;
  const statuses = (["corpus", "declared", "supplement", "proposed", "empty", "failed", "not_queried"] as CoverageStatus[]).filter(
    (status) => (data?.totals?.[status] ?? 0) > 0,
  );

  return (
    <section className="coverage-surface" aria-label="Publication coverage">
      <div className="coverage-head">
        <button
          className="declared-toggle"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          <strong>Coverage</strong>{" "}
          {report.isError
            ? "— the audit could not be read"
            : data === undefined
              ? "— reading what is stored…"
              : `${holding} of ${rows.length} publication${rows.length === 1 ? "" : "s"} ${
                  rows.length === 1 ? "holds" : "hold"
                } compounds`}
          {data !== undefined && (
            <span className="coverage-counts">
              {statuses.map((status) => (
                <span key={status} className={`coverage-chip coverage-${status}`}>
                  {data.totals[status]} {STATUS_LABEL[status]}
                </span>
              ))}
              {neverAsked > 0 && (
                <span className="coverage-chip coverage-partial">
                  {neverAsked} with a leg never asked
                </span>
              )}
              {failedLegs > 0 && (
                <span className="coverage-chip coverage-failed">
                  {failedLegs} ask{failedLegs === 1 ? "" : "s"} did not complete
                </span>
              )}
            </span>
          )}
          <span className="declared-caret">{open ? "▾" : "▸"}</span>
        </button>
      </div>

      <p className="fineprint">
        {notHeldByCorpus
          ? "The loaded corpus holds no document under this number. "
          : ""}
        Each leg below is read from stored rows — the corpus, stored source lookups and
        hand-added rows — and they are never summed: an occurrence in the corpus is not
        a source's declaration, and neither is a person's own row. “Never asked” is not
        “nothing exists”.
      </p>

      {report.error && (
        <div className="state-banner error" role="alert">
          <span>{(report.error as Error).message}</span>
        </div>
      )}

      {open && data && (
        <div className="coverage-body">
          <table className="coverage-table">
            <thead>
              <tr>
                <th scope="col">Publication</th>
                <th scope="col">Status</th>
                <th scope="col">Corpus</th>
                <th scope="col">Source</th>
                <th scope="col">By hand</th>
                <th scope="col">Never asked</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <CoverageRow
                  key={`${row.requested}-${row.matched ?? ""}`}
                  row={row}
                  onSelectPublication={onSelectPublication}
                />
              ))}
            </tbody>
          </table>

          {rows.map((row) => (
            <p key={`why-${row.requested}`} className="fineprint coverage-reason">
              <span className="mono">{row.matched ?? row.requested}</span> — {row.status_reason}
            </p>
          ))}

          <details
            className="declared-notes"
            open={notesOpen}
            onToggle={(event) => setNotesOpen((event.currentTarget as HTMLDetailsElement).open)}
          >
            <summary>Rule, notes and export</summary>
            <p className="fineprint">
              Rule <code>{data.rule}</code>: {data.rule_text}
            </p>
            <ul className="coverage-notes">
              {data.notes.map((note, index) => (
                <li key={index}>{note}</li>
              ))}
            </ul>
            <div className="declared-actions">
              <button
                className="btn btn-quiet"
                onClick={() => void api.exportPatentCoverage(numbers, "markdown")}
              >
                Export Markdown
              </button>
              <button
                className="btn btn-quiet"
                onClick={() => void api.exportPatentCoverage(numbers, "csv")}
              >
                Export CSV
              </button>
              <span className="fineprint">
                Every status is re-derivable from the stored rows; the file carries the
                rule that produced it and the leg each count came from.
              </span>
            </div>
          </details>
        </div>
      )}

      {!open && data && (
        <p className="fineprint">
          Open for the per-publication legs, the reason behind each status, and export.
        </p>
      )}
    </section>
  );
}

function CoverageRow({
  row,
  onSelectPublication,
}: {
  row: PublicationCoverage;
  onSelectPublication?: (number: string) => void;
}) {
  const byLeg = new Map(row.legs.map((leg) => [leg.leg, leg]));
  const canOpen = Boolean(onSelectPublication && row.matched && row.in_corpus);
  return (
    <tr>
      <td>
        {canOpen ? (
          <button
            className="coverage-open"
            onClick={() => onSelectPublication?.(row.matched as string)}
            title={`Show ${row.matched} in the compound table`}
          >
            {row.matched}
          </button>
        ) : (
          <span className="mono">{row.matched ?? row.requested}</span>
        )}
        {row.matched && row.matched !== row.requested && (
          <div className="fineprint">asked as {row.requested}</div>
        )}
        {row.doc_type && <div className="fineprint">{row.doc_type}</div>}
        {row.ambiguous.length > 0 && (
          <div className="fineprint" title="Reported, never chosen between">
            also matches {row.ambiguous.join(", ")}
          </div>
        )}
      </td>
      <td>
        <span className={`coverage-chip coverage-${row.status}`}>
          {STATUS_LABEL[row.status]}
        </span>
      </td>
      {(["corpus", "declared", "supplement"] as CoverageLegName[]).map((name) => (
        <td key={name} title={byLeg.get(name)?.detail}>
          <LegCell leg={byLeg.get(name)} />
        </td>
      ))}
      <td>{row.unqueried.length > 0 ? row.unqueried.map((name) => LEG_LABEL[name]).join(", ") : "—"}</td>
    </tr>
  );
}

function LegCell({ leg }: { leg: CoverageLeg | undefined }) {
  if (!leg) return <span className="fineprint">—</span>;
  const counts: string[] = [];
  if (leg.records > 0) counts.push(`${leg.records} row${leg.records === 1 ? "" : "s"}`);
  if (leg.compounds > 0) counts.push(`${leg.compounds} compound${leg.compounds === 1 ? "" : "s"}`);
  if (leg.unconfirmed_records > 0) counts.push(`${leg.unconfirmed_records} proposed`);
  if (leg.targets > 0) counts.push(`${leg.targets} target${leg.targets === 1 ? "" : "s"}`);
  return (
    <div>
      <span className={`coverage-chip coverage-${leg.state}`}>{LEG_STATE_LABEL[leg.state]}</span>
      {counts.length > 0 && <div className="fineprint">{counts.join(" · ")}</div>}
      {leg.answers.length > 1 && (
        <div className="fineprint">
          {leg.answers
            .map((answer) => {
              const label = ANSWER_LABEL[answer.kind] ?? answer.kind;
              return answer.source_name ? `${label} (${answer.source_name})` : label;
            })
            .join(" + ")}
        </div>
      )}
    </div>
  );
}
