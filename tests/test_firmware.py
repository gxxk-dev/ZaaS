"""Firmware metadata and local image verification contracts."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def firmware_rows(run_zw) -> dict:
    data = run_zw("firmware", "list").assert_ok(read_only=True)
    return {item.get("boardId"): item for item in data.get("firmware") or []}


def test_firmware_list_reports_pinned_board(
    run_zw, expected: dict, firmware_rows: dict
) -> None:
    case = expected["firmware"]
    data = run_zw("firmware", "list").assert_ok(read_only=True)
    assert data.get("count") == expected["boards"]
    assert case["boardId"] in firmware_rows
    assert firmware_rows[case["boardId"]].get("chip") is not None


def test_firmware_get_reports_profile(run_zw, expected: dict) -> None:
    case = expected["firmware"]
    data = run_zw("firmware", "get", case["board"]).assert_ok(read_only=True)
    assert (data.get("profile") or {}).get("boardId") == case["boardId"]


def test_firmware_verify_matches_pinned_image(
    run_zw, expected: dict, firmware_rows: dict
) -> None:
    case = expected["firmware"]
    local_path = firmware_rows[case["boardId"]].get("localPath")
    if not local_path:
        pytest.skip("local firmware image missing")
    data = run_zw(
        "firmware", "verify", case["board"], "--file", local_path
    ).assert_ok(read_only=True)
    assert data.get("matched") is True


def test_firmware_verify_rejects_mismatch(
    run_zw, expected: dict, write_text
) -> None:
    case = expected["firmware"]
    bad = write_text("bad.bin", "not-the-pinned-image")
    result = run_zw("firmware", "verify", case["board"], "--file", str(bad))
    result.assert_error(4, "FIRMWARE_MISMATCH")
    assert not result.payload.get("writes")


def test_firmware_verify_rejects_symlink(
    run_zw, expected: dict, firmware_rows: dict, write_text, tmp_path: Path
) -> None:
    case = expected["firmware"]
    local_path = firmware_rows[case["boardId"]].get("localPath")
    target = Path(local_path) if local_path else write_text(
        "bad.bin", "not-the-pinned-image"
    )
    link = tmp_path / "link.bin"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable")
    run_zw(
        "firmware", "verify", case["board"], "--file", str(link)
    ).assert_error(4, "FILE_INVALID")
