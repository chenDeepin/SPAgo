/**
 * B-43 check: one navigation step must be one history entry.
 *
 * Opens a target view, searches a publication from it, then reads the URL and
 * the visible scope after one Back press. Before the fix that push happened
 * twice with the same state, so one Back landed on a duplicate and a second was
 * needed to reach the target view.
 *
 *   DISPLAY=:1 node scripts/history-step-check.mjs
 */
import { chromium } from "playwright";

const BASE = process.env.SPAGO_BASE_URL ?? "http://127.0.0.1:8000";
const TARGET_ID = process.env.SPAGO_TARGET_ID ?? "5ed5e9f2-c733-543f-96dd-f58ae5a1f618";
const PUBLICATION = process.env.SPAGO_PUBLICATION ?? "DEMO-PATENT-A";

const browser = await chromium.launch({
  channel: "chrome",
  headless: false,
  args: ["--window-size=1600,1000", "--no-first-run"],
});
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
const page = await context.newPage();

const scope = async () => {
  const url = new URL(page.url());
  return {
    search: url.search,
    historyLength: await page.evaluate(() => history.length),
    candidateTable: await page.locator('[role=table][aria-label^="Candidate compounds"]').count(),
    compoundTable: await page.locator('[role=table][aria-label^="Compounds in"]').count(),
  };
};

await page.goto(`${BASE}/?q=IL6&t=${TARGET_ID}`);
await page.waitForSelector("[role=table]");
await page.waitForTimeout(2500);
const inTarget = await scope();

// One explicit navigation step: search the publication from inside the target view.
const search = page.getByRole("search");
await search.getByLabel("Patent publication number or target").fill(PUBLICATION);
await search.getByRole("button", { name: "Search" }).click();
await page.waitForSelector('[role=table][aria-label^="Compounds in"]');
await page.waitForTimeout(1200);
const afterSearch = await scope();

const steps = [];
for (let i = 1; i <= 3; i++) {
  await page.goBack();
  await page.waitForTimeout(1200);
  const s = await scope();
  steps.push({ back: i, ...s });
  if (s.candidateTable > 0) break;
}

// The regression this item warned about: the target entry's own filter state
// (B-39 keeps it in that entry's URL) must survive the round trip.
await page.goto(`${BASE}/?q=IL6&t=${TARGET_ID}`);
await page.waitForSelector("[role=table]");
await page.waitForTimeout(2000);
await page.getByRole("spinbutton", { name: /Potency threshold/ }).fill("1");
await page.getByRole("spinbutton", { name: /Potency threshold/ }).press("Enter");
await page.waitForTimeout(1500);
const withFilter = await scope();
await search.getByLabel("Patent publication number or target").fill(PUBLICATION);
await search.getByRole("button", { name: "Search" }).click();
await page.waitForSelector('[role=table][aria-label^="Compounds in"]');
await page.waitForTimeout(1000);
await page.goBack();
await page.waitForTimeout(1500);
const filterAfterBack = await scope();

console.log(JSON.stringify({ inTarget, afterSearch, back: steps, b39: { withFilter, filterAfterBack } }, null, 2));
await context.close();
await browser.close();
