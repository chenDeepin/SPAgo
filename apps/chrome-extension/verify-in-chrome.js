/**
 * Real-browser check for the companion extension (M4 / backlog item B2).
 *
 * `check.js` validates the manifest, the syntax and the detection contract in
 * Node. This script goes one step further and does what only a browser can:
 * Chrome loads the unpacked extension, a page under the content-script match
 * pattern is opened, and the handoff is read back out of the service worker's
 * own `chrome.storage.session`. Nothing about the extension is stubbed.
 *
 * What it verifies, end to end:
 *
 *   1. The browser accepts the manifest and installs the unpacked extension.
 *   2. The MV3 service worker starts (its target appears).
 *   3. The content script runs on a matching page, detects the publication
 *      number from the URL, and messages the worker.
 *   4. The worker stores it — read back from `storage.session` by the worker
 *      itself, which is exactly what the side panel reads.
 *   5. `sidepanel.html` renders that stored value ("Detected: US…"), so the
 *      panel's read-and-render path is exercised with real extension storage.
 *   6. The panel behavior the toolbar click relies on is *verified as set* in
 *      the running worker (`chrome.sidePanel.getPanelBehavior()` →
 *      `openPanelOnActionClick: true`) — a setup failure there would otherwise
 *      only ever be a silent `console.error`, and the click would do nothing.
 *
 * What it does **not** verify (recorded rather than implied): the physical
 * toolbar click and Chrome's own side panel surface chrome. Synthesizing a
 * browser-toolbar user gesture needs OS-level input injection (or a keyboard
 * shortcut added to the manifest for the test's sake); neither exists in this
 * checkout, so the click itself stays uncovered — and a pass here must never
 * be reported as "the extension workflow works".
 *
 * Browser choice: branded Google Chrome (137+) refuses `--load-extension`
 * ("not allowed in Google Chrome"), so this script prefers an unbranded
 * Chromium / Chrome for Testing build. Set `CHROME=/path/to/chrome` to pick one
 * explicitly; otherwise the known locations are searched, including the
 * Playwright browser cache (`~/.cache/ms-playwright/chromium-*`). If only a
 * branded Chrome is available the script fails with that reason instead of
 * reporting a broken extension.
 *
 * The page is served locally over HTTPS and mapped onto `patents.google.com`
 * with `--host-resolver-rules`, so no live network request is made and no
 * third-party site is contacted.
 *
 * Run:
 *     node apps/chrome-extension/verify-in-chrome.js
 * Optional: CHROME=/path/to/chrome, PORT=8443, DEBUG_PORT=9222, KEEP_PROFILE=1
 */
const { execFileSync, spawn } = require("child_process");
const fs = require("fs");
const https = require("https");
const os = require("os");
const path = require("path");

const EXTENSION_DIR = __dirname;
const PORT = Number(process.env.PORT || 8443);
const PATENT = "US10102057B2";
const PAGE_PATH = `/patent/${PATENT}/en`;
const HOST = "patents.google.com";
const DEBUG_PORT = Number(process.env.DEBUG_PORT || 9222);

/** Unbranded builds first: branded Chrome ignores `--load-extension`. */
function findChrome() {
  if (process.env.CHROME) return process.env.CHROME;
  const home = os.homedir();
  const candidates = [
    "chromium",
    "chromium-browser",
    "google-chrome-for-testing",
    "/usr/lib/chromium/chromium",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
  ];
  const playwrightCache = path.join(home, ".cache", "ms-playwright");
  if (fs.existsSync(playwrightCache)) {
    for (const entry of fs.readdirSync(playwrightCache).sort().reverse()) {
      if (!entry.startsWith("chromium-")) continue; // skip the headless shell
      const binary = path.join(playwrightCache, entry, "chrome-linux64", "chrome");
      if (fs.existsSync(binary)) return binary;
      const macBinary = path.join(
        playwrightCache,
        entry,
        "chrome-mac",
        "Chromium.app",
        "Contents",
        "MacOS",
        "Chromium",
      );
      if (fs.existsSync(macBinary)) return macBinary;
    }
  }
  for (const name of candidates) {
    if (name.startsWith("/") && fs.existsSync(name)) return name;
    try {
      const found = execFileSync("which", [name], { stdio: ["ignore", "pipe", "ignore"] })
        .toString()
        .trim();
      if (found) return found;
    } catch {
      /* try the next candidate */
    }
  }
  return "google-chrome";
}

/** A throwaway TLS server: the extension's match pattern is https-only, and the
 * page content is irrelevant — the detector reads the URL, which is the point
 * (it must not need the page's DOM to identify a patent). */
function startPageServer() {
  const key = path.join(os.tmpdir(), "spago-verify-key.pem");
  const cert = path.join(os.tmpdir(), "spago-verify-cert.pem");
  if (!fs.existsSync(key) || !fs.existsSync(cert)) {
    execFileSync(
      "openssl",
      [
        "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", key, "-out", cert, "-days", "1",
        "-subj", `/CN=${HOST}`,
      ],
      { stdio: "ignore" },
    );
  }
  const server = https.createServer(
    { key: fs.readFileSync(key), cert: fs.readFileSync(cert) },
    (_req, res) => {
      res.writeHead(200, { "content-type": "text/html" });
      res.end(`<!doctype html><title>${PATENT}</title><h1>${PATENT}</h1>`);
    },
  );
  return new Promise((resolve) => server.listen(PORT, "127.0.0.1", () => resolve(server)));
}

function httpJson(url) {
  return new Promise((resolve, reject) => {
    require("http")
      .get(url, (res) => {
        let body = "";
        res.on("data", (chunk) => (body += chunk));
        res.on("end", () => {
          try {
            resolve(JSON.parse(body));
          } catch (err) {
            reject(err);
          }
        });
      })
      .on("error", reject);
  });
}

/** Minimal CDP client: Node 22 ships a global WebSocket, so no dependency. */
function cdpEvaluate(wsUrl, expression) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(wsUrl);
    const timer = setTimeout(() => {
      socket.close();
      reject(new Error("CDP evaluate timed out"));
    }, 15000);
    socket.addEventListener("open", () => {
      socket.send(
        JSON.stringify({
          id: 1,
          method: "Runtime.evaluate",
          params: { expression, awaitPromise: true, returnByValue: true },
        }),
      );
    });
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.id !== 1) return;
      clearTimeout(timer);
      socket.close();
      const details = message.result?.exceptionDetails;
      if (message.error) reject(new Error(message.error.message));
      else if (details) {
        reject(new Error(details.exception?.description || details.text || "evaluation threw"));
      } else resolve(message.result?.result?.value);
    });
    socket.addEventListener("error", (event) => {
      clearTimeout(timer);
      reject(new Error(`CDP socket error: ${event.message || "unknown"}`));
    });
  });
}

/** Opens a tab and returns its target (used for the side panel page). */
function openTab(url) {
  return new Promise((resolve, reject) => {
    const request = require("http").request(
      { host: "127.0.0.1", port: DEBUG_PORT, path: `/json/new?${encodeURIComponent(url)}`, method: "PUT" },
      (res) => {
        let body = "";
        res.on("data", (chunk) => (body += chunk));
        res.on("end", () => {
          try {
            resolve(JSON.parse(body));
          } catch (err) {
            reject(err);
          }
        });
      },
    );
    request.on("error", reject);
    request.end();
  });
}

async function waitFor(predicate, { attempts, delayMs, label }) {
  for (let i = 0; i < attempts; i++) {
    const value = await predicate();
    if (value) return value;
    await new Promise((resolve) => setTimeout(resolve, delayMs));
  }
  throw new Error(`timed out waiting for ${label}`);
}

function removeProfile(dir) {
  try {
    fs.rmSync(dir, { recursive: true, force: true });
  } catch {
    // Chrome may still be flushing the profile as it exits; a leftover temp
    // directory is not a verification failure.
  }
}

async function main() {
  const profileDir = fs.mkdtempSync(path.join(os.tmpdir(), "spago-ext-profile-"));
  const server = await startPageServer();
  const chromePath = findChrome();
  console.log(`browser: ${chromePath}`);
  const chrome = spawn(
    chromePath,
    [
      "--headless=new",
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-gpu",
      "--ignore-certificate-errors",
      `--load-extension=${EXTENSION_DIR}`,
      `--disable-extensions-except=${EXTENSION_DIR}`,
      `--user-data-dir=${profileDir}`,
      `--remote-debugging-port=${DEBUG_PORT}`,
      `--host-resolver-rules=MAP ${HOST} 127.0.0.1:${PORT}`,
      `https://${HOST}${PAGE_PATH}`,
    ],
    { stdio: ["ignore", "pipe", "pipe"] },
  );
  let chromeLog = "";
  chrome.stdout.on("data", (d) => (chromeLog += d.toString()));
  chrome.stderr.on("data", (d) => (chromeLog += d.toString()));

  let failures = 0;
  try {
    const worker = await waitFor(
      async () => {
        const targets = await httpJson(`http://127.0.0.1:${DEBUG_PORT}/json/list`).catch(() => []);
        return targets.find(
          (t) =>
            t.type === "service_worker" &&
            t.url.startsWith("chrome-extension://") &&
            t.url.endsWith("/background.js"),
        );
      },
      { attempts: 40, delayMs: 500, label: "the extension service worker" },
    ).catch((err) => {
      if (/load-extension is not allowed/.test(chromeLog)) {
        throw new Error(
          "this browser refuses --load-extension (branded Google Chrome); " +
            "set CHROME to a Chromium / Chrome for Testing binary",
        );
      }
      throw err;
    });
    console.log(`service worker: ${worker.url}`);
    const extensionId = new URL(worker.url).host;

    // The content script runs at `document_idle`, so the worker target can
    // exist before the message arrives: poll the stored value, not the API.
    const stored = await waitFor(
      async () =>
        cdpEvaluate(
          worker.webSocketDebuggerUrl,
          "chrome.storage.session.get(null).then((s) => s.spagoPublicationNumber || '')",
        ),
      { attempts: 30, delayMs: 500, label: "the handoff to reach storage.session" },
    ).catch(() => null);
    if (stored !== PATENT) {
      const last = await cdpEvaluate(
        worker.webSocketDebuggerUrl,
        "chrome.storage.session.get(null)",
      ).catch((err) => `unreadable: ${err.message}`);
      console.error(
        `FAIL: expected storage.session.spagoPublicationNumber=${PATENT}, got ${JSON.stringify(last)}`,
      );
      failures++;
    } else {
      console.log(`storage.session.spagoPublicationNumber=${stored}`);
    }

    const targets = await httpJson(`http://127.0.0.1:${DEBUG_PORT}/json/list`);
    const page = targets.find((t) => t.type === "page" && t.url.includes(PAGE_PATH));
    if (!page) {
      console.error(`FAIL: the mapped test page ${PAGE_PATH} never loaded`);
      failures++;
    } else {
      console.log(`page: ${page.url}`);
    }

    // The panel is a page like any other: what it renders is what a user sees
    // once Chrome shows it in the side panel surface.
    const panel = await openTab(`chrome-extension://${extensionId}/sidepanel.html`);
    const panelText = await waitFor(
      async () =>
        cdpEvaluate(
          panel.webSocketDebuggerUrl,
          "(document.getElementById('detected') || {}).textContent || ''",
        ),
      { attempts: 20, delayMs: 500, label: "the side panel to render the detected number" },
    );
    console.log(`side panel: ${JSON.stringify(panelText)}`);
    if (!String(panelText).includes(PATENT)) {
      console.error(`FAIL: side panel did not render the detected number ${PATENT}`);
      failures++;
    }

    // The toolbar click opens the panel only while the worker's
    // `setPanelBehavior` actually took effect. Read it back from the running
    // worker instead of trusting a promise nobody observed (B-18).
    const behavior = await cdpEvaluate(
      worker.webSocketDebuggerUrl,
      "chrome.sidePanel.getPanelBehavior().then((b) => ({ open: !!(b && b.openPanelOnActionClick) }))",
    ).catch((err) => ({ error: err.message }));
    if (behavior && behavior.open === true) {
      console.log("panel behavior: openPanelOnActionClick=true (read back from the running worker)");
    } else {
      console.error(
        `FAIL: expected the running worker's sidePanel behavior openPanelOnActionClick=true, got ${JSON.stringify(behavior)}`,
      );
      failures++;
    }
  } catch (err) {
    console.error(`FAIL: ${err.message}`);
    failures++;
    if (chromeLog.trim()) console.error(`browser output:\n${chromeLog.trim()}`);
  } finally {
    chrome.kill("SIGTERM");
    server.close();
    if (process.env.KEEP_PROFILE) console.log(`profile kept at ${profileDir}`);
    else removeProfile(profileDir);
  }

  if (failures === 0) {
    console.log(
      "companion browser check: load, service worker, detection, handoff, panel render and " +
        "panel-behavior flag verified." +
        " The physical toolbar click and the side panel surface itself are not covered by this script.",
    );
    return 0;
  }
  console.error(`companion browser check: ${failures} failed`);
  return 1;
}

main().then((code) => process.exit(code));
