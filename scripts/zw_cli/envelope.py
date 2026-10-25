"""Uniform JSON envelope, error type and exit codes."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field

SCHEMA = "zw.cli/v1"


@dataclass
class CommandResult:
    data: dict
    warnings: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    exit_code: int = 0


class ZwError(Exception):
    """A user-facing failure with a stable code and exit status."""

    def __init__(
        self,
        code: str,
        message: str,
        hint: str = "",
        exit_code: int = 2,
        *,
        details: dict | None = None,
        writes: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.exit_code = exit_code
        self.details = details or {}
        self.writes = writes or []


def ok(
    command: str,
    data: dict,
    *,
    writes: list[str] | None = None,
    warnings: list[str] | None = None,
    source: dict | None = None,
) -> dict:
    return {
        "schema": SCHEMA,
        "command": command,
        "ok": True,
        "readOnly": not writes,
        "writes": writes or [],
        "source": source or {},
        "data": data,
        "warnings": warnings or [],
    }


def failure(command: str, error: ZwError, *, source: dict | None = None) -> dict:
    payload = {
        "schema": SCHEMA,
        "command": command,
        "ok": False,
        "readOnly": not error.writes,
        "writes": error.writes,
        "source": source or {},
        "error": {
            "code": error.code,
            "message": error.message,
            "hint": error.hint,
        },
    }
    if error.details:
        payload["error"]["details"] = error.details
    return payload


def print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def print_error(error: ZwError) -> None:
    print(f"zw: {error.message}", file=sys.stderr)
    if error.hint:
        print(f"提示: {error.hint}", file=sys.stderr)
