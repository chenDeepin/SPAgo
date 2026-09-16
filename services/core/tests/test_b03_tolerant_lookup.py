"""B-03: the number a scientist types opens the family it names.

Three things are being held apart here, and each has its own section below:

- the **shape rule** that decides which server lookup a query reaches (tolerant,
  deterministic, mirrored in the client and kept identical by a parity test);
- the **lookup** that compares the request with the stored corpus through the same
  normalizer the source paths use, and reports which stored identifier answered;
- the **refusals**, which matter as much as the hits: a genuine miss stays a miss,
  free text is not turned into an identifier, and two stored documents that
  normalize alike are reported instead of guessed.

The corpus for the lookup tests is a family this module creates and removes again,
so nothing here changes what the demo fixture holds for every other module.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from spago_core.domain.patent_numbers import (
    MATCH_RULE,
    _QUERY_RE,
    _QUERY_SEPARATORS_RE,
    looks_like_publication_number,
)
from spago_core.services import AmbiguousError, NotFoundError, find_patent, plan_execution

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The family these tests own. `DEMO-FAMILY-1` is left exactly as the fixture
#: seeded it: a module that adds documents to it would change another module's
#: counts.
FAMILY_KEY = "B03-FAMILY-1"

#: A publication stored the way SureChEMBL writes it, and the ways a person writes
#: the same number. The kind code and the separators differ; the patent does not.
STORED = "WO-2020-123456-A"

#: The WIPO split form of another patent, stored with separators.
SPLIT_STORED = "WO-2019-047734-A"
SPLIT_QUERY = "WO2019047734A1"

#: Two documents whose identifiers normalize to one token: a granted patent stored
#: twice, once per kind code. The lookup must report both, not choose.
AMBIGUOUS_A = "US-8618102-B1"
AMBIGUOUS_B = "US8618102B2"


@pytest.fixture(scope="module")
def tagged_corpus(seeded_engine):
    """A family this module owns, removed again when the module ends.

    The scratch database is shared and `seeded_engine` resets it to the demo
    fixture at module start, so this module's starting state does not depend on
    which module ran before it.
    """
    family_id = uuid.uuid4()
    with seeded_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM patent_families WHERE family_key = :k"), {"k": FAMILY_KEY}
        )
        conn.execute(
            text(
                """
                INSERT INTO patent_families (id, family_key, title, source_name,
                                             dataset_version, retrieved_at)
                VALUES (:id, :k, 'B-03 test family', 'stub', 'stub:2026-09-16', now())
                """
            ),
            {"id": family_id, "k": FAMILY_KEY},
        )
        for number in (STORED, SPLIT_STORED, AMBIGUOUS_A, AMBIGUOUS_B):
            conn.execute(
                text(
                    """
                    INSERT INTO patent_documents (id, family_id, publication_number,
                                                  source_name, dataset_version, retrieved_at)
                    VALUES (:id, :fid, :pn, 'stub', 'stub:2026-09-16', now())
                    """
                ),
                {"id": uuid.uuid4(), "fid": family_id, "pn": number},
            )
    try:
        yield family_id
    finally:
        with seeded_engine.begin() as conn:
            conn.execute(text("DELETE FROM patent_families WHERE id = :id"), {"id": family_id})


def _stored_numbers(engine, family_id) -> list[str]:
    with engine.connect() as conn:
        return sorted(
            r[0]
            for r in conn.execute(
                text("SELECT publication_number FROM patent_documents WHERE family_id = :fid"),
                {"fid": family_id},
            ).all()
        )


class TestTheQueryShape:
    """What counts as a publication number, and what deliberately does not."""

    @pytest.mark.parametrize(
        "value",
        [
            "WO2020123456A1",
            "wo2020123456a1",
            "WO-2020-123456-A",
            "wo 2020/123456",
            "WO 2020 123456 A1",
            "WO 2020/123456",
            "US-5153197-A",
            "US 10,123,456 B2",
            "EP1234567",  # no kind code: still a publication number
            "  WO2020123456A1  ",
            "WO2020123456A1.",  # sentence punctuation
        ],
    )
    def test_a_number_people_actually_type_is_recognised(self, value):
        assert looks_like_publication_number(value)

    @pytest.mark.parametrize(
        "value",
        [
            "",
            None,
            "TSLP",
            "Q969D9",  # a UniProt accession is not a publication number
            "P05231",
            "IL-6",
            "not a patent",
            "thirteen elephants",
            "US12345",  # body below the six-digit floor
            "1234567",  # no country code
            "DEMO-PATENT-A",  # a synthetic sample identifier
            "WO2019047734A1; US10123456B2",  # two numbers are not one number
            "US1234567 EP7654321",
            "US1234567A EP7654321",
            "WO2020123456A1 and then some prose",
            "see WO2020123456A1",
        ],
    )
    def test_free_text_and_non_identifiers_are_refused(self, value):
        assert not looks_like_publication_number(value)

    def test_the_client_rule_is_the_same_rule(self):
        """A comment claiming two rules agree is not a check.

        The browser decides which server lookup a query reaches, so a drift between
        the two patterns would send identifiers to the language model (or prose to
        the patent route) without any test noticing.
        """
        source = (REPO_ROOT / "apps" / "web" / "src" / "state" / "url.ts").read_text(
            encoding="utf-8"
        )
        pattern = re.search(r"const PUBLICATION_NUMBER = /(.+?)/;", source)
        separators = re.search(r"const PUBLICATION_SEPARATORS = /(.+?)/g;", source)
        assert pattern is not None and separators is not None
        assert pattern.group(1) == _QUERY_RE.pattern
        assert separators.group(1) == _QUERY_SEPARATORS_RE.pattern


class TestTheLookup:
    def test_the_stored_number_still_takes_the_exact_path(self, seeded_engine, tagged_corpus):
        lookup = find_patent(seeded_engine, STORED)
        assert lookup.exact is True
        assert lookup.requested == STORED
        assert lookup.matched == STORED
        assert lookup.rule == MATCH_RULE
        assert lookup.overview.family.id == tagged_corpus

    @pytest.mark.parametrize(
        "query", ["WO2020123456A1", "wo 2020/123456", "WO-2020-123456", "WO 2020 123456 A1"]
    )
    def test_the_same_number_written_differently_opens_the_same_family(
        self, seeded_engine, tagged_corpus, query
    ):
        lookup = find_patent(seeded_engine, query)
        assert lookup.overview.family.family_key == FAMILY_KEY
        assert lookup.document.publication_number == STORED
        assert lookup.matched == STORED
        assert lookup.requested == query
        assert lookup.exact is False
        assert lookup.rule == MATCH_RULE

    def test_the_split_wipo_form_is_found_from_the_unified_one(self, seeded_engine, tagged_corpus):
        lookup = find_patent(seeded_engine, SPLIT_QUERY)
        assert lookup.matched == SPLIT_STORED
        assert lookup.exact is False

    @pytest.mark.parametrize("query", ["WO2020123456A1", "wo 2020/123456"])
    def test_the_stored_identifier_is_never_rewritten(self, seeded_engine, tagged_corpus, query):
        find_patent(seeded_engine, query)
        assert _stored_numbers(seeded_engine, tagged_corpus) == sorted(
            [STORED, SPLIT_STORED, AMBIGUOUS_A, AMBIGUOUS_B]
        )

    def test_a_genuine_miss_is_still_a_miss(self, seeded_engine, tagged_corpus):
        with pytest.raises(NotFoundError) as exc:
            find_patent(seeded_engine, "WO9999999999A1")
        assert "not found in current dataset" in str(exc.value)

    def test_free_text_is_not_turned_into_an_identifier(self, seeded_engine, tagged_corpus):
        with pytest.raises(NotFoundError) as exc:
            find_patent(seeded_engine, "thirteen elephants")
        assert "carries no publication number" in str(exc.value)

    def test_two_stored_documents_that_normalize_alike_are_reported(self, seeded_engine, tagged_corpus):
        with pytest.raises(AmbiguousError) as exc:
            find_patent(seeded_engine, "US8618102")
        assert sorted(exc.value.candidates) == [AMBIGUOUS_A, AMBIGUOUS_B]
        assert AMBIGUOUS_A in str(exc.value) and AMBIGUOUS_B in str(exc.value)


class TestTheServedSurface:
    def test_a_tolerant_query_travels_and_names_the_stored_identifier(self, tagged_corpus, app_client):
        # The canonical form is what a client can put in a path: a "/" is decoded
        # before routing, so `%2F` never reaches the handler (see state/url.ts).
        response = app_client.get("/api/v1/patents/WO2020123456")
        assert response.status_code == 200
        body = response.json()
        assert body["document"]["publication_number"] == STORED
        assert body["match"] == {
            "requested": "WO2020123456",
            "matched": STORED,
            "exact": False,
            "rule": MATCH_RULE,
        }

    def test_an_exact_query_reports_an_exact_match(self, tagged_corpus, app_client):
        body = app_client.get(f"/api/v1/patents/{STORED}").json()
        assert body["match"]["exact"] is True
        assert body["match"]["matched"] == STORED

    def test_an_ambiguous_number_is_a_conflict_that_names_the_candidates(
        self, tagged_corpus, app_client
    ):
        response = app_client.get("/api/v1/patents/US8618102")
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert AMBIGUOUS_A in detail and AMBIGUOUS_B in detail
        assert "will not choose" in detail

    def test_a_miss_is_still_a_404(self, tagged_corpus, app_client):
        response = app_client.get("/api/v1/patents/WO9999999999A1")
        assert response.status_code == 404
        assert "not found in current dataset" in response.json()["detail"]

    def test_free_text_is_refused_with_a_reason_not_a_crash(self, tagged_corpus, app_client):
        response = app_client.get("/api/v1/patents/thirteen%20elephants")
        assert response.status_code == 404
        assert "carries no publication number" in response.json()["detail"]


class TestThePlanPath:
    """The ask box reaches the same lookup, and says the same thing about it."""

    def test_a_tolerant_number_in_a_plan_is_accepted_and_reported(
        self, seeded_engine, tagged_corpus
    ):
        plan = {"query": "wo 2020/123456", "producer": "offline", "steps": []}
        result = plan_execution.execute_plan(
            seeded_engine,
            {**plan, "steps": [{"op": "open_patent", "publication_number": "wo 2020/123456"}]},
        )
        step = result.steps[0]
        assert step.status == "ok"
        assert step.data["publication_number"] == STORED
        assert step.data["match_exact"] is False
        assert step.data["match_rule"] == MATCH_RULE
        assert STORED in step.detail

    def test_an_ambiguous_number_in_a_plan_is_reported_with_its_candidates(
        self, seeded_engine, tagged_corpus
    ):
        result = plan_execution.execute_plan(
            seeded_engine,
            {
                "query": "US8618102",
                "producer": "offline",
                "steps": [{"op": "open_patent", "publication_number": "US8618102"}],
            },
        )
        step = result.steps[0]
        assert step.status == "ambiguous"
        assert sorted(step.data["candidates"]) == [AMBIGUOUS_A, AMBIGUOUS_B]

    def test_the_offline_planner_recognises_the_form_people_type(self):
        from spago_core.services.planner import offline_plan

        for query in ("wo 2020/123456", "WO-2020-123456-A"):
            plan = offline_plan(query)
            assert [s["op"] for s in plan.steps] == ["open_patent"], query
            assert plan.steps[0]["publication_number"] == query.upper()

    def test_the_offline_planner_leaves_prose_alone(self):
        from spago_core.services.planner import offline_plan

        plan = offline_plan("the compound reported in WO2020123456A1 shows activity")
        numbers = [s["publication_number"] for s in plan.steps if s["op"] == "open_patent"]
        # The number is a token and is recognised; the prose around it is not
        # absorbed into the identifier, and it is reported unresolved instead.
        assert numbers == ["WO2020123456A1"]
        assert "activity" in plan.unresolved
