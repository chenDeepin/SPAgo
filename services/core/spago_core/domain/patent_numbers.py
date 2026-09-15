"""Publication-number normalization for identifiers coming from *sources*.

Two different jobs must stay apart:

- **Validating user input** is strict: :data:`spago_core.services.planner._PUBNUM_RE`
  accepts a publication-number shape and refuses everything else, so free text is
  never turned into an identifier (AGENTS.md §12).
- **Extracting an identifier from source data** is lenient: a database field such
  as ChEMBL's ``patent_id`` may be ``WO2019047734A1``, ``WO 2019/047734``,
  ``US-5153197-A`` or a string with several numbers in it, and dropping those
  facts would lose the patent link that makes this product patent-native.

Normalization is deliberately lossy in exactly one way: the kind code
(``A1``/``B2``) and separators are dropped, so ``WO2019047734A1`` and
``WO-2019-047734-A1`` are the same patent for *matching*. The raw string is kept
wherever the normalized value is stored, so nothing is silently rewritten.

The pattern is adapted from the author's local ``BindingDB_IO`` project
(``bindingdb_io/patents.py``, reviewed 2026-09-15): country + body with at least
six digits. Six is a deliberate floor — a shorter body is not extracted, because
inventing a patent number is worse than missing one.
"""
from __future__ import annotations

import re
from typing import Iterable

#: Country/office code followed by the publication body and an optional kind code.
#: The body is either a single digit run (``WO2019047734``) or the split WIPO form
#: (``WO2019/047734``, whose serial is the same number); a split body requires the
#: separator so two unrelated numbers are never joined.
_PATENT_RE = re.compile(
    r"(?<![A-Z0-9])([A-Z]{2})[\s\-/]*(\d{6,}|\d{4}[\s\-/]\d{2,8})(?:[\s\-/]*([A-Z]\d?))?",
    re.IGNORECASE,
)

#: Thousands separators inside a number ("US 10,123,456") are punctuation, not digits.
_GROUPING_RE = re.compile(r"(?<=\d)[,\s](?=\d)")

#: Separators that remain inside a captured split body ("2019/047734").
_BODY_SEPARATORS_RE = re.compile(r"[\s\-/]")


def patent_tokens(value: object) -> list[str]:
    """Every normalized ``CC<digits>`` token found in ``value``, in order, deduped."""
    text = _GROUPING_RE.sub("", str(value or "").upper())
    out: list[str] = []
    seen: set[str] = set()
    for country, body, _kind in _PATENT_RE.findall(text):
        number = _BODY_SEPARATORS_RE.sub("", body)
        token = f"{country.upper()}{number}"
        if token not in seen:
            seen.add(token)
            out.append(token)
    return out


def normalize_patent_number(value: object) -> str:
    """First normalized token, or ``""`` when the text carries no publication number."""
    tokens = patent_tokens(value)
    return tokens[0] if tokens else ""


def patent_number_match(left: object, right: object) -> bool:
    """True when two identifiers name the same publication.

    Compares normalized tokens on both sides, so a corpus value with a kind code
    matches a source value without one, and vice versa.
    """
    a = {token for token in patent_tokens(left)}
    b = {token for token in patent_tokens(right)}
    return bool(a & b)


def unique_patent_numbers(values: Iterable[object]) -> list[str]:
    """Normalized, deduplicated, sorted tokens for a list of raw identifiers."""
    found: set[str] = set()
    for value in values:
        found.update(patent_tokens(value))
    return sorted(found)
