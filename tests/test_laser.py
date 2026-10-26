"""Laser template, text and rounded-box contracts."""

from __future__ import annotations

import json


def test_laser_build_plate(run_zw, expected: dict, tmp_path) -> None:
    case = expected["laserPlate"]
    out = tmp_path / "laser"
    data = run_zw(
        "laser",
        "build",
        "--template",
        case["template"],
        "--params",
        json.dumps(case["params"]),
        "--out",
        str(out),
    ).assert_ok(read_only=False)
    drawing = data.get("drawing") or {}
    for key, value in case["drawing"].items():
        assert abs(float(drawing.get(key, -1)) - value) <= 1e-6, (key, drawing)
    for name in case["files"]:
        assert (out / name).is_file(), name


def test_laser_build_rejects_unknown_param(run_zw, tmp_path) -> None:
    out = tmp_path / "laser-bad"
    run_zw(
        "laser",
        "build",
        "--template",
        "plate",
        "--params",
        '{"not_a_param":1}',
        "--out",
        str(out),
    ).assert_error(2, "PARAM_UNKNOWN")
    assert not out.exists()


def test_laser_text_preview_is_read_only(run_zw, expected: dict) -> None:
    case = expected["laserText"]
    data = run_zw("laser", "text", "--text", case["text"]).assert_ok(
        read_only=True
    )
    assert float(data.get("textWidth") or 0) > 0
    assert (data.get("drawing") or {}).get("shapes") == 1


def test_laser_text_writes_files(run_zw, expected: dict, tmp_path) -> None:
    case = expected["laserText"]
    out = tmp_path / "laser-text"
    run_zw(
        "laser",
        "text",
        "--text",
        case["text"],
        "--out",
        str(out),
    ).assert_ok(read_only=False)
    for name in case["files"]:
        assert (out / name).is_file(), name
    design = json.loads((out / "design.json").read_text(encoding="utf-8"))
    assert design.get("template") == "text"
    assert design["params"].get("size") == case["size"]


def test_laser_text_rejects_empty_text(run_zw) -> None:
    run_zw("laser", "text", "--text", "").assert_error(4, "TEXT_INVALID")


def test_laser_rounded_box_pattern_versions(
    run_zw, expected: dict, tmp_path
) -> None:
    case = expected["laserRounded"]
    outputs = {}
    for version in (1, 2):
        out = tmp_path / f"rounded-v{version}"
        params = {**case["params"], "pattern_version": version}
        run_zw(
            "laser",
            "build",
            "--template",
            "rounded-box",
            "--params",
            json.dumps(params),
            "--out",
            str(out),
        ).assert_ok(read_only=False)
        outputs[version] = out
    design = json.loads(
        (outputs[1] / "design.json").read_text(encoding="utf-8")
    )
    assert design["params"].get("pattern_version") == 1
    assert (outputs[1] / "cut.svg").read_bytes() != (
        outputs[2] / "cut.svg"
    ).read_bytes()


def test_laser_templates(run_zw, expected: dict) -> None:
    data = run_zw("laser", "templates").assert_ok(read_only=True)
    templates = {item.get("id"): item for item in data.get("templates") or []}
    assert data.get("count") == 5
    assert set(expected["laserTemplates"]) <= set(templates)
    rounded = templates.get("rounded-box", {})
    assert rounded.get("patternVersions") == [1, 2]
    assert any(
        item.get("name") == "pattern_version"
        for item in rounded.get("parameters") or []
    )
