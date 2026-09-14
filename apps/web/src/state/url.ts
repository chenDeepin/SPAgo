/** URL state contract (design doc §9): q, doc, c survive reload and back. */

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

export function writeUrlState(state: UrlState): void {
  const params = new URLSearchParams();
  if (state.q) params.set("q", state.q);
  if (state.doc) params.set("doc", state.doc);
  if (state.c) params.set("c", state.c);
  const qs = params.toString();
  const url = `${window.location.pathname}${qs ? `?${qs}` : ""}`;
  window.history.replaceState(null, "", url);
}
