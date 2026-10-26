"""Structure template catalog, enclosure profiles and launcher routing."""

from __future__ import annotations

import pytest

ROUTES = [
    pytest.param(("structure", "templates"), "core", id="structure-templates"),
    pytest.param(("structure", "library"), "core", id="structure-library"),
    pytest.param(("enclosure", "profiles"), "core", id="enclosure-profiles"),
    pytest.param(("enclosure", "plan"), "core", id="enclosure-plan"),
    pytest.param(("structure", "template"), "cad", id="structure-template"),
    pytest.param(("structure", "solid"), "cad", id="structure-solid"),
    pytest.param(("structure", "freeform", "plan"), "core", id="freeform-plan"),
    pytest.param(("structure", "freeform", "build"), "cad", id="freeform-build"),
    pytest.param(("enclosure", "build"), "cad", id="enclosure-build"),
]


def test_structure_templates(run_zw, expected: dict) -> None:
    case = expected["structureTemplates"]
    data = run_zw("structure", "templates").assert_ok(read_only=True)
    templates = {item.get("id"): item for item in data.get("templates") or []}
    assert data.get("count") == len(case["packaged"]) + len(case["designSpec"])
    for identifier in case["packaged"]:
        assert templates.get(identifier, {}).get("source") == "packaged", identifier
    for identifier in case["designSpec"]:
        assert templates.get(identifier, {}).get("source") == "design-spec", identifier
    defaults = {
        item.get("name"): item.get("default")
        for item in templates.get("box", {}).get("parameters") or []
    }
    assert defaults == case["boxDefaults"]


def test_enclosure_profiles(run_zw, expected: dict) -> None:
    case = expected["enclosureProfiles"]
    data = run_zw("enclosure", "profiles").assert_ok(read_only=True)
    by_id = {item.get("profileId"): item for item in data.get("profiles") or []}
    assert case["trusted"] in by_id
    package = by_id.get(case["packageProfile"])
    assert package is not None, f"missing package profile {case['packageProfile']}"
    assert package.get("source") == "package-mechanical"
    assert package.get("componentId") == case["packageComponent"]


@pytest.mark.parametrize(("args", "expected_group"), ROUTES)
def test_launcher_selects_requirements_group(
    launcher_route, args: tuple[str, ...], expected_group: str
) -> None:
    assert launcher_route(*args) == expected_group
