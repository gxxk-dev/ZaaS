"""Status and board catalog contracts."""

from __future__ import annotations

import json

from tests.helpers import ZwResult


def test_status_reports_expected_catalog(
    status_result: ZwResult, expected: dict, zw_home
) -> None:
    data = status_result.assert_ok(read_only=True)
    assert len(data.get("boards", [])) == expected["boards"]
    for key in ("laser", "cad"):
        actual = data.get("templates", {}).get(key, [])
        ids = {item.get("id") if isinstance(item, dict) else item for item in actual}
        missing = set(expected[f"{key}Templates"]) - ids
        assert not missing, f"{key} templates missing: {sorted(missing)}"
    version_path = zw_home / "version.json"
    if version_path.is_file():
        expected_version = json.loads(
            version_path.read_text(encoding="utf-8")
        ).get("version")
        assert data.get("zhangwenVersion") == expected_version


def test_boards_lists_expected_controllers(
    run_zw, expected: dict
) -> None:
    data = run_zw("boards").assert_ok(read_only=True)
    assert len(data.get("boards", [])) == expected["boards"]
