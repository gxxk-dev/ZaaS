"""MicroPython source checks; never executes the program."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from . import env
from .envelope import CommandResult, ZwError


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
