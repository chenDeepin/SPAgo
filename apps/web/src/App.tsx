import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api/client";
import type { CompoundRow } from "./api/types";
import { CompoundTable } from "./components/CompoundTable";
import { EvidencePanel } from "./components/EvidencePanel";
import { ExportMenu } from "./components/ExportMenu";
import { FamilySidebar } from "./components/FamilySidebar";
import { SaveToProjectDialog } from "./components/SaveToProjectDialog";
import { StructureDrawer } from "./components/StructureDrawer";
import type { StructureSearchSummary } from "./components/StructureSearchDialog";
const StructureSearchDialog = lazy(() => import("./components/StructureSearchDialog").then((m) => ({ default: m.StructureSearchDialog })));
import { SearchBar } from "./components/SearchBar";
import { TopBar } from "./components/TopBar";
import { EmptyState, NoStructuresNote, SkeletonRows, StateBanner } from "./components/states";
import { readUrlState, subscribeUrlState, writeUrlState, type UrlState } from "./state/url";

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
  // Server-side page size for the plain compound table; grows via Load more up
  // to the API hard cap (500). Reset with the context.
  const [compoundsLimit, setCompoundsLimit] = useState(100);

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

  // Compounds for the family, optionally scoped to one document.
  const compoundsQuery = useQuery({
    queryKey: ["compounds", familyId, urlState.doc, compoundsLimit],
    queryFn: ({ signal }) =>
      api.compounds(familyId as string, urlState.doc, signal, compoundsLimit),
    enabled: familyId !== null,
    staleTime: 5 * 60_000,
  });

  // Evidence for the inspected compound.
  const evidenceQuery = useQuery({
    queryKey: ["evidence", urlState.c],
    queryFn: ({ signal }) => api.evidence(urlState.c as string, signal),
    enabled: urlState.c !== null,
  });

  // Selected compound row (from whichever page is loaded).
  const selectedRow: CompoundRow | null = useMemo(() => {
    if (!urlState.c || !compoundsQuery.data) return null;
    return (
      compoundsQuery.data.items.find((r) => r.compound.id === urlState.c) ?? null
    );
  }, [urlState.c, compoundsQuery.data]);

  const handleSearch = (value: string) => {
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
        setUrlState(restored);
        setSubmittedQuery(restored.q);
        setLastGoodQuery(restored.q);
      }),
    [],
  );

  const handleSelectDoc = (docId: string | null) => {
    updateUrl({ ...urlState, doc: docId });
  };

  const handleSelectCompound = (compoundId: string) => {
    updateUrl({ ...urlState, c: compoundId });
  };

  const handleCloseEvidence = useCallback(() => {
    // Capture the row before clearing selection so focus can return to it.
    const rowToFocus = document.querySelector<HTMLElement>('[role="row"][aria-selected="true"]');
    updateUrl({ ...urlState, c: null });
    setTimeout(() => rowToFocus?.focus(), 0);
  }, [updateUrl, urlState]);

  const toggleSelection = useCallback((compoundId: string, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(compoundId);
      else next.delete(compoundId);
      return next;
    });
  }, []);

  const toggleSelectAllLoaded = useCallback(
    (checked: boolean) => {
      const loaded = compoundsQuery.data?.items.map((r) => r.compound.id) ?? [];
      setSelectedIds((prev) => {
        const next = new Set(prev);
        for (const id of loaded) {
          if (checked) next.add(id);
          else next.delete(id);
        }
        return next;
      });
    },
    [compoundsQuery.data],
  );

  // Reset bulk selection whenever the scope or query changes: stale selections
  // must never silently carry into a new context.
  useEffect(() => {
    setSelectedIds(new Set());
    setSearchSummary(null);
    setCompoundsLimit(100);
  }, [familyId, urlState.doc, submittedQuery]);

  // Apply search results only if they belong to the family still on screen
  // (the dialog also aborts on close; this guards late responses after a
  // context switch that outlived the dialog).
  const applySearchResults = useCallback(
    (summary: StructureSearchSummary) => {
      if (!patentQuery.data || patentQuery.data.family.id !== summary.familyId) return;
      setSearchSummary(summary);
      setSelectedIds(new Set());
      setSearchOpen(false);
    },
    [patentQuery.data],
  );

  const [loadingMore, setLoadingMore] = useState(false);

  const loadMoreResults = useCallback(async () => {
    if (!searchSummary || !searchSummary.requestParams || loadingMore) return;
    const ctxFamily = searchSummary.familyId;
    setLoadingMore(true);
    try {
      const body = await api.structureSearch(ctxFamily, {
        ...searchSummary.requestParams,
        offset: searchSummary.rows.length,
        limit: searchSummary.limit,
      });
      // The context may have changed while the page was loading.
      if (patentQuery.data && patentQuery.data.family.id !== ctxFamily) return;
      const items = body.items.map((it) => ({
        compound: it.compound,
        mentions: it.mentions,
        activity: [],
      }));
      setSearchSummary((prev) => {
        if (!prev || prev.familyId !== ctxFamily || prev.requestKey !== searchSummary.requestKey)
          return prev;
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
    } catch {
      // Load-more failures keep the loaded rows; the chip stays actionable.
    } finally {
      setLoadingMore(false);
    }
  }, [searchSummary, loadingMore, patentQuery.data]);

  const structureRow: CompoundRow | null = useMemo(() => {
    if (!structureOpenId || !compoundsQuery.data) return null;
    return compoundsQuery.data.items.find((r) => r.compound.id === structureOpenId) ?? null;
  }, [structureOpenId, compoundsQuery.data]);

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
      <TopBar />
      <SearchBar
        initialQuery={submittedQuery ?? ""}
        submitted={submittedQuery}
        isSearching={searching}
        error={
          patentError && patentError.status === 404
            ? patentError.message + " Check the number, or try the demo patent."
            : null
        }
        onSearch={handleSearch}
        onCancel={handleCancelSearch}
      />

      {submittedQuery !== null && (
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
                {compoundsQuery.data ? `${scopeLabel} · ${compoundsQuery.data.total} compounds` : null}
              </span>
              <span className="spacer" />
              {patentQuery.data && compoundsQuery.data && compoundsQuery.data.total > 0 && (
                <>
                  <button className="btn btn-quiet" onClick={() => setSearchOpen(true)}>
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
                  onClick={() => setSearchSummary(null)}
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
                    onLoadMore={loadMoreResults}
                    loadingMore={loadingMore}
                    onToggleSelection={toggleSelection}
                    onToggleSelectAll={toggleSelectAllLoaded}
                    onClearSelection={() => setSelectedIds(new Set())}
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
                compoundsQuery.data.total === 0 ? (
                  <NoStructuresNote scopeLabel={scopeLabel} />
                ) : (
                  <CompoundTable
                    page={compoundsQuery.data}
                    selectedCompoundId={urlState.c}
                    selectedIds={selectedIds}
                    sarMode={sarMode}
                    scopeLabel={scopeLabel}
                    onLoadMore={() =>
                      setCompoundsLimit((n) => Math.min(n + 100, 500))
                    }
                    loadingMore={compoundsQuery.isFetching}
                    onToggleSelection={toggleSelection}
                    onToggleSelectAll={toggleSelectAllLoaded}
                    onClearSelection={() => setSelectedIds(new Set())}
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

      {submittedQuery === null && <EmptyState demoHint={datasetInfo ? "DEMO-PATENT-A" : null} />}

      {saveOpen && patentQuery.data && (
        <SaveToProjectDialog
          familyId={patentQuery.data.family.id}
          familyKey={patentQuery.data.family.family_key}
          datasetVersion={datasetInfo?.dataset_version ?? "unknown"}
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
