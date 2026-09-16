"""Publication-number normalization for identifiers discovered in text.

Three different jobs must stay apart:

- **Classifying a query** is tolerant but shape-only:
  :func:`looks_like_publication_number` accepts one whole identifier in the forms
  people write (``WO2020123456A1``, ``wo 2020/123456``, ``US-5153197-A``), so the
  number a scientist copies from a slide or a paper reaches the patent endpoint
  instead of being sent to a language model. It is a deterministic shape, not an
  interpretation (AGENTS.md §12).
- **Extracting an identifier from source data** is lenient: a database field such
  as ChEMBL's ``patent_id`` may be ``WO2019047734A1``, ``WO 2019/047734``,
  ``US-5153197-A`` or a string with several numbers in it, and dropping those
  facts would lose the patent link that makes this product patent-native.
- **Read-only coverage reporting** (:func:`spago_core.services.core.publications_in_corpus`)
  stays exact: "was *this* number imported?" must not be softened by normalization.

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

#: Version of the tolerant *lookup* rule. It travels with every answer that used
#: it, so a changed rule is visible in the artifact rather than hidden in a session.
MATCH_RULE = "publication-number-tolerant-v1"

#: Punctuation a person types between the parts of one number. Removing it is what
#: lets a single shape rule cover "WO-2020-123456-A", "wo 2020/123456" and
#: "US 10,123,456 B2" alike.
_QUERY_SEPARATORS_RE = re.compile(r"[\s\-/.,]+")

#: The shape of a whole *query*: country code, a body of six to thirteen digits, an
#: optional kind code. The floor is the same six digits as :data:`_PATENT_RE` above
#: (a shorter body is not an identifier); the ceiling only rejects digit soup. The
#: body may be one run or the split year+serial form, and the kind code may be absent
#: ("EP1234567"), because the separators are removed first. The mirrored TypeScript
#: literal lives in ``apps/web/src/state/url.ts`` and a parity test keeps the two
#: identical.
_QUERY_RE = re.compile(r"^[A-Z]{2}\d{6,13}(?:[A-Z]\d?)?$")


def looks_like_publication_number(value: object) -> bool:
    """True when the whole string is one publication number, in any common form.

    Case, separators and the presence of a kind code do not matter. What does
    matter is that the *whole* string is the number: a sentence, a two-number
    comparison or free text is refused here and keeps going to the reviewed plan
    path, so language never becomes an identifier (AGENTS.md §12).
    """
    text = _QUERY_SEPARATORS_RE.sub("", str(value or "")).upper()
    return bool(_QUERY_RE.match(text))



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
