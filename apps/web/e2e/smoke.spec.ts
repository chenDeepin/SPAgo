/**
 * B-17: one end-to-end smoke of the MVP workflow loop (PROMPT.md §13) against
 * a seeded stack: a publication number opens its family, compounds are
 * inspected, a structure query filters the family's compounds, and the
 * filtered results export as CSV. This is the workflow a new user runs first;
 * it does not duplicate the Python suite's API-level coverage — it exists
 * because only a browser can prove the loop the product promises.
 *
 * Prerequisite: the seeded compose stack (`docker compose up -d --build`,
 * demo fixture loaded) reachable at SPAGO_BASE_URL (default
 * http://127.0.0.1:8000).
 */
import { expect, test } from "@playwright/test";

const DEMO_PUBLICATION = "DEMO-PATENT-A";
/** The demo family's first compound (SC-DEMO-0001); an exact member of the
 * set, so the substructure query must match at least it. */
const ASPIRIN_SMILES = "CC(=O)Oc1ccccc1C(=O)O";

test("a number opens a family, compounds filter by structure, results export", async ({
  page,
}) => {
  await page.goto("/");

  // Search: the publication number names the family it opens.
  const search = page.getByRole("search");
  await search.getByLabel("Patent publication number or target").fill(DEMO_PUBLICATION);
  await search.getByRole("button", { name: "Search" }).click();

  // Family view: the loaded-family status and the compound table are visible.
  await expect(page.locator(".a11y-status")).toContainText("Family DEMO-FAMILY-1 loaded");
  const table = page.getByRole("table", { name: /Compounds in family DEMO-FAMILY-1/ });
  await expect(table).toBeVisible();
  // B-19 put the header row inside the table container, so data rows are
  // scoped to the rowgroup — the first row of the table is the header.
  const firstRow = table.getByRole("rowgroup").getByRole("row").first();
  await expect(firstRow).toBeVisible();

  // Compound: opening a row inspects its evidence — the record's citations are
  // one action away, as the evidence-first contract requires.
  await firstRow.click();
  const inspector = page.getByRole("dialog", { name: "Evidence inspector" });
  await expect(inspector).toBeVisible();
  await inspector.getByRole("button", { name: "Close evidence panel" }).click();
  await expect(inspector).toBeHidden();

  // Structure filter: an exact member's SMILES as a substructure query must
  // return at least one compound, and the table states it is the filtered set.
  await page.getByRole("button", { name: "Structure ▾" }).click();
  const dialog = page.getByRole("dialog", { name: "Structure search" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Structure (SMILES)").fill(ASPIRIN_SMILES);
  await dialog.getByRole("button", { name: "Run search" }).click();
  const filtered = page.getByRole("table", {
    name: /Compounds in family DEMO-FAMILY-1 \(structure search\)/,
  });
  await expect(filtered).toBeVisible();
  await expect(filtered.getByRole("rowgroup").getByRole("row").first()).toBeVisible();

  // Export: the filtered result set exports as a CSV download.
  await page.getByRole("button", { name: "Export ▾" }).click();
  const menu = page.getByRole("menu", { name: "Export options" });
  await expect(menu).toBeVisible();
  const csvItem = menu.getByRole("menuitem", { name: /CSV · Structure results \([1-9]\d*\)/ });
  await expect(csvItem).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await csvItem.click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^spago-export.*\.csv$/);
});
