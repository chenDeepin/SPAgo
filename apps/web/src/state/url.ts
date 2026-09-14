/** URL state contract (design doc §9): q, doc, c survive reload and back.
 *
 * History granularity (UI review round): submitting a new patent query pushes a
 * history entry (browser Back returns to the previous query); document scope
 * and compound selection are view state and replace the current entry. A
 * popstate listener restores the encoded context for Back/Forward; large
 * structures are never encoded (query results are re-runnable from q). */

export interface UrlState {
  q: string | null; // patent publication number
  doc: string | null; // selected document id (document scope)
  c: string | null; // selected compound id
}

export function readUrlState(): UrlState {
  const params = new URLSearchParams(window.location.search);
  return {
    q: params.get("q"),
    doc: params.get("doc"),
    c: params.get("c"),
  };
}

export function writeUrlState(state: UrlState, mode: "push" | "replace" = "replace"): void {
  const params = new URLSearchParams();
  if (state.q) params.set("q", state.q);
  if (state.doc) params.set("doc", state.doc);
  if (state.c) params.set("c", state.c);
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
