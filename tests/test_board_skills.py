"""Board Skill layout, context and guide-kind contracts."""

from __future__ import annotations

import pytest


def test_boards_full_strict_skill(run_zw, expected: dict) -> None:
    case = expected["boardSkills"]
    data = run_zw(
        "boards", "--board", case["strictBoard"], "--full"
    ).assert_ok(read_only=True)
    skill = data.get("skill") or {}
    assert skill.get("layout") == "strict"
    assert skill.get("verified") is True
    assert data.get("entry") and data["entry"].get("content")
    assert data.get("programmingContext")


def test_boards_full_inlines_file(run_zw, expected: dict) -> None:
    case = expected["boardSkills"]
    data = run_zw(
        "boards",
        "--board",
        case["strictBoard"],
        "--full",
        "--file",
        case["file"],
    ).assert_ok(read_only=True)
    file_item = data.get("file") or {}
    assert file_item.get("path") == case["file"]
    assert file_item.get("content")


def test_boards_full_legacy_skill(run_zw, expected: dict) -> None:
    case = expected["boardSkills"]
    result = run_zw("boards", "--board", case["legacyBoard"], "--full")
    data = result.assert_ok(read_only=True)
    skill = data.get("skill") or {}
    assert skill.get("layout") == "legacy"
    assert skill.get("verified") is False
    assert any("legacy" in item for item in result.payload.get("warnings") or [])


def test_boards_full_without_skill(run_zw) -> None:
    data = run_zw("boards", "--board", "mpython3", "--full").assert_ok(
        read_only=True
    )
    assert data.get("skill") is None
    assert data.get("programmingContext")


def test_boards_context_package(run_zw, expected: dict) -> None:
    case = expected["boardSkills"]
    data = run_zw(
        "boards",
        "--board",
        case["strictBoard"],
        "--context",
        case["contextQuery"],
    ).assert_ok(read_only=True)
    package = data.get("package") or {}
    assert package.get("profileId") == case["contextProfile"]
    assert data.get("references")
    assert data.get("templates")


@pytest.mark.parametrize("case_id", ["legacy-context", "full-without-board", "file-without-skill"])
def test_boards_negative(run_zw, expected: dict, case_id: str) -> None:
    case = expected["boardSkills"]
    cases = {
        "legacy-context": (
            ("boards", "--board", case["legacyBoard"], "--context", "GPIO"),
            4,
            "BOARD_SKILL_CONTEXT_UNAVAILABLE",
        ),
        "full-without-board": (
            ("boards", "--full"),
            2,
            "REQUEST_INVALID",
        ),
        "file-without-skill": (
            ("boards", "--board", "mpython3", "--full", "--file", "SKILL.md"),
            3,
            "FILE_NOT_FOUND",
        ),
    }
    args, exit_code, error_code = cases[case_id]
    run_zw(*args).assert_error(exit_code, error_code)


def test_guide_kind_positive(run_zw, expected: dict) -> None:
    case = expected["boardSkills"]
    data = run_zw(
        "hardware",
        "guide",
        case["guideId"],
        "--board",
        case["strictBoard"],
        "--kind",
        case["guideKind"],
    ).assert_ok(read_only=True)
    assert (data.get("guide") or {}).get("kind") == case["guideKind"]


def test_guide_kind_rejects_mismatch(run_zw, expected: dict) -> None:
    case = expected["boardSkills"]
    run_zw(
        "hardware",
        "guide",
        case["guideId"],
        "--board",
        case["strictBoard"],
        "--kind",
        "functional",
    ).assert_error(4, "GUIDE_KIND_MISMATCH")
