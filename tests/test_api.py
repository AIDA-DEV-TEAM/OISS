"""API tests, including the acceptance criteria for POST /ingest/upload."""
from __future__ import annotations

import shutil
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.api import main as api_main
from app.api.service import block_lookup
from app.ingest.loaders import process_source
from app.ingest.readers import SOURCES_BY_NAME

DATASET = "earas_2024_25_district_land_use"


@pytest.fixture(scope="module")
def api_db(db_path: Path, tmp_path_factory) -> Path:
    """A private copy of the built database.

    Uploads write governance rows by design, so these tests must not share the
    database the reconciliation tests assert against.
    """
    target = tmp_path_factory.mktemp("api") / "oiss.duckdb"
    shutil.copyfile(db_path, target)
    return target


@pytest.fixture
def client(api_db: Path) -> TestClient:
    """A client bound to this module's database copy, not the project one."""
    api_main.app.dependency_overrides[api_main.database_path] = lambda: api_db
    try:
        yield TestClient(api_main.app)
    finally:
        api_main.app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def bundled_bytes() -> bytes:
    return SOURCES_BY_NAME[DATASET].path.read_bytes()


def test_health_reports_the_built_database(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database_present"] is True
    assert body["fact_rows"]["fact_price"] > 0
    assert body["last_run_status"] == "succeeded"


def test_datasets_uses_the_list_envelope(client: TestClient) -> None:
    response = client.get("/datasets", params={"size": 5})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total", "page", "size"}
    assert body["total"] >= 15
    assert len(body["items"]) == 5


def test_lineage_walks_source_to_export(client: TestClient) -> None:
    version_id = client.get("/datasets", params={"size": 200}).json()["items"]
    version_id = next(
        item["dataset_version_id"] for item in version_id if item["layer"] == "raw"
    )
    body = client.get(f"/lineage/{version_id}").json()
    edge_types = {edge["edge_type"] for edge in body["edges"]}
    assert edge_types == {"extract", "transform", "load", "publish"}


def test_unknown_dataset_version_returns_the_error_shape(client: TestClient) -> None:
    response = client.get("/datasets/does-not-exist@000/validation")
    assert response.status_code == 404
    assert set(response.json()) == {"detail", "code"}
    assert response.json()["code"] == "dataset_not_found"


def test_upload_of_a_bundled_file_matches_the_batch_loader(
    client: TestClient, bundled_bytes: bytes
) -> None:
    """Acceptance: the upload path and the batch path agree on the findings."""
    response = client.post(
        "/ingest/upload",
        data={"dataset_name": DATASET},
        files={"file": ("land_use.csv", bundled_bytes, "text/csv")},
    )
    assert response.status_code == 201
    body = response.json()

    batch = process_source(SOURCES_BY_NAME[DATASET], blocks=block_lookup())
    expected: dict[tuple[str, str], int] = {}
    for finding in batch.findings:
        key = (finding.rule_code, finding.severity)
        expected[key] = expected.get(key, 0) + 1

    uploaded = {
        (row["rule_code"], row["severity"]): row["count"]
        for row in body["findings_by_rule"]
    }
    assert uploaded == expected
    assert body["dataset_version_id"] == batch.dataset_version_id
    assert body["rows_quarantined"] == 0


def test_uploading_a_bundled_file_leaves_its_build_record_intact(
    client: TestClient, bundled_bytes: bytes, api_db: Path
) -> None:
    body = client.post(
        "/ingest/upload",
        data={"dataset_name": DATASET},
        files={"file": ("land_use.csv", bundled_bytes, "text/csv")},
    ).json()
    # Opened after the request: DuckDB refuses a read-only connection while a
    # read-write one to the same file is open in this process.
    connection = duckdb.connect(str(api_db))
    try:
        layer, source_file = connection.execute(
            "SELECT layer, source_file FROM analytics.dataset_version WHERE dataset_version_id = ?",
            [body["dataset_version_id"]],
        ).fetchone()
    finally:
        connection.close()
    assert layer == "raw", "the upload must not restate the build's own version"
    assert not source_file.startswith("upload:")


def test_broken_upload_reports_rule_codes_and_quarantines_without_failing(
    client: TestClient, bundled_bytes: bytes
) -> None:
    """Acceptance: unknown district, text in a numeric column, duplicate row."""
    frame = pd.read_csv(SOURCES_BY_NAME[DATASET].path, dtype=str)
    frame.loc[0, "district_as_published"] = "Atlantis"
    frame.loc[1, "value"] = "not a number"
    frame = pd.concat([frame, frame.iloc[[5]]], ignore_index=True)
    payload = frame.to_csv(index=False, lineterminator="\n").encode()

    response = client.post(
        "/ingest/upload",
        data={"dataset_name": DATASET},
        files={"file": ("broken.csv", payload, "text/csv")},
    )
    assert response.status_code == 201, "a broken file must not fail the request"
    body = response.json()

    errors = {
        row["rule_code"] for row in body["findings_by_rule"] if row["severity"] == "error"
    }
    assert errors == {"UNKNOWN_DISTRICT", "TYPE_MISMATCH", "DUPLICATE_KEY"}
    assert body["rows_read"] == len(frame)
    assert body["rows_quarantined"] == 3
    assert body["rows_staged"] == len(frame) - 3
    assert body["quarantine_table"] is not None


def test_upload_rejects_an_unknown_dataset_name(client: TestClient) -> None:
    response = client.post(
        "/ingest/upload",
        data={"dataset_name": "not_a_dataset"},
        files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "unknown_dataset"


def test_upload_of_a_wrong_schema_reports_schema_mismatch(client: TestClient) -> None:
    response = client.post(
        "/ingest/upload",
        data={"dataset_name": DATASET},
        files={"file": ("wrong.csv", b"alpha,beta\n1,2\n", "text/csv")},
    )
    assert response.status_code == 201
    body = response.json()
    assert {row["rule_code"] for row in body["findings_by_rule"]} == {"SCHEMA_MISMATCH"}
    assert body["rows_staged"] == 0


# --------------------------------------------------------------------------
# Reader selection on upload
#
# Regression cover for a bug where the reader was chosen from the *target*
# dataset rather than from the uploaded file. A CSV uploaded against a
# Stata-backed dataset was handed to pandas.read_stata, which raised
# "Version of given Stata file is 116" -- 116 being the ASCII 't' of the CSV's
# own first header -- before any validation rule could run.
# --------------------------------------------------------------------------
CSV_SOURCES = [name for name, spec in SOURCES_BY_NAME.items() if spec.source_type == "csv"]
STATA_SOURCES = [name for name, spec in SOURCES_BY_NAME.items() if spec.source_type == "stata"]


@pytest.mark.parametrize("dataset_name", sorted(CSV_SOURCES))
def test_uploading_each_bundled_csv_is_validated_against_its_own_schema(
    client: TestClient, dataset_name: str
) -> None:
    """Every bundled CSV, uploaded as itself, matches the batch loader exactly."""
    spec = SOURCES_BY_NAME[dataset_name]
    response = client.post(
        "/ingest/upload",
        data={"dataset_name": dataset_name},
        files={"file": (spec.path.name, spec.path.read_bytes(), "text/csv")},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    batch = process_source(spec, blocks=block_lookup())
    expected: dict[tuple[str, str], int] = {}
    for finding in batch.findings:
        key = (finding.rule_code, finding.severity)
        expected[key] = expected.get(key, 0) + 1
    uploaded = {
        (row["rule_code"], row["severity"]): row["count"] for row in body["findings_by_rule"]
    }

    assert uploaded == expected
    assert body["dataset_version_id"] == batch.dataset_version_id
    # A file validated against its own schema has no schema finding at all.
    assert not any(code == "SCHEMA_MISMATCH" for code, _ in uploaded)


@pytest.mark.parametrize("dataset_name", sorted(STATA_SOURCES))
def test_uploading_a_csv_against_a_stata_dataset_reports_schema_not_parser_error(
    client: TestClient, dataset_name: str
) -> None:
    """The reported bug: a CSV sent to a Stata-backed target.

    It must be read as the CSV it is and rejected on schema, not crash the
    Stata parser with a version error.
    """
    csv_spec = SOURCES_BY_NAME["price_statistics_2020"]
    response = client.post(
        "/ingest/upload",
        data={"dataset_name": dataset_name},
        files={"file": (csv_spec.path.name, csv_spec.path.read_bytes(), "text/csv")},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    codes = {row["rule_code"] for row in body["findings_by_rule"]}
    assert codes == {"SCHEMA_MISMATCH"}, f"expected only a schema mismatch, got {codes}"

    # The CSV was genuinely parsed -- its own 6,300 rows and 10 columns -- and
    # every row quarantined, rather than the request dying in the reader.
    assert body["rows_read"] == 6300
    assert body["rows_quarantined"] == 6300

    messages = " ".join(f["message"] for f in body["findings"])
    assert "Stata" not in messages
    target = SOURCES_BY_NAME[dataset_name]
    # It names the columns the target wanted and the ones the file actually had.
    assert any(column in messages for column in target.expected_columns)
    assert "table_no" in messages


def test_uploading_a_stata_file_against_a_csv_dataset_also_reports_schema(
    client: TestClient,
) -> None:
    """The mirror case: Stata bytes sent to a CSV-backed target."""
    stata_spec = SOURCES_BY_NAME["earas_2022_23_block_paddy"]
    response = client.post(
        "/ingest/upload",
        data={"dataset_name": "earas_2024_25_district_land_use"},
        files={
            "file": (stata_spec.path.name, stata_spec.path.read_bytes(), "application/octet-stream")
        },
    )
    assert response.status_code == 201, response.text
    codes = {row["rule_code"] for row in response.json()["findings_by_rule"]}
    assert codes == {"SCHEMA_MISMATCH"}


def test_a_csv_renamed_dta_is_still_read_as_a_csv(client: TestClient) -> None:
    """Content decides the reader, not the extension a browser attached."""
    csv_spec = SOURCES_BY_NAME["price_statistics_2020"]
    response = client.post(
        "/ingest/upload",
        data={"dataset_name": "price_statistics_2020"},
        files={"file": ("mislabelled.dta", csv_spec.path.read_bytes(), "application/octet-stream")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["rows_read"] == 6300
    assert not any(row["rule_code"] == "SCHEMA_MISMATCH" for row in body["findings_by_rule"])


def test_ingest_schemas_lists_every_upload_target(client: TestClient) -> None:
    """The ingest screen reads this to match a file to the right dataset."""
    response = client.get("/ingest/schemas")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(SOURCES_BY_NAME)
    by_name = {item["dataset_name"]: item for item in body["items"]}
    assert set(by_name) == set(SOURCES_BY_NAME)
    price = by_name["price_statistics_2020"]
    assert price["source_type"] == "csv"
    assert "table_no" in price["expected_columns"]
    assert by_name["earas_2022_23_block_land_use"]["source_type"] == "stata"


def test_upload_returns_detail_rows_for_every_rule_it_reports(client: TestClient) -> None:
    """Regression: a flat cap starved the rules that fired later.

    Uploading the price CSV reported 847 MISSING_VALUE findings in the summary
    and returned none of them, because MSP_SUBSTITUTED fired first and consumed
    all 200 slots. The ingest screen then showed a populated count above an
    empty table.
    """
    spec = SOURCES_BY_NAME["price_statistics_2020"]
    response = client.post(
        "/ingest/upload",
        data={"dataset_name": "price_statistics_2020"},
        files={"file": (spec.path.name, spec.path.read_bytes(), "text/csv")},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    summarised = {row["rule_code"] for row in body["findings_by_rule"]}
    detailed = {finding["rule_code"] for finding in body["findings"]}
    assert summarised, "the price CSV should produce findings"
    assert summarised == detailed, (
        f"rules with a count but no detail rows: {sorted(summarised - detailed)}"
    )
    # The rule from the report specifically.
    assert "MISSING_VALUE" in detailed
    assert any(f["rule_code"] == "MISSING_VALUE" and f["row_ref"] for f in body["findings"])


def test_upload_detail_is_capped_per_rule_not_across_all_rules(client: TestClient) -> None:
    """Each rule gets its own allowance, so no rule can crowd out another."""
    from app.api.service import FINDINGS_PER_RULE

    spec = SOURCES_BY_NAME["price_statistics_2020"]
    body = client.post(
        "/ingest/upload",
        data={"dataset_name": "price_statistics_2020"},
        files={"file": (spec.path.name, spec.path.read_bytes(), "text/csv")},
    ).json()

    per_rule: dict[str, int] = {}
    for finding in body["findings"]:
        per_rule[finding["rule_code"]] = per_rule.get(finding["rule_code"], 0) + 1

    counts = {row["rule_code"]: row["count"] for row in body["findings_by_rule"]}
    for code, shown in per_rule.items():
        assert shown <= FINDINGS_PER_RULE
        # A rule with more findings than the allowance is shown at the cap,
        # never at zero.
        assert shown == min(counts[code], FINDINGS_PER_RULE)
