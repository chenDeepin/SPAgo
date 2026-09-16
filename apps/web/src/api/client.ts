/** Typed, abortable fetch client for the SPAgo core API. */

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { signal, headers: { Accept: "application/json" } });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, "Source unavailable: the SPAgo service could not be reached.");
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep generic detail */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

/** Double-submit CSRF value for hosted mode. The cookie is readable by design;
 * the session cookie is not. In local mode there is no cookie and no header. */
function csrfHeaders(): Record<string, string> {
  const match = document.cookie.match(/(?:^|;\s*)spago_csrf=([^;]+)/);
  return match ? { "X-Spago-CSRF": decodeURIComponent(match[1]) } : {};
}

async function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: "POST",
      signal,
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...csrfHeaders(),
      },
      body: JSON.stringify(body),
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, "Source unavailable: the SPAgo service could not be reached.");
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep generic detail */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

async function downloadFile(path: string, body: unknown, filename: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...csrfHeaders() },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Export failed: the SPAgo service could not be reached.");
  }
  if (!res.ok) {
    let detail = `Export failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* keep generic detail */
    }
    throw new ApiError(res.status, detail);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Fetch a file the server renders (no body) and hand it to the browser. */
async function downloadGet(path: string, filename: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(path, { headers: { Accept: "text/markdown" } });
  } catch {
    throw new ApiError(0, "Export failed: the SPAgo service could not be reached.");
  }
  if (!res.ok) {
    let detail = `Export failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* keep generic detail */
    }
    throw new ApiError(res.status, detail);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export const api = {  // --- ONLINE-03: hosted access ---
  authStatus: (signal?: AbortSignal) =>
    getJson<import("./types").AuthStatus>("/api/v1/auth/status", signal),
  redeemInvitation: (token: string, signal?: AbortSignal) =>
    postJson<import("./types").SessionInfo>("/api/v1/auth/invitations/redeem", { token }, signal),
  logout: (signal?: AbortSignal) => postJson<{ signed_out: boolean }>("/api/v1/auth/logout", {}, signal),
  usage: (signal?: AbortSignal) => getJson<import("./types").UsageReport>("/api/v1/usage", signal),
  health: (signal?: AbortSignal) => getJson<import("./types").HealthResponse>("/healthz", signal),
  datasetInfo: (signal?: AbortSignal) =>
    getJson<import("./types").DatasetInfoResponse>("/api/v1/datasets/info", signal),
  corpus: (signal?: AbortSignal) =>
    getJson<import("./types").CorpusResponse>("/api/v1/corpus", signal),
  // --- B-10: stored analyses ---
  analyses: (
    params: { scope?: string | null; search?: string | null; offset?: number; limit?: number },
    signal?: AbortSignal,
  ) => {
    const query = new URLSearchParams();
    if (params.scope) query.set("scope", params.scope);
    if (params.search) query.set("search", params.search);
    if (params.offset) query.set("offset", String(params.offset));
    if (params.limit) query.set("limit", String(params.limit));
    const suffix = query.toString();
    return getJson<import("./types").AnalysisListResponse>(
      `/api/v1/analyses${suffix ? `?${suffix}` : ""}`,
      signal,
    );
  },
  analysis: (analysisId: string, signal?: AbortSignal) =>
    getJson<import("./types").AnalysisDetail>(`/api/v1/analyses/${analysisId}`, signal),
  exportAnalysis: async (analysis: { analysis_id: string; scope: string }) => {
    await downloadGet(
      `/api/v1/analyses/${analysis.analysis_id}/export`,
      `spago-${analysis.scope}-analysis-${analysis.analysis_id.slice(0, 8)}.md`,
    );
  },
  patent: (publicationNumber: string, signal?: AbortSignal) =>
    getJson<import("./types").PatentResponse>(
      `/api/v1/patents/${encodeURIComponent(publicationNumber)}`,
      signal,
    ),
  // --- B-24: what a source declares for a publication ---
  patentSourceCompounds: (
    publicationNumber: string,
    params: { offset?: number; limit?: number } = {},
    signal?: AbortSignal,
  ) => {
    const query = new URLSearchParams();
    if (params.offset) query.set("offset", String(params.offset));
    if (params.limit) query.set("limit", String(params.limit));
    const suffix = query.toString();
    return getJson<import("./types").PatentSourceResponse>(
      `/api/v1/patents/${encodeURIComponent(publicationNumber)}/source-compounds${
        suffix ? `?${suffix}` : ""
      }`,
      signal,
    );
  },
  lookupPatentSourceCompounds: (publicationNumber: string, signal?: AbortSignal) =>
    postJson<import("./types").PatentSourceResponse>(
      `/api/v1/patents/${encodeURIComponent(publicationNumber)}/source-compounds`,
      {},
      signal,
    ),
  exportPatentSourceCompounds: async (
    publicationNumber: string,
    format: "csv" | "sdf",
  ) => {
    await downloadGet(
      `/api/v1/patents/${encodeURIComponent(publicationNumber)}/source-compounds/export?format=${format}`,
      `spago-${publicationNumber}-source-declared.${format}`,
    );
  },
  family: (familyId: string, signal?: AbortSignal) =>
    getJson<import("./types").FamilyResponse>(
      `/api/v1/families/${familyId}`,
      signal,
    ),
  compounds: (
    familyId: string,
    documentId: string | null,
    signal?: AbortSignal,
    limit = 100,
    offset = 0,
  ) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (documentId) params.set("document_id", documentId);
    return getJson<import("./types").CompoundPage>(
      `/api/v1/families/${familyId}/compounds?${params.toString()}`,
      signal,
    );
  },
  evidence: (compoundId: string, signal?: AbortSignal) =>
    getJson<import("./types").EvidenceRecord[]>(
      `/api/v1/compounds/${compoundId}/evidence`,
      signal,
    ),
  depictionUrl: (compoundId: string) => `/api/v1/compounds/${compoundId}/depiction`,
  // --- M1 ---
  projects: (signal?: AbortSignal) =>
    getJson<import("./types").ProjectSummary[]>("/api/v1/projects", signal),
  project: (id: string, signal?: AbortSignal) =>
    getJson<import("./types").ProjectDetail>(`/api/v1/projects/${id}`, signal),
  createProject: (name: string, signal?: AbortSignal) =>
    postJson<import("./types").ProjectSummary>("/api/v1/projects", { name }, signal),
  saveScope: (
    projectId: string,
    body: { family_id: string; compound_ids: string[] | null; dataset_version: string },
    signal?: AbortSignal,
  ) =>
    postJson<import("./types").SaveScopeResult>(
      `/api/v1/projects/${projectId}/items`,
      body,
      signal,
    ),
  exportFile: async (body: {
    family_id?: string | null;
    target_id?: string | null;
    include_all_modalities?: boolean;
    document_id?: string | null;
    compound_ids?: string[] | null;
    structure_query?: {
      mode: string;
      smiles: string;
      threshold?: number | null;
    } | null;
    format: "csv" | "sdf";
  }) => {
    const ext = body.format;
    await downloadFile("/api/v1/export", body, `spago-export.${ext}`);
  },
  activity: (compoundId: string, signal?: AbortSignal) =>
    getJson<import("./types").ActivitySummary[]>(
      `/api/v1/compounds/${compoundId}/activity`,
      signal,
    ),
  familySummary: (familyId: string, mode: "offline" | "llm", signal?: AbortSignal) =>
    postJson<import("./types").FamilySummaryResponse>(
      `/api/v1/families/${familyId}/summary`,
      { mode },
      signal,
    ),
  documentSummary: (documentId: string, mode: "offline" | "llm", signal?: AbortSignal) =>
    postJson<import("./types").FamilySummaryResponse>(
      `/api/v1/documents/${documentId}/summary`,
      { mode },
      signal,
    ),
  targetSummary: (
    targetId: string,
    mode: "offline" | "llm",
    includeAllModalities = false,
    signal?: AbortSignal,
  ) =>
    postJson<import("./types").FamilySummaryResponse>(
      `/api/v1/targets/${targetId}/summary`,
      { mode, include_all_modalities: includeAllModalities },
      signal,
    ),
  plan: (
    body: {
      query: string;
      family_id?: string | null;
      document_id?: string | null;
      selected_compound_id?: string | null;
      use_llm?: boolean;
    },
    signal?: AbortSignal,
  ) => postJson<import("./types").SearchPlanResponse>("/api/v1/ai/plan", body, signal),
  executePlan: (plan: Record<string, unknown>, signal?: AbortSignal) =>
    postJson<import("./types").PlanExecuteResponse>("/api/v1/ai/plan/execute", { plan }, signal),
  aiStatus: (signal?: AbortSignal) =>
    getJson<import("./types").AiStatusResponse>("/api/v1/ai/status", signal),
  // --- M2 ---
  structureSearch: (
    familyId: string,
    params: Record<string, unknown>,
    signal?: AbortSignal,
  ) =>
    postJson<import("./types").StructureSearchResponse>(
      `/api/v1/families/${familyId}/structure-search`,
      params,
      signal,
    ),
  // --- ONLINE-00: target-led investigation ---
  resolveTarget: (
    body: { query: string; species?: string; include_related?: boolean },
    signal?: AbortSignal,
  ) => postJson<import("./types").TargetResolution>("/api/v1/targets/resolve", body, signal),
  target: (targetId: string, signal?: AbortSignal) =>
    getJson<import("./types").ResolvedTarget>(`/api/v1/targets/${targetId}`, signal),
  discoverTarget: (
    body: { target_id: string; sources?: string[] },
    signal?: AbortSignal,
  ) => postJson<import("./types").DiscoverResponse>("/api/v1/targets/discover", body, signal),
  targetCoverage: (targetId: string, signal?: AbortSignal) =>
    getJson<import("./types").SourceRetrieval[]>(
      `/api/v1/targets/${targetId}/coverage`,
      signal,
    ),
  /** ONLINE-06: the potency-reference verdict for a target.
   *
   * `thresholdNanomolar` is an explicit, user-stated override (validated
   * server-side); omitting it asks for the deployment policy. The verdict is
   * always recomputed from stored rows, so a changed threshold can never leave
   * a stale class behind. */
  targetReference: (
    targetId: string,
    params: { thresholdNanomolar?: number | null; includeAllModalities?: boolean } = {},
    signal?: AbortSignal,
  ) => {
    const search = new URLSearchParams();
    if (params.thresholdNanomolar != null) {
      search.set("activity_threshold_nm", String(params.thresholdNanomolar));
    }
    if (params.includeAllModalities) search.set("include_all_modalities", "true");
    const suffix = search.toString();
    return getJson<import("./types").ReferenceVerdict>(
      `/api/v1/targets/${targetId}/reference${suffix ? `?${suffix}` : ""}`,
      signal,
    );
  },
  targetCandidates: (
    targetId: string,
    params: {
      offset?: number;
      limit?: number;
      modality?: string | null;
      evidence_class?: string | null;
      include_all_modalities?: boolean;
      activity_threshold_nm?: number | null;
      /** Defect D2: keep these compounds visible (labelled rows) even when the
       * filter excludes them — the selected one and every item an opened project
       * saved for this target. */
      include_compound_ids?: string[];
    },
    signal?: AbortSignal,
  ) => {
    const search = new URLSearchParams();
    search.set("limit", String(params.limit ?? 100));
    search.set("offset", String(params.offset ?? 0));
    if (params.modality) search.set("modality", params.modality);
    if (params.evidence_class) search.set("evidence_class", params.evidence_class);
    if (params.include_all_modalities) search.set("include_all_modalities", "true");
    if (params.activity_threshold_nm != null) {
      search.set("activity_threshold_nm", String(params.activity_threshold_nm));
    }
    for (const id of params.include_compound_ids ?? []) {
      search.append("include_compound_id", id);
    }
    return getJson<import("./types").CandidatePage>(
      `/api/v1/targets/${targetId}/candidates?${search.toString()}`,
      signal,
    );
  },
  targetMeasurements: (
    targetId: string,
    params: {
      compound_id?: string | null;
      evidence_class?: string | null;
      limit?: number;
      activity_threshold_nm?: number | null;
    },
    signal?: AbortSignal,
  ) => {
    const search = new URLSearchParams();
    search.set("limit", String(params.limit ?? 200));
    if (params.compound_id) search.set("compound_id", params.compound_id);
    if (params.evidence_class) search.set("evidence_class", params.evidence_class);
    if (params.activity_threshold_nm != null) {
      search.set("activity_threshold_nm", String(params.activity_threshold_nm));
    }
    return getJson<import("./types").TargetMeasurement[]>(
      `/api/v1/targets/${targetId}/measurements?${search.toString()}`,
      signal,
    );
  },
  saveCandidates: (
    projectId: string,
    body: { target_id: string; compound_ids: string[] },
    signal?: AbortSignal,
  ) =>
    postJson<{ created_rows: number; already_present_rows: number; target_key: string }>(
      `/api/v1/projects/${projectId}/candidates`,
      body,
      signal,
    ),
  targetSupplements: (
    targetId: string,
    rows: import("./types").SupplementRowInput[],
    signal?: AbortSignal,
  ) =>
    postJson<import("./types").SupplementImport>(
      `/api/v1/targets/${targetId}/supplements`,
      { rows },
      signal,
    ),
  targetSupplementRemarks: (targetId: string, signal?: AbortSignal) =>
    getJson<import("./types").SupplementRemark[]>(
      `/api/v1/targets/${targetId}/supplements/remarks`,
      signal,
    ),
  /** Rows this user added by hand and later took back: the audit trail behind the
   * verdict's `withdrawn_supplements` count (defect D3). */
  targetWithdrawnSupplements: (targetId: string, signal?: AbortSignal) =>
    getJson<import("./types").WithdrawnSupplement[]>(
      `/api/v1/targets/${targetId}/supplements/withdrawn`,
      signal,
    ),
  /** Take a hand-added row back. A reason is required by the API: a withdrawal
   * that cannot say why is a silent edit. The row is never deleted. */
  withdrawTargetSupplement: (
    targetId: string,
    recordId: string,
    reason: string,
    signal?: AbortSignal,
  ) =>
    postJson<import("./types").SupplementWithdrawal>(
      `/api/v1/targets/${targetId}/supplements/${encodeURIComponent(recordId)}/withdraw`,
      { reason },
      signal,
    ),
};
