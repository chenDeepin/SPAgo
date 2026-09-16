/** URL state contract (design doc §9): q, doc, c survive reload and back.
 *
 * History granularity (UI review round): submitting a new patent query pushes a
 * history entry (browser Back returns to the previous query); document scope
 * and compound selection are view state and replace the current entry. A
 * popstate listener restores the encoded context for Back/Forward; large
 * structures are never encoded (query results are re-runnable from q).
 *
 * ONLINE-00 extends the same contract to target investigations: `t` is the
 * resolved target id, `q` holds the requested target query (a gene symbol or
 * accession), and `c` selects a candidate. Only identifiers are encoded — never
 * structures, SMILES or result sets. */

export interface UrlState {
  q: string | null; // patent publication number, or a requested target query
  doc: string | null; // selected document id (document scope)
  c: string | null; // selected compound id
  t: string | null; // resolved target id (target investigation)
}

/** Deterministic publication-number shape, mirrored from
 * `spago_core/domain/patent_numbers.py::looks_like_publication_number` (a parity
 * test keeps the two identical; keep them in step by changing both).
 *
 * Separators are removed first, so one rule covers "WO-2020-123456-A" and
 * "wo 2020/123456" alike, and the presence of a kind code does not matter. The
 * whole string must be the number: prose is never turned into an identifier, and
 * the server stays authoritative about what exists. */
const PUBLICATION_NUMBER = /^[A-Z]{2}\d{6,13}(?:[A-Z]\d?)?$/;
const PUBLICATION_SEPARATORS = /[\s\-/.,]+/g;

/** The number without separators, uppercased. */
export function canonicalPublicationNumber(value: string): string {
  return value.replace(PUBLICATION_SEPARATORS, "").toUpperCase();
}

export function looksLikePublicationNumber(value: string): boolean {
  return PUBLICATION_NUMBER.test(canonicalPublicationNumber(value));
}

/** The form of the number that travels in a request path.
 *
 * A "/" cannot be a path segment: `GET /patents/wo%202020%2F123456` is decoded
 * before routing, so the server sees two segments and answers a bare 404 that says
 * nothing about the patent (observed on the local stack, 2026-09-16). Only that
 * case is canonicalized; everything else travels exactly as typed, so a number
 * spelled the way the corpus stores it still takes the exact, indexed lookup
 * instead of being "helpfully" rewritten. The typed query stays in the URL and on
 * screen, and the answer names the identifier the corpus actually stores. */
export function publicationPath(value: string): string {
  return value.includes("/") ? canonicalPublicationNumber(value) : value.trim();
}

export function readUrlState(): UrlState {
  const params = new URLSearchParams(window.location.search);
  return {
    q: params.get("q"),
    doc: params.get("doc"),
    c: params.get("c"),
    t: params.get("t"),
  };
}

export function writeUrlState(state: UrlState, mode: "push" | "replace" = "replace"): void {
  const params = new URLSearchParams();
  if (state.q) params.set("q", state.q);
  if (state.doc) params.set("doc", state.doc);
  if (state.c) params.set("c", state.c);
  if (state.t) params.set("t", state.t);
  const qs = params.toString();
  const url = `${window.location.pathname}${qs ? `?${qs}` : ""}`;
  if (mode === "push") {
    window.history.pushState({ spago: state }, "", url);
  } else {
    window.history.replaceState({ spago: state }, "", url);
  }
}

/** Re-apply encoded state on browser Back/Forward. Returns an unsubscribe. */
export function subscribeUrlState(onChange: (state: UrlState) => void): () => void {
  const handler = () => onChange(readUrlState());
  window.addEventListener("popstate", handler);
  return () => window.removeEventListener("popstate", handler);
}
