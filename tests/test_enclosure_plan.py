"""Enclosure plan contracts; CAD builds live under tests/cad."""

from __future__ import annotations

import json


def test_enclosure_plan_is_deterministic(
    run_zw, expected: dict, write_json
) -> None:
    case = expected["enclosure"]
    request = write_json("box.json", case["boxRequest"])
    data = run_zw(
        "enclosure", "plan", "--request", str(request)
    ).assert_ok(read_only=True)
    assert data.get("template") == "box_with_lid"
    assert (data.get("validation") or {}).get("ok")
    spec = data.get("spec") or {}
    assert len(spec.get("hardware") or []) == 2
    enclosure = spec.get("enclosure") or {}
    for key, minimum in (
        ("inner_length_x", 30),
        ("inner_width_y", 30),
        ("inner_height_z", 12),
    ):
        assert float(enclosure.get(key, 0)) >= minimum, (key, enclosure.get(key))
    again = run_zw(
        "enclosure", "plan", "--request", str(request)
    ).assert_ok(read_only=True)
    assert json.dumps(data.get("spec"), sort_keys=True) == json.dumps(
        again.get("spec"), sort_keys=True
    )


def test_enclosure_needs_input_questions(
    run_zw, expected: dict, write_json
) -> None:
    case = expected["enclosure"]
    needs = write_json(
        "needs.json",
        {"components": [{"component_id": case["needsInputComponent"]}]},
    )
    error = run_zw(
        "enclosure", "plan", "--request", str(needs)
    ).assert_error(4, "NEEDS_INPUT")
    questions = (error.get("details") or {}).get("questions") or []
    assert questions


def test_enclosure_rejects_mount_conflict(
    run_zw, expected: dict, write_json
) -> None:
    case = expected["enclosure"]
    conflict = write_json("k10-conflict.json", case["k10ConflictRequest"])
    run_zw(
        "enclosure", "plan", "--request", str(conflict)
    ).assert_error(4, "MOUNT_CONFLICT")


def test_enclosure_derives_k10_mount(
    run_zw, expected: dict, write_json
) -> None:
    case = expected["enclosure"]
    derived = write_json("k10-derived.json", case["k10DerivedRequest"])
    result = run_zw("enclosure", "plan", "--request", str(derived))
    data = result.assert_ok(read_only=True)
    provenance = data.get("provenance") or []
    assert provenance and provenance[0].get("source") == "derived"
    profile_ids = [
        item.get("profile_id")
        for item in (data.get("spec") or {}).get("profiles", [])
    ]
    assert any(
        str(name).startswith("unihiker_k10_derived_") for name in profile_ids
    )
    assert any(
        "派生" in item for item in result.payload.get("warnings") or []
    )


def test_enclosure_component_mount(
    run_zw, expected: dict, write_json
) -> None:
    case = expected["enclosure"]
    mount = write_json("mount.json", case["componentMountRequest"])
    data = run_zw(
        "enclosure", "plan", "--request", str(mount)
    ).assert_ok(read_only=True)
    assert data.get("template") == "component_mount"
    hardware = (data.get("layout") or {}).get("hardware") or []
    assert len(hardware) == 1
    assert hardware[0].get("surface") == "external"
    center_z = float((hardware[0].get("center") or {}).get("z", 0))
    assert abs(center_z - case["componentMountCenterZ"]) <= 1e-6
    assert (data.get("validation") or {}).get("ok")


def test_enclosure_component_mount_rejects_two_components(
    run_zw, write_json
) -> None:
    two = {
        "template": "component_mount",
        "components": [
            {"profile_id": "xiao_esp32s3"},
            {"profile_id": "grove_button"},
        ],
    }
    path = write_json("mount-two.json", two)
    run_zw(
        "enclosure", "plan", "--request", str(path)
    ).assert_error(2, "REQUEST_INVALID")


def test_enclosure_component_mount_rejects_standoffs(
    run_zw, write_json
) -> None:
    standoff = {
        "template": "component_mount",
        "components": [{"profile_id": "xiao_esp32s3"}],
        "standoffs": [
            {
                "standoff_id": "post",
                "center": {"x": 0, "y": 0},
                "outer_diameter": 5,
                "bore_diameter": 2,
                "height": 4,
            }
        ],
    }
    path = write_json("mount-standoff.json", standoff)
    run_zw(
        "enclosure", "plan", "--request", str(path)
    ).assert_error(2, "REQUEST_INVALID")


def test_enclosure_left_surface_needs_center(
    run_zw, expected: dict, write_json
) -> None:
    case = expected["enclosure"]
    left = write_json("left.json", case["leftNeedsCenterRequest"])
    error = run_zw(
        "enclosure", "plan", "--request", str(left)
    ).assert_error(4, "NEEDS_INPUT")
    questions = (error.get("details") or {}).get("questions") or []
    assert any(item.get("field") == "center" for item in questions)


def test_enclosure_rejects_invalid_spec(
    run_zw, expected: dict, write_json, tmp_path
) -> None:
    case = expected["enclosure"]
    bad_spec = write_json("bad-spec.json", case["invalidSpec"])
    bad_out = tmp_path / "bad-spec-out"
    run_zw(
        "enclosure",
        "build",
        "--spec",
        str(bad_spec),
        "--out",
        str(bad_out),
    ).assert_error(2, "SPEC_INVALID")
    assert not bad_out.exists()
