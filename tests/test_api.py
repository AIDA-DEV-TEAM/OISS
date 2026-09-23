"""API tests, including the acceptance criteria for POST /ingest/upload."""
from __future__ import annotations

import shutil
import zlib
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import db
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
    # The build wrote the version this code expects.
    assert body["schema_version"] == db.SCHEMA_VERSION


def test_the_backend_starts_against_a_database_of_its_own_schema_version(
    api_db: Path,
) -> None:
    api_main.app.dependency_overrides[api_main.database_path] = lambda: api_db
    try:
        with TestClient(api_main.app) as client:
            assert client.get("/health").json()["schema_version"] == db.SCHEMA_VERSION
    finally:
        api_main.app.dependency_overrides.clear()
        api_main.close_connections()


@pytest.mark.parametrize("found", [None, 1])
def test_the_backend_refuses_to_start_on_a_schema_mismatch(
    db_path: Path, tmp_path: Path, found: int | None
) -> None:
    """A database built by other code fails at startup, not as a 500 later.

    ``None`` is a database built before versioning, which counts as v1.
    """
    stale = tmp_path / "stale.duckdb"
    shutil.copyfile(db_path, stale)
    con = duckdb.connect(str(stale))
    try:
        if found is None:
            con.execute("DROP TABLE analytics.schema_meta")
        else:
            con.execute("UPDATE analytics.schema_meta SET version = ?", [found])
    finally:
        con.close()

    api_main.app.dependency_overrides[api_main.database_path] = lambda: stale
    try:
        expected = (
            f"DB schema v1, code expects v{db.SCHEMA_VERSION}: "
            "stop the backend and run app.cli build."
        )
        with pytest.raises(db.SchemaMismatch) as refused:
            with TestClient(api_main.app):
                pass
        assert str(refused.value) == expected
    finally:
        api_main.app.dependency_overrides.clear()
        api_main.close_connections()


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


# --------------------------------------------------------------------------
# Upload: unregistered files, workbooks, and a deliberately broken CSV
# --------------------------------------------------------------------------
BROKEN_CSV = Path(__file__).parent / "fixtures" / "broken_upload.csv"


def _distinct(raw: bytes, tag: str) -> bytes:
    """The same file with one extra clean row, so its checksum is its own.

    Version ids are content-addressed, so two tests uploading identical bytes
    would make the second a duplicate of the first. Each test that needs its own
    version therefore varies the content rather than only the filename.
    """
    # zlib.crc32, not hash(): str hashing is salted per process, which would
    # make the uploaded bytes differ between runs and the version id with them.
    area = 1000 + zlib.crc32(tag.encode("utf-8")) % 900
    # A district, season and crop the fixture does not already use, so the extra
    # row cannot collide on the natural key and add a DUPLICATE_KEY finding.
    row = f"2023-24,Sambalpur,Summer,Kulthi,{area},5.00,{area * 5}"
    return raw.rstrip(b"\n") + b"\n" + row.encode("utf-8") + b"\n"


def test_broken_csv_reports_unknown_district_type_and_duplicate(
    client: TestClient,
) -> None:
    """The demo fixture: one file carrying three different kinds of fault."""
    response = client.post(
        "/ingest/upload",
        data={"dataset_name": "earas_2023_24_district_minor_crops"},
        files={"file": ("broken_upload.csv", BROKEN_CSV.read_bytes(), "text/csv")},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    codes = {row["rule_code"] for row in body["findings_by_rule"]}
    assert {"UNKNOWN_DISTRICT", "TYPE_MISMATCH", "DUPLICATE_KEY"} <= codes

    # Those rules are errors, so their rows are quarantined. Staged rows are
    # not comparable to raw rows here: this transform melts one published row
    # into three, one per measure.
    assert body["rows_read"] == 9
    assert body["rows_quarantined"] == 6
    assert body["quarantine_table"]

    messages = " ".join(f["message"] for f in body["findings"])
    assert "Shangri-La" in messages and "Atlantis" in messages


def test_unregistered_upload_is_validated_for_generic_problems(
    client: TestClient,
) -> None:
    """A file matching no declared schema is still read and checked.

    No schema means no SCHEMA_MISMATCH -- there is nothing to mismatch against.
    What it does get is the checks that hold for any table.
    """
    response = client.post(
        "/ingest/upload",
        data={"dataset_name": "", "data_origin": "official"},
        files={"file": ("unreg_generic.csv", _distinct(BROKEN_CSV.read_bytes(), "generic"), "text/csv")},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    codes = {row["rule_code"] for row in body["findings_by_rule"]}
    assert "SCHEMA_MISMATCH" not in codes
    assert "UNKNOWN_DISTRICT" in codes, "a District column should still be checked"
    assert "TYPE_MISMATCH" in codes, "text in a numeric column should still be caught"
    assert body["rows_read"] == 10
    assert body["dataset_version_id"].startswith("upload_unreg_generic@")


def test_unregistered_upload_of_a_clean_file_quarantines_nothing(
    client: TestClient,
) -> None:
    """Published markers must not be mistaken for bad data.

    The price extract's `raw_value` column carries "-" and footnote asterisks
    such as "1310*". Treating those as text in a numeric column condemned every
    row of a perfectly good file.
    """
    spec = SOURCES_BY_NAME["price_statistics_2020"]
    body = client.post(
        "/ingest/upload",
        data={"dataset_name": "", "data_origin": "official"},
        files={"file": (spec.path.name, spec.path.read_bytes(), "text/csv")},
    ).json()

    assert body["rows_read"] == 6300
    assert body["rows_quarantined"] == 0
    codes = {row["rule_code"] for row in body["findings_by_rule"]}
    assert "TYPE_MISMATCH" not in codes


def test_an_uploaded_workbook_is_read_as_a_workbook(client: TestClient) -> None:
    """XLSX is chosen by content, not by the target dataset or the extension."""
    openpyxl = pytest.importorskip("openpyxl")
    from io import BytesIO

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(
        ["Year", "District", "Season", "Minor_Crop", "Area_ha",
         "Yield_rate_qtl_per_ha", "Production_qtls"]
    )
    sheet.append(["2023-24", "Angul", "Winter", "Mung", 1240, 5.2, 6448])
    sheet.append(["2023-24", "Nowhere", "Winter", "Mung", 900, 5.0, 4500])
    buffer = BytesIO()
    workbook.save(buffer)

    response = client.post(
        "/ingest/upload",
        data={"dataset_name": "earas_2023_24_district_minor_crops"},
        files={
            "file": (
                "minor_crops.xlsx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    # Two data rows were genuinely parsed out of the workbook.
    assert body["rows_read"] == 2
    codes = {row["rule_code"] for row in body["findings_by_rule"]}
    assert "SCHEMA_MISMATCH" not in codes, "the workbook's columns match the target"
    assert "UNKNOWN_DISTRICT" in codes


# --------------------------------------------------------------------------
# Promotion and the active version
# --------------------------------------------------------------------------
PADDY_2023_24 = {
    "metric": "production",
    "dimensions": ["agri_year"],
    "filters": [
        {"dimension": "crop", "op": "in", "values": ["CR17"]},
        {"dimension": "agri_year", "op": "eq", "values": ["2023-24"]},
    ],
}


def _paddy_lakh_mt(client: TestClient) -> float:
    rows = client.post("/query", json=PADDY_2023_24).json()["rows"]
    return rows[0]["value"] / 1e6


def _halve_one_row(raw: bytes) -> bytes:
    """Halve Angul's autumn paddy production, so the change is exact."""
    lines = raw.decode("utf-8-sig").splitlines()
    for index, line in enumerate(lines):
        if line.startswith("2023-24,Angul,Autumn,Paddy,"):
            parts = line.split(",")
            parts[6] = f"{float(parts[6]) / 2:.2f}"
            lines[index] = ",".join(parts)
            break
    else:  # pragma: no cover - the fixture row must exist
        raise AssertionError("Angul autumn paddy row not found")
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_promoting_a_bundled_upload_leaves_the_figures_unchanged(
    client: TestClient,
) -> None:
    """Re-uploading a bundled file is content-identical, so nothing moves."""
    spec = SOURCES_BY_NAME["earas_2023_24_district_paddy"]
    before = _paddy_lakh_mt(client)
    assert round(before, 2) == 174.83

    body = client.post(
        "/ingest/upload",
        data={"dataset_name": "earas_2023_24_district_paddy"},
        files={"file": (spec.path.name, spec.path.read_bytes(), "text/csv")},
    ).json()
    # Identical bytes are the version already loaded, so nothing is promoted.
    assert body["duplicate_of"] == "earas_2023_24_district_paddy@5e8bdea5ea67"
    assert body["rows_promoted"] == 0
    assert body["promoted_to"] is None
    assert round(_paddy_lakh_mt(client), 2) == 174.83

    # Activating the version it points at changes nothing: same data.
    client.post(f"/datasets/{body['duplicate_of']}/activate")
    assert round(_paddy_lakh_mt(client), 2) == 174.83


def test_activating_a_modified_upload_changes_figures_by_exactly_that_row(
    client: TestClient,
) -> None:
    """The whole point of the active version: promotion alone must not count."""
    spec = SOURCES_BY_NAME["earas_2023_24_district_paddy"]
    modified = _halve_one_row(spec.path.read_bytes())
    baseline = _paddy_lakh_mt(client)

    body = client.post(
        "/ingest/upload",
        data={"dataset_name": "earas_2023_24_district_paddy"},
        files={"file": ("modified.csv", modified, "text/csv")},
    ).json()
    version_id = body["dataset_version_id"]
    assert body["rows_promoted"] > 0

    # Promoted but inactive: the dashboard is untouched.
    assert _paddy_lakh_mt(client) == pytest.approx(baseline)

    client.post(f"/datasets/{version_id}/activate")
    activated = _paddy_lakh_mt(client)
    # 9.79 -> 4.89 '000 MT is 4.90 '000 MT, which is 0.049 lakh MT.
    assert activated == pytest.approx(baseline - 0.049, abs=1e-3)

    client.post(f"/datasets/{version_id}/deactivate")
    assert _paddy_lakh_mt(client) == pytest.approx(baseline)


def test_activation_deactivates_the_previous_version(client: TestClient) -> None:
    """Exactly one version per dataset is ever active."""
    spec = SOURCES_BY_NAME["earas_2023_24_district_paddy"]
    modified = _halve_one_row(spec.path.read_bytes())
    body = client.post(
        "/ingest/upload",
        data={"dataset_name": "earas_2023_24_district_paddy"},
        files={"file": ("modified2.csv", modified, "text/csv")},
    ).json()
    version_id = body["dataset_version_id"]

    result = client.post(f"/datasets/{version_id}/activate").json()
    assert result["activated"] == version_id
    assert result["deactivated"], "the build's version should have been stood down"

    active = [
        item
        for item in client.get("/datasets", params={"size": 200}).json()["items"]
        if item["dataset_name"] == "earas_2023_24_district_paddy" and item["is_active"]
    ]
    assert len(active) == 1 and active[0]["dataset_version_id"] == version_id
    client.post(f"/datasets/{version_id}/deactivate")


def test_an_uploaded_version_starts_inactive(client: TestClient) -> None:
    spec = SOURCES_BY_NAME["earas_2023_24_district_paddy"]
    body = client.post(
        "/ingest/upload",
        data={"dataset_name": "earas_2023_24_district_paddy"},
        files={"file": ("modified3.csv", _halve_one_row(spec.path.read_bytes()), "text/csv")},
    ).json()
    version = client.get(f"/datasets/{body['dataset_version_id']}").json()
    assert version["is_active"] is False
    assert version["layer"] == "upload"


def test_partial_promotion_keeps_bad_rows_out_and_promotes_the_rest(
    client: TestClient,
) -> None:
    """All-or-nothing is wrong: the clean rows must still land."""
    body = client.post(
        "/ingest/upload",
        data={"dataset_name": "earas_2023_24_district_minor_crops"},
        files={"file": ("partial.csv", _distinct(BROKEN_CSV.read_bytes(), "partial"), "text/csv")},
    ).json()
    assert body["rows_quarantined"] == 6
    assert body["rows_promoted"] > 0, "the clean rows should have been promoted"
    # The quarantined rows are absent from the promoted set, not the whole file.
    assert body["rows_staged"] > 0
    assert body["promoted_to"] == "analytics.fact_crop_ayp"


def test_unregistered_upload_stops_at_staging(client: TestClient) -> None:
    """No declared schema means no fact table to promote into."""
    body = client.post(
        "/ingest/upload",
        data={"dataset_name": "", "data_origin": "official"},
        files={"file": ("unreg_staging.csv", _distinct(BROKEN_CSV.read_bytes(), "staging"), "text/csv")},
    ).json()
    assert body["staging_table"]
    assert body["rows_promoted"] == 0
    assert body["promoted_to"] is None


def test_lineage_edges_only_point_at_tables_that_exist(client: TestClient) -> None:
    """A clean upload quarantines nothing, so there is no quarantine edge."""
    spec = SOURCES_BY_NAME["earas_2023_24_district_paddy"]
    body = client.post(
        "/ingest/upload",
        data={"dataset_name": "earas_2023_24_district_paddy"},
        files={"file": ("clean.csv", _halve_one_row(spec.path.read_bytes()), "text/csv")},
    ).json()
    assert body["rows_quarantined"] == 0

    edges = client.get(f"/lineage/{body['dataset_version_id']}").json()["edges"]
    upload_edges = [e for e in edges if e["from_node"].startswith("upload:")]
    assert upload_edges, "an upload should record its own lineage"
    assert not any("quarantine" in e["to_node"] for e in upload_edges)
    assert any(e["to_node"].startswith("staging.") for e in upload_edges)
    assert any(e["edge_type"] == "load" for e in edges)


def test_layer_journey_reports_the_uploads_own_counts(client: TestClient) -> None:
    """Regression: it used to read the bundled dataset's tables instead."""
    body = client.post(
        "/ingest/upload",
        data={"dataset_name": "earas_2023_24_district_minor_crops"},
        files={"file": ("broken_upload.csv", BROKEN_CSV.read_bytes(), "text/csv")},
    ).json()
    layers = client.get(f"/datasets/{body['dataset_version_id']}/layers").json()["items"]
    by_layer = {row["layer"]: row for row in layers}

    assert by_layer["raw"]["row_count"] == 9, "the upload's own 9 rows, not the build's"
    assert by_layer["quarantine"]["row_count"] == 6, "an upload that quarantined must show it"


# --------------------------------------------------------------------------
# Duplicate content and declared data_origin
# --------------------------------------------------------------------------
def _fact_fingerprint(api_db: Path, version_id: str) -> list[tuple]:
    """Every fact row for a version, ordered, so identity can be compared."""
    con = duckdb.connect(str(api_db))
    try:
        return con.execute(
            """
            SELECT period_id, district_id, crop_id, product, measure,
                   value_canonical, data_origin
            FROM analytics.fact_crop_ayp
            WHERE dataset_version_id = ?
            ORDER BY period_id, district_id, crop_id, product, measure
            """,
            [version_id],
        ).fetchall()
    finally:
        con.close()


def test_reuploading_a_bundled_file_is_a_duplicate_and_writes_nothing(
    client: TestClient, api_db: Path
) -> None:
    """The build's rows are untouched, proved on row identity not totals."""
    spec = SOURCES_BY_NAME["earas_2023_24_district_paddy"]
    version_id = "earas_2023_24_district_paddy@5e8bdea5ea67"

    before = _fact_fingerprint(api_db, version_id)
    assert before, "the build should already have loaded this version"

    response = client.post(
        "/ingest/upload",
        data={"dataset_name": "earas_2023_24_district_paddy"},
        files={"file": (spec.path.name, spec.path.read_bytes(), "text/csv")},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["duplicate_of"] == version_id
    assert body["duplicate_layer"] == "raw"
    assert body["rows_promoted"] == 0
    assert body["staging_table"] is None
    assert body["promoted_to"] is None

    after = _fact_fingerprint(api_db, version_id)
    assert after == before, "a duplicate upload must not rewrite the build's rows"


def test_a_duplicate_upload_records_a_run_and_a_duplicate_of_edge(
    client: TestClient, api_db: Path
) -> None:
    spec = SOURCES_BY_NAME["earas_2023_24_district_paddy"]
    body = client.post(
        "/ingest/upload",
        data={"dataset_name": "earas_2023_24_district_paddy"},
        files={"file": ("again.csv", spec.path.read_bytes(), "text/csv")},
    ).json()

    con = duckdb.connect(str(api_db))
    try:
        status = con.execute(
            "SELECT status FROM analytics.load_run WHERE run_id = ?", [body["run_id"]]
        ).fetchone()
        edges = con.execute(
            "SELECT from_node, to_node FROM analytics.lineage_edge "
            "WHERE edge_type = 'duplicate_of' AND dataset_version_id = ?",
            [body["duplicate_of"]],
        ).fetchall()
    finally:
        con.close()

    assert status is not None and status[0] == "duplicate"
    assert any(to_node == body["duplicate_of"] for _, to_node in edges)


def test_the_promotion_path_refuses_to_touch_a_build_version(api_db: Path) -> None:
    """The guard itself, exercised directly.

    Reaching the promotion path with a build version should be impossible via
    the endpoint, because duplicates short-circuit first. The guard is the
    second lock: if a future change lets one through, it fails loudly.
    """
    from app.api.service import BuildVersionImmutable, _assert_upload_version

    con = duckdb.connect(str(api_db))
    try:
        with pytest.raises(BuildVersionImmutable, match="batch build"):
            _assert_upload_version(con, "earas_2023_24_district_paddy@5e8bdea5ea67")
        # An id the uploader created, or one that does not exist yet, is fine.
        _assert_upload_version(con, "not_a_version@deadbeef")
    finally:
        con.close()


def test_unregistered_upload_requires_a_declared_data_origin(
    client: TestClient,
) -> None:
    """No default: the uploader says whether this is official or synthetic."""
    response = client.post(
        "/ingest/upload",
        data={"dataset_name": ""},
        files={"file": ("broken_upload.csv", BROKEN_CSV.read_bytes(), "text/csv")},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "data_origin_required"
    assert body["field"] == "data_origin"
    assert set(body["allowed_values"]) == {"official", "synthetic"}


@pytest.mark.parametrize("origin", ["official", "synthetic"])
def test_unregistered_upload_records_the_declared_origin(
    client: TestClient, origin: str
) -> None:
    response = client.post(
        "/ingest/upload",
        data={"dataset_name": "", "data_origin": origin},
        files={"file": (f"decl_{origin}.csv", BROKEN_CSV.read_bytes(), "text/csv")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["data_origin"] == origin


def test_a_rejected_data_origin_names_what_it_would_accept(client: TestClient) -> None:
    response = client.post(
        "/ingest/upload",
        data={"dataset_name": "", "data_origin": "guesswork"},
        files={"file": ("bad_origin.csv", BROKEN_CSV.read_bytes(), "text/csv")},
    )
    assert response.status_code == 422
    assert response.json()["field"] == "data_origin"


def test_registered_uploads_still_take_origin_from_the_dataset(
    client: TestClient,
) -> None:
    """A registered target declares its own origin; the form field is ignored."""
    body = client.post(
        "/ingest/upload",
        data={"dataset_name": "earas_2023_24_district_minor_crops", "data_origin": "synthetic"},
        files={"file": ("broken_upload.csv", BROKEN_CSV.read_bytes(), "text/csv")},
    ).json()
    assert body["data_origin"] == "official"


def test_unregistered_staging_holds_only_the_rows_that_passed(client, api_db):
    """Staging is what survived validation, and rows_staged says how many.

    The unregistered branch used to copy the whole raw frame into staging --
    quarantined rows included -- while reporting rows_staged as zero. Both
    halves of that were wrong in opposite directions.
    """
    payload = BROKEN_CSV.read_bytes()
    response = client.post(
        "/ingest/upload",
        files={"file": ("staging_truth.csv", payload, "text/csv")},
        data={"dataset_name": "", "data_origin": "synthetic"},
    )
    assert response.status_code == 201
    body = response.json()

    assert body["rows_read"] == 9
    assert body["rows_quarantined"] == 6
    assert body["rows_staged"] == 3

    con = duckdb.connect(str(api_db))
    try:
        staged = con.execute(f"SELECT COUNT(*) FROM {body['staging_table']}").fetchone()[0]
        held = con.execute(f"SELECT COUNT(*) FROM {body['quarantine_table']}").fetchone()[0]
    finally:
        con.close()
    assert staged == body["rows_staged"]
    assert held == body["rows_quarantined"]
    assert staged + held == body["rows_read"]
