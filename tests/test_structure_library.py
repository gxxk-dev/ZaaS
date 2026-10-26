"""Legacy structure-cad library contracts."""

from __future__ import annotations


def test_library_lists_legacy_profiles(run_zw, expected: dict) -> None:
    case = expected["legacyLibrary"]
    result = run_zw("structure", "library")
    data = result.assert_ok(read_only=True)
    profiles = data.get("profiles") or []
    assert profiles
    assert data.get("count") == len(profiles)
    assert data.get("source") == "legacy-hardware-library"
    required = {
        "id",
        "name",
        "category",
        "roles",
        "dimensions_mm",
        "thumbnail_url",
        "source_status",
        "integration_status",
    }
    assert required <= set(profiles[0]), sorted(set(profiles[0]))
    assert any(
        "enclosure profiles" in warning
        for warning in result.payload.get("warnings") or []
    )


def test_library_filters_by_category(run_zw, expected: dict) -> None:
    case = expected["legacyLibrary"]
    data = run_zw(
        "structure", "library", "--category", case["category"]
    ).assert_ok(read_only=True)
    rows = data.get("profiles") or []
    assert rows
    assert all(item.get("category") == case["category"] for item in rows)


def test_library_filters_by_query(run_zw, expected: dict) -> None:
    case = expected["legacyLibrary"]
    data = run_zw(
        "structure", "library", "--query", case["query"]
    ).assert_ok(read_only=True)
    rows = data.get("profiles") or []
    needle = case["query"].lower()
    assert rows
    for item in rows:
        assert (
            needle in item["id"].lower() or needle in item["name"].lower()
        ), item


def test_library_gets_profile(run_zw, expected: dict) -> None:
    case = expected["legacyLibrary"]
    data = run_zw(
        "structure", "library", case["profile"]
    ).assert_ok(read_only=True)
    profile = data.get("profile") or {}
    assert profile.get("id") == case["profile"]
    assert (data.get("library") or {}).get("units") == "mm"
    assert isinstance(profile.get("dimensions_mm"), dict)


def test_library_rejects_profile_with_filter(run_zw, expected: dict) -> None:
    case = expected["legacyLibrary"]
    run_zw(
        "structure", "library", case["profile"], "--category", "sensor"
    ).assert_error(2, "REQUEST_INVALID")


def test_library_reports_missing_profile(run_zw, expected: dict) -> None:
    case = expected["legacyLibrary"]
    run_zw("structure", "library", case["missing"]).assert_error(
        3, "PROFILE_NOT_FOUND"
    )


def test_library_empty_filter_warns(run_zw) -> None:
    result = run_zw("structure", "library", "--category", "no_such_category")
    data = result.assert_ok(read_only=True)
    assert data.get("count") == 0
    assert result.payload.get("warnings")
