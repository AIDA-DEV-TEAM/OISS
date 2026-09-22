"""One test per validation rule, each calling the rule directly."""
from __future__ import annotations

import pandas as pd
import pytest

from app.validation import rules as R
from app.validation.rules import Finding, RuleContext

CTX = RuleContext("unit_test", ("district",))


def codes(findings: list[Finding]) -> list[str]:
    return [finding.rule_code for finding in findings]


def test_unknown_district_flags_only_unresolvable_names() -> None:
    frame = pd.DataFrame({"district": ["Angul", "ANUGUL", "Atlantis"]})
    findings = R.check_unknown_district(frame, "district", CTX)
    assert codes(findings) == ["UNKNOWN_DISTRICT"]
    assert findings[0].severity == "error"
    assert findings[0].observed_value == "Atlantis"


def test_unknown_crop_accepts_every_published_spelling() -> None:
    frame = pd.DataFrame({"crop": ["Biri", "BLACKGRAM", "Grountnut", "Dragonfruit"]})
    findings = R.check_unknown_crop(frame, "crop", CTX)
    assert codes(findings) == ["UNKNOWN_CROP"]
    assert findings[0].observed_value == "Dragonfruit"


def test_type_mismatch_flags_text_but_not_blanks() -> None:
    frame = pd.DataFrame({"value": ["1.5", "", None, "NA", "-", "2,300"]})
    findings = R.check_type_mismatch(frame, ["value"], CTX)
    assert codes(findings) == ["TYPE_MISMATCH", "TYPE_MISMATCH"]
    assert {f.observed_value for f in findings} == {"NA", "-"}


def test_schema_mismatch_reports_missing_and_extra_columns() -> None:
    frame = pd.DataFrame(columns=["a", "c"])
    findings = R.check_schema(frame, ["a", "b"], CTX)
    assert codes(findings) == ["SCHEMA_MISMATCH", "SCHEMA_MISMATCH"]
    assert {f.column_name for f in findings} == {"b", "c"}


def test_schema_match_is_silent() -> None:
    frame = pd.DataFrame(columns=["a", "b"])
    assert R.check_schema(frame, ["a", "b"], CTX) == []


def test_duplicate_key_flags_the_second_occurrence() -> None:
    frame = pd.DataFrame({"a": [1, 1, 2], "b": ["x", "x", "x"]})
    findings = R.check_duplicate_key(frame, ["a", "b"], CTX)
    assert codes(findings) == ["DUPLICATE_KEY"]
    assert findings[0].row_ref.startswith("row=1")


@pytest.mark.parametrize(
    "value, kind, expected",
    [
        (-1.0, "yield", ["OUT_OF_RANGE"]),
        (0.0, "yield", ["OUT_OF_RANGE"]),
        (1_500.0, "yield", ["OUT_OF_RANGE"]),
        (45.0, "yield", []),
        (60_000.0, "price", ["OUT_OF_RANGE"]),
        (2_400.0, "price", []),
    ],
)
def test_out_of_range_bounds(value: float, kind: str, expected: list[str]) -> None:
    frame = pd.DataFrame({"v": [value]})
    findings = R.check_out_of_range(frame, "v", kind, CTX)
    assert codes(findings) == expected
    assert all(f.severity == "warning" for f in findings)


def test_missing_value_flags_nulls_in_a_measure_column() -> None:
    frame = pd.DataFrame({"v": [1.0, None, 3.0]})
    findings = R.check_missing_value(frame, ["v"], CTX)
    assert codes(findings) == ["MISSING_VALUE"]
    assert findings[0].severity == "warning"


def test_total_row_in_detail_flags_state_labels() -> None:
    frame = pd.DataFrame({"district": ["Angul", "ORISSA  STATE", "STATE"]})
    findings = R.check_total_row_in_detail(frame, "district", CTX)
    assert codes(findings) == ["TOTAL_ROW_IN_DETAIL", "TOTAL_ROW_IN_DETAIL"]


def test_identity_mismatch_uses_a_two_percent_tolerance() -> None:
    frame = pd.DataFrame(
        {
            "area": [100.0, 100.0, 100.0],
            "rate": [10.0, 10.0, 10.0],
            # exact, 1% off (passes), 10% off (flagged)
            "production": [1_000.0, 1_010.0, 1_110.0],
        }
    )
    findings = R.check_identity(frame, "area", "rate", "production", CTX)
    assert codes(findings) == ["IDENTITY_MISMATCH"]
    assert findings[0].row_ref.startswith("row=2")


def test_cross_source_mismatch_compares_two_sources() -> None:
    left = pd.DataFrame({"k": ["a", "b"], "v": [100.0, 100.0]})
    right = pd.DataFrame({"k": ["a", "b"], "v": [100.5, 130.0]})
    findings = R.check_cross_source_mismatch(left, right, ["k"], "v", CTX)
    assert codes(findings) == ["CROSS_SOURCE_MISMATCH"]
    assert findings[0].severity == "info"


def test_msp_substituted_marks_provisional_paddy_prices() -> None:
    frame = pd.DataFrame(
        {"cell_status": ["ok", "provisional"], "commodity": ["Wheat", "Paddy"]}
    )
    findings = R.check_msp_substituted(frame, "cell_status", "commodity", CTX)
    assert codes(findings) == ["MSP_SUBSTITUTED"]
    assert findings[0].severity == "info"
    assert "minimum support price" in findings[0].message


def test_unknown_block_keys_on_district_and_block_together() -> None:
    # 'Nuagaon' exists in several districts, so the name alone is not a key.
    known = {"OD01|NUAGAON"}
    frame = pd.DataFrame(
        {"district": ["Angul", "Boudh"], "block": ["Nuagaon", "Nuagaon"]}
    )
    findings = R.check_unknown_block(frame, "district", "block", known, CTX)
    assert codes(findings) == ["UNKNOWN_BLOCK"]
    assert findings[0].severity == "warning"
    assert "Boudh" in findings[0].message


def test_quarantine_index_selects_only_error_rows() -> None:
    findings = [
        Finding("UNKNOWN_DISTRICT", "error", "row=3|x=1", None, "m", None),
        Finding("MISSING_VALUE", "warning", "row=4|x=1", None, "m", None),
        Finding("SCHEMA_MISMATCH", "error", "dataset=x", None, "m", None),
    ]
    assert R.quarantine_index(findings) == {3}


def test_finding_rejects_an_unknown_severity() -> None:
    with pytest.raises(ValueError):
        Finding("X", "critical", "row=0", None, "m", None)


def test_missing_value_and_structurally_absent_split_the_nulls() -> None:
    """A null in a series that exists is a gap; a null in one that never does is not."""
    frame = pd.DataFrame(
        {
            "district": ["Angul", "Angul", "Boudh"],
            "_series_key": ["ayp|OD01|CR23|Summer", "ayp|OD01|CR23|Summer", "ayp|OD11|CR23|Autumn"],
            "value": [None, 12.0, None],
        }
    )
    present = {"ayp|OD01|CR23|Summer"}

    missing = R.check_missing_value(frame, ["value"], CTX, present, "_series_key")
    absent = R.check_structurally_absent(frame, ["value"], CTX, present, "_series_key")

    assert codes(missing) == ["MISSING_VALUE"]
    assert missing[0].row_ref.startswith("row=0")
    assert missing[0].severity == "warning"

    assert codes(absent) == ["STRUCTURALLY_ABSENT"]
    assert absent[0].row_ref.startswith("row=2")
    assert absent[0].severity == "info"


def test_missing_value_is_unchanged_without_a_presence_index() -> None:
    """The rule stays independently callable with no index supplied."""
    frame = pd.DataFrame({"value": [None, 1.0, None]})
    assert codes(R.check_missing_value(frame, ["value"], CTX)) == [
        "MISSING_VALUE",
        "MISSING_VALUE",
    ]


def test_structurally_absent_needs_its_key_column() -> None:
    frame = pd.DataFrame({"value": [None]})
    assert R.check_structurally_absent(frame, ["value"], CTX, set(), "_series_key") == []
