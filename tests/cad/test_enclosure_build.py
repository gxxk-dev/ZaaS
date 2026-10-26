"""Enclosure CAD build contracts; run with the cad marker."""

from __future__ import annotations

import json

import pytest

pytestmark = [
    pytest.mark.cad,
    pytest.mark.usefixtures("require_cad"),
]


@pytest.fixture(scope="module")
def enclosure_build(require_cad, run_zw, expected: dict, tmp_path_factory):
    root = tmp_path_factory.mktemp("enclosure-build")
    request = root / "box.json"
    request.write_text(
        json.dumps(expected["enclosure"]["boxRequest"], ensure_ascii=False),
        encoding="utf-8",
    )
    out = root / "out"
    data = run_zw(
        "enclosure",
        "build",
        "--request",
        str(request),
        "--out",
        str(out),
        timeout=600,
    ).assert_ok(read_only=False)
    return root, request, out, data


def test_enclosure_build_writes_expected_artifacts(
    enclosure_build, expected: dict
) -> None:
    _root, _request, out, data = enclosure_build
    case = expected["enclosure"]
    for name in case["cadBuildFiles"]:
        assert (out / name).is_file(), name
    assert (data.get("validation") or {}).get("ok")


def test_enclosure_rebuild_from_spec_matches_digest(
    enclosure_build, run_zw, tmp_path
) -> None:
    _root, _request, out, data = enclosure_build
    first_sha = data.get("specSha256")
    rebuild = run_zw(
        "enclosure",
        "build",
        "--spec",
        str(out / "spec.json"),
        "--out",
        str(tmp_path / "cad-out-2"),
        timeout=600,
    ).assert_ok(read_only=False)
    assert rebuild.get("specSha256") == first_sha


def test_enclosure_build_rejects_nonempty_out(
    run_zw, expected: dict, write_json, tmp_path
) -> None:
    case = expected["enclosure"]
    request = write_json("box.json", case["boxRequest"])
    out = tmp_path / "nonempty"
    out.mkdir()
    (out / "keep.txt").write_text("keep", encoding="utf-8")
    run_zw(
        "enclosure",
        "build",
        "--request",
        str(request),
        "--out",
        str(out),
        timeout=600,
    ).assert_error(6, "OUT_NOT_EMPTY")
    assert (out / "keep.txt").is_file()
