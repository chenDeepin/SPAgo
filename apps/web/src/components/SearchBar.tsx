import { useEffect, useRef, useState } from "react";

interface SearchBarProps {
  initialQuery: string;
  submitted: string | null;
  isSearching: boolean;
  error: string | null;
  /** Optional follow-up control for the failure the message describes, e.g.
   * opening the synthetic sample record after a 404 (ONLINE-01 finding). */
  errorAction?: { label: string; onClick: () => void } | null;
  onSearch: (value: string) => void;
  onCancel: () => void;
}

/** Search row: a patent publication number opens a patent family, any other
 * identifier-shaped query is resolved as a target (ONLINE-00). Empty input is
 * validated in place; the searching state offers cancel; a not-found keeps the
 * input for retry. The input itself decides nothing — it submits one string and
 * the server answers. */
export function SearchBar({
  initialQuery,
  submitted,
  isSearching,
  error,
  errorAction,
  onSearch,
  onCancel,
}: SearchBarProps) {
  const [value, setValue] = useState(initialQuery);
  const [localError, setLocalError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (submitted !== null) setValue(submitted);
  }, [submitted]);

  const submit = (e: { preventDefault(): void }) => {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) {
      setLocalError("Enter a patent publication number or a target to search.");
      return;
    }
    setLocalError(null);
    onSearch(trimmed);
  };

  const shownError = localError ?? error;

  return (
    <div className="searchrow">
      <form onSubmit={submit} role="search" aria-label="Patent or target search">
        <input
          ref={inputRef}
          className="search-input"
          type="text"
          placeholder="Patent number (WO2018000001A1) or target (TSLP, Q969D9)"
          aria-label="Patent publication number or target"
          aria-invalid={shownError ? true : undefined}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            if (localError) setLocalError(null);
          }}
          onKeyDown={(e) => {
            // Explicit Enter handling: implicit form submission is not reliably
            // triggered in every embedding, and the design contract requires
            // Enter to run the search (design doc §1).
            if (e.key === "Enter") {
              e.preventDefault();
              submit(e);
            }
          }}
        />
        {isSearching ? (
          <button type="button" className="btn btn-quiet" onClick={onCancel}>
            Cancel
          </button>
        ) : (
          <button type="submit" className="btn btn-primary">
            Search
          </button>
        )}
      </form>
      {shownError && (
        <span className="search-error" role="alert">
          {shownError}
          {errorAction && (
            <>
              {" "}
              <button
                type="button"
                // Same inline-link action style as the candidate picker.
                className="evidence-link"
                onClick={errorAction.onClick}
              >
                {errorAction.label}
              </button>
            </>
          )}
        </span>
      )}
    </div>
  );
}
