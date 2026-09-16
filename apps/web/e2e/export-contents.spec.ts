/**
 * B-38 / B-33 regression: the candidates CSV must agree with the menu that
 * offered it, and the file must carry the policy the screen was looking at.
 * The menu claims "Current candidates (N)" while the table shows a filtered
 * view — if the export ignored the evidence-class filter or the threshold
 * override, the row count or the `reference_threshold_nM` column would betray
 * it (AGENTS.md §11: the threshold travels with every export).
 *
 * No route injection: the download is the real export endpoint's answer for
 * the stored IL6 investigation, under a filter and threshold set through the
 * real controls. The threshold (5 µM) is chosen below the deployment policy so
 * the override is distinguishable from the default in the file.
 *
 * Viewport: tall (B-42), same as the other target-view specs.
 */
import fs from "node:fs";
import { expect, test } from "@playwright/test";

/** Stored IL6 investigation opened by URL state (AGENTS.md §19). */
const IL6_URL =
  "/?q=IL6&t=5ed5e9f2-c733-543f-96dd-f58ae5a1f618";
const THRESHOLD_MICROMOLAR = 5;
const THRESHOLD_NANOMOLAR = String(THRESHOLD_MICROMOLAR * 1000);

test.use({ viewport: { width: 1600, height: 1000 } });

/** Minimal quote-aware CSV splitter (standard library only, §23): patent
 * lists join with "|" but fields like SMILES and dataset version JSON contain
 * commas and doubled quotes, so a plain split would miscount columns. */
function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += ch;
      }
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      row.push(field);
      field = "";
    } else if (ch === "\n") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else if (ch !== "\r") {
      field += ch;
    }
  }
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows.filter((r) => r.length > 1 || r[0] !== "");
}

test("the candidates CSV matches the menu's count and the applied threshold policy", async ({
  page,
}) => {
  await page.goto(IL6_URL);

  // The view is up: coverage chips and candidate rows answer from stored data.
  await expect(page.getByRole("list", { name: "Source coverage" })).toBeVisible();
  const table = page.getByRole("table", { name: "Candidate compounds for IL6" });
  await expect(table).toBeVisible();

  // Apply a threshold override below the deployment policy. The table's footer
  // states the policy its classes were computed under, so the override — and
  // the recomputation it must trigger — is visible before any export runs.
  const thresholdInput = page.getByLabel("Potency threshold in micromolar");
  await expect(thresholdInput).toBeVisible();
  await thresholdInput.fill(String(THRESHOLD_MICROMOLAR));
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page.locator(".table-footer").first()).toContainText(
    `${THRESHOLD_MICROMOLAR} µM`,
  );

  // Narrow the scope with the evidence-class filter and let that exact query
  // settle before the menu's claimed count is read.
  const filteredCandidates = page.waitForResponse(
    (response) => response.url().includes("evidence_class=measured_direct_binding"),
  );
  await page.getByLabel("Evidence class").selectOption("measured_direct_binding");
  await filteredCandidates;
  await expect(
    table.getByRole("checkbox", { name: /Select candidate / }).first(),
  ).toBeVisible();

  // The menu states how many rows "current candidates" covers.
  await page.getByRole("button", { name: "Export ▾" }).click();
  const menu = page.getByRole("menu", { name: "Export options" });
  await expect(menu).toBeVisible();
  const csvItem = menu.getByRole("menuitem", { name: /CSV · Current candidates \(\d+\)/ });
  await expect(csvItem).toBeVisible();
  const claimed = (await csvItem.innerText()).match(/\((\d+)\)/);
  expect(claimed).not.toBeNull();
  const claimedCount = Number(claimed![1]);
  // A filtered view of the stored investigation is a real result set, not a
  // degenerate one — this pins the fixture's health for the count comparison.
  expect(claimedCount).toBeGreaterThan(0);

  const downloadPromise = page.waitForEvent("download");
  await csvItem.click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^spago-export\.csv$/);

  const rows = parseCsv(fs.readFileSync((await download.path())!, "utf8"));
  const header = rows[0] ?? [];
  const thresholdCol = header.indexOf("reference_threshold_nM");
  const policyCol = header.indexOf("reference_policy_version");
  expect(thresholdCol).toBeGreaterThanOrEqual(0);
  expect(policyCol).toBeGreaterThanOrEqual(0);

  const dataRows = rows.slice(1);
  // The file's row count equals the count the menu claimed.
  expect(dataRows.length).toBe(claimedCount);
  // …and every row states the policy the screen applied, not the default.
  for (const row of dataRows) {
    expect(row[thresholdCol]).toBe(THRESHOLD_NANOMOLAR);
    expect(row[policyCol]).toBe("potency-gate-v1");
  }
});
