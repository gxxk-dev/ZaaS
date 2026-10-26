"""MicroPython source checks; never executes the program."""

from __future__ import annotations

import difflib
import hashlib
import sys
from pathlib import Path

from . import env
from .envelope import CommandResult, ZwError

MAX_SOURCE_BYTES = 65536


def _read_source(value: str) -> tuple[str, str]:
    try:
        if value == "-":
            return sys.stdin.read(), "<stdin>"
        path = Path(value).expanduser()
        return path.read_text(encoding="utf-8"), str(path)
    except OSError as exc:
        raise ZwError("SOURCE_READ_FAILED", f"无法读取源码：{value}", str(exc), 7) from exc
    except UnicodeDecodeError as exc:
        raise ZwError("SOURCE_ENCODING", f"源码不是 UTF-8：{value}", str(exc), 7) from exc


def _upstream_fix():
    try:
        from zhangwen.web.programming import (
            programming_diagnostics,
            repair_k10_screen,
            repair_mpython_pins,
        )
    except ImportError as exc:
        raise ZwError(
            "DEPENDENCY_MISSING",
            f"无法导入代码修复模块：{exc}",
            "确认 ZW_HOME 完整。",
            5,
        ) from exc
    return {
        "diagnostics": programming_diagnostics,
        "repairs": {
            "k10-screen": repair_k10_screen,
            "mpython-pins": repair_mpython_pins,
        },
    }


def _compile(source: str, source_name: str) -> None:
    try:
        compile(source, source_name, "exec")
    except (SyntaxError, ValueError) as exc:
        raise ZwError(
            "CODE_INVALID",
            "源码无法编译，未做任何修复。",
            "先修复语法错误，再运行 zw code fix。",
            4,
            details={
                "source": source_name,
                "message": getattr(exc, "msg", str(exc)),
                "line": getattr(exc, "lineno", None),
                "column": getattr(exc, "offset", None),
            },
        ) from exc


def cmd_fix(board: str, *, file: str, out_value: str | None = None) -> CommandResult:
    record = env.resolve_board(board)
    source, source_name = _read_source(file)
    size = len(source.encode("utf-8"))
    if size > MAX_SOURCE_BYTES:
        raise ZwError(
            "CODE_INVALID",
            f"源码超过 {MAX_SOURCE_BYTES} 字节，不能自动修复。",
            "精简源码后重试；修复输出同样受 64 KiB 限制。",
            4,
            details={"source": source_name, "bytes": size, "limit": MAX_SOURCE_BYTES},
        )
    _compile(source, source_name)

    mods = _upstream_fix()
    initial = mods["diagnostics"](source, record["componentId"])
    current = source
    applied: list[dict] = []
    skipped: list[dict] = []
    warnings: list[str] = []
    attempted: set[str] = set()
    board_id = record["componentId"]

    for _ in range(3):
        diagnostics = mods["diagnostics"](current, board_id)
        actionable = [
            item
            for item in diagnostics
            if item.get("repair") in mods["repairs"] and item["repair"] not in attempted
        ]
        if not actionable:
            break
        progressed = False
        for item in actionable:
            key = item["repair"]
            attempted.add(key)
            try:
                repaired = mods["repairs"][key](current, board_id)
            except ValueError as exc:
                skipped.append({"repair": key, "reason": str(exc)})
                warnings.append(f"{key} 未应用：{exc}")
                continue
            if repaired == current:
                skipped.append({"repair": key, "reason": "修复未改变源码。"})
                warnings.append(f"{key} 未改变源码；保留原稿。")
                continue
            try:
                compile(repaired, source_name, "exec")
            except (SyntaxError, ValueError) as exc:
                raise ZwError(
                    "CODE_INVALID",
                    "修复结果无法编译，未写入输出。",
                    "人工核对修复结果；不要直接上板。",
                    4,
                    details={
                        "source": source_name,
                        "repair": key,
                        "applied": applied,
                        "message": getattr(exc, "msg", str(exc)),
                        "line": getattr(exc, "lineno", None),
                    },
                ) from exc
            applied.append(
                {
                    "repair": key,
                    "beforeSha256": hashlib.sha256(current.encode("utf-8")).hexdigest(),
                    "afterSha256": hashlib.sha256(repaired.encode("utf-8")).hexdigest(),
                }
            )
            current = repaired
            progressed = True
            break
        if not progressed:
            break

    remaining = mods["diagnostics"](current, board_id)
    changed = bool(applied)
    diff = "".join(
        difflib.unified_diff(
            source.splitlines(keepends=True),
            current.splitlines(keepends=True),
            fromfile=source_name,
            tofile=f"{source_name} (fixed)",
        )
    )
    if remaining:
        warnings.append(
            f"仍有 {len(remaining)} 条诊断；exit 0 只表示修复流程完成，不代表代码已通过检查或实测。"
        )
    if changed:
        warnings.append("修复是确定性预览改写，需人工复核；未执行、未上板。")

    writes: list[str] = []
    out_path = None
    if out_value:
        out_path = env.resolve_out_file(out_value)
        writes = [env.write_text_file(out_path, current)]

    data = {
        "board": {
            "componentId": record["componentId"],
            "skillName": record["skillName"],
            "displayName": record["displayName"],
        },
        "source": source_name,
        "changed": changed,
        "applied": applied,
        "skipped": skipped,
        "diff": diff,
        "after": current,
        "afterSha256": hashlib.sha256(current.encode("utf-8")).hexdigest(),
        "diagnostics": initial,
        "remaining": remaining,
    }
    if out_path is not None:
        data["out"] = str(out_path)
    return CommandResult(data=data, warnings=warnings, writes=writes)


def cmd_check(board: str, *, file: str, components: list[str]) -> CommandResult:
    record = env.resolve_board(board)
    source, source_name = _read_source(file)
    try:
        from zhangwen.web.programming import programming_diagnostics
    except ImportError as exc:
        raise ZwError(
            "DEPENDENCY_MISSING",
            f"无法导入编程检查模块：{exc}",
            "确认 ZW_HOME 完整。",
            5,
        ) from exc

    diagnostics: list[dict] = []
    syntax_ok = True
    try:
        compile(source, source_name, "exec")
    except (SyntaxError, ValueError) as exc:
        syntax_ok = False
        diagnostics.append(
            {
                "severity": "FAIL",
                "code": "syntax",
                "message": getattr(exc, "msg", str(exc)),
                "line": getattr(exc, "lineno", None),
                "column": getattr(exc, "offset", None),
            }
        )

    if syntax_ok:
        for item in programming_diagnostics(source, record["componentId"]):
            diagnostics.append(
                {
                    "severity": item.get("severity", "WARNING"),
                    "code": item.get("repair") or "programming",
                    "message": item.get("message", ""),
                    **({"line": item["line"]} if item.get("line") else {}),
                    **({"repair": item["repair"]} if item.get("repair") else {}),
                }
            )

    hardware_checks: list[dict] = []
    hardware_valid = True
    warnings: list[str] = []
    if components:
        from .hardware import _detail, _repo, _upstream

        mods = _upstream()
        requested = [record["componentId"], *components]
        seen: set[str] = set()
        entries = []
        rules = []
        for value in requested:
            package, detail = _detail(value)
            if detail.componentId in seen:
                continue
            seen.add(detail.componentId)
            entries.append(_repo().component_from_detail(detail))
            rules.extend(detail.rules)
            if detail.verificationStatus != "OFFICIAL_DOC_VERIFIED":
                warnings.append(f"{detail.skillName}: verificationStatus={detail.verificationStatus}，不能表述为已实测。")
        result = mods["validate"](entries, rules=rules) if rules else mods["validate"](entries)
        hardware_valid = (result.overall.value if hasattr(result.overall, "value") else str(result.overall)) != "FAIL"
        hardware_checks = [
            {
                "dimension": check.dimension,
                "severity": check.severity.value if hasattr(check.severity, "value") else str(check.severity),
                "message": check.message,
                "details": check.details,
            }
            for check in result.checks
        ]

    valid = syntax_ok and hardware_valid and not any(item["severity"] == "FAIL" for item in diagnostics)
    data = {
        "board": {
            "componentId": record["componentId"],
            "skillName": record["skillName"],
            "displayName": record["displayName"],
        },
        "source": source_name,
        "valid": valid,
        "checksum": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "diagnostics": diagnostics,
        "hardwareChecks": hardware_checks,
    }
    if not valid:
        warnings.append("存在 FAIL；按提示修改后重新运行 zw code check。")
    return CommandResult(data=data, warnings=warnings, exit_code=0 if valid else 4)
