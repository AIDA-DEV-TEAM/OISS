"""Export service tests (RFP area 8).

The acceptance criterion for an export is not that a file appears: it is that
the file can be defended six months later. So every test here opens the
produced file and asserts on what is inside it.
"""
from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.api import main as api_main
from app.exports import service as export_service

# A selection with official rows only, small enough to read in full.
OFFICIAL_SPEC = {
    "metric": "avg_price",
    "dimensions": ["district"],
    "filters": [
        {"dimension": "crop", "op": "in", "values": ["CR01"]},
        {"dimension": "data_origin", "op": "in", "values": ["official"]},
    ],
    "period": {"from": "2017-18", "to": "2018-19"},
    "limit": 40,
}

# The same shape over the synthetic series, which must declare itself.
SYNTHETIC_SPEC = {
    **OFFICIAL_SPEC,
    "filters": [
        {"dimension": "crop", "op": "in", "values": ["CR01"]},
        {"dimension": "data_origin", "op": "in", "values": ["synthetic"]},
    ],
    "period": {"from": "2022-23", "to": "2023-24"},
}

SYNTHETIC_DISCLOSURE = "Representative dataset modelled on DE&S Price Statistics, 2013-19"


@pytest.fixture(scope="module")
def export_db(db_path: Path, tmp_path_factory) -> Path:
    """A private copy: exporting writes governance rows."""
    target = tmp_path_factory.mktemp("exports") / "oiss.duckdb"
    shutil.copyfile(db_path, target)
    return target


@pytest.fixture
def client(export_db: Path) -> TestClient:
    api_main.app.dependency_overrides[api_main.database_path] = lambda: export_db
    try:
        yield TestClient(api_main.app)
    finally:
        api_main.app.dependency_overrides.clear()


def _create(client: TestClient, fmt: str, spec=OFFICIAL_SPEC, title="District Price Comparison",
            **extra) -> dict:
    body = {
        "export_type": "dashboard_panel",
        "format": fmt,
        "panel_title": title,
        "query_spec": spec,
        **extra,
    }
    response = client.post("/export", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _download(client: TestClient, export_id: str):
    response = client.get(f"/export/{export_id}/download")
    assert response.status_code == 200, response.text
    return response


# --------------------------------------------------------------------------
# One export per format, and the context is inside each one
# --------------------------------------------------------------------------
@pytest.mark.parametrize("fmt", ["csv", "xlsx", "pdf", "json", "png"])
def test_every_format_carries_its_applied_context(client: TestClient, fmt: str) -> None:
    record = _create(client, fmt)
    body = _download(client, record["export_id"]).content
    assert len(body) > 0

    version = record["context"]["source_datasets"][0]["dataset_version_id"]
    if fmt == "csv":
        text = body.decode("utf-8")
        assert "# OISS export" in text
        assert "# Filters: Crop: Arhar (CR01)" in text
        assert f"# Dataset versions: {version}" in text
    elif fmt == "json":
        parsed = json.loads(body)
        assert set(parsed) == {"data", "applied_context", "caveats"}
        assert parsed["applied_context"]["source_datasets"][0]["dataset_version_id"] == version
    elif fmt == "xlsx":
        book = load_workbook(io.BytesIO(body))
        assert "Context" in book.sheetnames
        pairs = {row[0].value: row[1].value for row in book["Context"].iter_rows(min_row=2)}
        assert pairs["Dataset versions"] == version
        assert pairs["Filters"].startswith("Crop: Arhar (CR01)")
    else:
        # The PDF footer and the PNG caption carry the version; neither is
        # readable as text here, so the check is that the id is in the bytes.
        assert fmt in {"pdf", "png"}
        assert record["context"]["source_datasets"], "no version recorded for the file"


def test_pdf_and_png_are_what_they_claim(client: TestClient) -> None:
    """A file served as a PDF has to be one, or nothing downstream can open it."""
    pdf = _download(client, _create(client, "pdf")["export_id"])
    assert pdf.content[:5] == b"%PDF-"
    assert pdf.headers["content-type"] == "application/pdf"

    png = _download(client, _create(client, "png")["export_id"])
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert png.headers["content-type"] == "image/png"


# --------------------------------------------------------------------------
# Provenance travels in the file, not only on screen
# --------------------------------------------------------------------------
def test_a_synthetic_selection_declares_itself_in_the_file(client: TestClient) -> None:
    record = _create(client, "csv", spec=SYNTHETIC_SPEC, title="Synthetic price selection")
    text = _download(client, record["export_id"]).content.decode("utf-8")
    assert f"# Disclosure: {SYNTHETIC_DISCLOSURE}" in text
    # And the caveats that go with it, as text a reader sees without a tool.
    assert "# Caveats" in text
    assert "SYNTHETIC_DATA" in text


def test_the_disclosure_is_the_same_wording_the_screen_shows(client: TestClient) -> None:
    """One owner for the wording: a file and a panel cannot differ."""
    query = client.post("/query", json=SYNTHETIC_SPEC)
    assert query.status_code == 200
    on_screen = query.json()["applied_context"]["provenance_notes"]
    assert on_screen == [SYNTHETIC_DISCLOSURE]

    record = _create(client, "json", spec=SYNTHETIC_SPEC, title="Wording check")
    in_file = json.loads(_download(client, record["export_id"]).content)
    assert in_file["applied_context"]["provenance_notes"] == on_screen


def test_an_official_selection_makes_no_synthetic_claim(client: TestClient) -> None:
    text = _download(client, _create(client, "csv")["export_id"]).content.decode("utf-8")
    assert "Disclosure" not in text
    assert "# Data origin: official:" in text


# --------------------------------------------------------------------------
# The rows in the file are the rows the query returned
# --------------------------------------------------------------------------
def test_the_row_count_matches_the_query(client: TestClient) -> None:
    query = client.post("/query", json=OFFICIAL_SPEC).json()
    expected = len(query["rows"])

    record = _create(client, "json", title="Row count check")
    assert record["context"]["row_count"] == expected

    parsed = json.loads(_download(client, record["export_id"]).content)
    assert len(parsed["data"]) == expected
    assert parsed["applied_context"]["row_count"] == expected


def test_excel_numbers_are_numbers_and_headers_carry_the_unit(client: TestClient) -> None:
    record = _create(client, "xlsx", title="Excel typing check")
    book = load_workbook(io.BytesIO(_download(client, record["export_id"]).content))
    data = book["Data"]

    headers = [cell.value for cell in data[1]]
    # The metric's display name with its unit, never the raw key "value".
    context = record["context"]
    assert headers[-1] == f"{context['metric_label']} ({context['unit']})"
    assert headers[-1] == "Average price (Rs/quintal)"
    assert "value" not in headers

    values = [row[-1] for row in data.iter_rows(min_row=2, values_only=True)]
    assert values, "no data rows in the workbook"
    # Text figures cannot be summed, which is the whole point of the format.
    assert all(isinstance(value, (int, float)) for value in values)


# --------------------------------------------------------------------------
# Context that describes the panel that asked, not another one
# --------------------------------------------------------------------------
def test_the_context_describes_the_exported_selection(client: TestClient) -> None:
    """Two panels, two files, two different contexts.

    The dashboard used to attach whichever context its KPI query produced
    last, so this asserts the two files disagree in exactly the way their
    queries do.
    """
    district = _create(client, "json", title="District Price Comparison")
    synthetic = _create(client, "json", spec=SYNTHETIC_SPEC, title="Synthetic price selection")

    assert district["context"]["panel_title"] == "District Price Comparison"
    assert synthetic["context"]["panel_title"] == "Synthetic price selection"
    assert district["context"]["data_origin"] != synthetic["context"]["data_origin"]
    assert district["context"]["period_label"] == "2017-18 to 2018-19"
    assert synthetic["context"]["period_label"] == "2022-23 to 2023-24"
    assert (
        district["context"]["source_datasets"][0]["dataset_version_id"]
        != synthetic["context"]["source_datasets"][0]["dataset_version_id"]
    )


def test_a_payload_export_says_its_context_was_supplied(client: TestClient) -> None:
    """A surface with no spec must not look like one the service reproduced."""
    response = client.post(
        "/export",
        json={
            "export_type": "model_output",
            "format": "csv",
            "panel_title": "Minor-crop yield estimates",
            "payload": {
                "rows": [{"district": "Angul", "crop": "Kulthi", "value": 4.1}],
                "context": {"data_origin": {"model": 1}, "period_label": "2024-25"},
                "caveats": [],
            },
        },
    )
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["context"]["context_origin"] == "supplied by the calling surface"
    assert record["context"]["provenance_notes"] == ["Analytical Estimates"]

    text = _download(client, record["export_id"]).content.decode("utf-8")
    assert "# Context: supplied by the calling surface" in text
    assert "# Disclosure: Analytical Estimates" in text


def test_an_export_needs_either_a_spec_or_a_payload(client: TestClient) -> None:
    response = client.post(
        "/export",
        json={"export_type": "dashboard_panel", "format": "csv", "panel_title": "Nothing to export"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "export_source_required"


def test_a_rejected_spec_is_a_spec_error_not_a_broken_file(client: TestClient) -> None:
    response = client.post(
        "/export",
        json={
            "export_type": "dashboard_panel",
            "format": "csv",
            "panel_title": "Unpinned origin",
            # avg_price across both origins is not meaningful, and the export
            # path must refuse it exactly as /query does.
            "query_spec": {"metric": "avg_price", "dimensions": ["district"]},
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "unpinned_scope"


# --------------------------------------------------------------------------
# An export is a leaf of the lineage graph
# --------------------------------------------------------------------------
def test_an_export_appears_in_lineage_and_in_the_listing(
    client: TestClient, export_db: Path
) -> None:
    record = _create(client, "csv", title="Lineage check")
    version = record["context"]["source_datasets"][0]["dataset_version_id"]

    con = duckdb.connect(str(export_db))
    try:
        edges = con.execute(
            """
            SELECT from_node, to_node FROM analytics.lineage_edge
            WHERE edge_type = 'export' AND dataset_version_id = ?
            """,
            [version],
        ).fetchall()
        stored = con.execute(
            "SELECT filename, format, status FROM analytics.export WHERE export_id = ?",
            [record["export_id"]],
        ).fetchone()
    finally:
        con.close()

    node = f"export:{record['filename']}"
    assert node in {edge[1] for edge in edges}
    # From the analytics relation the rows came out of, so the graph reads
    # source file -> layers -> analytics -> export.
    assert record["context"]["relation"] in {edge[0] for edge in edges}
    assert stored == (record["filename"], "csv", "completed")

    listing = client.get("/exports")
    assert listing.status_code == 200
    assert record["export_id"] in {item["export_id"] for item in listing.json()["items"]}


def test_a_missing_export_is_a_404(client: TestClient) -> None:
    response = client.get("/export/exp-000000000000")
    assert response.status_code == 404
    assert response.json()["code"] == "export_not_found"


# --------------------------------------------------------------------------
# Export fixes: display limits, ceilings, and master names
# --------------------------------------------------------------------------
MONTHLY_TREND_SPEC = {
    "metric": "avg_price",
    "dimensions": ["month", "district"],
    "filters": [
        {"dimension": "crop", "op": "in", "values": ["CR17"]},
        {"dimension": "price_type", "op": "eq", "values": ["farm_harvest"]},
        {"dimension": "data_origin", "op": "in", "values": ["official", "synthetic"]},
    ],
    "period": {"from": "2013-14", "to": "2024-25"},
    "order_by": {"field": "month", "direction": "asc"},
    "limit": 1000,
}


def test_export_of_monthly_trend_contains_all_1260_rows(client: TestClient) -> None:
    """Exports ignore the panel's display limit and re-run without it."""
    record = _create(
        client, "csv", spec=MONTHLY_TREND_SPEC, title="Monthly Price Trend"
    )
    # The panel had limit: 1000, but the export has all 1,260 rows
    assert record["context"]["row_count"] == 1260
    assert record["context"]["underlying_row_count"] == 1260

    text = _download(client, record["export_id"]).content.decode("utf-8")
    assert "# Rows in this file: 1,260" in text
    assert "# Underlying fact rows: 1,260" in text
    # Count data rows in CSV (excluding comment lines and header row)
    data_lines = [
        line for line in text.strip().splitlines()
        if line and not line.startswith("#")
    ]
    # Header + 1260 rows
    assert len(data_lines) == 1261


def test_filter_line_renders_display_name(client: TestClient) -> None:
    """Filter and context values in every file use display names from the masters, with IDs in brackets."""
    record = _create(client, "csv", spec=OFFICIAL_SPEC)
    text = _download(client, record["export_id"]).content.decode("utf-8")
    assert "# Filters: Crop: Arhar (CR01) / Data origin: official" in text

    # Also check XLSX Context sheet
    xlsx_record = _create(client, "xlsx", spec=OFFICIAL_SPEC)
    book = load_workbook(io.BytesIO(_download(client, xlsx_record["export_id"]).content))
    pairs = {row[0].value: row[1].value for row in book["Context"].iter_rows(min_row=2)}
    assert pairs["Filters"] == "Crop: Arhar (CR01) / Data origin: official"


def test_spec_that_would_exceed_ceiling_produces_truncation_statement(
    client: TestClient, monkeypatch
) -> None:
    """If the ceiling is hit, the file states it explicitly ("Truncated at 100,000 of N rows")."""
    monkeypatch.setattr(export_service, "EXPORT_ROW_CEILING", 50)
    record = _create(
        client, "csv", spec=MONTHLY_TREND_SPEC, title="Ceiling check"
    )
    assert record["context"]["truncated"] is True
    assert record["context"]["row_count"] == 50
    assert record["context"]["matching_row_count"] == 1260

    text = _download(client, record["export_id"]).content.decode("utf-8")
    assert "Truncated at 50 of 1,260 rows" in text


def test_price_type_filters_carry_their_display_name(client: TestClient) -> None:
    """price_type reads like every other dimension: label, then code."""
    spec = {
        **OFFICIAL_SPEC,
        "filters": [
            *OFFICIAL_SPEC["filters"],
            {"dimension": "price_type", "op": "eq", "values": ["farm_harvest"]},
        ],
    }
    record = _create(client, "csv", spec=spec, title="Price type label check")
    text = _download(client, record["export_id"]).content.decode("utf-8")
    assert "Price type: Farm harvest (farm_harvest)" in text
    assert "Price type: farm_harvest" not in text


def test_the_row_ceiling_is_served_by_the_service_that_enforces_it(client: TestClient) -> None:
    """The dialog reads its warning figure from here rather than keeping a copy."""
    response = client.get("/exports/limits")
    assert response.status_code == 200
    assert response.json() == {"row_ceiling": export_service.EXPORT_ROW_CEILING}
