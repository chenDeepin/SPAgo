/**
 * B-38: saved work survives being closed and reopened — a scientist must be
 * able to park a selection in a project and get the same rows back (PROMPT.md
 * §2.5). This spec keeps to the family scope: create a project, save one
 * selected compound, leave the view entirely, reopen through the Projects
 * dialog, and check the item and the selection are intact.
 *
 * Auth shape: this stack runs in local single-user mode (auth disabled), so
 * the whole write path runs with no sign-in surface — the spec states that
 * shape explicitly instead of assuming it.
 *
 * Writes real records (one project + one item per run, unique name) into the
 * seeded stack's database; that is the workflow under test and cannot be
 * rehearsed read-only. No route injection is used in this file.
 */
import { expect, test } from "@playwright/test";

const DEMO_PUBLICATION = "DEMO-PATENT-A";
/** A demo-family compound with its patent-local label (fixture data). */
const COMPOUND_INCHIKEY = "ABBQHOQBGMUPJH-UHFFFAOYSA-M";

test("a saved family selection survives close and reopen without sign-in", async ({ page }) => {
  // Local auth shape, stated not assumed: the deployment answers "disabled"
  // and requires no session (ADR local single-user mode).
  const auth = await (await page.request.get("/api/v1/auth/status")).json();
  expect(auth.mode).toBe("disabled");
  expect(auth.required).toBe(false);

  await page.goto("/");

  // Open the family and select one compound for saving.
  const search = page.getByRole("search");
  await search.getByLabel("Patent publication number or target").fill(DEMO_PUBLICATION);
  await search.getByRole("button", { name: "Search" }).click();
  await expect(page.locator(".a11y-status")).toContainText("Family DEMO-FAMILY-1 loaded");

  const familyTable = page.getByRole("table", { name: /Compounds in family DEMO-FAMILY-1/ });
  const selectBox = familyTable.getByRole("checkbox", {
    name: `Select compound ${COMPOUND_INCHIKEY}`,
  });
  await expect(selectBox).toBeVisible();
  // The virtualized table re-measures rows continuously; force the click and
  // assert the resulting selection state, not the click itself.
  await selectBox.click({ force: true });
  await expect(page.getByText("1 selected for save")).toBeVisible();

  // Save it into a fresh project (unique name: this spec writes real rows).
  const projectName = `B38 save-reopen ${Date.now()}`;
  await page.getByRole("button", { name: "Save to project" }).click();
  const saveDialog = page.getByRole("dialog", { name: "Save to project" });
  await expect(saveDialog).toBeVisible();
  await expect(saveDialog.getByText("Selected compounds (1)")).toBeVisible();
  await saveDialog.getByLabel("…or create a new project").fill(projectName);
  // Exact names: the modal's own close control is "Close Save to project",
  // which a substring match for "Save"/"Close" would also hit.
  await saveDialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(saveDialog.getByText("Saved to project.")).toBeVisible();
  await saveDialog.getByRole("button", { name: "Close", exact: true }).click();
  await expect(saveDialog).toHaveCount(0);

  // Leave the view completely — a fresh load of the landing page.
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Inspect patent chemistry" })).toBeVisible();

  // Reopen through the Projects dialog.
  await page.getByRole("button", { name: "Projects" }).click();
  const projectsDialog = page.getByRole("dialog", { name: "Open project" });
  await expect(projectsDialog).toBeVisible();
  const projectRow = projectsDialog.getByRole("listitem").filter({ hasText: projectName });
  await expect(projectRow).toBeVisible();
  await projectRow.getByRole("button", { name: "Open" }).click();
  await expect(projectsDialog).toHaveCount(0);

  // The banner reports the saved item, the family is back on screen…
  const banner = page.getByRole("status").filter({ hasText: `Project ${projectName}` });
  await expect(banner).toBeVisible();
  await expect(banner).toContainText("1 saved item");
  await expect(page.locator(".a11y-status")).toContainText("Family DEMO-FAMILY-1 loaded");
  // …and the saved selection is restored on the row it was made on.
  await expect(
    page
      .getByRole("table", { name: /Compounds in family DEMO-FAMILY-1/ })
      .getByRole("checkbox", { name: `Select compound ${COMPOUND_INCHIKEY}` }),
  ).toBeChecked();
  await expect(page.getByText("1 selected for save")).toBeVisible();
});
