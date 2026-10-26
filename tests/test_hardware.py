"""Hardware search, detail, guide and validation contracts."""

from __future__ import annotations


def test_hardware_search_prefers_board_recommendation(run_zw, expected: dict) -> None:
    case = expected["dfr0026"]
    data = run_zw(
        "hardware", "search", case["query"], "--board", case["board"]
    ).assert_ok(read_only=True)
    results = data.get("results", [])
    assert results, "hardware search returned no results"
    first = results[0]
    assert first.get("skillName") == case["recommended"], first
    assert first.get("recommended") is True, first
    assert first.get("verificationStatus") == case["verification"], first


def test_hardware_get_reports_migration_and_guides(run_zw, expected: dict) -> None:
    case = expected["dfr0026"]
    data = run_zw("hardware", "get", "hw_dfrobot_dfr0026_k10").assert_ok(
        read_only=True
    )
    assert data.get("verificationStatus") == case["verification"]
    assert len(data.get("guides", [])) == 5


def test_hardware_guide_resolves_board_pin_label(run_zw, expected: dict) -> None:
    case = expected["dfr0026"]
    data = run_zw(
        "hardware",
        "guide",
        "hw_dfrobot_dfr0026_k10",
        "--board",
        case["board"],
    ).assert_ok(read_only=True)
    wiring = next(
        (
            item
            for item in data.get("wiring", [])
            if item.get("signal") == case["wiringSignal"]
        ),
        None,
    )
    assert wiring is not None, f"missing wiring signal {case['wiringSignal']}"
    assert str(wiring.get("targetLabel", "")).startswith(case["wiringLabelPrefix"])


def test_hardware_validate_accepts_k10_with_light_sensor(run_zw) -> None:
    data = run_zw(
        "hardware",
        "validate",
        "hw_seed_unihiker_k10",
        "hw_dfrobot_dfr0026_k10",
    ).assert_ok(read_only=True)
    assert data.get("overall") != "FAIL"
