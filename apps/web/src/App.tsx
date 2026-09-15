import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api/client";
import type { CompoundRow, ProjectDetail } from "./api/types";
import { CompoundTable } from "./components/CompoundTable";
import { EvidencePanel } from "./components/EvidencePanel";
import { ExportMenu } from "./components/ExportMenu";
import { FamilySidebar } from "./components/FamilySidebar";
import { ProjectsDialog } from "./components/ProjectsDialog";
import { SaveToProjectDialog } from "./components/SaveToProjectDialog";
import { StructureDrawer } from "./components/StructureDrawer";
import type { StructureSearchSummary } from "./components/StructureSearchDialog";
const StructureSearchDialog = lazy(() => import("./components/StructureSearchDialog").then((m) => ({ default: m.StructureSearchDialog })));
import { SearchBar } from "./components/SearchBar";
import { TopBar } from "./components/TopBar";
import { EmptyState, NoStructuresNote, SkeletonRows, StateBanner } from "./components/states";
import { readUrlState, subscribeUrlState, writeUrlState, type UrlState } from "./state/url";

/** Server page size for the plain compound table. Pages are appended by real
 * offset pagination (the API caps a single response at 500 rows). */
const PLAIN_PAGE_SIZE = 100;

/** A paging failure belongs to the request it came from: a stale error must
 * never surface on a newer query/family/document. */
interface PagingError {
  requestKey: string;
  message: string;
}

export function App() {
  const queryClient = useQueryClient();
  const [urlState, setUrlState] = useState<UrlState>(() => readUrlState());
  const [submittedQuery, setSubmittedQuery] = useState<string | null>(urlState.q);
  const [lastGoodQuery, setLastGoodQuery] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [saveOpen, setSaveOpen] = useState(false);
  const [structureOpenId, setStructureOpenId] = useState<string | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [sarMode, setSarMode] = useState(false);
  const [searchSummary, setSearchSummary] = useState<StructureSearchSummary | null>(null);
  const [projectsOpen, setProjectsOpen] = useState(false);
  const [openedProject, setOpenedProject] = useState<ProjectDetail | null>(null);
  const [projectError, setProjectError] = useState<string | null>(null);
  // Selection restored by an opened project, applied once its family is on
  // screen (the context-reset effect clears selections on family changes, so
  // applying earlier would be wiped by the navigation itself).
  const [pendingProjectSelection, setPendingProjectSelection] = useState<{
    familyId: string;
    publicationNumber: string;
    ids: string[];
  } | null>(null);
  const projectNavigationAbort = useRef<AbortController | null>(null);
  const [openedProjectFamilyId, setOpenedProjectFamilyId] = useState<string | null>(null);
  const [projectLoading, setProjectLoading] = useState(false);
  // Structure-result paging: one in-flight request at a time, abortable on any
  // context change; the error is tagged with the request it belongs to.
  const [structurePaging, setStructurePaging] = useState(false);
  const [structurePagingError, setStructurePagingError] = useState<PagingError | null>(null);
  const structurePagingAbort = useRef<AbortController | null>(null);

  const updateUrl = useCallback((next: UrlState, mode: "push" | "replace" = "replace") => {
    setUrlState(next);
    writeUrlState(next, mode);
  }, []);

  const { data: datasetInfo } = useQuery({
    queryKey: ["dataset"],
    queryFn: ({ signal }) => api.datasetInfo(signal),
    staleTime: 5 * 60_000,
  });

  // Patent lookup for the submitted publication number.
  const patentQuery = useQuery({
    queryKey: ["patent", submittedQuery],
    queryFn: ({ signal }) => api.patent(submittedQuery as string, signal),
    enabled: submittedQuery !== null,
    retry: (count, error) => (error as { status?: number })?.status === 0 && count < 2,
  });

  const familyId = patentQuery.data?.family.id ?? null;

  // Compounds for the family, optionally scoped to one document. Pages are
  // fetched by offset and appended, so row 501+ is reachable without ever
  // re-downloading a growing first page (UI-07).
  const compoundsQuery = useInfiniteQuery({
    queryKey: ["compounds", familyId, urlState.doc],
    queryFn: ({ pageParam, signal }) =>
      api.compounds(
        familyId as string,
        urlState.doc,
        signal,
        PLAIN_PAGE_SIZE,
        pageParam as number,
      ),
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.offset + lastPage.items.length < lastPage.total
        ? lastPage.offset + lastPage.items.length
        : undefined,
    enabled: familyId !== null,
    staleTime: 5 * 60_000,
  });

  const plainItems: CompoundRow[] = useMemo(
    () => compoundsQuery.data?.pages.flatMap((p) => p.items) ?? [],
    [compoundsQuery.data],
  );
  const plainPages = compoundsQuery.data?.pages;
  const plainTotal = plainPages?.length ? (plainPages[plainPages.length - 1]?.total ?? 0) : 0;

  // Rows the table currently shows: a structure filter replaces the plain list.
  const displayedRows: CompoundRow[] = searchSummary ? searchSummary.rows : plainItems;
  // Inspection follows the selected object in either scope, including rows from
  // a structure page that the plain first page does not contain.
  const loadedRowPool = useMemo(
    () => (searchSummary ? [...searchSummary.rows, ...plainItems] : plainItems),
    [searchSummary, plainItems],
  );
  const findLoadedRow = useCallback(
    (compoundId: string | null): CompoundRow | null =>
      compoundId
        ? (loadedRowPool.find((r) => r.compound.id === compoundId) ?? null)
        : null,
    [loadedRowPool],
  );

  // Evidence for the inspected compound.
  const evidenceQuery = useQuery({
    queryKey: ["evidence", urlState.c],
    queryFn: ({ signal }) => api.evidence(urlState.c as string, signal),
    enabled: urlState.c !== null,
  });

  const selectedRow = useMemo(() => findLoadedRow(urlState.c), [findLoadedRow, urlState.c]);

  const cancelProjectNavigation = useCallback(() => {
    if (projectNavigationAbort.current) {
      setOpenedProject(null);
      setOpenedProjectFamilyId(null);
      setProjectError(null);
    }
    projectNavigationAbort.current?.abort();
    projectNavigationAbort.current = null;
    setPendingProjectSelection(null);
    setProjectLoading(false);
  }, []);

  const closeProject = useCallback(() => {
    cancelProjectNavigation();
    setOpenedProject(null);
    setOpenedProjectFamilyId(null);
    setProjectError(null);
  }, [cancelProjectNavigation]);

  useEffect(() => () => projectNavigationAbort.current?.abort(), []);

  const handleSearch = (value: string) => {
    closeProject();
    if (value === submittedQuery) {
      queryClient.invalidateQueries({ queryKey: ["patent", value] });
      return;
    }
    setSubmittedQuery(value);
    // A new query is a navigation step: browser Back returns to the previous search.
    updateUrl({ q: value, doc: null, c: null }, "push");
  };

  const handleCancelSearch = () => {
    queryClient.cancelQueries({ queryKey: ["patent", submittedQuery] });
    // Restore the last successfully loaded patent, if any.
    setSubmittedQuery(lastGoodQuery);
  };

  useEffect(() => {
    if (patentQuery.isSuccess) setLastGoodQuery(submittedQuery);
  }, [patentQuery.isSuccess, submittedQuery]);

  // Browser Back/Forward restores the encoded context (q/doc/c).
  useEffect(
    () =>
      subscribeUrlState((restored) => {
        closeProject();
        setUrlState(restored);
        setSubmittedQuery(restored.q);
        setLastGoodQuery(restored.q);
      }),
    [closeProject],
  );

  const handleSelectDoc = (docId: string | null) => {
    cancelProjectNavigation();
    updateUrl({ ...urlState, doc: docId });
  };

  const handleSelectCompound = (compoundId: string) => {
    cancelProjectNavigation();
    updateUrl({ ...urlState, c: compoundId });
  };

  const handleCloseEvidence = useCallback(() => {
    cancelProjectNavigation();
    // Capture the row before clearing selection so focus can return to it.
    const rowToFocus = document.querySelector<HTMLElement>('[role="row"][aria-selected="true"]');
    updateUrl({ ...urlState, c: null });
    setTimeout(() => rowToFocus?.focus(), 0);
  }, [cancelProjectNavigation, updateUrl, urlState]);

  const toggleSelection = useCallback((compoundId: string, checked: boolean) => {
    cancelProjectNavigation();
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(compoundId);
      else next.delete(compoundId);
      return next;
    });
  }, [cancelProjectNavigation]);

  const toggleSelectAllLoaded = useCallback(
    (checked: boolean) => {
      cancelProjectNavigation();
      const loaded = displayedRows.map((r) => r.compound.id);
      setSelectedIds((prev) => {
        const next = new Set(prev);
        for (const id of loaded) {
          if (checked) next.add(id);
          else next.delete(id);
        }
        return next;
      });
    },
    [cancelProjectNavigation, displayedRows],
  );

  // Reset bulk selection and paging state whenever the scope or query changes:
  // stale selections and stale pages must never silently carry into a new
  // context, and in-flight paging responses are discarded on arrival.
  useEffect(() => {
    structurePagingAbort.current?.abort();
    structurePagingAbort.current = null;
    setSelectedIds(new Set());
    setSearchSummary(null);
    setStructurePaging(false);
    setStructurePagingError(null);
  }, [familyId, urlState.doc, submittedQuery]);

  useEffect(() => () => structurePagingAbort.current?.abort(), []);

  // Apply search results only if they belong to the family still on screen
  // (the dialog also aborts on close; this guards late responses after a
  // context switch that outlived the dialog).
  const applySearchResults = useCallback(
    (summary: StructureSearchSummary) => {
      if (!patentQuery.data || patentQuery.data.family.id !== summary.familyId) return;
      // A new search supersedes any paging request and error of the old one.
      structurePagingAbort.current?.abort();
      structurePagingAbort.current = null;
      setStructurePaging(false);
      setStructurePagingError(null);
      setSearchSummary(summary);
      setSelectedIds(new Set());
      setSearchOpen(false);
    },
    [patentQuery.data],
  );

  // Navigation and restored selection belong to one explicit project/family
  // request. Closing, searching or opening a different family obsoletes it.
  const openProjectFamily = useCallback(
    async (project: ProjectDetail, savedFamilyId: string) => {
      cancelProjectNavigation();
      const controller = new AbortController();
      projectNavigationAbort.current = controller;
      setOpenedProject(project);
      setOpenedProjectFamilyId(savedFamilyId);
      setProjectError(null);
      setProjectLoading(true);
      setSelectedIds(new Set());
      try {
        const family = await api.family(savedFamilyId, controller.signal);
        if (controller.signal.aborted) return;
        const doc = family.documents[0];
        if (!doc) throw new Error("The saved family has no documents in the current data.");
        const ids = project.items
          .filter((it) => it.family_id === savedFamilyId && !it.record_missing)
          .map((it) => it.compound_id)
          .filter((id): id is string => id !== null);
        structurePagingAbort.current?.abort();
        setSearchSummary(null);
        setStructurePaging(false);
        setStructurePagingError(null);
        setSearchOpen(false);
        setStructureOpenId(null);
        setSubmittedQuery(doc.publication_number);
        updateUrl({ q: doc.publication_number, doc: null, c: null },
          doc.publication_number === submittedQuery ? "replace" : "push");
        setPendingProjectSelection({ familyId: savedFamilyId, publicationNumber: doc.publication_number, ids });
      } catch (err) {
        if (!controller.signal.aborted) {
          setProjectError((err as Error).message || "The saved family could not be loaded.");
        }
      } finally {
        if (projectNavigationAbort.current === controller) {
          projectNavigationAbort.current = null;
          setProjectLoading(false);
        }
      }
    },
    [cancelProjectNavigation, submittedQuery, updateUrl],
  );

  const openProject = useCallback((project: ProjectDetail) => {
    cancelProjectNavigation();
    setProjectsOpen(false);
    setOpenedProject(project);
    setProjectError(null);
    setSelectedIds(new Set());
    setOpenedProjectFamilyId(null);
    const first = project.items.find((it) => !it.record_missing) ?? project.items[0];
    if (first) void openProjectFamily(project, first.family_id);
    else {
      structurePagingAbort.current?.abort();
      setSearchSummary(null);
      setStructurePaging(false);
      setStructurePagingError(null);
      setSubmittedQuery(null);
      updateUrl({ q: null, doc: null, c: null });
    }
  }, [cancelProjectNavigation, openProjectFamily, updateUrl]);

  useEffect(() => {
    if (!pendingProjectSelection || !patentQuery.data) return;
    if (submittedQuery !== pendingProjectSelection.publicationNumber || urlState.doc !== null) return;
    if (patentQuery.data.family.id !== pendingProjectSelection.familyId) return;
    setSelectedIds(new Set(pendingProjectSelection.ids));
    setPendingProjectSelection(null);
  }, [pendingProjectSelection, patentQuery.data, submittedQuery, urlState.doc]);

  const openedProjectFamilies = useMemo(() => {
    const families = new Map<string, string>();
    for (const item of openedProject?.items ?? []) families.set(item.family_id, item.family_key);
    return Array.from(families, ([id, label]) => ({ id, label }));
  }, [openedProject]);

  const openedProjectVersions = useMemo(() => {
    if (!openedProject) return [] as string[];
    const seen = new Set<string>();
    for (const it of openedProject.items) {
      for (const v of it.dataset_versions ?? []) {
        seen.add(`${v.dataset_version} (${v.source_name})`);
      }
      if (!it.dataset_versions?.length) seen.add(it.dataset_version);
    }
    return Array.from(seen).sort();
  }, [openedProject]);

  const openedProjectDrift = useMemo(() => {
    if (!openedProject) return { missing: 0, updated: 0 };
    return {
      missing: openedProject.items.filter((it) => it.record_missing).length,
      updated: openedProject.items.filter((it) => it.source_updated).length,
    };
  }, [openedProject]);

  const loadMoreResults = useCallback(async () => {
    if (!searchSummary || !searchSummary.requestParams || structurePaging) return;
    const ctxFamily = searchSummary.familyId;
    const ctxKey = searchSummary.requestKey;
    structurePagingAbort.current?.abort();
    const controller = new AbortController();
    structurePagingAbort.current = controller;
    setStructurePaging(true);
    setStructurePagingError(null);
    try {
      const body = await api.structureSearch(
        ctxFamily,
        {
          ...searchSummary.requestParams,
          offset: searchSummary.rows.length,
          limit: searchSummary.limit,
        },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      // The context may have changed while the page was loading.
      if (patentQuery.data && patentQuery.data.family.id !== ctxFamily) return;
      const items = body.items.map((it) => ({
        compound: it.compound,
        mentions: it.mentions,
        activity: [],
      }));
      setSearchSummary((prev) => {
        if (!prev || prev.familyId !== ctxFamily || prev.requestKey !== ctxKey) return prev;
        const scores = { ...prev.scores };
        for (const it of body.items) {
          if (it.score != null) scores[it.compound.inchikey] = it.score;
        }
        return {
          ...prev,
          offset: body.offset,
          total: body.total,
          rows: [...prev.rows, ...items],
          scores,
        };
      });
    } catch (err) {
      // Load-more failures keep the loaded rows and surface a retryable error
      // that belongs to this request; a superseded request reports nothing.
      if (controller.signal.aborted) return;
      setStructurePagingError({
        requestKey: ctxKey,
        message: (err as Error)?.message ?? "The next structure page could not be loaded.",
      });
    } finally {
      if (structurePagingAbort.current === controller) {
        structurePagingAbort.current = null;
        setStructurePaging(false);
      }
    }
  }, [searchSummary, structurePaging, patentQuery.data]);

  const structureRow = useMemo(
    () => findLoadedRow(structureOpenId),
    [findLoadedRow, structureOpenId],
  );

  // Keep the URL in sync with async query completion (e.g. restored state).
  useEffect(() => {
    document.title = submittedQuery
      ? `${submittedQuery} — SPAgo`
      : "SPAgo — small molecule patent analysis";
  }, [submittedQuery]);

  const patentError = patentQuery.error as (Error & { status?: number }) | null;
  const searching = patentQuery.isFetching || (submittedQuery !== null && patentQuery.isLoading);

  const scopeLabel =
    urlState.doc && patentQuery.data
      ? (patentQuery.data.documents.find((d) => d.id === urlState.doc)?.publication_number ??
        "selected document")
      : patentQuery.data
        ? `family ${patentQuery.data.family.family_key}`
        : "the current scope";

  return (
    <div className="app">
      <TopBar onOpenProjects={() => { cancelProjectNavigation(); setProjectsOpen(true); }} />
      <SearchBar
        initialQuery={submittedQuery ?? ""}
        submitted={submittedQuery}
        isSearching={searching}
        error={
          patentError && patentError.status === 404
            ? patentError.message +
              (datasetInfo?.synthetic
                ? " Check the number, or try the demo patent."
                : " It is not covered by the currently loaded source data.")
            : null
        }
        onSearch={handleSearch}
        onCancel={handleCancelSearch}
      />

      {(submittedQuery !== null || openedProject !== null) && (
        <div className="workspace">
          <FamilySidebar
            patent={patentQuery.data ?? null}
            selectedDocId={urlState.doc}
            collapsed={!patentQuery.data || sidebarCollapsed}
            onSelectDoc={handleSelectDoc}
          />

          <main className="table-area" aria-busy={patentQuery.isFetching}>
            <div className="table-header">
              <h1>{patentQuery.data ? patentQuery.data.family.title : "Compounds"}</h1>
              <span className="scope-note">
                {compoundsQuery.data ? `${scopeLabel} · ${plainTotal} compounds` : null}
              </span>
              <span className="spacer" />
              {patentQuery.data && plainTotal > 0 && (
                <>
                  <button className="btn btn-quiet" onClick={() => { cancelProjectNavigation(); setSearchOpen(true); }}>
                    Structure ▾
                  </button>
                  <button
                    className={`btn btn-quiet${sarMode ? " sar-active" : ""}`}
                    aria-pressed={sarMode}
                    title="Group compounds by Murcko scaffold"
                    onClick={() => setSarMode((s) => !s)}
                  >
                    Scaffold ▾
                  </button>
                  <button className="btn btn-primary" onClick={() => setSaveOpen(true)}>
                    Save to project
                  </button>
                  <ExportMenu
                    familyId={patentQuery.data.family.id}
                    documentId={urlState.doc}
                    selectedIds={Array.from(selectedIds)}
                    resultsTotal={plainTotal}
                    structureFilter={
                      searchSummary
                        ? {
                            mode: searchSummary.mode,
                            smiles: String(searchSummary.requestParams.smiles ?? ""),
                            threshold: searchSummary.threshold,
                            total: searchSummary.total,
                          }
                        : null
                    }
                  />
                </>
              )}
              <button
                className="btn btn-quiet sidebar-toggle"
                aria-expanded={!sidebarCollapsed}
                onClick={() => setSidebarCollapsed((c) => !c)}
              >
                {sidebarCollapsed ? "Show family" : "Hide family"}
              </button>
            </div>

            {openedProject && (
              <div className="project-banner" role="status">
                <span>
                  Project <strong>{openedProject.name}</strong> · {openedProject.item_count} saved
                  item{openedProject.item_count === 1 ? "" : "s"}
                  {openedProject.item_count === 0 && " · Nothing saved yet"}
                  {projectLoading && " · Opening saved family…"}
                  {openedProjectVersions.length > 0 && (
                    <> · source {openedProjectVersions.join(", ")}</>
                  )}
                  {openedProjectDrift.missing > 0 && (
                    <span className="paging-error">
                      {" "}
                      · {openedProjectDrift.missing} saved record(s) no longer in the data
                    </span>
                  )}
                  {openedProjectDrift.updated > 0 && (
                    <span className="paging-error">
                      {" "}
                      · {openedProjectDrift.updated} record(s) changed source version since saving
                    </span>
                  )}
                </span>
                {openedProjectFamilies.length > 1 && (
                  <label>
                    Saved family{" "}
                    <select className="select-input" value={openedProjectFamilyId ?? ""}
                      onChange={(event) => void openProjectFamily(openedProject, event.target.value)}>
                      {openedProjectFamilies.map((family) => (
                        <option key={family.id} value={family.id}>{family.label}</option>
                      ))}
                    </select>
                  </label>
                )}
                <span className="spacer" />
                <button
                  className="show-all-occ"
                  onClick={closeProject}
                  aria-label="Close project view"
                >
                  Close project ×
                </button>
              </div>
            )}
            {projectError && (
              <StateBanner kind="error" message={projectError} onRetry={() => {
                if (openedProject && openedProjectFamilyId) void openProjectFamily(openedProject, openedProjectFamilyId);
              }} />
            )}

            {searchSummary && (
              <div className="search-chip" role="status">
                <span>
                  {searchSummary.mode === "similarity"
                    ? `Similarity (Tanimoto ≥ ${searchSummary.threshold?.toFixed(2)})`
                    : searchSummary.mode === "exact"
                      ? "Exact structure"
                      : "Substructure"}{" "}
                  · current family ·{" "}
                  <span className="mono">{searchSummary.query_canonical_smiles}</span> ·{" "}
                  {searchSummary.total} result{searchSummary.total === 1 ? "" : "s"}
                </span>
                <button
                  className="show-all-occ"
                  onClick={() => {
                    // Removing the filter also discards its in-flight next page
                    // and any error that belonged to it.
                    structurePagingAbort.current?.abort();
                    structurePagingAbort.current = null;
                    setStructurePaging(false);
                    setStructurePagingError(null);
                    setSearchSummary(null);
                  }}
                  aria-label="Remove structure filter"
                >
                  Remove ×
                </button>
              </div>
            )}

            {patentError && patentError.status !== 404 && (
              <StateBanner
                kind="error"
                message={patentError.message}
                onRetry={() => patentQuery.refetch()}
              />
            )}

            {patentQuery.isLoading ? (
              <SkeletonRows />
            ) : patentQuery.data ? (
              searchSummary ? (
                searchSummary.rows.length > 0 ? (
                  <CompoundTable
                    page={{
                      total: searchSummary.total,
                      offset: 0,
                      limit: searchSummary.limit,
                      items: searchSummary.rows,
                    }}
                    selectedCompoundId={urlState.c}
                    selectedIds={selectedIds}
                    sarMode={sarMode}
                    scopeLabel={`${scopeLabel} (structure search)`}
                    sourceNote={
                      datasetInfo && !datasetInfo.synthetic
                        ? `Source: ${datasetInfo.source_name} · ${datasetInfo.dataset_version}`
                        : undefined
                    }
                    onLoadMore={loadMoreResults}
                    loadingMore={structurePaging}
                    loadMoreError={
                      structurePagingError?.requestKey === searchSummary.requestKey
                        ? structurePagingError.message
                        : null
                    }
                    onToggleSelection={toggleSelection}
                    onToggleSelectAll={toggleSelectAllLoaded}
                    onClearSelection={() => { cancelProjectNavigation(); setSelectedIds(new Set()); }}
                    onOpenStructure={(id) => setStructureOpenId(id)}
                    onSelectCompound={handleSelectCompound}
                  />
                ) : (
                  <div className="state-banner" role="status">
                    <span>
                      No compounds in the current family match this structure query.
                    </span>
                  </div>
                )
              ) : compoundsQuery.isLoading ? (
                <SkeletonRows />
              ) : compoundsQuery.data ? (
                plainTotal === 0 ? (
                  <NoStructuresNote scopeLabel={scopeLabel} />
                ) : (
                  <CompoundTable
                    page={{
                      total: plainTotal,
                      offset: 0,
                      limit: PLAIN_PAGE_SIZE,
                      items: plainItems,
                    }}
                    selectedCompoundId={urlState.c}
                    selectedIds={selectedIds}
                    sarMode={sarMode}
                    scopeLabel={scopeLabel}
                    sourceNote={
                      datasetInfo && !datasetInfo.synthetic
                        ? `Source: ${datasetInfo.source_name} · ${datasetInfo.dataset_version}`
                        : undefined
                    }
                    onLoadMore={() => {
                      if (!compoundsQuery.isFetchingNextPage) compoundsQuery.fetchNextPage();
                    }}
                    loadingMore={compoundsQuery.isFetchingNextPage}
                    loadMoreError={
                      compoundsQuery.isFetchNextPageError
                        ? ((compoundsQuery.error as Error | null)?.message ??
                          "The next page could not be loaded.")
                        : null
                    }
                    onToggleSelection={toggleSelection}
                    onToggleSelectAll={toggleSelectAllLoaded}
                    onClearSelection={() => { cancelProjectNavigation(); setSelectedIds(new Set()); }}
                    onOpenStructure={(id) => setStructureOpenId(id)}
                    onSelectCompound={handleSelectCompound}
                  />
                )
              ) : (
                <StateBanner
                  kind="error"
                  message={
                    (compoundsQuery.error as Error | null)?.message ??
                    "Compound list could not be loaded."
                  }
                  onRetry={() => compoundsQuery.refetch()}
                />
              )
            ) : null}

            {datasetInfo && datasetInfo.ingestion_issues.length > 0 && patentQuery.data && (
              <div className="state-banner" style={{ marginTop: 12 }}>
                <span>
                  {datasetInfo.ingestion_issues.length} source record
                  {datasetInfo.ingestion_issues.length === 1 ? "" : "s"} in this dataset had
                  invalid structures and were recorded as ingestion issues (never shown as
                  compounds).
                </span>
              </div>
            )}
          </main>

          {urlState.c && selectedRow && (
            <EvidencePanel
              compound={selectedRow.compound}
              mentions={selectedRow.mentions}
              familyId={patentQuery.data ? patentQuery.data.family.id : ""}
              familyKey={patentQuery.data ? patentQuery.data.family.family_key : ""}
              evidence={evidenceQuery.data}
              evidenceLoading={evidenceQuery.isFetching}
              evidenceError={(evidenceQuery.error as Error | null)?.message ?? null}
              onClose={handleCloseEvidence}
            />
          )}
        </div>
      )}

      {submittedQuery === null && !openedProject && (
        <EmptyState
          demoHint={datasetInfo?.synthetic ? "DEMO-PATENT-A" : null}
          sourceNote={
            datasetInfo
              ? datasetInfo.synthetic
                ? null
                : `Loaded source: ${datasetInfo.source_name} · ${datasetInfo.dataset_version}. Enter a covered publication number to open its family.`
              : null
          }
        />
      )}

      {projectsOpen && (
        <ProjectsDialog onClose={() => setProjectsOpen(false)} onOpen={openProject} />
      )}

      {saveOpen && patentQuery.data && (
        <SaveToProjectDialog
          familyId={patentQuery.data.family.id}
          familyKey={patentQuery.data.family.family_key}
          datasetVersion={datasetInfo?.dataset_version ?? "unknown"}
          sourceIsSynthetic={datasetInfo?.synthetic ?? true}
          selectedIds={Array.from(selectedIds)}
          onClose={() => setSaveOpen(false)}
        />
      )}

      {structureRow && (
        <StructureDrawer
          compound={structureRow.compound}
          labels={structureRow.mentions.map((m) =>
            [m.publication_number, m.patent_label].filter(Boolean).join(" · "),
          )}
          onClose={() => setStructureOpenId(null)}
        />
      )}

      {searchOpen && patentQuery.data && (
        <Suspense fallback={null}>
        <StructureSearchDialog
          familyId={patentQuery.data.family.id}
          scopeLabel={patentQuery.data.family.family_key}
          onClose={() => setSearchOpen(false)}
          onResults={applySearchResults}
        />
        </Suspense>
      )}

      <span className="a11y-status" role="status" aria-live="polite">
        {patentQuery.data
          ? `Family ${patentQuery.data.family.family_key} loaded`
          : searching
            ? "Searching"
            : ""}
      </span>
    </div>
  );
}
