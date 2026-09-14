import { useEffect, useRef, useState } from "react";

interface SearchBarProps {
  initialQuery: string;
  submitted: string | null;
  isSearching: boolean;
  error: string | null;
  onSearch: (value: string) => void;
  onCancel: () => void;
}

/** Patent-number search row. Empty/whitespace input is validated in place;
 * searching state offers cancel; a not-found keeps the input for retry. */
export function SearchBar({
  initialQuery,
  submitted,
  isSearching,
  error,
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
      setLocalError("Enter a patent publication number to search.");
      return;
    }
    setLocalError(null);
    onSearch(trimmed);
  };

  const shownError = localError ?? error;

  return (
    <div className="searchrow">
      <form onSubmit={submit} role="search" aria-label="Patent number search">
        <input
          ref={inputRef}
          className="search-input"
          type="text"
          placeholder="Enter patent publication number"
          aria-label="Patent publication number"
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
        </span>
      )}
    </div>
  );
}
