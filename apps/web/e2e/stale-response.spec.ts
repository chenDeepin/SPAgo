/**
 * B-38: stale-response protection — a slow response for scope A must never
 * overwrite a faster switch to scope B (PROMPT.md §2.5: the workflow stays
 * trustworthy while the scientist changes context).
 *
 * Fault injection is bounded to one route per test: the handler fetches the
 * *real* server response and only delays its delivery (`route.fetch()` +
 * `fulfill({ response })`), so no response body is fabricated — only latency
 * is injected, and only for the duration of the test.
 *
 * Data is the seeded demo stack (DEMO-PATENT-A family, stored IL6
 * investigation); no server or database state is modified.
 *
 * Row locators are scoped by the row's checkbox label, never by positional
 * order: the compound table's header row also carries role="row" (B-19), so
 * `getByRole("row").first()` is the header, not a data row. The virtualized
 * table re-measures rows while scrolling, so row clicks use force and assert
 * the resulting view state instead of the click itself.
 */
import { expect, test } from "@playwright/test";

const DEMO_PUBLICATION = "DEMO-PATENT-A";
/** Stored IL6 investigation opened by URL state (AGENTS.md §19). */
const IL6_URL =
  "/?q=IL6&t=5ed5e9f2-c733-543f-96dd-f58ae5a1f618";
/** First two demo compounds, ordered as the table sorts them (by InChIKey). */
const COMPOUND_A = {
  id: "1bdeb9cd-b629-5dac-bca6-768d6d5a1f49",
  inchikey: "ABBQHOQBGMUPJH-UHFFFAOYSA-M",
  /** The demo fixture's patent-local label for compound A. */
  label: "Example 12",
};
const COMPOUND_B = {
  inchikey: "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
  label: "Example 01",
};

test("a slow family response cannot overwrite a faster switch to a target scope", async ({
  page,
}) => {
  // INJECTED LATENCY: the family's compounds response is held back past the
  // scope switch. The body is the real server's answer, only its delivery is
  // delayed.
  await page.route("**/api/v1/families/*/compounds*", async (route) => {
    const response = await route.fetch();
    await new Promise((resolve) => setTimeout(resolve, 20_000));
    await route.fulfill({ response });
  });

  await page.goto("/");

  // Scope A: open the demo family. The patent lookup returns quickly; the
  // compounds response stays in flight.
  const search = page.getByRole("search");
  await search.getByLabel("Patent publication number or target").fill(DEMO_PUBLICATION);
  await search.getByRole("button", { name: "Search" }).click();
  await expect(page.locator(".a11y-status")).toContainText("Family DEMO-FAMILY-1 loaded");

  // Watch for the delayed response so the final assertions provably run after
  // it has arrived at the browser.
  const lateFamilyResponse = page.waitForResponse(
    (response) => response.url().includes("/compounds") && response.request().method() === "GET",
  );

  // Scope B: leave the family before its compounds arrive. Free text is
  // interpreted into a reviewed plan (ONLINE-02); Run is the explicit action.
  await search.getByLabel("Patent publication number or target").fill("IL6");
  await search.getByRole("button", { name: "Search" }).click();
  const plan = page.getByRole("group", { name: "Interpreted request" });
  await expect(plan).toBeVisible();
  await plan.getByRole("button", { name: "Run" }).click();

  // The delayed family response may land before, during or after the target
  // view; whichever way, the view must answer scope B afterwards.
  await lateFamilyResponse;

  const targetTable = page.getByRole("table", { name: "Candidate compounds for IL6" });
  await expect(targetTable).toBeVisible();
  await expect(page.getByRole("list", { name: "Source coverage" })).toBeVisible();
  // The family's late data must not resurrect the family table in the target
  // scope (unmounted means zero matches, not merely hidden).
  await expect(
    page.getByRole("table", { name: /Compounds in family DEMO-FAMILY-1/ }),
  ).toHaveCount(0);
});

test("a slow evidence response cannot overwrite a newer compound selection", async ({
  page,
}) => {
  // INJECTED LATENCY: only compound A's evidence response is delayed; every
  // other compound's evidence passes through untouched.
  await page.route("**/api/v1/compounds/*/evidence", async (route) => {
    if (!route.request().url().includes(COMPOUND_A.id)) {
      await route.fallback();
      return;
    }
    const response = await route.fetch();
    await new Promise((resolve) => setTimeout(resolve, 3_000));
    await route.fulfill({ response });
  });

  await page.goto("/");

  const search = page.getByRole("search");
  await search.getByLabel("Patent publication number or target").fill(DEMO_PUBLICATION);
  await search.getByRole("button", { name: "Search" }).click();
  await expect(page.locator(".a11y-status")).toContainText("Family DEMO-FAMILY-1 loaded");

  const familyTable = page.getByRole("table", { name: /Compounds in family DEMO-FAMILY-1/ });
  const rowA = familyTable
    .getByRole("row")
    .filter({ has: page.getByRole("checkbox", { name: `Select compound ${COMPOUND_A.inchikey}` }) });
  const rowB = familyTable
    .getByRole("row")
    .filter({ has: page.getByRole("checkbox", { name: `Select compound ${COMPOUND_B.inchikey}` }) });
  await expect(rowA).toBeVisible();
  await expect(rowB).toBeVisible();

  // Select A and immediately switch to B — B's evidence loads fast while A's
  // is still in flight. The app may satisfy the staleness contract either way
  // (AGENTS.md §15: cancellation *or* obsolescence): it can abort A's now
  // unobserved request, or let it land and ignore it. Whichever happens, the
  // request must settle at the network layer before the final assertions.
  const isEvidenceForA = (url: string) =>
    url.includes(`/compounds/${COMPOUND_A.id}/evidence`);
  const aAborted = page
    .waitForEvent("requestfailed", (request) => isEvidenceForA(request.url()))
    .then(() => "aborted" as const);
  const aArrived = page
    .waitForResponse((response) => isEvidenceForA(response.url()))
    .then(() => "arrived" as const);
  aAborted.catch(() => undefined);
  aArrived.catch(() => undefined);

  await rowA.click({ force: true });
  await rowB.click({ force: true });

  const inspector = page.getByRole("dialog", { name: "Evidence inspector" });
  await expect(inspector).toBeVisible();
  await expect(inspector).toContainText(COMPOUND_B.inchikey);

  // B's own evidence arrived and rendered (the panel is not stuck pending)…
  await expect(inspector.locator(".provenance-chip").first()).not.toContainText(
    "Provenance pending",
  );
  // …and once A's obsolete request settled — aborted, or delivered late — the
  // panel still shows B's record, not A's.
  await Promise.race([aAborted, aArrived]);
  await expect(inspector).toContainText(COMPOUND_B.inchikey);
  await expect(inspector).not.toContainText(COMPOUND_A.label);
});
