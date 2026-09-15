/** Bundler interop shim for Ketcher's Raphael access (see `StructureEditor`).
 *
 * `ketcher-core`'s Raphael integration is written for a CommonJS bundler:
 *
 *     var u_ = typeof window < "u" ? require("raphael") : void 0
 *
 * In an ESM bundle there is no `require`, so evaluating the module throws
 * `ReferenceError: require is not defined` and the whole lazy chunk — the
 * structure-search dialog — fails to load. The `typeof window` guard only
 * distinguishes browser from server; it never checks for a CommonJS loader.
 * Verified 2026-09-16 against `ketcher-react@3.18.0` in the built bundle.
 *
 * This module installs a `require` that resolves *only* the one name Ketcher
 * asks for and returns `undefined` for anything else, so a future Ketcher
 * release that needs another module fails loudly at the call site instead of
 * silently receiving something wrong. It is imported before Ketcher in
 * `StructureSearchDialog.tsx`, and ESM evaluates dependencies in import order,
 * so the shim is installed before Ketcher's module body runs.
 *
 * Remove this file when Ketcher ships an ESM-safe build: the check is that the
 * built chunk no longer contains `require("raphael")`.
 */
import * as raphael from "raphael";

type RequireShim = (name: string) => unknown;

const target = globalThis as { require?: RequireShim };

if (typeof target.require !== "function") {
  target.require = (name: string) => {
    if (name === "raphael") {
      // `raphael` publishes a UMD bundle; the namespace may wrap the value.
      return (raphael as { default?: unknown }).default ?? raphael;
    }
    // Not silently ignored: Ketcher asking for another module is a real change
    // in its packaging that this shim does not cover.
    console.warn(`[spago] bundled ketcher requested module ${name}; only raphael is shimmed`);
    return undefined;
  };
}
