"""The corpus surface: what is loaded, per dataset version (B-01).

The point of the surface is that it cannot flatter the corpus: every number is a
count over the corpus tables, an import that failed is reported with its error,
and a version nobody registered is still listed rather than dropped. A file the
operator never imported must stay visible as absent instead of looking like a
patent with no chemistry.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import bindparam, text


def _direct_counts(engine, kind: str) -> dict[str, int]:
    """The same numbers, read independently of the service under test."""
    table = {
        "families": "patent_families",
        "documents": "patent_documents",
        "compounds": "compounds",
        "mentions": "compound_mentions",
        "evidence": "evidence_records",
        "measurements": "measurements",
        "issues": "ingestion_issues",
    }[kind]
    with engine.connect() as conn:
        rows = conn.execute(
            text(f"SELECT dataset_version, count(*) FROM {table} GROUP BY dataset_version")
        ).all()
    return {r[0]: int(r[1]) for r in rows}


@pytest.fixture()
def inserted_job_ids(seeded_engine):
    """Rows this module inserts into `import_jobs`, removed afterwards.

    The stale-`running` recovery in `import_package` acts on every running row,
    so leaving test rows behind would change another module's job counts.
    """
    ids: list[uuid.UUID] = []
    yield ids
    with seeded_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM import_jobs WHERE id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": ids},
        )


class TestCorpusSurface:
    def test_every_count_matches_the_corpus_tables(self, app_client, seeded_engine):
        """The surface is a report of the database, not a cached claim."""
        body = app_client.get("/api/v1/corpus").json()
        assert body["sources"], "the seeded fixture must show up as at least one source"

        for kind in ("families", "documents", "compounds", "mentions", "evidence", "measurements", "issues"):
            expected = _direct_counts(seeded_engine, kind)
            reported = {s["dataset_version"]: s[kind] for s in body["sources"]}
            assert reported == expected, f"{kind} disagrees with the {kind} table"

        for kind in ("families", "documents", "compounds", "mentions", "evidence", "measurements", "issues"):
            assert body["totals"][kind] == sum(s[kind] for s in body["sources"])

    def test_the_demo_fixture_names_itself_and_its_versions(self, app_client):
        """A scientist reading this surface can say which release is loaded."""
        body = app_client.get("/api/v1/corpus").json()
        demo = [s for s in body["sources"] if s["registered"]]
        assert demo, "the demo package must be a registered source"
        first = demo[0]
        assert first["source_name"]
        assert first["dataset_version"]
        assert first["synthetic"] is True
        assert first["retrieved_at"], "a registered source carries its retrieval time"

    def test_a_failed_import_is_reported_with_its_error(self, app_client, seeded_engine, inserted_job_ids):
        """A failed import must not be invisible: the corpus is thin because of it."""
        job_id = uuid.uuid4()
        with seeded_engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO import_jobs (id, source_name, dataset_version, synthetic,
                                             status, error, finished_at)
                    VALUES (:id, 'operator_dump', 'dump-2026-09', false, 'failed',
                            'unsupported manifest schema_version 9', now())
                    """
                ),
                {"id": job_id},
            )
        inserted_job_ids.append(job_id)

        body = app_client.get("/api/v1/corpus").json()
        assert body["imports"]["failed"] >= 1
        last = body["imports"]["last_error"]
        assert last["dataset_version"] == "dump-2026-09"
        assert "unsupported manifest schema_version 9" in last["error"]
        assert body["imports"]["last_finished_at"]

    def test_an_interrupted_import_is_named_in_the_notes(self, app_client, seeded_engine, inserted_job_ids):
        job_id = uuid.uuid4()
        with seeded_engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO import_jobs (id, source_name, dataset_version, synthetic,
                                             status, error, started_at, finished_at)
                    VALUES (:id, 'operator_dump', 'dump-killed', false, 'interrupted',
                            'stopped before finishing', now() - interval '3 hours', now())
                    """
                ),
                {"id": job_id},
            )
        inserted_job_ids.append(job_id)

        body = app_client.get("/api/v1/corpus").json()
        assert body["imports"]["interrupted"] >= 1
        assert any("interrupted" in note for note in body["notes"])

    def test_an_unregistered_version_is_listed_and_labelled(self, app_client, seeded_engine):
        """Rows a source lookup wrote (never `import_package`) are corpus too, and
        the surface says they are not an operator-imported package."""
        version = f"unregistered-test-{uuid.uuid4().hex[:8]}"
        try:
            with seeded_engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO ingestion_issues (id, dataset_version, source_record_id,
                                                      patent_label, raw_smiles, issue)
                        VALUES (:id, :v, 'rec-1', 'XX-0000001-A', 'not-a-smiles',
                                'unparseable structure')
                        """
                    ),
                    {"id": uuid.uuid4(), "v": version},
                )
            body = app_client.get("/api/v1/corpus").json()
            row = next(s for s in body["sources"] if s["dataset_version"] == version)
            assert row["registered"] is False
            assert row["issues"] == 1
            assert row["source_name"] is None, "nothing recorded a source name for this version"
            assert any(version in note for note in body["notes"])
        finally:
            with seeded_engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM ingestion_issues WHERE dataset_version = :v"), {"v": version}
                )

    def test_a_target_investigation_version_keeps_its_source_name(
        self, app_client, seeded_engine
    ):
        """A version without a `dataset_info` row still names its source, because
        the bioactivity tables record `source_name` per row."""
        version = f"bindingdb-test-{uuid.uuid4().hex[:8]}"
        target_id, assay_id, compound_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        try:
            with seeded_engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO targets (id, target_key, name, organism, source_name,
                                             dataset_version, retrieved_at)
                        VALUES (:t, :tk, 'Test target', 'Homo sapiens', 'bindingdb_rest',
                                :v, now())
                        """
                    ),
                    {"t": target_id, "tk": f"TEST-{version}", "v": version},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO assays (id, assay_key, target_id, assay_type,
                                            source_name, dataset_version, retrieved_at)
                        VALUES (:a, :ak, :t, 'binding', 'bindingdb_rest', :v, now())
                        """
                    ),
                    {"a": assay_id, "ak": f"ASSAY-{version}", "t": target_id, "v": version},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO compounds (id, canonical_smiles, inchikey, dataset_version)
                        VALUES (:c, 'CCO', :ik, :v)
                        """
                    ),
                    {"c": compound_id, "ik": "LFQSCWFLJHTTHZ-UHFFFAOYSA-N", "v": version},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO measurements (id, compound_id, assay_id, standard_type,
                                                  value, unit, relation, source_name,
                                                  extraction_method, provenance_state,
                                                  dataset_version, retrieved_at)
                        VALUES (:m, :c, :a, 'IC50', 12.0, 'nM', '=', 'bindingdb_rest',
                                'adapter', 'database_curated', :v, now())
                        """
                    ),
                    {"m": uuid.uuid4(), "c": compound_id, "a": assay_id, "v": version},
                )

            body = app_client.get("/api/v1/corpus").json()
            row = next(s for s in body["sources"] if s["dataset_version"] == version)
            assert row["measurements"] == 1
            assert row["compounds"] == 1
            assert row["registered"] is False
        finally:
            with seeded_engine.begin() as conn:
                conn.execute(text("DELETE FROM measurements WHERE dataset_version = :v"), {"v": version})
                conn.execute(text("DELETE FROM assays WHERE dataset_version = :v"), {"v": version})
                conn.execute(text("DELETE FROM targets WHERE dataset_version = :v"), {"v": version})
                conn.execute(text("DELETE FROM compounds WHERE dataset_version = :v"), {"v": version})

class TestPublicationList:
    """The input side of a batch load: the operator's list, read exactly."""

    def test_a_plain_list_keeps_order_and_drops_duplicates(self, tmp_path):
        from spago_core.services.core import read_publication_list

        path = tmp_path / "patents.txt"
        path.write_text(
            "# a comment\nWO-2020000001-A\n\nUS-5153197-A\nWO-2020000001-A\n  EP-1234567-A1  \n",
            encoding="utf-8",
        )
        assert read_publication_list(path) == ["WO-2020000001-A", "US-5153197-A", "EP-1234567-A1"]

    def test_a_tabular_export_is_read_by_column_name(self, tmp_path):
        from spago_core.services.core import read_publication_list

        path = tmp_path / "set.csv"
        path.write_text(
            "target,patent_number,note\nTSLP,US-1111111-A,first\nTSLP,US-2222222-B,\n",
            encoding="utf-8",
        )
        assert read_publication_list(path, "patent_number") == ["US-1111111-A", "US-2222222-B"]
        assert read_publication_list(path, "1") == ["US-1111111-A", "US-2222222-B"]

    def test_a_multi_column_file_without_a_column_is_refused(self, tmp_path):
        """Guessing a column would silently check the wrong numbers."""
        from spago_core.services.core import read_publication_list

        path = tmp_path / "pairs.csv"
        path.write_text("target,patent_number\nTSLP,US-1-A\n", encoding="utf-8")
        with pytest.raises(ValueError, match="name the one holding publication numbers"):
            read_publication_list(path)
        with pytest.raises(ValueError, match="not in pairs.csv"):
            read_publication_list(path, "number")

    def test_a_single_column_export_with_a_header_row_skips_the_label(self, tmp_path):
        from spago_core.services.core import read_publication_list

        path = tmp_path / "one_column.csv"
        path.write_text("patent_number\nUS-1-A\nUS-2-B\n", encoding="utf-8")
        assert read_publication_list(path) == ["US-1-A", "US-2-B"]


class TestCorpusStatusCli:
    """The terminal surface, which is also what a batch run ends with."""

    def test_it_reports_the_coverage_gap_and_exits_non_zero(
        self, seeded_engine, tmp_path, monkeypatch, capsys
    ):
        from spago_core import corpus_status

        with seeded_engine.connect() as conn:
            present = [
                r[0]
                for r in conn.execute(
                    text("SELECT publication_number FROM patent_documents ORDER BY publication_number")
                )
            ]
        assert present
        listing = tmp_path / "checked.txt"
        listing.write_text(
            "\n".join(present + ["US-9999999-ZZ"]) + "\n", encoding="utf-8"
        )

        monkeypatch.setattr(corpus_status, "make_engine", lambda *a, **k: seeded_engine)
        assert corpus_status.main(["--patents", str(listing)]) == 1
        out = capsys.readouterr().out
        assert "US-9999999-ZZ" in out, "the missing number must appear verbatim"
        assert f"{len(present)}/{len(present) + 1} publication(s)" in out

    def test_a_list_that_is_fully_loaded_exits_zero(self, seeded_engine, tmp_path, monkeypatch, capsys):
        from spago_core import corpus_status

        with seeded_engine.connect() as conn:
            present = [
                r[0]
                for r in conn.execute(
                    text("SELECT publication_number FROM patent_documents ORDER BY publication_number")
                )
            ]
        listing = tmp_path / "loaded.txt"
        listing.write_text("\n".join(present) + "\n", encoding="utf-8")

        monkeypatch.setattr(corpus_status, "make_engine", lambda *a, **k: seeded_engine)
        assert corpus_status.main(["--patents", str(listing)]) == 0
        out = capsys.readouterr().out
        assert f"{len(present)}/{len(present)} publication(s) in the corpus" in out

    def test_json_output_carries_the_same_numbers_as_the_api(
        self, seeded_engine, tmp_path, monkeypatch, capsys
    ):
        import json

        from spago_core import corpus_status

        monkeypatch.setattr(corpus_status, "make_engine", lambda *a, **k: seeded_engine)
        assert corpus_status.main(["--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["sources"] and payload["totals"]
        assert "completed" in payload["imports"]
        assert "notes" in payload
