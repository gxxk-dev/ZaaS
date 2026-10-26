"""Small pytest helpers; the test runner itself is pytest."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

SCHEMA = "zw.cli/v1"


@lru_cache(maxsize=1)
def load_expected() -> dict[str, Any]:
    path = Path(__file__).resolve().parent / "data" / "expected.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == SCHEMA, f"unexpected snapshot schema: {path}"
    return payload


def canonical_sha256(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ZwResult:
    args: tuple[str, ...]
    code: int
    payload: dict[str, Any]
    stdout: str
    stderr: str

    def _context(self) -> str:
        return (
            f"zw {' '.join(self.args)}\n"
            f"exit={self.code}\n"
            f"stdout={self.stdout[:4000]!r}\n"
            f"stderr={self.stderr[:4000]!r}"
        )

    @property
    def data(self) -> dict[str, Any]:
        return self.payload.get("data") or {}

    @property
    def error(self) -> dict[str, Any]:
        return self.payload.get("error") or {}

    @property
    def error_code(self) -> str | None:
        return self.error.get("code")

    def assert_exit(self, exit_code: int) -> None:
        assert self.code == exit_code, f"expected exit {exit_code}\n{self._context()}"

    def assert_ok(self, *, read_only: bool | None = None) -> dict[str, Any]:
        self.assert_exit(0)
        assert self.payload.get("schema") == SCHEMA, (
            f"schema mismatch\n{self._context()}"
        )
        assert self.payload.get("ok") is True, (
            f"expected ok envelope\n{self._context()}"
        )
        if read_only is not None:
            assert self.payload.get("readOnly") is read_only, (
                f"readOnly mismatch\n{self._context()}"
            )
            writes = self.payload.get("writes") or []
            if read_only:
                assert writes == [], f"expected no writes\n{self._context()}"
            else:
                assert writes, f"expected writes\n{self._context()}"
        return self.data

    def assert_error(self, exit_code: int, error_code: str) -> dict[str, Any]:
        self.assert_exit(exit_code)
        assert self.payload.get("schema") == SCHEMA, (
            f"schema mismatch\n{self._context()}"
        )
        assert self.payload.get("ok") is False, (
            f"expected error envelope\n{self._context()}"
        )
        assert self.error_code == error_code, (
            f"expected {error_code}, got {self.error_code}\n{self._context()}"
        )
        return self.error
