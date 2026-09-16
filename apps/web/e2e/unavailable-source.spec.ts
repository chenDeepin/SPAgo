/**
 * B-38: an unavailable source is an error state with a retry affordance, never
 * an empty-success state (PROMPT.md §2.5; AGENTS.md §22 — a source failure
 * must not be disguised as an empty result). The demo fixture's own words make
 * the distinction testable: "no records" is a finding, "source failed" is not.
 *
 * Fault injection is bounded: exactly one API route (`…/candidates`) is
 * aborted while the error state is observed, then unblocked so the app's own
 * Retry control proves recovery. Everything else on the page is the seeded
 * stack's stored data.
 *
 * Viewport: the target view's header content overflows short viewports
 * (backlog B-42), so this spec pins the tall viewport the view is built for.
 */
import { expect, test } from "@playwright/test";

/** Stored IL6 investigation opened by URL state (AGENTS.md §19). */
const IL6_URL =
  "/?q=IL6&t=5ed5e9f2-c733-543f-96dd-f58ae5a1f618";
const CANDIDATES_ROUTE = "**/api/v1/targets/*/candidates*";
const COVERAGE_ROUTE = "**/api/v1/targets/*/coverage*";

test.use({ viewport: { width: 1600, height: 1000 } });

test("a failed coverage fetch states the failure, never a false never-run", async ({ page }) => {
  // INJECTED FAILURE: the stored-coverage route is unreachable. B-38's round
  // found this rendered as "No retrieval has been run for this target yet."
  // — an authoritative-sounding false statement (AGENTS.md §22). The fix
  // renders the failure with its own retry; this pins it.
  await page.route(COVERAGE_ROUTE, (route) => route.abort());

  await page.goto(IL6_URL);

  const error = page.getByTestId("coverage-error");
  // (React Query's bounded retries first; the assertion timeout covers them.)
  await expect(error).toBeVisible();
  await expect(error).toContainText("could not be read");

  // The false statement must not appear while the read failed, and the chips
  // (stored rows the outage made unavailable) must not render as data.
  await expect(page.getByText("No retrieval has been run for this target yet")).toHaveCount(0);
  await expect(
    page.getByRole("list", { name: "Source coverage" }).getByRole("listitem"),
  ).toHaveCount(0);

  // Recovery: unblock and retry; the stored chips come back.
  await page.unroute(COVERAGE_ROUTE);
  await error.getByRole("button", { name: "Retry coverage" }).click();
  const coverage = page.getByRole("list", { name: "Source coverage" });
  await expect(coverage.getByRole("listitem").first()).toBeVisible();
  await expect(error).toHaveCount(0);
});

test("a failed candidates fetch renders an error with retry, not an empty result", async ({
  page,
}) => {
  // INJECTED FAILURE: the candidates API is unreachable for this page; the
  // coverage strip and target header keep answering from stored data, so the
  // outage is scoped like a real partial failure.
  await page.route(CANDIDATES_ROUTE, (route) => route.abort());

  await page.goto(IL6_URL);

  // The rest of the view really did load — this is a one-route outage, not a
  // dead backend, and the spec must not pass against one.
  const coverage = page.getByRole("list", { name: "Source coverage" });
  await expect(coverage).toBeVisible();
  await expect(coverage.getByRole("listitem").first()).toBeVisible();

  // Error state: the fetch failure surfaces with its own retry affordance.
  // (React Query retries a few times first; the assertion's own timeout
  // covers that backoff without a sleep.)
  const errorBanner = page.getByRole("alert").filter({ hasText: "Source unavailable" });
  await expect(errorBanner).toBeVisible();
  await expect(errorBanner.getByRole("button", { name: "Retry" })).toBeVisible();

  // Not an empty-success state: the "no candidates" banner must stay absent
  // while the error is on screen, and the candidate table must not render.
  await expect(page.getByText("No candidates match this filter")).toHaveCount(0);
  await expect(page.getByRole("table", { name: "Candidate compounds for IL6" })).toHaveCount(0);

  // Recovery: unblock the route and use the app's own Retry control.
  await page.unroute(CANDIDATES_ROUTE);
  await errorBanner.getByRole("button", { name: "Retry" }).click();

  const table = page.getByRole("table", { name: "Candidate compounds for IL6" });
  await expect(table).toBeVisible();
  // A data row is present (the header row also carries role="row" since B-19,
  // so scope the locator by the row checkbox instead of row order).
  await expect(
    table.getByRole("checkbox", { name: /Select candidate / }).first(),
  ).toBeVisible();
  await expect(errorBanner).toHaveCount(0);
});
