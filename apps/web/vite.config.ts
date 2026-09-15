import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies API calls to the FastAPI core so the browser sees one origin.
export default defineConfig({
  plugins: [react()],
  define: {
    // `ketcher-react@3.18.0` ships a browser build that reads and writes a bare
    // `global` (a Node/CJS leftover) while initializing the editor state, so the
    // structure dialog throws `ReferenceError: global is not defined` and never
    // renders a canvas. Aliasing the identifier to `globalThis` restores the
    // intended behaviour: `global.currentState = …` becomes a property on the
    // page's global object, which is what the code means in a browser.
    //
    // Scope and risk: this rewrite applies to the whole bundle, so a dependency
    // that detects Node with `typeof global !== "undefined"` would now take its
    // Node path. That is the reason this is a one-line, documented shim rather
    // than a routine setting: remove it when Ketcher stops referencing `global`,
    // and re-check the rest of the app in the browser when upgrading Ketcher.
    global: "globalThis",
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/healthz": "http://localhost:8000",
    },
  },
});
