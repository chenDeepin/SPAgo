"""Evidence-grounded AI services (Milestone 5).

The default provider is offline and purely extractive: it assembles summaries
only from typed records already stored in PostgreSQL and cites the underlying
evidence rows. It performs NO inference, so its output is labeled
machine_extracted. A real LLM provider plugged in behind the same protocol must
label its output llm_inferred (AGENTS.md §10/§12) — never silently upgrading
inference to fact.
"""
from __future__ import annotations

import json
import re
import uuid

from sqlalchemy import text
from sqlalchemy.engine import Engine

from spago_core.domain import ProvenanceState


class SummaryProvider:
    """Protocol for summary providers. `name` identifies the implementation."""

    name = "provider"
    provenance_state = ProvenanceState.LLM_INFERRED
    interpretation = ""

    def summarize(self, facts: dict) -> str:
        raise NotImplementedError


class OfflineExtractiveProvider(SummaryProvider):
    """Assembles a deterministic summary from typed DB facts. No LLM."""

    name = "offline-extractive"
    provenance_state = ProvenanceState.MACHINE_EXTRACTED
    interpretation = (
        "Interpretation (SAR narrative, claim scope discussion) requires an LLM "
        "provider, which is not configured on this deployment. Everything above is "
        "assembled verbatim from stored records."
    )

    def summarize(self, facts: dict) -> str:
        lines: list[str] = []
        family = facts["family"]
        lines.append(
            f"Family {family['family_key']} contains {facts['document_count']} document(s) "
            f"with {facts['compound_count']} deduplicated compound(s) "
            f"(dataset {facts['dataset_version']}, synthetic demo fixture)."
        )
        if facts["scaffolds"]:
            top = ", ".join(f"{s} ({n})" for s, n in facts["scaffolds"][:5])
            lines.append(f"Murcko scaffolds present: {top}.")
        if facts["measurements"]:
            lines.append(
                f"{facts['measurement_count']} typed measurement(s) exist. Values are listed "
                "per assay and are not ranked or combined into selectivity numbers:"
            )
            seen: set[tuple] = set()
            unique_lines: list[str] = []
            for m in facts["measurements"]:
                key = (m["inchikey"], m["assay_key"], m["standard_type"], m["value"], m["relation"])
                if key in seen:
                    continue
                seen.add(key)
                unique_lines.append(
                    f"- {m['inchikey']} {m['standard_type']} {m['relation']} {m['value']:g} "
                    f"{m['unit']} in {m['assay_key']} (evidence-linked)."
                )
            lines.extend(unique_lines[:12])
        else:
            lines.append("No typed measurements exist for these compounds; absence of a "
                         "measurement is not evidence of inactivity.")
        if facts["issues"]:
            lines.append(f"{facts['issues']} source structure(s) failed validation during "
                         "ingestion and are recorded as issues, not compounds.")
        lines.append(self.interpretation)
        return "\n".join(lines)


def _collect_family_facts(engine: Engine, family_id: uuid.UUID) -> dict:
    from spago_core.services import NotFoundError, get_family_overview

    overview = get_family_overview(engine, family_id)  # raises NotFoundError
    with engine.connect() as conn:
        compound_count = conn.execute(
            text(
                """
                SELECT count(DISTINCT c.id)
                FROM compounds c
                JOIN compound_mentions m ON m.compound_id = c.id
                JOIN patent_documents d ON d.id = m.document_id
                WHERE d.family_id = :fid
                """
            ),
            {"fid": family_id},
        ).scalar_one()
        scaffolds = conn.execute(
            text(
                """
                SELECT c.scaffold, count(*) AS n
                FROM compounds c
                JOIN compound_mentions m ON m.compound_id = c.id
                JOIN patent_documents d ON d.id = m.document_id
                WHERE d.family_id = :fid AND c.scaffold IS NOT NULL
                GROUP BY c.scaffold ORDER BY n DESC, c.scaffold
                """
            ),
            {"fid": family_id},
        ).all()
        measurements = conn.execute(
            text(
                """
                SELECT c.inchikey, mm.standard_type, mm.relation, mm.value, mm.unit,
                       a.assay_key, e.id AS evidence_id
                FROM measurements mm
                JOIN compounds c ON c.id = mm.compound_id
                JOIN assays a ON a.id = mm.assay_id
                LEFT JOIN evidence_records e ON e.compound_id = c.id
                JOIN compound_mentions cm ON cm.compound_id = c.id
                JOIN patent_documents d ON d.id = cm.document_id
                WHERE d.family_id = :fid
                ORDER BY c.inchikey, a.assay_key
                """
            ),
            {"fid": family_id},
        ).mappings().all()
        issues = conn.execute(text("SELECT count(*) FROM ingestion_issues")).scalar_one()
        info = conn.execute(
            text(
                """
                SELECT d.dataset_version
                FROM patent_documents d
                WHERE d.family_id = :fid LIMIT 1
                """
            ),
            {"fid": family_id},
        ).scalar()

    return {
        "family": {"id": str(overview.family.id), "family_key": overview.family.family_key},
        "document_count": len(overview.documents),
        "compound_count": int(compound_count),
        "scaffolds": [(r[0], int(r[1])) for r in scaffolds],
        "measurements": [
            {
                "inchikey": r["inchikey"],
                "standard_type": r["standard_type"],
                "relation": r["relation"],
                "value": float(r["value"]),
                "unit": r["unit"],
                "assay_key": r["assay_key"],
                "evidence_id": str(r["evidence_id"]) if r["evidence_id"] else None,
            }
            for r in measurements
        ],
        "measurement_count": len({(r["inchikey"], r["assay_key"]) for r in measurements}),
        "issues": int(issues),
        "dataset_version": info or "unknown",
    }


def summarize_family(engine: Engine, family_id: uuid.UUID, provider: SummaryProvider | None = None):
    """Generate (or reuse) an evidence-cited family summary. Deterministic:
    the same data yields the same text, so repeated calls reuse the stored row."""
    from spago_core.services import NotFoundError  # noqa: F401  (re-exported for routes)

    provider = provider or OfflineExtractiveProvider()
    facts = _collect_family_facts(engine, family_id)
    summary_text = provider.summarize(facts)

    citations = []
    for m in facts["measurements"]:
        if m["evidence_id"]:
            citations.append({"evidence_id": m["evidence_id"], "inchikey": m["inchikey"]})

    analysis_id = uuid.uuid5(
        uuid.UUID("9f0c3d1a-7e2b-4c8d-a1b2-3c4d5e6f7a8b"),
        f"summary:{provider.name}:{facts['family']['id']}:{facts['dataset_version']}:{len(facts['measurements'])}:{len(facts['scaffolds'])}",
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO ai_analyses (id, family_id, provider, analysis_kind, text,
                                         citations, provenance_state, dataset_version)
                VALUES (:id, :family_id, :provider, 'family_summary', :text,
                        CAST(:citations AS jsonb), :provenance_state, :dataset_version)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": analysis_id,
                "family_id": family_id,
                "provider": provider.name,
                "text": summary_text,
                "citations": json.dumps(citations),
                "provenance_state": provider.provenance_state.value,
                "dataset_version": facts["dataset_version"],
            },
        )
        created = conn.execute(
            text(
                """
                SELECT created_at FROM ai_analyses WHERE id = :id
                """
            ),
            {"id": analysis_id},
        ).scalar_one()

    return {
        "analysis_id": analysis_id,
        "provider": provider.name,
        "provenance_state": provider.provenance_state.value,
        "text": summary_text,
        "citations": citations,
        "dataset_version": facts["dataset_version"],
        "created_at": created.isoformat(),
    }


_PUBNUM_RE = re.compile(r"\b([A-Z]{2}\d{5,12}[A-Z]\d?)\b")


def plan_query(query: str) -> dict:
    """Deterministic identifier parsing only (PROMPT.md §12): extract
    publication-number-shaped tokens into a validated plan; everything else is
    reported unresolved rather than guessed."""
    tokens = _PUBNUM_RE.findall((query or "").upper())
    remainder = _PUBNUM_RE.sub(" ", (query or "").upper()).strip()
    return {
        "patent_queries": tokens,
        "unresolved_text": remainder or None,
        "note": (
            "Offline planner: only publication-number identifiers are extracted. "
            "Language interpretation requires an LLM provider."
        ),
    }
