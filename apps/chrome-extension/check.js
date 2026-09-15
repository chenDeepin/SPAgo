/**
 * Node-based checks for the companion extension: manifest validity, JS syntax,
 * and the URL detection contract. Run: node apps/chrome-extension/check.js
 */
const fs = require("fs");
const path = require("path");
const { detectPublicationNumber } = require("./detect");

const dir = __dirname;
let failures = 0;

const manifest = JSON.parse(fs.readFileSync(path.join(dir, "manifest.json"), "utf8"));
if (manifest.manifest_version !== 3) { console.error("FAIL: manifest_version must be 3"); failures++; }
const required = ["background.service_worker", "side_panel.default_path", "action.default_title"];
for (const key of required) {
  if (!key.split(".").reduce((o, k) => (o ? o[k] : undefined), manifest)) {
    console.error(`FAIL: manifest missing ${key}`); failures++;
  }
}

// `verify-in-chrome.js` is a Node harness, not an extension file, but it ships
// here and a parse error in it would only surface when someone runs the
// browser check, so its syntax is checked with the rest.
for (const jsFile of [
  "background.js",
  "content.js",
  "sidepanel.js",
  "detect.js",
  "verify-in-chrome.js",
]) {
  const src = fs.readFileSync(path.join(dir, jsFile), "utf8");
  try {
    new Function(src.replace(/^chrome\./gm, "globalThis.__stub.")); // syntax-only check stub
  } catch {
    try {
      new (require("vm").Script)(src);
    } catch (err) {
      console.error(`FAIL: ${jsFile} syntax: ${err.message}`);
      failures++;
    }
  }
}

const cases = [
  ["https://patents.google.com/patent/US10102057B2/en", "US10102057B2"],
  ["https://worldwide.espacenet.com/patent/search?q=pn%3DEP1234567A1", "EP1234567A1"],
  ["https://worldwide.espacenet.com/patent/search?q=EP1234567A1", "EP1234567A1"],
  ["https://worldwide.espacenet.com/patent/EP4321000A1", "EP4321000A1"],
  ["https://patents.google.com/?q=food", null],
  ["https://example.com/patent/US10102057B2", null],
];
for (const [url, expected] of cases) {
  const got = detectPublicationNumber(url);
  if (got !== expected) {
    console.error(`FAIL: detect(${url}) = ${got}, expected ${expected}`);
    failures++;
  }
}

if (failures === 0) {
  console.log("companion checks: all passed");
} else {
  console.error(`companion checks: ${failures} failed`);
  process.exit(1);
}
