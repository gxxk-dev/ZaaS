"""Freeform CAD build contracts; run with the cad marker."""

from __future__ import annotations

import json

import pytest

from tests.helpers import canonical_sha256

pytestmark = [
    pytest.mark.cad,
    pytest.mark.usefixtures("require_cad"),
]


@pytest.fixture(scope="module")
def request_build(require_cad, run_zw, expected: dict, tmp_path_factory):
    root = tmp_path_factory.mktemp("freeform-request")
    request = root / "request.json"
    request.write_text(
        json.dumps(expected["freeform"]["request"], ensure_ascii=False),
        encoding="utf-8",
    )
    out = root / "out"
    result = run_zw(
        "structure",
        "freeform",
        "build",
        "--request",
        str(request),
        "--out",
        str(out),
        timeout=600,
    )
    data = result.assert_ok(read_only=False)
    spec_doc = json.loads((out / "spec.json").read_text(encoding="utf-8"))
    writes = result.payload.get("writes") or []
    return root, request, out, data, spec_doc, canonical_sha256(spec_doc), writes


@pytest.fixture(scope="module")
def text_build(require_cad, run_zw, expected: dict, tmp_path_factory):
    root = tmp_path_factory.mktemp("freeform-text")
    request = root / "text.json"
    request.write_text(
        json.dumps(expected["freeform"]["textRequest"], ensure_ascii=False),
        encoding="utf-8",
    )
    out = root / "out"
    data = run_zw(
        "structure",
        "freeform",
        "build",
        "--request",
        str(request),
        "--out",
        str(out),
        timeout=600,
    ).assert_ok(read_only=False)
    spec_doc = json.loads((out / "spec.json").read_text(encoding="utf-8"))
    return root, request, out, data, spec_doc, canonical_sha256(spec_doc)


def test_freeform_build_writes_expected_artifacts(
    request_build, expected: dict
) -> None:
    _root, _request, out, data, spec_doc, digest, writes = request_build
    case = expected["freeform"]
    missing = [name for name in case["cadBuildFiles"] if not (out / name).is_file()]
    assert not missing, missing
    reported = data.get("files") or []
    for name in ("manifest.json", "spec.json", "request.json"):
        assert name in reported, name
    assert len(writes) == len(reported)
    assert data.get("design_id") == case["request"]["design_id"]
    assert data.get("template") == "freeform_structure"
    assert spec_doc.get("schema") == "zw.freeform-spec/v1"
    assert spec_doc.get("textOperations") == []
    spec = spec_doc.get("spec") or {}
    assert spec.get("template") == "freeform_structure"
    assert spec.get("template_revision") == "freeform-structure.v1"
    assert data.get("specSha256") == digest
    assert (data.get("manifest") or {}).get("spec_sha256") == digest
    request_doc = json.loads((out / "request.json").read_text(encoding="utf-8"))
    assert request_doc.get("design_id") == case["request"]["design_id"]


def test_freeform_rebuild_from_spec_matches_digest(
    request_build, run_zw, tmp_path
) -> None:
    _root, _request, out, _data, _spec_doc, digest, _writes = request_build
    second = tmp_path / "cad-rebuild"
    rebuild = run_zw(
        "structure",
        "freeform",
        "build",
        "--spec",
        str(out / "spec.json"),
        "--out",
        str(second),
        timeout=600,
    ).assert_ok(read_only=False)
    assert rebuild.get("specSha256") == digest
    assert not (second / "request.json").exists()
    assert (rebuild.get("validation") or {}).get("ok")


def test_freeform_text_build_writes_text_operations(
    text_build, expected: dict
) -> None:
    _root, _request, out, data, spec_doc, digest = text_build
    case = expected["freeform"]
    missing = [name for name in case["cadBuildFiles"] if not (out / name).is_file()]
    assert not missing, missing
    assert (data.get("validation") or {}).get("ok")
    parts = (data.get("geometrySummary") or {}).get("parts") or []
    assert len(parts) == 1
    assert parts[0].get("solid_count") == 1
    volume = float(parts[0].get("volume_mm3") or 0)
    assert 0 < case["textBaseVolume"] - volume < 100
    assert len(spec_doc.get("textOperations") or []) == 1
    assert data.get("specSha256") == digest
    request_doc = json.loads((out / "request.json").read_text(encoding="utf-8"))
    text_rows = [
        item
        for item in request_doc.get("operations") or []
        if item.get("shape") == "text"
    ]
    assert len(text_rows) == 1
    assert text_rows[0].get("text") == "掌问"


def test_freeform_text_rebuild_matches_volume(
    text_build, run_zw, tmp_path
) -> None:
    _root, _request, out, data, _spec_doc, digest = text_build
    parts = (data.get("geometrySummary") or {}).get("parts") or []
    volume = float(parts[0].get("volume_mm3") or 0)
    rebuild = run_zw(
        "structure",
        "freeform",
        "build",
        "--spec",
        str(out / "spec.json"),
        "--out",
        str(tmp_path / "text-rebuild"),
        timeout=600,
    ).assert_ok(read_only=False)
    assert rebuild.get("specSha256") == digest
    rebuilt_parts = (rebuild.get("geometrySummary") or {}).get("parts") or []
    rebuilt_volume = float(rebuilt_parts[0].get("volume_mm3") or 0)
    assert abs(rebuilt_volume - volume) <= 1e-6


def test_freeform_text_no_effect(
    run_zw, expected: dict, write_json, tmp_path
) -> None:
    case = expected["freeform"]
    off_body = write_json("text-off.json", case["textNoEffectRequest"])
    run_zw(
        "structure",
        "freeform",
        "build",
        "--request",
        str(off_body),
        "--out",
        str(tmp_path / "text-off-out"),
        timeout=600,
    ).assert_error(4, "TEXT_NO_EFFECT")


def test_freeform_build_rejects_nonempty_out(
    run_zw, expected: dict, write_json, tmp_path
) -> None:
    case = expected["freeform"]
    request = write_json("request.json", case["request"])
    out = tmp_path / "nonempty"
    out.mkdir()
    (out / "keep.txt").write_text("keep", encoding="utf-8")
    run_zw(
        "structure",
        "freeform",
        "build",
        "--request",
        str(request),
        "--out",
        str(out),
        timeout=600,
    ).assert_error(6, "OUT_NOT_EMPTY")
    assert (out / "keep.txt").is_file()
