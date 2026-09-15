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

/** Deterministic publication-number shape (the same rule the offline planner
 * uses). Used only to choose which server lookup to call: the server remains
 * authoritative about what exists, and a target query is never guessed from
 * free text. */
const PUBLICATION_NUMBER = /^[A-Z]{2}\d{5,12}[A-Z]\d?$/;

export function looksLikePublicationNumber(value: string): boolean {
  return PUBLICATION_NUMBER.test(value.trim().toUpperCase());
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
