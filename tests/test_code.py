"""MicroPython check and deterministic repair contracts."""

from __future__ import annotations


def test_code_check_reports_k10_screen(run_zw, expected: dict, write_text) -> None:
    case = expected["k10BadCode"]
    bad = write_text("bad.py", case["source"])
    result = run_zw("code", "check", "--board", "k10", "--file", str(bad))
    result.assert_exit(case["exit"])
    assert result.payload.get("ok") is True
    assert result.payload.get("readOnly") is True
    assert not result.payload.get("writes")
    codes = {item.get("code") for item in result.data.get("diagnostics", [])}
    assert case["diagnostic"] in codes, codes


def test_code_fix_previews_k10_screen(run_zw, expected: dict, write_text) -> None:
    case = expected["k10BadCode"]
    source = write_text("fix.py", case["source"])
    data = run_zw(
        "code", "fix", "--board", "k10", "--file", str(source)
    ).assert_ok(read_only=True)
    applied = [item.get("repair") for item in data.get("applied") or []]
    assert data.get("changed") is True
    assert "k10-screen" in applied
    assert "screen.text(" not in (data.get("after") or "")
    assert data.get("diff")


def test_code_fix_maps_mpython_pins(run_zw, expected: dict, write_text) -> None:
    source = write_text("pins.py", expected["codeFix"]["mpythonSource"])
    data = run_zw(
        "code", "fix", "--board", "mpython", "--file", str(source)
    ).assert_ok(read_only=True)
    applied = [item.get("repair") for item in data.get("applied") or []]
    assert "mpython-pins" in applied
    assert "Pin(33)" in (data.get("after") or "")


def test_code_fix_refuses_ambiguous_text_args(
    run_zw, expected: dict, write_text
) -> None:
    source = write_text("refusal.py", expected["codeFix"]["badArgsSource"])
    data = run_zw(
        "code", "fix", "--board", "k10", "--file", str(source)
    ).assert_ok(read_only=True)
    assert not data.get("changed")
    assert data.get("skipped") == [
        {
            "repair": "k10-screen",
            "reason": (
                "此处文字参数无法可靠转换，请按官方draw_text关键字参数手动修改；"
                "原代码保留。"
            ),
        }
    ]
    assert any(
        item.get("repair") == "k10-screen"
        for item in data.get("remaining") or []
    )


def test_code_fix_writes_new_out(
    run_zw, expected: dict, write_text, tmp_path
) -> None:
    source = write_text("fix.py", expected["k10BadCode"]["source"])
    out_file = tmp_path / "fixed.py"
    result = run_zw(
        "code",
        "fix",
        "--board",
        "k10",
        "--file",
        str(source),
        "--out",
        str(out_file),
    )
    data = result.assert_ok(read_only=False)
    assert str(out_file) in (result.payload.get("writes") or [])
    assert out_file.read_text(encoding="utf-8") == data.get("after")


def test_code_fix_rejects_existing_out(
    run_zw, expected: dict, write_text, tmp_path
) -> None:
    source = write_text("fix.py", expected["k10BadCode"]["source"])
    out_file = write_text("fixed.py", "keep me")
    before = out_file.read_text(encoding="utf-8")
    run_zw(
        "code",
        "fix",
        "--board",
        "k10",
        "--file",
        str(source),
        "--out",
        str(out_file),
    ).assert_error(6, "OUT_EXISTS")
    assert out_file.read_text(encoding="utf-8") == before


def test_code_fix_rejects_invalid_syntax(
    run_zw, expected: dict, write_text
) -> None:
    source = write_text("syntax.py", expected["codeFix"]["syntaxSource"])
    run_zw(
        "code", "fix", "--board", "k10", "--file", str(source)
    ).assert_error(4, "CODE_INVALID")
