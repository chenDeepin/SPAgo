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

async function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: "POST",
      signal,
      headers: { "Content-Type": "application/json", Accept: "application/json" },
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
      headers: { "Content-Type": "application/json" },
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

export const api = {
  health: (signal?: AbortSignal) => getJson<import("./types").HealthResponse>("/healthz", signal),
  datasetInfo: (signal?: AbortSignal) =>
    getJson<import("./types").DatasetInfoResponse>("/api/v1/datasets/info", signal),
  patent: (publicationNumber: string, signal?: AbortSignal) =>
    getJson<import("./types").PatentResponse>(
      `/api/v1/patents/${encodeURIComponent(publicationNumber)}`,
      signal,
    ),
  compounds: (
    familyId: string,
    documentId: string | null,
    signal?: AbortSignal,
    limit = 100,
  ) => {
    const params = new URLSearchParams({ limit: String(limit) });
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
    family_id: string;
    document_id?: string | null;
    compound_ids?: string[] | null;
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
  familySummary: (familyId: string, signal?: AbortSignal) =>
    postJson<import("./types").FamilySummaryResponse>(
      `/api/v1/families/${familyId}/summary`,
      {},
      signal,
    ),
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
};
