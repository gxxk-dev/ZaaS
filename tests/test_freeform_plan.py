"""Freeform plan contracts; CAD builds live under tests/cad."""

from __future__ import annotations

import json

import pytest

from tests.helpers import load_expected

NEGATIVE_IDS = tuple(sorted(load_expected()["freeform"]["negatives"]))


def test_freeform_plan_builds_deterministic_spec(
    run_zw, expected: dict, write_json
) -> None:
    case = expected["freeform"]
    request = write_json("request.json", case["request"])
    data = run_zw(
        "structure", "freeform", "plan", "--request", str(request)
    ).assert_ok(read_only=True)
    assert data.get("design_id") == case["request"]["design_id"]
    assert data.get("template") == "freeform_structure"
    assert data.get("template_revision") == "freeform-structure.v1"
    primitives = (
        (data.get("spec") or {}).get("freeform_geometry", {}).get("primitives")
        or []
    )
    assert len(primitives) == len(case["request"]["operations"])
    assert (data.get("validation") or {}).get("ok")
    again = run_zw(
        "structure", "freeform", "plan", "--request", str(request)
    ).assert_ok(read_only=True)
    assert json.dumps(data.get("spec"), sort_keys=True) == json.dumps(
        again.get("spec"), sort_keys=True
    )


@pytest.mark.parametrize("case_id", NEGATIVE_IDS)
def test_freeform_plan_rejects_invalid_request(
    run_zw, expected: dict, write_json, case_id: str
) -> None:
    body = expected["freeform"]["negatives"][case_id]
    path = write_json(f"{case_id}.json", body)
    run_zw(
        "structure", "freeform", "plan", "--request", str(path)
    ).assert_error(2, "REQUEST_INVALID")


def test_freeform_text_plan(run_zw, expected: dict, write_json) -> None:
    case = expected["freeform"]
    text_request = write_json("text.json", case["textRequest"])
    data = run_zw(
        "structure", "freeform", "plan", "--request", str(text_request)
    ).assert_ok(read_only=True)
    operations = data.get("textOperations") or []
    assert len(operations) == 1
    operation = operations[0]
    assert operation.get("text") == "掌问"
    assert operation.get("operation") == "cut"
    assert operation.get("fontSize") == 6
    primitives = (
        (data.get("spec") or {}).get("freeform_geometry", {}).get("primitives")
        or []
    )
    assert len(primitives) == 1


def test_freeform_text_rejects_missing_glyph(
    run_zw, expected: dict, write_json
) -> None:
    glyph = write_json("bad-glyph.json", expected["freeform"]["badGlyphRequest"])
    run_zw(
        "structure", "freeform", "plan", "--request", str(glyph)
    ).assert_error(4, "TEXT_INVALID")


def test_freeform_build_requires_request_or_spec(run_zw, tmp_path) -> None:
    out = tmp_path / "no-mode"
    run_zw(
        "structure", "freeform", "build", "--out", str(out)
    ).assert_error(2, "REQUEST_INVALID")
    assert not out.exists()
