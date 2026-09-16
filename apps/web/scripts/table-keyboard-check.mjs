/**
 * B-46 keyboard check: does Tab cross a virtualized table in a bounded number of
 * stops, and do the arrow keys move the current row (including across the
 * virtual window)? Runs against the stack; prints a JSON summary.
 *
 *   DISPLAY=:1 node scripts/table-keyboard-check.mjs
 */
import { chromium } from "playwright";

const BASE = process.env.SPAGO_BASE_URL ?? "http://127.0.0.1:8000";
const TARGET_ID = process.env.SPAGO_TARGET_ID ?? "5ed5e9f2-c733-543f-96dd-f58ae5a1f618";
const PUBLICATION = process.env.SPAGO_PUBLICATION ?? "DEMO-PATENT-A";

const browser = await chromium.launch({
  channel: "chrome",
  headless: false,
  args: ["--force-renderer-accessibility", "--window-size=1600,1000", "--window-position=0,0", "--no-first-run"],
});
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
const page = await context.newPage();

const focus = () =>
  page.evaluate(() => {
    const el = document.activeElement;
    if (!el) return { none: true };
    const row = el.closest?.("[role=row]");
    return {
      tag: el.tagName,
      role: el.getAttribute("role"),
      name: el.getAttribute("aria-label") ?? (el.textContent ?? "").trim().slice(0, 28),
      row: row?.getAttribute("aria-rowindex") ?? null,
      tabIndex: el.tabIndex,
    };
  });

async function countStopsThroughTable(label) {
  // Enter the table, then count Tab presses until focus leaves it.
  let inRow = false;
  let stopsToEnter = 0;
  for (let i = 1; i <= 60 && !inRow; i++) {
    await page.keyboard.press("Tab");
    stopsToEnter = i;
    const f = await focus();
    if (f.role === "row") inRow = true;
  }
  if (!inRow) return { label, entered: false };
  let stopsInside = 0;
  const seen = [];
  for (let i = 0; i < 40; i++) {
    await page.keyboard.press("Tab");
    const f = await focus();
    seen.push(`${f.tag}${f.role ? `[${f.role}]` : ""}${f.row ? ` row ${f.row}` : ""}:${f.name}`);
    if (f.role !== "row" && !f.row) break;
    stopsInside += 1;
  }
  return { label, stopsToEnter, stopsInside, trail: seen };
}

const report = {};

await page.goto(`${BASE}/?q=${PUBLICATION}`);
await page.waitForSelector("[role=table]");
await page.bringToFront();
await page.waitForTimeout(1500);
report.compoundTableStops = await countStopsThroughTable("compound");

// Arrow keys: move down five rows from the current row and read where focus is.
await page.evaluate(() => document.querySelectorAll("[role=rowgroup] [data-index]")[0]?.focus());
const before = await focus();
for (let i = 0; i < 5; i++) await page.keyboard.press("ArrowDown");
const afterDown = await focus();
await page.keyboard.press("End");
const afterEnd = await focus();
await page.keyboard.press("Home");
const afterHome = await focus();
report.compoundArrow = { before, afterDown, afterEnd, afterHome };

// Enter still inspects; Space on the row checkbox still selects without inspecting.
await page.evaluate(() => document.querySelectorAll("[role=rowgroup] [data-index]")[1]?.focus());
await page.keyboard.press("Enter");
await page.waitForTimeout(700);
report.enterOpensInspector = await page.locator('[role=dialog]').count();
await page.keyboard.press("Escape");
await page.waitForTimeout(400);
await page.evaluate(() => document.querySelectorAll("[role=rowgroup] [data-index]")[1]?.focus());
await page.keyboard.press("Tab"); // to the checkbox inside the current row
await page.keyboard.press(" ");
await page.waitForTimeout(500);
report.spaceOnCheckbox = await page.evaluate(() => ({
  inspector: document.querySelectorAll("[role=dialog]").length,
  checked: [...document.querySelectorAll("[role=rowgroup] input[type=checkbox]")].filter((b) => b.checked).length,
}));

await page.goto(`${BASE}/?q=IL6&t=${TARGET_ID}`);
await page.waitForSelector("[role=table]");
await page.bringToFront();
await page.waitForTimeout(2500);
report.candidateTableStops = await countStopsThroughTable("candidate");

// Cross the virtual window: 60 ArrowDown presses must keep focus on a live,
// rendered row (the virtualizer scrolls instead of unmounting the focused row).
await page.evaluate(() => document.querySelectorAll("[role=rowgroup] [data-index]")[0]?.focus());
const startRow = await focus();
for (let i = 0; i < 60; i++) await page.keyboard.press("ArrowDown");
await page.waitForTimeout(600);
report.longArrowRun = { startRow, end: await focus(), rendered: await page.locator("[role=rowgroup] [data-index]").count() };

console.log(JSON.stringify(report, null, 2));
await context.close();
await browser.close();
