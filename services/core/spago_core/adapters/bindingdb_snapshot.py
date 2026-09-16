"""BindingDB local snapshot adapter (B-23).

Reads an *operator-supplied* BindingDB TSV release from disk (for example
`BindingDB_All_2609.tsv`, 8.9 GB / 640 columns / ~3.2 M data rows) and turns the
rows that match one target into the same normalized records the REST path
produces. Nothing here contacts BindingDB: the file is the source.

Three things the REST path cannot supply and this one therefore states:

- **The file's identity.** The release, file digest, size and rows scanned travel
  in the retrieval's stored query (`ActivityResult.query_context`) and in
  `dataset_version` (`bindingdb-snapshot:<release>`), so a stored measurement can
  say which snapshot release it came from (AGENTS.md §25). The digest is computed
  while the file is parsed, so it costs no second pass.
- **The organism.** `Target Source Organism …` is filtered against the target's own
  organism (rows that state none are kept), because mixing a rat assay into a human
  reference set is a silent scientific error, not extra coverage; the excluded
  count and examples are reported (§11).
- **Whether the scan was complete.** `complete` means the file was read to the end;
  a bound (`max_rows` / `max_seconds`) stops the scan and reports `partial` with a
  warning saying rows after that point were not read, so a zero result can never be
  confused with a half-answer (§22).

Matching (D3): the reviewed UniProt accession first, against every
`UniProt (SwissProt|TrEMBL) Primary ID / Secondary ID(s) / Alternative ID(s) of
Target Chain N` column; then `Target Name` — exactly by default, because substring
matching is how a related protein's rows ("Interleukin-6 receptor subunit alpha")
enter the requested target's set.

Counting units, stated because they are not the same thing: `records_seen` counts
the measurement records handed forward (one per filled endpoint column) plus one
for each matched row dropped before its endpoints were read; `records_excluded`
counts those dropped rows, so a row with a missing structure counts once there
whatever it would have contributed. The scan warning always reports **rows**.

The reader, the alias resolution and the match semantics are ported from the
author's own `BindingDB_IO` project (`readers/tsv.py`, `readers/multi.py`,
`match.py`, `targets.py`, `schema.py`); see `THIRD_PARTY_NOTICES.md`.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

from spago_core.adapters.bioactivity_base import ActivityRecord, ActivityResult
from spago_core.chemistry import clean_external_smiles
from spago_core.domain import EvidenceClass, RetrievalStatus, SourceEnvelope, TargetType
from spago_core.domain.patent_numbers import normalize_patent_number

SOURCE_NAME = "bindingdb"
SOURCE_VERSION = "bindingdb-snapshot-tsv"
EXTRACTION_METHOD = "bindingdb_snapshot_tsv"

#: Required to read anything at all. A file without them is not a BindingDB
#: release, and saying so beats emitting a partial answer.
REQUIRED_COLUMNS = ("Target Name", "Ligand SMILES")

TARGET_NAME_COLUMN = "Target Name"
SMILES_COLUMN = "Ligand SMILES"
ID_COLUMN = "BindingDB Reactant_set_id"
MONOMER_COLUMN = "BindingDB MonomerID"
LIGAND_NAME_COLUMN = "BindingDB Ligand Name"
ORGANISM_COLUMN = "Target Source Organism According to Curator or DataSource"
CHAIN_COUNT_COLUMN = "Number of Protein Chains in Target (>1 implies a multichain complex)"
CURATION_COLUMN = "Curation/DataSource"
DOI_COLUMN = "Article DOI"
ENTRY_DOI_COLUMN = "BindingDB Entry DOI"
PMID_COLUMN = "PMID"
PATENT_COLUMN = "Patent Number"
PAIR_URL_COLUMN = "Link to Ligand-Target Pair in BindingDB"

#: (column, standard_type, unit). The unit is the column's own, as reported: the
#: potency columns are nanomolar and kon/koff are not concentrations, so the
#: deterministic classifier reports the kinetics `not_applicable` rather than
#: comparing them with a potency threshold (`chemistry/activities.py`).
ENDPOINT_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("Ki (nM)", "Ki", "nM"),
    ("IC50 (nM)", "IC50", "nM"),
    ("Kd (nM)", "Kd", "nM"),
    ("EC50 (nM)", "EC50", "nM"),
    ("kon (M-1-s-1)", "kon", "M-1-s-1"),
    ("koff (s-1)", "koff", "s-1"),
)

#: Mirrors the REST adapter's reading of the same endpoint names (ONLINE-00 B),
#: extended to the two kinetic columns the snapshot carries.
_ENDPOINT_EVIDENCE = {
    "ki": EvidenceClass.MEASURED_DIRECT_BINDING,
    "kd": EvidenceClass.MEASURED_DIRECT_BINDING,
    "ic50": EvidenceClass.MEASURED_DIRECT_BINDING,
    "ec50": EvidenceClass.FUNCTIONAL_EFFECT,
    "kon": EvidenceClass.MEASURED_DIRECT_BINDING,
    "koff": EvidenceClass.MEASURED_DIRECT_BINDING,
}

_UNIPROT_COLUMN_RE = re.compile(
    r"^UniProt \((?:SwissProt|TrEMBL)\) "
    r"(?:Primary ID|Secondary ID\(s\)|Alternative ID\(s\)) of Target Chain (\d+)$"
)

_RELEASE_RE = re.compile(r"(\d{4})")

#: A digest is reported to 16 hex characters, the same width the retrieval row
#: uses for its query checksum; the full digest is not needed and is not stored.
DIGEST_CHARS = 16


#: Species names a release actually writes, folded to one canonical token per
#: organism. BindingDB's `Target Source Organism` column mixes the common name and
#: the binomial ("Human" on some rows, "Homo sapiens" on others, the target row in
#: SPAgo carries a third wording), so comparing the strings directly dropped 86 of
#: 153 real IL6 rows as a false mismatch on 2026-09-16 — the silent scientific error
#: this filter exists to prevent, in reverse. Anything not listed is *unverified*:
#: kept and counted, never silently dropped and never silently mixed in.
ORGANISM_SYNONYMS: dict[str, str] = {
    # laboratory mammals
    "human": "human",
    "homo sapiens": "human",
    "homo sapiens sapiens": "human",
    "rat": "rat",
    "rats": "rat",
    "rattus norvegicus": "rat",
    "rattus rattus": "rat",
    "mouse": "mouse",
    "mice": "mouse",
    "mus musculus": "mouse",
    "guinea pig": "guinea pig",
    "cavia porcellus": "guinea pig",
    "hamster": "hamster",
    "chinese hamster": "hamster",
    "cricetulus griseus": "hamster",
    "mesocricetus auratus": "hamster",
    "rabbit": "rabbit",
    "oryctolagus cuniculus": "rabbit",
    "bovine": "bovine",
    "cattle": "bovine",
    "cow": "bovine",
    "bos taurus": "bovine",
    "pig": "pig",
    "porcine": "pig",
    "sus scrofa": "pig",
    "sus scrofa domesticus": "pig",
    "sheep": "sheep",
    "ovis aries": "sheep",
    "goat": "goat",
    "capra hircus": "goat",
    "horse": "horse",
    "equine": "horse",
    "equus caballus": "horse",
    "dog": "dog",
    "canis familiaris": "dog",
    "canis lupus familiaris": "dog",
    "cat": "cat",
    "feline": "cat",
    "felis catus": "cat",
    # non-mammalian laboratory organisms
    "chicken": "chicken",
    "gallus gallus": "chicken",
    "zebrafish": "zebrafish",
    "danio rerio": "zebrafish",
    "frog": "frog",
    "xenopus laevis": "frog",
    "xenopus tropicalis": "frog",
    "fruit fly": "fruit fly",
    "drosophila melanogaster": "fruit fly",
    "worm": "worm",
    "caenorhabditis elegans": "worm",
    "c elegans": "worm",
    "yeast": "yeast",
    "saccharomyces cerevisiae": "yeast",
    "escherichia coli": "e coli",
    "e coli": "e coli",
    # pathogens a target may itself be (antibacterials, antivirals, antiparasitics)
    "staphylococcus aureus": "s aureus",
    "methicillin resistant staphylococcus aureus": "s aureus",
    "mrsa": "s aureus",
    "streptococcus pneumoniae": "s pneumoniae",
    "enterococcus faecalis": "e faecalis",
    "enterococcus faecium": "e faecium",
    "bacillus subtilis": "b subtilis",
    "pseudomonas aeruginosa": "p aeruginosa",
    "acinetobacter baumannii": "a baumannii",
    "klebsiella pneumoniae": "k pneumoniae",
    "mycobacterium tuberculosis": "m tuberculosis",
    "m tuberculosis": "m tuberculosis",
    "helicobacter pylori": "h pylori",
    "candida albicans": "c albicans",
    "plasmodium falciparum": "p falciparum",
    "trypanosoma brucei": "t brucei",
    "trypanosoma cruzi": "t cruzi",
    "leishmania donovani": "l donovani",
    "schistosoma mansoni": "s mansoni",
    "human immunodeficiency virus 1": "hiv 1",
    "hiv 1": "hiv 1",
    "hepatitis c virus": "hcv",
    "hcv": "hcv",
    "hepatitis b virus": "hbv",
    "hbv": "hbv",
    "influenza a virus": "influenza a",
    "severe acute respiratory syndrome coronavirus 2": "sars cov 2",
    "sars cov 2": "sars cov 2",
}

_NON_IDENTIFIER_RE = re.compile(r"[^a-z0-9 ]+")
_PARENTHETICAL_RE = re.compile(r"\(([^)]*)\)")


def canonical_organism(value: Optional[str]) -> Optional[str]:
    """The species an organism string names, or None when it cannot be decided.

    Returns `None` rather than guessing: a caller that cannot decide must report
    that, not treat an unknown string as a mismatch against the target.
    """
    text = (value or "").strip()
    if not text:
        return None
    candidate = " ".join(_NON_IDENTIFIER_RE.sub(" ", text.casefold()).split())
    known = ORGANISM_SYNONYMS.get(candidate)
    if known:
        return known
    # `Homo sapiens (Human)` and `Human (Homo sapiens)`: one side of the
    # parenthetical is usually the binomial, so try each part before giving up.
    for part in [*_PARENTHETICAL_RE.findall(text), text.split("(", 1)[0]]:
        folded = " ".join(_NON_IDENTIFIER_RE.sub(" ", part.casefold()).split())
        known = ORGANISM_SYNONYMS.get(folded)
        if known:
            return known
    return None


def organism_verdict(target_organism: Optional[str], row_organism: Optional[str]) -> str:
    """`match`, `mismatch` or `unverified` for one row against the target.

    Silence is a match: a row that states no organism is kept (its own field shows
    the absence), because dropping it would lose a real record for a missing label.
    """
    if not (row_organism or "").strip():
        return "match"
    target = canonical_organism(target_organism)
    row = canonical_organism(row_organism)
    if target is None or row is None:
        return "unverified"
    return "match" if target == row else "mismatch"


def default_release(path: str | os.PathLike[str]) -> str:
    """The release named by the file, when the filename carries one.

    BindingDB's own releases are coded in the filename (`BindingDB_All_2609.tsv`),
    so the operator does not have to restate what the file already says. Anything
    else falls back to the file stem, which is still more than no version at all.
    """
    stem = Path(path).stem
    match = _RELEASE_RE.search(stem)
    return match.group(1) if match else stem


def match_target_name(target_name: str, aliases: Iterable[str], *, mode: str = "exact") -> bool:
    """Whether a BindingDB `Target Name` value names this target.

    Ported from `bindingdb_io/match.py::match_target_name`, with the default mode
    changed from `auto` to `exact`: `auto`/`contains` accept a substring, which is
    how a related protein's rows enter the set. Short aliases (< 4 characters, e.g.
    `IL6`) are equality-only in every mode, because a short token inside a longer
    name is a coincidence rather than a match.
    """
    name = (target_name or "").strip()
    if not name:
        return False
    name_lower = name.lower()
    alias_list = [a.strip() for a in aliases if a and str(a).strip()]
    if not alias_list:
        return False
    if mode == "exact":
        return any(name_lower == alias.lower() for alias in alias_list)
    if mode not in {"auto", "contains"}:
        raise ValueError(f"Unknown name mode {mode!r}; expected exact, auto or contains.")
    for alias in alias_list:
        alias_lower = alias.lower()
        if name_lower == alias_lower:
            return True
        if len(alias_lower) < 4:
            continue
        if alias_lower in name_lower or (mode == "contains" and name_lower in alias_lower):
            return True
    return False


def _chain_of_uniprot_column(name: str) -> Optional[int]:
    """The chain number of a UniProt identifier column, or None."""
    match = _UNIPROT_COLUMN_RE.match(name or "")
    return int(match.group(1)) if match else None


def _split_line(raw: bytes) -> list[str]:
    """One TSV line as cells, with the snapshot's NUL padding removed."""
    text = raw.decode("utf-8", "replace").replace("\x00", "")
    return text.rstrip("\r\n").split("\t")


def _cell(parts: Sequence[str], index: Optional[int]) -> str:
    if index is None or index >= len(parts):
        return ""
    return parts[index].strip()


def _split_value(raw: str) -> tuple[Optional[float], str]:
    """BindingDB values arrive space-padded, sometimes with a relation."""
    text = (raw or "").strip()
    if not text:
        return None, "="
    relation = "="
    if text[0] in "<>~":
        relation = text[0]
        text = text[1:].strip()
    try:
        return float(text), relation
    except ValueError:
        return None, relation


def _accessions_in(value: str) -> list[str]:
    """Accession-looking tokens in one UniProt cell (a cell can list several)."""
    return [token.upper() for token in re.split(r"[\s;,]+", value or "") if token]


def _document_ref(patent: str, doi: str, pmid: str) -> Optional[str]:
    """A document key for the snapshot's own duplicate detection.

    Cross-source duplicate flagging compares this string between records, so it is
    built from the strongest identifier the row carries. ChEMBL keys its records on
    a ChEMBL document id, so the two vocabularies do not meet yet: what this buys is
    that the same paper's row stored twice from one snapshot is flagged as one
    experiment rather than two (stated as a limit in the round's record).
    """
    if doi:
        return f"doi:{doi.lower()}"
    if pmid:
        return f"pmid:{pmid}"
    if patent:
        return f"patent:{patent}"
    return None


@dataclass
class _RowOutcome:
    """What one matched row contributed, so the caller can count honestly."""

    records: list[ActivityRecord] = field(default_factory=list)
    unparseable_values: int = 0
    had_value: bool = False
    #: The release carried no record key for this row, so nothing can be stored
    #: idempotently (AGENTS §22); the row is counted instead of guessed at.
    missing_record_id: bool = False


class _Layout:
    """Column positions for one snapshot header, and the row projection."""

    def __init__(self, index: dict[str, int], snapshot_file: str, release: str) -> None:
        self.index = index
        self.snapshot_file = snapshot_file
        self.release = release
        self.target_name = index.get(TARGET_NAME_COLUMN)
        self.smiles = index.get(SMILES_COLUMN)
        self.reactant = index.get(ID_COLUMN)
        self.monomer = index.get(MONOMER_COLUMN)
        self.organism = index.get(ORGANISM_COLUMN)
        self.chain_count = index.get(CHAIN_COUNT_COLUMN)
        self.curation = index.get(CURATION_COLUMN)
        self.doi = index.get(DOI_COLUMN)
        self.entry_doi = index.get(ENTRY_DOI_COLUMN)
        self.pmid = index.get(PMID_COLUMN)
        self.patent = index.get(PATENT_COLUMN)
        self.pair_url = index.get(PAIR_URL_COLUMN)
        self.endpoints = tuple(
            (index[column], standard_type, unit)
            for column, standard_type, unit in ENDPOINT_COLUMNS
            if column in index
        )
        #: `(position, chain number)` for every UniProt identifier column, so a row
        #: matches on any chain rather than chain 1 only.
        self.uniprot_columns = tuple(
            (position, chain)
            for name, position in sorted(index.items(), key=lambda item: item[1])
            if (chain := _chain_of_uniprot_column(name)) is not None
        )
        absent = [
            column for column, _type, _unit in ENDPOINT_COLUMNS if column not in index
        ]
        self.warnings = (
            [
                "This snapshot has no column for "
                + ", ".join(absent)
                + "; those endpoints cannot be reported from this file."
            ]
            if absent
            else []
        )

    def matches_accession(self, parts: Sequence[str], accession: str) -> bool:
        """Whether any UniProt identifier column of this row names the accession.

        A real release declares UniProt identifiers for *every* chain and every ID
        kind — `BindingDB_All_2609.tsv` carries 300 such columns — while a given row
        fills only a few of them, so the naive version tokenized 300 cells per data
        row. Measured on that release (2026-09-16): 129 µs/row tokenizing every
        cell against 10 µs/row with the prefix check, which is a 25× smaller scan
        time for the same matches. The prefix check is exact rather than a
        heuristic — a token equal to `accession` always appears inside the
        upper-cased cell — so it only skips work that could not have matched.
        """
        if not accession:
            return False
        for position, _chain in self.uniprot_columns:
            cell = _cell(parts, position)
            if accession in cell.upper() and accession in _accessions_in(cell):
                return True
        return False

    def records_for(
        self,
        parts: Sequence[str],
        *,
        accession: str,
        cleaned_smiles: str,
        dataset_version: str,
    ) -> _RowOutcome:
        outcome = _RowOutcome()
        reactant_id = _cell(parts, self.reactant) or _cell(parts, self.monomer)
        monomer_id = _cell(parts, self.monomer)
        if not reactant_id:
            # Every BindingDB row carries the release's own record key, and the
            # stored measurement is keyed on it: without one, re-running this query
            # would duplicate rows instead of updating them (AGENTS §22), so the row
            # is refused and counted rather than given an invented id.
            outcome.missing_record_id = True
            return outcome
        target_name = _cell(parts, self.target_name)
        organism = _cell(parts, self.organism) or None
        curation = _cell(parts, self.curation)
        doi = _cell(parts, self.doi) or _cell(parts, self.entry_doi)
        pmid = _cell(parts, self.pmid)
        patent = normalize_patent_number(_cell(parts, self.patent))
        document_ref = _document_ref(patent, doi, pmid)
        chains = _chain_count(_cell(parts, self.chain_count))
        target_type = (
            TargetType.SINGLE_PROTEIN
            if chains == 1
            else TargetType.PROTEIN_COMPLEX
            if chains is not None and chains > 1
            else None
        )
        target_key = f"bindingdb:{accession}" if accession else f"bindingdb-snapshot:{target_name}"
        pair_url = _cell(parts, self.pair_url) or (
            "https://www.bindingdb.org/rwd/bind/chemsearch/marvin/"
            f"Monomer.jsp?monomerid={monomer_id}"
            if monomer_id
            else None
        )
        context = " · ".join(
            part
            for part in (
                f"BindingDB snapshot {self.release}",
                f"row {reactant_id}" if reactant_id else "",
                target_name,
                f"{chains} protein chain(s)" if chains is not None else "",
                organism or "organism not stated",
                curation,
            )
            if part
        )

        for position, standard_type, unit in self.endpoints:
            raw_value = _cell(parts, position)
            if not raw_value:
                continue
            outcome.had_value = True
            value, relation = _split_value(raw_value)
            if value is None:
                outcome.unparseable_values += 1
                continue
            outcome.records.append(
                ActivityRecord(
                    source_record_id=f"bindingdb-snapshot:{reactant_id}:{standard_type}",
                    compound_source_id=cleaned_smiles,
                    target_key=target_key,
                    target_name=target_name or None,
                    # Keyed by the extraction path *and* the file's own assay shape
                    # (target × ligand × endpoint, matching the REST path), not by the
                    # row: two rows of one release that report the same ligand and
                    # endpoint are one assay reported twice, and the path prefix keeps
                    # the file's wording from overwriting the assay row a REST
                    # retrieval stored for the same experiment (and the reverse). The
                    # measurement rows, keyed on their own record ids, reconcile across
                    # the two paths.
                    assay_key=(
                        f"bindingdb-snapshot:{accession}:{standard_type}:"
                        f"{monomer_id or reactant_id}"
                    ),
                    assay_type="binding",
                    standard_type=standard_type,
                    value=value,
                    unit=unit,
                    relation=relation,
                    evidence_class=_ENDPOINT_EVIDENCE.get(
                        standard_type.lower(), EvidenceClass.UNSPECIFIED
                    ),
                    raw_value=raw_value,
                    assay_description=(
                        f"{context}. Value as reported by the release; no assay-level "
                        "context beyond the columns this file carries."
                    ),
                    species=organism,
                    document_ref=document_ref,
                    document_patent_number=patent or None,
                    document_doi=doi or None,
                    document_pmid=pmid or None,
                    source_url=pair_url,
                    source_molecule_id=monomer_id or None,
                    raw_smiles=cleaned_smiles,
                    target_type_declared=target_type.value if target_type else None,
                    source_name=SOURCE_NAME,
                    source_dataset_version=dataset_version,
                    extraction_method=EXTRACTION_METHOD,
                )
            )
        return outcome


def _chain_count(value: str) -> Optional[int]:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


class BindingDBSnapshotAdapter:
    """Target-led BindingDB retrieval from a local snapshot file.

    Constructed by `scripts/bindingdb_snapshot.py` only: a multi-gigabyte scan must
    never run inside an interactive request (AGENTS.md §21), so the web app keeps
    the REST adapter and this one has no configuration hook into it.
    """

    source_name = SOURCE_NAME
    extraction_method = EXTRACTION_METHOD

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        release: Optional[str] = None,
        names: Sequence[str] = (),
        name_mode: str = "exact",
        organism: Optional[str] = None,
        all_organisms: bool = False,
        max_rows: Optional[int] = None,
        max_seconds: Optional[float] = None,
        progress_every: int = 1_000_000,
        progress: Optional[Callable[[str], None]] = None,
        synthetic: bool = False,
    ) -> None:
        self.path = Path(path)
        self.release = release or default_release(self.path)
        self.names = [n.strip() for n in names if n and n.strip()]
        self.name_mode = name_mode
        self.organism = (organism or "").strip() or None
        self.all_organisms = all_organisms
        self.max_rows = max_rows
        self.max_seconds = max_seconds
        self.progress_every = progress_every
        self.progress = progress
        #: `True` only when a fixture stands in for the operator's file, so its rows
        #: are labelled synthetic like every other fixture path (AGENTS §18).
        self.synthetic = synthetic

    @property
    def dataset_version(self) -> str:
        return f"bindingdb-snapshot:{self.release}"

    # -- scanning -------------------------------------------------------------

    def load(self, accession: str) -> ActivityResult:
        """Scan the snapshot once for one target and return its measurements."""
        started = time.monotonic()
        retrieved_at = datetime.now(timezone.utc)
        accession = (accession or "").strip().upper()
        aliases = [*self.names, accession] if accession else list(self.names)
        warnings: list[str] = []
        records: list[ActivityRecord] = []
        rejection_counts: dict[str, int] = {}
        organism_examples: list[str] = []
        unverified = 0
        unverified_examples: list[str] = []

        if not self.path.is_file():
            return self._result(
                retrieved_at,
                [],
                RetrievalStatus.FAILED,
                warnings=[
                    f"The snapshot file {self.path} does not exist, so nothing was read. "
                    "This is a configuration failure, not an empty answer."
                ],
                rows_scanned=0,
                bytes_read=0,
                complete=False,
                digest=None,
                aliases=aliases,
                accession=accession,
            )

        matched = matched_by_accession = matched_by_name = 0
        dropped = 0
        rows_scanned = 0
        bytes_read = 0
        complete = False
        digest = hashlib.sha256()

        try:
            with open(self.path, "rb") as handle:
                header_raw = handle.readline()
                if not header_raw:
                    raise ValueError("the file is empty")
                digest.update(header_raw)
                bytes_read += len(header_raw)
                header = _split_line(header_raw)
                index = {name: position for position, name in enumerate(header)}
                missing = [name for name in REQUIRED_COLUMNS if name not in index]
                if missing:
                    raise ValueError(
                        "the snapshot is missing the required column(s): " + ", ".join(missing)
                    )
                layout = _Layout(index, self.path.name, self.release)
                if not layout.endpoints:
                    raise ValueError(
                        "the snapshot has no endpoint column; expected one of: "
                        + ", ".join(column for column, _t, _u in ENDPOINT_COLUMNS)
                    )
                warnings.extend(layout.warnings)

                for raw in handle:
                    digest.update(raw)
                    bytes_read += len(raw)
                    rows_scanned += 1
                    parts = _split_line(raw)
                    by_accession = layout.matches_accession(parts, accession)
                    by_name = not by_accession and match_target_name(
                        _cell(parts, layout.target_name), aliases, mode=self.name_mode
                    )
                    if not (by_accession or by_name):
                        if (
                            self.progress
                            and self.progress_every
                            and rows_scanned % self.progress_every == 0
                        ):
                            self.progress(
                                f"[bindingdb-snapshot] scanned {rows_scanned:,} row(s), "
                                f"{matched:,} matched so far"
                            )
                        if self._bounded(rows_scanned, started):
                            break
                        continue

                    matched += 1
                    matched_by_accession += int(by_accession)
                    matched_by_name += int(by_name)

                    organism = _cell(parts, layout.organism)
                    if not self.all_organisms and self.organism:
                        # One comparison, three outcomes: the target's species, a
                        # different one (excluded and counted), or a string the
                        # synonym table cannot decide (kept and counted, because
                        # neither dropping nor silently mixing it is honest).
                        verdict = organism_verdict(self.organism, organism)
                        if verdict == "mismatch":
                            rejection_counts["organism_mismatch"] = (
                                rejection_counts.get("organism_mismatch", 0) + 1
                            )
                            dropped += 1
                            if len(organism_examples) < 3 and organism not in organism_examples:
                                organism_examples.append(organism)
                            if self._bounded(rows_scanned, started):
                                break
                            continue
                        if verdict == "unverified":
                            unverified += 1
                            if (
                                len(unverified_examples) < 3
                                and organism not in unverified_examples
                            ):
                                unverified_examples.append(organism)

                    raw_smiles = _cell(parts, layout.smiles)
                    if not raw_smiles:
                        rejection_counts["missing_structure"] = (
                            rejection_counts.get("missing_structure", 0) + 1
                        )
                        dropped += 1
                        if self._bounded(rows_scanned, started):
                            break
                        continue

                    cleaned, notes = clean_external_smiles(raw_smiles)
                    outcome = layout.records_for(
                        parts,
                        accession=accession,
                        cleaned_smiles=cleaned,
                        dataset_version=self.dataset_version,
                    )
                    if outcome.missing_record_id:
                        rejection_counts["missing_record_id"] = (
                            rejection_counts.get("missing_record_id", 0) + 1
                        )
                    if not outcome.had_value and not outcome.missing_record_id:
                        rejection_counts["missing_affinity"] = (
                            rejection_counts.get("missing_affinity", 0) + 1
                        )
                    if not outcome.records:
                        # One count per matched row that contributed nothing, whatever
                        # the reason recorded above.
                        dropped += 1
                    if outcome.unparseable_values:
                        rejection_counts["unparseable_standard_value"] = (
                            rejection_counts.get("unparseable_standard_value", 0)
                            + outcome.unparseable_values
                        )
                    if outcome.records:
                        records.extend(outcome.records)
                        if notes:
                            for note in notes:
                                warnings.append(
                                    f"{outcome.records[0].source_record_id}: {note}"
                                )
                    if self._bounded(rows_scanned, started):
                        break

                else:
                    complete = True

        except (OSError, ValueError) as exc:
            return self._result(
                retrieved_at,
                [],
                RetrievalStatus.FAILED,
                warnings=[f"The snapshot could not be read: {exc}"],
                rows_scanned=rows_scanned,
                bytes_read=bytes_read,
                complete=False,
                digest=None,
                rejection_counts=rejection_counts,
                aliases=aliases,
                accession=accession,
            )

        digest_hex = digest.hexdigest()[:DIGEST_CHARS] if complete else None
        seconds = time.monotonic() - started
        warnings.append(
            f"Scanned {rows_scanned:,} data row(s) ({bytes_read / 1_000_000_000:.2f} GB) of "
            f"{self.path.name} in {seconds:.1f} s; {matched:,} row(s) matched the requested "
            f"target ({matched_by_accession:,} by UniProt accession, "
            f"{matched_by_name:,} by target name under mode '{self.name_mode}')."
        )
        if complete:
            warnings.append(
                f"The file was read to the end, so this is the whole snapshot, not a "
                f"prefix. Release {self.release}, sha256:{digest_hex}… "
                f"({bytes_read:,} bytes)."
            )
        else:
            warnings.append(
                "The scan stopped at the configured bound before the end of the file: "
                "rows after that point were not read, no file digest is recorded because a "
                "prefix has no file identity, and this answer is a prefix rather than the "
                "snapshot."
            )
        if rejection_counts.get("organism_mismatch"):
            warnings.append(
                f"{rejection_counts['organism_mismatch']:,} matched row(s) were from another "
                f"organism ({', '.join(organism_examples)}) and were excluded; pass "
                "--all-organisms to include them."
            )
        if unverified:
            warnings.append(
                f"{unverified:,} matched row(s) state an organism that could not be compared "
                f"with {self.organism!r} ({', '.join(unverified_examples)}); they are kept and "
                "flagged in the retrieval's search context rather than dropped or silently "
                "mixed in — add the species to ORGANISM_SYNONYMS if it is the target's."
            )
        if not records:
            warnings.append(
                "No measurement was stored from this scan. The scan summary above says "
                "whether the whole file was read, so this is 'nothing in the release "
                "matched' and not a half-answer."
            )
        warnings.append(
            "Values are the release's own: potency columns in nM, kon/koff as reported. "
            "Unlike the REST path these rows state the target organism, the chain count "
            "and the document (DOI/PMID/patent) when BindingDB has one."
        )

        status = RetrievalStatus.COMPLETE if records else RetrievalStatus.EMPTY
        if not complete:
            status = RetrievalStatus.PARTIAL
        return self._result(
            retrieved_at,
            records,
            status,
            warnings=warnings,
            rows_scanned=rows_scanned,
            bytes_read=bytes_read,
            complete=complete,
            digest=digest_hex,
            records_seen=len(records) + dropped,
            records_excluded=dropped,
            rejection_counts=rejection_counts,
            matched=matched,
            matched_by_accession=matched_by_accession,
            matched_by_name=matched_by_name,
            organism_unverified=unverified,
            aliases=aliases,
            accession=accession,
        )

    def _bounded(self, rows_scanned: int, started: float) -> bool:
        if self.max_rows and rows_scanned >= self.max_rows:
            return True
        if self.max_seconds and (time.monotonic() - started) > self.max_seconds:
            return True
        return False

    # -- result assembly ------------------------------------------------------

    def _result(
        self,
        retrieved_at: datetime,
        records: list[ActivityRecord],
        status: RetrievalStatus,
        *,
        warnings: list[str],
        rows_scanned: int,
        bytes_read: int,
        complete: bool,
        digest: Optional[str],
        records_seen: int = 0,
        records_excluded: int = 0,
        rejection_counts: Optional[dict[str, int]] = None,
        matched: int = 0,
        matched_by_accession: int = 0,
        matched_by_name: int = 0,
        organism_unverified: int = 0,
        aliases: Sequence[str] = (),
        accession: str = "",
    ) -> ActivityResult:
        dataset_version = self.dataset_version
        for record in records:
            record.source_name = SOURCE_NAME
            record.source_dataset_version = dataset_version
        return ActivityResult(
            envelope=SourceEnvelope(
                source_name=SOURCE_NAME,
                source_version=SOURCE_VERSION,
                dataset_version=dataset_version,
                retrieved_at=retrieved_at,
                synthetic=self.synthetic,
                warnings=list(warnings),
            ),
            records=records,
            warnings=list(warnings),
            status=status.value,
            # One pass over one file: there is no page sequence to report, and the
            # scan summary above is what a reader needs instead.
            pages_fetched=1 if rows_scanned else 0,
            records_seen=records_seen,
            records_excluded=records_excluded,
            rejection_counts=rejection_counts or {},
            # B-23 D6: the search parameters this run actually used, merged into the
            # stored retrieval query so the ask is reconstructible from the record
            # rather than from a run log (AGENTS.md §25).
            query_context={
                "uniprot": accession,
                "match_mode": self.name_mode,
                "names": ", ".join(self.names),
                "snapshot_file": self.path.name,
                "snapshot_release": self.release,
                "snapshot_sha256": digest or "",
                "snapshot_size_bytes": bytes_read,
                "snapshot_rows_scanned": rows_scanned,
                "snapshot_complete": complete,
                "matched_rows": matched,
                "matched_by_accession": matched_by_accession,
                "matched_by_name": matched_by_name,
                "matched_aliases": ", ".join(aliases),
                # B-23: the filter the ask actually applied, and what it could not
                # decide, so the stored retrieval states both (AGENTS §25).
                "organism_filter": self.organism or "",
                "all_organisms": self.all_organisms,
                "organism_mismatch_rows": (rejection_counts or {}).get(
                    "organism_mismatch", 0
                ),
                "organism_unverified_rows": organism_unverified,
            },
        )
