/**
 * B-44 — screen-reader announcement pass over the two virtualized tables.
 *
 * A DOM assertion cannot close the assistive-technology half of AGENTS.md §27:
 * this harness runs a *real* screen reader (Orca, via speech-dispatcher) against
 * the app in Google Chrome with `--force-renderer-accessibility`, drives the
 * tables by keyboard exactly as a reader user would, and captures the exact
 * utterance stream Orca produced for each step.
 *
 * It records three things per step:
 *   1. what DOM element took focus,
 *   2. what Orca actually announced (`SPEECH OUTPUT:` lines from its debug file),
 *   3. the accessibility tree Chrome exposed for the focused row
 *      (`Accessibility.getFullAXTree` through CDP), i.e. the shape the reader
 *      reads from — roles, names and indexes, not the DOM.
 *
 * Requirements (all on this workstation, none added to the product):
 *   - an X display (`DISPLAY`), Orca installed, speech-dispatcher installed,
 *   - Google Chrome installed (Playwright launches it via `channel: "chrome"`),
 *   - the seeded stack reachable at SPAGO_BASE_URL.
 *
 * Usage (from apps/web):
 *   DISPLAY=:1 SPAGO_TARGET_ID=<uuid> node scripts/at-pass.mjs
 *   SPAGO_SCENARIO=family|target   (default: both, family first)
 *   AT_OUT=<path>                  transcript (default: at-pass-transcript.txt)
 *
 * Limits stated up front: the URL under test is served by the running stack, so
 * the pass covers the frontend this checkout built *if the stack serves it*;
 * record `build_id` from /healthz with the run. The desktop session is shared
 * with the human user, so `SPEECH OUTPUT` lines can include announcements for
 * other windows; the transcript keeps them and labels the boundary.
 */
import { chromium } from "playwright";
import { spawn, spawnSync } from "node:child_process";
import { appendFileSync, readFileSync, writeFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const FOCUS_HELPER = join(HERE, "x11-focus.py");

const BASE = process.env.SPAGO_BASE_URL ?? "http://127.0.0.1:8000";
const TARGET_ID = process.env.SPAGO_TARGET_ID ?? "";
const SCENARIO = process.env.SPAGO_SCENARIO ?? "all";
const OUT = process.env.AT_OUT ?? join(process.cwd(), "at-pass-transcript.txt");
const ORCA_LOG = process.env.ORCA_LOG ?? join(tmpdir(), `spago-at-pass-${Date.now()}.log`);
const ORCA = process.env.ORCA_BIN ?? "/usr/bin/orca";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function run(cmd, args) {
  const res = spawnSync(cmd, args, { encoding: "utf8", env: process.env });
  return `${(res.stdout ?? "").trim().split("\n")[0] || (res.stderr ?? "").trim()} (exit ${res.status})`;
}

const orcaVersion = () => `Orca ${run(existsSync(ORCA) ? ORCA : "orca", ["--version"])}`;
const speechServer = () => run("speech-dispatcher", ["--version"]);

function orcaUtterances(cursor) {
  if (!existsSync(ORCA_LOG)) return { utterances: [], cursor };
  const lines = readFileSync(ORCA_LOG, "utf8").split("\n");
  const out = [];
  for (const line of lines) {
    const m = line.match(/^(\d\d:\d\d:\d\d\.\d+) - SPEECH OUTPUT: '(.*)'\{/);
    if (!m) continue;
    const key = line.slice(0, line.indexOf("SPEECH OUTPUT"));
    if (key <= cursor) continue;
    cursor = key;
    out.push({ at: m[1], text: m[2] });
  }
  return { utterances: out, cursor };
}

writeFileSync(
  OUT,
  [
    `# SPAgo screen-reader announcement pass (B-44)`,
    `# date: ${new Date().toISOString()}`,
    `# base: ${BASE}   scenario: ${SCENARIO}`,
    `# reader: ${orcaVersion()} via speech-dispatcher, on DISPLAY=${process.env.DISPLAY} (window activation re-asserted each step)`,
    `# speech server: ${speechServer()}`,
    `# browser: Google Chrome (channel=chrome) with --force-renderer-accessibility`,
    `# healthz: ${await fetch(`${BASE}/healthz`).then((r) => r.json()).then((h) => JSON.stringify({ build_id: h.build_id, dataset_version: h.dataset_version })).catch((e) => `unreachable: ${e.message}`)}`,
    ``,
  ].join("\n"),
);

const browser = await chromium.launch({
  channel: "chrome",
  headless: false,
  args: [
    "--force-renderer-accessibility",
    "--window-size=1600,1000",
    "--window-position=0,0",
    "--no-first-run",
    "--no-default-browser-check",
  ],
});
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
const page = await context.newPage();
const cdp = await context.newCDPSession(page);

async function focusDescription() {
  return page.evaluate(() => {
    const el = document.activeElement;
    if (!el || el === document.body) return { focus: "document body" };
    const row = el.closest?.("[role=row]");
    const cell = el.closest?.("[role=cell],[role=columnheader]");
    return {
      focus: `${el.tagName.toLowerCase()}${el.getAttribute("role") ? `[role=${el.getAttribute("role")}]` : ""}`,
      name: el.getAttribute("aria-label") ?? (el.textContent ?? "").trim().slice(0, 60),
      row: row ? row.getAttribute("aria-rowindex") : null,
      cell: cell ? (cell.textContent ?? "").trim().slice(0, 40) : null,
    };
  });
}

/** The accessibility tree Chrome exposes around the focused object — the shape
 * a screen reader reads, as opposed to the DOM the app wrote. */
async function axNeighbourhood() {
  const { nodes } = await cdp.send("Accessibility.getFullAXTree");
  const byId = new Map(nodes.map((n) => [n.nodeId, n]));
  const interesting = nodes.filter((n) => {
    const r = n.role?.value;
    return r === "table" || r === "row" || r === "cell" || r === "columnheader" || r === "rowgroup";
  });
  const summarise = (n) => ({
    role: n.role?.value,
    name: (n.name?.value ?? "").slice(0, 50),
    rowindex: n.properties?.find((p) => p.name === "rowIndex")?.value?.value,
    colindex: n.properties?.find((p) => p.name === "columnIndex")?.value?.value,
    ownedChildren: (n.childIds ?? []).length,
    implicitRowCount: n.properties?.find((p) => p.name === "rowCount")?.value?.value,
    ignored: n.ignored,
    parent: n.parentId ? byId.get(n.parentId)?.role?.value : undefined,
  });
  return interesting.slice(0, 14).map(summarise);
}

/** A reader announces the *active* window only. `bringToFront` alone left
 * `_NET_ACTIVE_WINDOW` at 0x0 in this session and Orca silently dropped every
 * focus event ("[frame | …] lacks state active"), so this asks X for the
 * activation explicitly and reports what the root window then says. */
let lastActivation = null;
function activateWindow(always = false) {
  if (!process.env.DISPLAY || !existsSync(FOCUS_HELPER)) {
    appendFileSync(OUT, `\n# window activation skipped (no DISPLAY or no helper)\n`);
    return;
  }
  const python = existsSync("/usr/bin/python3") ? "/usr/bin/python3" : "python3";
  const res = spawnSync(python, [FOCUS_HELPER, "--title-match", "SPAgo"], {
    env: process.env,
    encoding: "utf8",
  });
  const line = (res.stdout ?? "").trim() || (res.stderr ?? "").trim();
  // A reader announces the active window only, and this is a shared desktop:
  // re-assert activation before every step, but record it only when it changed.
  if (always || line !== lastActivation) {
    appendFileSync(OUT, `\n# window activation: ${line} (exit ${res.status})\n`);
    lastActivation = line;
  }
}

let cursor = "";
async function step(label, fn) {
  ({ cursor } = orcaUtterances(cursor)); // drain before the step
  activateWindow();
  // A reader speaks for the active window only, and this desktop's other
  // windows claim activation while the pass runs: hold it for the step.
  const keeper = setInterval(() => activateWindow(true), 250);
  await fn();
  await sleep(1100);
  clearInterval(keeper);
  const { utterances, cursor: next } = orcaUtterances(cursor);
  cursor = next;
  const focus = await focusDescription();
  const block = [
    ``,
    `### ${label}`,
    `focus: ${JSON.stringify(focus)}`,
    utterances.length ? `announced:` : `announced: (nothing)`,
    ...utterances.map((u) => `  [${u.at}] ${u.text}`),
  ].join("\n");
  appendFileSync(OUT, block + "\n");
  console.log(block);
}

/** Tab until focus lands on an element matching `predicate`, reporting the
 * announcement at each stop, and how many stops it took. */
async function tabTo(label, predicate, max = 40) {
  for (let i = 1; i <= max; i++) {
    await step(`${label}: Tab #${i}`, () => page.keyboard.press("Tab"));
    const d = await focusDescription();
    if (predicate(d)) {
      appendFileSync(OUT, `> reached after ${i} Tab press(es)\n`);
      return i;
    }
  }
  appendFileSync(OUT, `> NOT reached within ${max} Tab presses\n`);
  return -1;
}

async function startOrca() {
  if (process.env.AT_ORCA === "external") {
    appendFileSync(OUT, `\n# Orca is expected to be running externally (AT_ORCA=external)\n`);
    return null;
  }
  if (!existsSync(ORCA)) {
    appendFileSync(OUT, `\n# Orca not found at ${ORCA}; announcement capture unavailable\n`);
    return null;
  }
  try {
    rmSync(ORCA_LOG, { force: true });
  } catch {}
  const child = spawn(ORCA, ["--replace", "--debug", `--debug-file=${ORCA_LOG}`], {
    env: process.env,
    stdio: "ignore",
    detached: false,
  });
  await sleep(7000); // Orca announces "Screen reader on." and attaches to AT-SPI
  appendFileSync(OUT, `\n# Orca started (pid ${child.pid}), debug file ${ORCA_LOG}\n`);
  return child;
}

const orca = await startOrca();

if (SCENARIO === "all" || SCENARIO === "family") {
  await step("family view: open DEMO-PATENT-A", async () => {
    await page.goto(`${BASE}/?q=DEMO-PATENT-A`);
    await page.waitForSelector('[role=table]');
    await page.bringToFront();
    activateWindow();
    await sleep(1200);
  });
  await step("family view: the table is announced when focus enters it", async () =>
    page.keyboard.press("Tab"));
  await tabTo("family view", (d) => d.row === "2", 40);
  appendFileSync(OUT, `\nfamily header/tree:\n${JSON.stringify(await axNeighbourhood(), null, 1)}\n`);
  // A table user's own reading commands. Orca grabs these at the X level;
  // Playwright injects keys into the renderer, so whether they arrive is
  // itself part of what this records.
  await step("family view: Orca next column (Ctrl+Alt+Right)", () =>
    page.keyboard.press("Control+Alt+ArrowRight"));
  await step("family view: Orca next row (Ctrl+Alt+Down)", () =>
    page.keyboard.press("Control+Alt+ArrowDown"));
  await step("family view: ArrowDown on the focused row", () => page.keyboard.press("ArrowDown"));
  await step("family view: Tab to the row's own checkbox", () => page.keyboard.press("Tab"));
  await step("family view: Space on the checkbox (selects, must not inspect)", async () => {
    await page.keyboard.press(" ");
    await sleep(500);
    const state = await page.evaluate(() => ({
      inspected: document.querySelectorAll('[role=dialog]').length > 0,
      boxes: [...document.querySelectorAll('[role=rowgroup] [role=row] input[type=checkbox]')].filter(
        (b) => b.checked,
      ).length,
    }));
    appendFileSync(
      OUT,
      `> keyboard rule (B-19) on this build: after Space on a row checkbox — inspector open: ${state.inspected}, checked row boxes: ${state.boxes}\n`,
    );
  });
  await step("family view: Shift+Tab back to the row, then Enter (inspects)", async () => {
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Enter");
    await sleep(700);
    const inspected = await page.evaluate(() =>
      [...document.querySelectorAll('[role=dialog]')].map((d) => d.getAttribute("aria-label")),
    );
    appendFileSync(
      OUT,
      `> keyboard rule (B-19) on this build: after Enter on the focused row — dialogs: ${JSON.stringify(inspected)}\n`,
    );
  });
  await step("family view: close the inspector", async () => {
    await page.keyboard.press("Escape");
    await sleep(600);
  });
}

if (SCENARIO === "all" || SCENARIO === "target") {
  if (!TARGET_ID) {
    appendFileSync(OUT, `\n# SPAGO_TARGET_ID unset: target-view half skipped\n`);
  } else {
    await step("target view: open the stored investigation", async () => {
      await page.goto(`${BASE}/?q=IL6&t=${TARGET_ID}`);
      await page.waitForSelector('[role=table]');
      await page.bringToFront();
      activateWindow();
      await sleep(1200);
    });
    await step("target view: enter the table", () => page.keyboard.press("Tab"));
    const stops = await tabTo("target view", (d) => d.row === "2", 40);
    appendFileSync(OUT, `\ntarget header/tree:\n${JSON.stringify(await axNeighbourhood(), null, 1)}\n`);
    appendFileSync(OUT, `\ntarget table (candidate) accessibility shape:\n${JSON.stringify((await axNeighbourhood()).filter((n) => n.role === "table" || n.role === "rowgroup" || (n.role === "row" && !n.parent)), null, 1)}\n`);
    await step("target view: Orca next column (Ctrl+Alt+Right)", () =>
      page.keyboard.press("Control+Alt+ArrowRight"));
    await step("target view: Orca next row (Ctrl+Alt+Down)", () =>
      page.keyboard.press("Control+Alt+ArrowDown"));
    await step("target view: Space on a candidate row (inspects)", () => page.keyboard.press(" "));
    await step("target view: Escape closes", async () => {
      await page.keyboard.press("Escape");
      await sleep(600);
    });
    // How many tab stops does it cost to cross the table? Each row carries
    // tabIndex=0, so this measures the reader user's cost of passing the table.
    let crossed = 0;
    for (let i = 0; i < 30; i++) {
      await page.keyboard.press("Tab");
      crossed += 1;
      const d = await focusDescription();
      if (!d.row) break;
    }
    appendFileSync(
      OUT,
      `\n> after leaving the first row, ${crossed} further Tab press(es) still landed inside rows\n`,
    );
    void stops;
  }
}

appendFileSync(OUT, `\n# end of pass. Orca debug file kept at ${ORCA_LOG}\n`);
if (orca) {
  orca.kill("SIGTERM");
  await sleep(1500);
}
await context.close();
await browser.close();
console.log(`transcript: ${OUT}`);
