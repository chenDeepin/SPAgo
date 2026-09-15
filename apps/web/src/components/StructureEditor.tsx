import { useCallback, useEffect, useRef, useState } from "react";
import { Editor } from "ketcher-react";
// `binaryWasm` loads the Indigo engine as a separate `.wasm` asset; the package
// default inlines it as base64 inside a 21 MB JavaScript file, which would make
// this dialog the largest thing SPAgo ships. Both entries export the same
// provider; only the loading strategy differs.
import { StandaloneStructServiceProvider } from "ketcher-standalone/dist/binaryWasm";
import "ketcher-react/dist/index.css";

/** The minimal surface of the Ketcher instance this wrapper uses.
 *
 * Deliberately narrow: the editor's own API is large and version-dependent, and
 * the structure-search contract only needs "give me the drawing as SMILES" and
 * "tell me when it changed". Keeping that surface here means a Ketcher upgrade
 * breaks this file, not the dialog.
 *
 * `changeEvent` is the 3.18 API (`ketcher-core`'s `Ketcher` class exposes
 * `changeEvent: Subscription`, whose method is `add(handler)`). Earlier drafts of
 * this wrapper subscribed through `editor.subscribe("change", …)`, which 3.x does
 * not provide — the optional chaining made that a silent no-op, so a drawing
 * never reached the SMILES box (found 2026-09-16 in the browser; the box stayed
 * empty while the canvas edit registered). */
interface KetcherInstance {
  getSmiles: (options?: { isExtended?: boolean }) => Promise<string>;
  setMolecule: (structure: string) => Promise<unknown>;
  changeEvent?: {
    add: (handler: () => void) => void;
    remove: (handler: () => void) => void;
  };
}

interface StructureEditorProps {
  /** The draft the dialog holds. The editor is initialized from it once; after
   * that the editor is the source and reports changes upward. */
  initialSmiles: string;
  /** Called with the current drawing as SMILES whenever the drawing changes. */
  onChange: (smiles: string) => void;
  /** Rendered under the canvas; the dialog uses it for its own hint text. */
  onReady?: () => void;
}

const structServiceProvider = new StandaloneStructServiceProvider();

/** Embedded structure editor (Ketcher), isolated from search/depiction code.
 *
 * AGENTS.md §14: editor code and structure-grid depiction code stay separate —
 * Ketcher draws a query, it is not the renderer for result rows. This component
 * owns no search state: a drawing change only updates the draft, and the dialog
 * still requires an explicit action before anything is executed (AGENTS.md §15).
 */
export function StructureEditor({ initialSmiles, onChange, onReady }: StructureEditorProps) {
  const ketcherRef = useRef<KetcherInstance | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The editor is initialized once from the passed draft. Later prop changes must
  // not reset the canvas under the user's cursor, so this is captured, not synced.
  const initialRef = useRef(initialSmiles);
  // The change handler is removed on unmount: the Ketcher instance outlives this
  // component inside the dialog, and a stale handler would report changes from a
  // canvas the reader can no longer see.
  const changeHandlerRef = useRef<(() => void) | null>(null);

  const handleInit = useCallback(
    (instance: unknown) => {
      const ketcher = instance as KetcherInstance;
      ketcherRef.current = ketcher;
      setReady(true);
      onReady?.();
      if (initialRef.current.trim()) {
        // A draft typed before the editor mounted is loaded into the canvas so the
        // two inputs never disagree about the current structure.
        void ketcher.setMolecule(initialRef.current.trim()).catch(() => {
          setError("The draft could not be loaded into the editor; it is still used as typed.");
        });
      }
      if (!ketcher.changeEvent) {
        // Loud, not silent: without the subscription the drawing never reaches the
        // SMILES box, and a quiet no-op would look like a working editor.
        setError(
          "This editor build does not report changes; the SMILES box is not updated by drawing.",
        );
        return;
      }
      const handler = () => {
        void ketcher
          .getSmiles()
          .then((smiles) => {
            setError(null);
            onChange(smiles ?? "");
          })
          .catch(() => {
            setError("The drawing could not be converted to SMILES; the last valid draft is kept.");
          });
      };
      changeHandlerRef.current = handler;
      ketcher.changeEvent.add(handler);
    },
    [onChange, onReady],
  );

  useEffect(
    () => () => {
      const handler = changeHandlerRef.current;
      if (handler) ketcherRef.current?.changeEvent?.remove(handler);
    },
    [],
  );

  useEffect(() => {
    // Ketcher's provider is a singleton with process-wide state; the wrapper
    // reports a failure rather than leaving a blank canvas unexplained.
    const timer = window.setTimeout(() => {
      if (!ketcherRef.current) {
        setError("The structure editor did not finish loading. A SMILES string can still be typed.");
      }
    }, 8000);
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <div className="structure-editor">
      <Editor
        staticResourcesUrl=""
        structServiceProvider={structServiceProvider}
        onInit={handleInit}
        errorHandler={(message: string) => setError(String(message))}
      />
      {!ready && <div className="structure-editor-loading">Loading the structure editor…</div>}
      {error && (
        <div className="structure-editor-error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
