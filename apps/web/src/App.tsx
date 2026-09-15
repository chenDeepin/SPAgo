import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api/client";
import type {
  Candidate,
  CompoundRow,
  PlanStep,
  ProjectDetail,
  SearchPlanResponse,
} from "./api/types";
import { CompoundTable } from "./components/CompoundTable";
import { CandidateTable } from "./components/CandidateTable";
import { EvidencePanel } from "./components/EvidencePanel";
import { ExportMenu } from "./components/ExportMenu";
import { FamilySidebar } from "./components/FamilySidebar";
import { PlanCard } from "./components/PlanCard";
import { SignInGate } from "./components/SignInGate";
import { ProjectsDialog } from "./components/ProjectsDialog";
import { ResolutionState } from "./components/ResolutionState";
import { SaveCandidatesDialog } from "./components/SaveCandidatesDialog";
import { SaveToProjectDialog } from "./components/SaveToProjectDialog";
import { StructureDrawer } from "./components/StructureDrawer";
import { TargetEvidencePanel } from "./components/TargetEvidencePanel";
import { TargetHeader, coverageChipId } from "./components/TargetHeader";
import type { StructureSearchSummary } from "./components/StructureSearchDialog";
const StructureSearchDialog = lazy(() => import("./components/StructureSearchDialog").then((m) => ({ default: m.StructureSearchDialog })));
import { SearchBar } from "./components/SearchBar";
import { TopBar } from "./components/TopBar";
import { EmptyState, NoStructuresNote, SkeletonRows, StateBanner } from "./components/states";
import {
  looksLikePublicationNumber,
  readUrlState,
  subscribeUrlState,
  writeUrlState,
  type UrlState,
} from "./state/url";

/** The query text a target investigation should display after a plan runs. */
function planQueryFor(query: string, data: Record<string, unknown>): string {
  const key = data.target_key;
  return typeof key === "string" && key ? key : query;
}

/** Server page size for the plain compound table. Pages are appended by real
 * offset pagination (the API caps a single response at 500 rows). */
const PLAIN_PAGE_SIZE = 100;

/** Identifier of the synthetic sample family served by the demo dataset. It is
 * deliberately not publication-number shaped, so the search box classifies it as
 * free text; the landing and 404 hints open it through an explicit control
 * instead (ONLINE-01 browser finding). */
const DEMO_SAMPLE_ID = "DEMO-PATENT-A";

/** A paging failure belongs to the request it came from: a stale error must
 * never surface on a newer query/family/document. */
interface PagingError {
  requestKey: string;
  message: string;
}

export function App() {
  const queryClient = useQueryClient();
  const [urlState, setUrlState] = useState<UrlState>(() => readUrlState());
  // A restored URL is classified by the same deterministic rule used on submit,
  // so reloading a target investigation does not replay it as a patent lookup.
  const [submittedQuery, setSubmittedQuery] = useState<string | null>(
    urlState.q && looksLikePublicationNumber(urlState.q) ? urlState.q : null,
  );
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

  // --- ONLINE-00: target investigation ---------------------------------------
  // A submitted query is either a publication number or a target query; the
  // server resolves the latter, and this state holds the *requested* string so
  // the input survives a reload. The resolved target id lives in the URL.
  const [targetQuery, setTargetQuery] = useState<string | null>(
    urlState.q && !looksLikePublicationNumber(urlState.q) ? urlState.q : null,
  );
  // A non-identifier request is interpreted into a reviewable plan before
  // anything runs; the plan card owns the explicit Run action (ONLINE-02).
  const [pendingPlan, setPendingPlan] = useState<SearchPlanResponse | null>(null);
  const [planEdits, setPlanEdits] = useState<Record<string, string>>({});
  const [planError, setPlanError] = useState<string | null>(null);
  const [planWorking, setPlanWorking] = useState(false);
  const [allModalities, setAllModalities] = useState(false);
  const [evidenceClassFilter, setEvidenceClassFilter] = useState<string | null>(null);
  const [saveCandidatesOpen, setSaveCandidatesOpen] = useState(false);
  // Per-source citation focus: the header chip is flashed briefly, because the
  // coverage strip is a status list, not a selectable view.
  const [focusedSource, setFocusedSource] = useState<string | null>(null);

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

  // --- target investigation queries (ONLINE-00) -----------------------------
  // A target query is resolved server-side; the target id then lives in the URL
  // so the view is reproducible and Back/Forward work.
  const targetResolveQuery = useQuery({
    queryKey: ["target-resolve", targetQuery],
    queryFn: ({ signal }) => api.resolveTarget({ query: targetQuery as string }, signal),
    enabled: targetQuery !== null,
    retry: false,
  });

  const resolvedTargetId = urlState.t;

  useEffect(() => {
    if (!targetQuery) return;
    const id = targetResolveQuery.data?.target_id ?? null;
    if (id && id !== urlState.t) {
      updateUrl({ ...urlState, t: id, doc: null, c: null });
    }
  }, [targetQuery, targetResolveQuery.data, urlState, updateUrl]);

  const targetDetailQuery = useQuery({
    queryKey: ["target", resolvedTargetId],
    queryFn: ({ signal }) => api.target(resolvedTargetId as string, signal),
    enabled: resolvedTargetId !== null,
  });

  const coverageQuery = useQuery({
    queryKey: ["target-coverage", resolvedTargetId],
    queryFn: ({ signal }) => api.targetCoverage(resolvedTargetId as string, signal),
    enabled: resolvedTargetId !== null,
  });

  const candidatesQuery = useInfiniteQuery({
    queryKey: ["candidates", resolvedTargetId, allModalities, evidenceClassFilter],
    queryFn: ({ pageParam, signal }) =>
      api.targetCandidates(
        resolvedTargetId as string,
        {
          limit: PLAIN_PAGE_SIZE,
          offset: pageParam as number,
          include_all_modalities: allModalities,
          evidence_class: evidenceClassFilter,
        },
        signal,
      ),
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.offset + lastPage.items.length < lastPage.total
        ? lastPage.offset + lastPage.items.length
        : undefined,
    enabled: resolvedTargetId !== null,
  });

  const candidateItems: Candidate[] = useMemo(
    () => candidatesQuery.data?.pages.flatMap((p) => p.items) ?? [],
    [candidatesQuery.data],
  );
  const candidatePages = candidatesQuery.data?.pages;
  const candidateTotal = candidatePages?.length
    ? (candidatePages[candidatePages.length - 1]?.total ?? 0)
    : 0;
  const modalityBreakdown = candidatePages?.[0]?.modality_breakdown ?? {};

  const selectedCandidate = useMemo(
    () => candidateItems.find((c) => c.compound_id === urlState.c) ?? null,
    [candidateItems, urlState.c],
  );

  const measurementsQuery = useQuery({
    queryKey: ["candidate-measurements", resolvedTargetId, urlState.c],
    queryFn: ({ signal }) =>
      api.targetMeasurements(
        resolvedTargetId as string,
        { compound_id: urlState.c, limit: 200 },
        signal,
      ),
    enabled: resolvedTargetId !== null && urlState.c !== null,
  });

  const planMutation = useMutation({
    mutationFn: (body: { query: string; use_llm?: boolean }) =>
      api.plan({
        query: body.query,
        family_id: patentQuery.data?.family.id ?? null,
        document_id: urlState.doc,
        selected_compound_id: urlState.c,
        use_llm: body.use_llm ?? false,
      }),
    onSuccess: (plan) => {
      setPendingPlan(plan);
      setPlanEdits({});
      setPlanError(null);
    },
    onError: (err) => setPlanError((err as Error).message),
  });

  const runPlanMutation = useMutation({
    mutationFn: async (plan: SearchPlanResponse) => {
      const steps = plan.steps.map((step: PlanStep, index: number) => {
        const parameters: Record<string, unknown> = { ...step.parameters };
        for (const name of Object.keys(parameters)) {
          const edited = planEdits[`${index}:${name}`];
          if (edited === undefined) continue;
          parameters[name] =
            name === "threshold" || name === "limit" ? Number(edited) : edited.trim();
        }
        return { op: step.op, ...parameters };
      });
      return api.executePlan({
        query: plan.query,
        producer: plan.producer,
        steps,
      });
    },
    onSuccess: (result) => {
      setPendingPlan(null);
      setPlanWorking(false);
      const first = result.steps[0];
      if (!first) return;
      if (first.op === "target_discovery" && first.status === "ok") {
        const targetId = String(first.data.target_id ?? "");
        if (targetId) {
          setTargetQuery(planQueryFor(result.query, first.data));
          setAllModalities(false);
          setEvidenceClassFilter(null);
          updateUrl({ q: result.query, doc: null, c: null, t: targetId }, "push");
        }
        return;
      }
      if (first.op === "open_patent" && first.status === "ok") {
        setSubmittedQuery(String(first.data.publication_number ?? result.query));
        setTargetQuery(null);
        updateUrl(
          { q: String(first.data.publication_number ?? result.query), doc: null, c: null, t: null },
          "replace",
        );
        return;
      }
      setPlanError(first.detail || "The plan produced no viewable result.");
    },
    onError: (err) => {
      setPlanWorking(false);
      setPlanError((err as Error).message);
    },
  });

  const discoverMutation = useMutation({
    mutationFn: () =>
      api.discoverTarget({ target_id: resolvedTargetId as string, sources: ["chembl", "bindingdb", "pubchem"] }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["target-coverage", resolvedTargetId] });
      queryClient.invalidateQueries({ queryKey: ["candidates", resolvedTargetId] });
      queryClient.invalidateQueries({ queryKey: ["target", resolvedTargetId] });
    },
  });
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

  /** Opens a record by identifier: the single owner of the "show this patent"
   * step, shared by the search box, the candidate picker and the synthetic
   * sample controls. The server stays authoritative about what exists, so a
   * missing record still renders the normal 404 state. */
  const openPatent = useCallback(
    (value: string) => {
      setTargetQuery(null);
      if (resolvedTargetId) updateUrl({ q: value, doc: null, c: null, t: null }, "push");
      if (value === submittedQuery) {
        queryClient.invalidateQueries({ queryKey: ["patent", value] });
        return;
      }
      setSubmittedQuery(value);
      // A new query is a navigation step: browser Back returns to the previous search.
      updateUrl({ q: value, doc: null, c: null, t: null }, "push");
    },
    [queryClient, resolvedTargetId, submittedQuery, updateUrl],
  );

  /** Opens the synthetic sample record from the landing or 404 hint. The hint
   * exists because that identifier cannot be routed by the search box. */
  const openDemoSample = useCallback(() => {
    closeProject();
    openPatent(DEMO_SAMPLE_ID);
  }, [closeProject, openPatent]);

  const handleSearch = (value: string) => {
    closeProject();
    // Deterministic identifier shape decides which *server* lookup runs; the
    // server remains authoritative about what exists. Free text is never
    // interpreted here (AGENTS.md §12).
    if (looksLikePublicationNumber(value)) {
      openPatent(value);
      return;
    }
    // Anything else is interpreted into a plan the user reviews and runs.
    // (A literal publication number never reaches the model.)
    queryClient.cancelQueries({ queryKey: ["patent", submittedQuery] });
    setSubmittedQuery(null);
    setTargetQuery(null);
    setSelectedIds(new Set());
    setPlanEdits({});
    setPlanError(null);
    planMutation.mutate({ query: value });
    updateUrl({ q: value, doc: null, c: null, t: null }, "push");
  };

  const handleCancelSearch = () => {
    queryClient.cancelQueries({ queryKey: ["patent", submittedQuery] });
    setPendingPlan(null);
    setPlanError(null);
    queryClient.cancelQueries({ queryKey: ["target-resolve", targetQuery] });
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
        // A restored entry carrying a target id is a target investigation; the
        // requested query is re-resolved only when the id is absent.
        if (restored.t) {
          setTargetQuery(restored.q);
          setSubmittedQuery(null);
          setLastGoodQuery(null);
        } else {
          setTargetQuery(null);
          setSubmittedQuery(restored.q);
          setLastGoodQuery(restored.q);
        }
        setSelectedIds(new Set());
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

  // Focus the coverage chip a `source:<name>` citation refers to. The strip is
  // scrolled to the chip and the chip is flashed, so the click has a visible
  // destination instead of silently switching tabs (AGENTS.md §18).
  const focusSourceChip = useCallback((sourceName: string) => {
    setFocusedSource(sourceName);
    const chip = document.getElementById(coverageChipId(sourceName));
    chip?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  useEffect(() => {
    if (focusedSource === null) return;
    const timer = window.setTimeout(() => setFocusedSource(null), 2400);
    return () => window.clearTimeout(timer);
  }, [focusedSource]);

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
        updateUrl(
          { q: doc.publication_number, doc: null, c: null, t: null },
          doc.publication_number === submittedQuery ? "replace" : "push",
        );
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
    if (!first) {
      structurePagingAbort.current?.abort();
      setSearchSummary(null);
      setStructurePaging(false);
      setStructurePagingError(null);
      setSubmittedQuery(null);
      setTargetQuery(null);
      updateUrl({ q: null, doc: null, c: null, t: null });
      return;
    }
    if (first.family_id) {
      void openProjectFamily(project, first.family_id);
      return;
    }
    // A candidate item has no family: reopen it in the target investigation it
    // was saved from, so a non-patent candidate is as reopenable as a patent
    // compound (ONLINE-00 C).
    if (first.target_id) {
      structurePagingAbort.current?.abort();
      setSearchSummary(null);
      setStructurePaging(false);
      setStructurePagingError(null);
      setSubmittedQuery(null);
      setTargetQuery(first.target_key ?? first.target_name ?? "");
      setAllModalities(true);
      setEvidenceClassFilter(null);
      updateUrl({ q: first.target_key ?? null, doc: null, c: null, t: first.target_id }, "push");
      return;
    }
    setProjectError(
      "This saved item has neither a patent family nor a target scope, so it cannot be opened.",
    );
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
    for (const item of openedProject?.items ?? []) {
      // Candidate items have no family and are reopened through their target.
      if (item.family_id) families.set(item.family_id, item.family_key ?? item.family_id);
    }
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

  const inTargetMode = resolvedTargetId !== null || targetQuery !== null;
  const activeQuery = inTargetMode ? targetQuery : submittedQuery;

  return (
    <SignInGate>
    <div className="app">
      <TopBar onOpenProjects={() => { cancelProjectNavigation(); setProjectsOpen(true); }} />
      <SearchBar
        initialQuery={activeQuery ?? ""}
        submitted={activeQuery}
        isSearching={inTargetMode ? targetResolveQuery.isFetching : searching}
        error={
          inTargetMode
            ? ((targetResolveQuery.error as Error | null)?.message ?? null)
            : patentError && patentError.status === 404
              ? patentError.message +
                (datasetInfo?.synthetic
                  ? ". Check the number, or open the demo record."
                  : ". It is not covered by the currently loaded source data.")
              : null
        }
        errorAction={
          !inTargetMode && patentError?.status === 404 && datasetInfo?.synthetic
            ? { label: `Open ${DEMO_SAMPLE_ID}`, onClick: openDemoSample }
            : null
        }
        onSearch={handleSearch}
        onCancel={handleCancelSearch}
      />

      {pendingPlan && (
        <div className="workspace">
          <main className="table-area">
            <PlanCard
              plan={pendingPlan}
              working={runPlanMutation.isPending || planWorking}
              error={planError}
              edits={planEdits}
              onEdit={(index, name, value) =>
                setPlanEdits((prev) => ({ ...prev, [`${index}:${name}`]: value }))
              }
              onRun={() => {
                setPlanError(null);
                setPlanWorking(true);
                runPlanMutation.mutate(pendingPlan);
              }}
              onDiscard={() => {
                setPendingPlan(null);
                setPlanError(null);
                updateUrl({ ...urlState, q: null }, "replace");
              }}
            />
          </main>
        </div>
      )}

      {planMutation.isPending && (
        <div className="workspace">
          <main className="table-area">
            <div className="state-banner" role="status">
              <span>Interpreting the request…</span>
            </div>
          </main>
        </div>
      )}

      {planError && !pendingPlan && !inTargetMode && (
        <div className="workspace">
          <main className="table-area">
            <StateBanner
              kind="error"
              message={planError}
              onRetry={() => handleSearch(urlState.q ?? "")}
            />
          </main>
        </div>
      )}

      {inTargetMode && (
        <div className="workspace target-workspace">
          <main className="table-area" aria-busy={candidatesQuery.isFetching}>
            {openedProject && (
              <div className="project-banner" role="status">
                <span>
                  Project <strong>{openedProject.name}</strong> · {openedProject.item_count} saved
                  item{openedProject.item_count === 1 ? "" : "s"} · reopened from saved target scope
                </span>
                <span className="spacer" />
                <button className="show-all-occ" onClick={closeProject} aria-label="Close project view">
                  Close project ×
                </button>
              </div>
            )}
            {projectError && <StateBanner kind="error" message={projectError} />}

            {targetResolveQuery.isLoading && <SkeletonRows />}

            {!targetResolveQuery.isLoading &&
              targetResolveQuery.data &&
              targetResolveQuery.data.status !== "resolved" && (
                <ResolutionState
                  status={targetResolveQuery.data.status}
                  query={targetResolveQuery.data.query}
                  notes={targetResolveQuery.data.notes}
                  candidates={targetResolveQuery.data.candidates}
                  onPick={(identifier) => handleSearch(identifier)}
                />
              )}

            {targetDetailQuery.data && (
              <>
                <TargetHeader
                  target={targetDetailQuery.data}
                  coverage={coverageQuery.data ?? []}
                  discovery={discoverMutation.data ?? null}
                  discovering={discoverMutation.isPending}
                  discoverError={
                    discoverMutation.error ? (discoverMutation.error as Error).message : null
                  }
                  onDiscover={() => discoverMutation.mutate()}
                  onOpenRelated={(query) => handleSearch(query)}
                  focusedSource={focusedSource}
                />

                <div className="candidate-filters">
                  <label className="checkbox-row" style={{ margin: 0 }}>
                    <input
                      type="checkbox"
                      checked={allModalities}
                      onChange={(e) => {
                        setAllModalities(e.target.checked);
                        setSelectedIds(new Set());
                      }}
                    />
                    Include peptides, oligonucleotides and biologics
                    {Object.entries(modalityBreakdown)
                      .filter(([k]) => !["small_molecule", "unclassified"].includes(k))
                      .map(([k, v]) => ` · ${v} ${k}`)
                      .join("")}
                  </label>
                  <label>
                    Evidence class{" "}
                    <select
                      className="select-input"
                      value={evidenceClassFilter ?? ""}
                      onChange={(e) => {
                        setEvidenceClassFilter(e.target.value || null);
                        setSelectedIds(new Set());
                      }}
                    >
                      <option value="">any</option>
                      <option value="measured_direct_binding">measured direct binding</option>
                      <option value="interaction_disruption">interaction disruption</option>
                      <option value="functional_effect">functional effect</option>
                      <option value="screening_assay">screening assay</option>
                      <option value="unspecified">class unspecified</option>
                    </select>
                  </label>
                  <span className="spacer" />
                  {candidateTotal > 0 && (
                    <>
                      <ExportMenu
                        targetId={resolvedTargetId as string}
                        includeAllModalities={allModalities}
                        selectedIds={Array.from(selectedIds)}
                        resultsTotal={candidateTotal}
                        structureFilter={null}
                      />
                      <button
                        className="btn btn-primary"
                        disabled={selectedIds.size === 0}
                        onClick={() => setSaveCandidatesOpen(true)}
                      >
                        Save to project
                      </button>
                    </>
                  )}
                </div>

                {candidatesQuery.isLoading ? (
                  <SkeletonRows />
                ) : candidatesQuery.error ? (
                  <StateBanner
                    kind="error"
                    message={(candidatesQuery.error as Error).message}
                    onRetry={() => candidatesQuery.refetch()}
                  />
                ) : candidateItems.length === 0 ? (
                  <div className="state-banner" role="status">
                    <span>
                      No candidates match this filter. That is not evidence that no inhibitors
                      exist: check the per-source coverage above, which distinguishes “no records”
                      from “source failed” and “not queried”.
                    </span>
                  </div>
                ) : (
                  <CandidateTable
                    page={{
                      total: candidateTotal,
                      offset: 0,
                      limit: PLAIN_PAGE_SIZE,
                      items: candidateItems,
                      modality_breakdown: modalityBreakdown,
                      default_filter: allModalities
                        ? "all modalities"
                        : "small molecules and unclassified entities",
                    }}
                    selectedCompoundId={urlState.c}
                    selectedIds={selectedIds}
                    scopeLabel={targetDetailQuery.data.target_key}
                    onToggleSelection={toggleSelection}
                    onToggleSelectAll={toggleSelectAllLoaded}
                    onClearSelection={() => setSelectedIds(new Set())}
                    onSelectCandidate={handleSelectCompound}
                  />
                )}

                {candidateItems.length > 0 && (
                  <div className="table-footer">
                    {candidatesQuery.hasNextPage && (
                      <button
                        className="show-all-occ"
                        onClick={() => candidatesQuery.fetchNextPage()}
                        disabled={candidatesQuery.isFetchingNextPage}
                      >
                        {candidatesQuery.isFetchingNextPage ? "Loading…" : "Load more candidates"}
                      </button>
                    )}
                    {candidatesQuery.isFetchNextPageError && (
                      <span className="paging-error" role="alert">
                        {(candidatesQuery.error as Error | null)?.message ??
                          "The next candidate page could not be loaded."}
                      </span>
                    )}
                  </div>
                )}
              </>
            )}
          </main>

          {selectedCandidate && targetDetailQuery.data && (
            <TargetEvidencePanel
              candidate={selectedCandidate}
              target={targetDetailQuery.data}
              measurements={measurementsQuery.data}
              loading={measurementsQuery.isFetching}
              error={(measurementsQuery.error as Error | null)?.message ?? null}
              includeAllModalities={allModalities}
              onFocusSource={focusSourceChip}
              onClose={handleCloseEvidence}
            />
          )}
        </div>
      )}

      {!inTargetMode && (submittedQuery !== null || openedProject !== null) && (
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

      {!inTargetMode && !pendingPlan && submittedQuery === null && !openedProject && (
        <EmptyState
          demoHint={datasetInfo?.synthetic ? DEMO_SAMPLE_ID : null}
          onOpenDemo={openDemoSample}
          sourceNote={
            datasetInfo
              ? datasetInfo.synthetic
                ? null
                : `Loaded source: ${datasetInfo.source_name} · ${datasetInfo.dataset_version}. Enter a covered publication number to open its family, or a target (for example TSLP or Q969D9) to investigate open-database evidence.`
              : null
          }
        />
      )}

      {projectsOpen && (
        <ProjectsDialog onClose={() => setProjectsOpen(false)} onOpen={openProject} />
      )}

      {saveCandidatesOpen && resolvedTargetId && targetDetailQuery.data && (
        <SaveCandidatesDialog
          targetId={resolvedTargetId}
          targetKey={targetDetailQuery.data.target_key}
          selectedIds={Array.from(selectedIds)}
          onClose={() => setSaveCandidatesOpen(false)}
        />
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
    </SignInGate>
  );
}
