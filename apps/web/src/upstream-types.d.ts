/** Ambient declarations for upstream packages whose published types do not
 * cover an entry point we use.
 *
 * Kept in one file with the reason for each declaration, so removing one is a
 * deliberate change rather than an archaeology exercise.
 */

/**
 * `ketcher-standalone` publishes an `exports` map with a `./dist/binaryWasm`
 * entry that has no matching `types` condition, so TypeScript cannot resolve the
 * declaration file that ships next to the implementation. The runtime module is
 * the same `StandaloneStructServiceProvider` the package root exports — only the
 * Indigo loading strategy differs (a `.wasm` asset instead of a base64 string
 * inlined in JavaScript) — so re-exporting the root types is accurate, not a
 * placeholder. Re-check on every Ketcher upgrade.
 */
declare module "ketcher-standalone/dist/binaryWasm" {
  export * from "ketcher-standalone";
}
