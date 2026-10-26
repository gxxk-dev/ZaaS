"""Pytest fixtures for the black-box zw CLI contracts."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable

import pytest

pytest.register_assert_rewrite("tests.helpers")

from tests.helpers import ZwResult, load_expected

REPO_ROOT = Path(__file__).resolve().parents[1]
ZW = REPO_ROOT / "scripts" / "zw"
DEFAULT_ZW_HOME = Path("/mnt/dev-cold/zhangwen")


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def zw() -> Path:
    assert ZW.is_file(), f"launcher not found: {ZW}"
    return ZW


@pytest.fixture(scope="session")
def zw_home() -> Path:
    configured = os.environ.get("ZW_HOME")
    home = Path(configured).expanduser().resolve() if configured else DEFAULT_ZW_HOME
    install = home / "services" / "local-api" / "zhangwen"
    if not install.is_dir():
        message = f"not a ZhangWen install (missing {install}): {home}"
        if configured:
            pytest.fail(f"ZW_HOME is set but {message}")
        pytest.skip(
            f"ZhangWen install not found; {message}. "
            "Set ZW_HOME to run contract tests."
        )
    return home


@pytest.fixture(scope="session")
def zw_env(zw_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["ZW_HOME"] = str(zw_home)
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("ZW_LAUNCH_DEBUG_REQUIREMENTS", None)
    return env


@pytest.fixture(scope="session")
def run_zw(zw: Path, zw_env: dict[str, str]) -> Callable[..., ZwResult]:
    def _run(
        *args: str,
        timeout: float = 120,
        env_extra: dict[str, str] | None = None,
    ) -> ZwResult:
        env = dict(zw_env)
        if env_extra:
            env.update(env_extra)
        command = [str(zw), *args, "--json"]
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            pytest.fail(f"zw {' '.join(args)} timed out after {timeout}s")
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            pytest.fail(
                f"non-JSON stdout for zw {' '.join(args)} "
                f"(exit {proc.returncode}): {exc}\n"
                f"stdout={proc.stdout[:1000]!r}\n"
                f"stderr={proc.stderr[:1000]!r}"
            )
        assert isinstance(payload, dict), f"JSON payload is not an object: {payload!r}"
        return ZwResult(tuple(args), proc.returncode, payload, proc.stdout, proc.stderr)

    return _run


@pytest.fixture(scope="session")
def launcher_route(zw: Path, zw_env: dict[str, str]) -> Callable[..., str]:
    def _route(*args: str) -> str:
        try:
            proc = subprocess.run(
                [str(zw), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**zw_env, "ZW_LAUNCH_DEBUG_REQUIREMENTS": "1"},
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            pytest.fail(f"launcher debug timed out: zw {' '.join(args)}")
        assert proc.returncode == 0, (
            f"launcher debug failed: zw {' '.join(args)} exit={proc.returncode}\n"
            f"stdout={proc.stdout[:1000]!r}\n"
            f"stderr={proc.stderr[:1000]!r}"
        )
        return proc.stdout.strip()

    return _route


@pytest.fixture(scope="session")
def expected() -> dict[str, Any]:
    return load_expected()


@pytest.fixture(scope="session")
def status_result(run_zw: Callable[..., ZwResult]) -> ZwResult:
    return run_zw("status")


@pytest.fixture(scope="session")
def require_cad(status_result: ZwResult) -> None:
    deps = status_result.assert_ok().get("deps") or {}
    if not (deps.get("cadquery") or {}).get("installed"):
        pytest.skip("CadQuery is not installed for this ZhangWen installation")


@pytest.fixture
def write_json(tmp_path: Path) -> Callable[[str, dict[str, Any]], Path]:
    def _write(name: str, payload: dict[str, Any]) -> Path:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    return _write


@pytest.fixture
def write_text(tmp_path: Path) -> Callable[[str, str], Path]:
    def _write(name: str, content: str) -> Path:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    return _write
