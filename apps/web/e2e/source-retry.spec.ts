/**
 * B-38 / B-06 regression: retrying ONE source must ask only that source and
 * must not re-date the others. The coverage strip is the honest surface this
 * protects — each chip states its own source's stored outcome, so a retry that
 * silently re-spent healthy sources would show up as the other chips' text
 * changing.
 *
 * Injection is bounded and labelled:
 * - The stored stack currently holds pubchem as `partial`, so the "Retry
 *   pubchem" control renders from REAL stored state and no coverage fixture is
 *   needed for the initial view.
 * - If a future release makes pubchem healthy, the initial coverage is served
 *   from a FIXTURE (the live response with pubchem forced to `failed`) so the
 *   retry control still renders; that injection is announced in the test log
 *   and only affects this page.
 * - The click's POST (`/targets/discover`) is intercepted and answered with a
 *   fixture built from the live coverage rows, so no live source is actually
 *   asked and no stored retrieval is rewritten. The follow-up coverage GET is
 *   served a second fixture: pubchem `complete` with a later retrieval time,
 *   other sources byte-identical to what the server holds.
 *
 * Viewport: tall (B-42), same as the other target-view specs.
 */
import { expect, test } from "@playwright/test";

const TARGET_ID = "5ed5e9f2-c733-543f-96dd-f58ae5a1f618";
/** Stored IL6 investigation opened by URL state (AGENTS.md §19). */
const IL6_URL = `/?q=IL6&t=${TARGET_ID}`;
const COVERAGE_URL = `/api/v1/targets/${TARGET_ID}/coverage`;
const COVERAGE_ROUTE = "**/api/v1/targets/*/coverage";
const DISCOVER_ROUTE = "**/api/v1/targets/discover";

type CoverageEntry = Record<string, unknown> & { source_name: string; status: string };

test.use({ viewport: { width: 1600, height: 1000 } });

test("retrying pubchem asks only pubchem and leaves the other chips unchanged", async ({
  page,
}) => {
  const liveCoverage: CoverageEntry[] = (await (await page.request.get(COVERAGE_URL)).json()) as CoverageEntry[];
  const livePubchem = liveCoverage.find((entry) => entry.source_name === "pubchem");

  // Primary path: the stored outcome is already a recovery case (`partial` or
  // `failed`) and the retry control renders from real data. Fixture fallback:
  // force a failed pubchem so the control still exists (labelled injection).
  const fixtureInitial = livePubchem?.status !== "failed" && livePubchem?.status !== "partial";
  if (fixtureInitial) {
    // eslint-disable-next-line no-console
    console.log("[B-38 fixture injection] pubchem is healthy; serving a failed-pubchem coverage fixture");
    await page.route(COVERAGE_ROUTE, async (route) => {
      const served = liveCoverage.map((entry) =>
        entry.source_name === "pubchem" ? { ...entry, status: "failed" } : entry,
      );
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(served) });
    });
  }

  await page.goto(IL6_URL);

  const strip = page.getByRole("list", { name: "Source coverage" });
  await expect(strip).toBeVisible();
  const retryButton = strip.getByRole("button", { name: "Retry pubchem" });
  await expect(retryButton).toBeVisible();

  // The other sources' chips, exactly as the strip renders them (their
  // `retrieved_at` is not part of chip text; it lives in the served data,
  // which the second fixture keeps byte-identical for them).
  const otherChips = strip.getByRole("listitem").filter({ hasNotText: /pubchem/i });
  const beforeTexts = (await otherChips.allInnerTexts()).sort();

  // Bounded fault injection for the click: the discover POST never reaches the
  // server, and the coverage refresh reads a fixture where only pubchem moved.
  await page.route(DISCOVER_ROUTE, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        target_id: TARGET_ID,
        target_key: "IL6",
        // The run's own rows: pubchem was asked; the others explicitly were not.
        sources: liveCoverage.map((entry) => ({
          ...entry,
          requested_in_run: entry.source_name === "pubchem",
        })),
        compounds_stored: 0,
        compounds_reused: 0,
        measurements_stored: 0,
        candidates_stored: 0,
        small_molecule_candidates: 0,
        modality_counts: {},
        rejections: {},
        warnings: [],
        coverage_note: "B-38 fixture response: no live source was asked by this test.",
      }),
    });
  });
  const afterCoverage = liveCoverage.map((entry) =>
    entry.source_name === "pubchem"
      ? {
          ...entry,
          status: "complete",
          // A later retrieval time for pubchem only; the other entries —
          // including their retrieved_at — are passed through unchanged.
          retrieved_at: new Date(Date.parse(String(entry.retrieved_at)) + 3_600_000).toISOString(),
        }
      : entry,
  );
  await page.route(COVERAGE_ROUTE, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(afterCoverage) });
  });

  const discoverRequest = page.waitForRequest(
    (request) => request.url().includes("/api/v1/targets/discover"),
  );
  await retryButton.click();

  // The contract under test (B-06): the retry asks exactly one source.
  const body = JSON.parse((await discoverRequest).postData() ?? "{}") as {
    target_id?: string;
    sources?: string[];
  };
  expect(body.target_id).toBe(TARGET_ID);
  expect(body.sources).toEqual(["pubchem"]);

  // The run reports its own scope, naming the sources it did not ask.
  const note = page.getByText(/Asked pubchem only/);
  await expect(note).toBeVisible();
  await expect(note).toContainText("not asked again — their stored outcomes are unchanged");

  // Pubchem's own chip took the new outcome…
  await expect(strip.getByRole("listitem").filter({ hasText: "pubchem" })).toContainText(
    /pubchem complete/,
  );
  // …and the other chips still state exactly what they stated before.
  const afterTexts = (await otherChips.allInnerTexts()).sort();
  expect(afterTexts).toEqual(beforeTexts);
});
