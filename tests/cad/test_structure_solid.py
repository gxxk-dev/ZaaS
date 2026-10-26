"""Structure solid CAD contracts; run with the cad marker."""

from __future__ import annotations

import json

import pytest

pytestmark = [
    pytest.mark.cad,
    pytest.mark.usefixtures("require_cad"),
]


def test_structure_solid_builds_box(
    run_zw, expected: dict, tmp_path
) -> None:
    case = expected["designSpecBox"]
    out = tmp_path / "solid-box"
    data = run_zw(
        "structure",
        "solid",
        "--template",
        "box",
        "--params",
        json.dumps(case["params"]),
        "--out",
        str(out),
        timeout=600,
    ).assert_ok(read_only=False)
    assert data.get("template") == "box"
    assert data.get("title") == case["title"]
    missing = [name for name in case["files"] if not (out / name).is_file()]
    assert not missing, missing
    design = json.loads((out / "design-spec.json").read_text(encoding="utf-8"))
    assert design.get("spec", {}).get("title") == case["title"]


def test_structure_solid_rejects_unknown_template(run_zw, tmp_path) -> None:
    run_zw(
        "structure",
        "solid",
        "--template",
        "nope",
        "--params",
        "{}",
        "--out",
        str(tmp_path / "solid-nope"),
    ).assert_error(3, "TEMPLATE_NOT_FOUND")


def test_structure_solid_rejects_invalid_params(run_zw, tmp_path) -> None:
    run_zw(
        "structure",
        "solid",
        "--template",
        "box",
        "--params",
        '{"thickness":0}',
        "--out",
        str(tmp_path / "solid-zero"),
    ).assert_error(4, "PARAM_INVALID")
