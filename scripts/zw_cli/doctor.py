"""Self-check for the local install and skill dependencies."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import shutil
import subprocess
import sys

from . import env, index
from .envelope import CommandResult


def _version(distribution: str, module: str | None = None) -> dict:
    module = module or distribution
    installed = importlib.util.find_spec(module) is not None
    version = None
    try:
        version = importlib.metadata.version(distribution)
        installed = True
    except importlib.metadata.PackageNotFoundError:
        pass
    return {"installed": installed, "version": version}


def _command_version(command: str, args: tuple[str, ...] = ("--version",)) -> dict:
    path = shutil.which(command)
    if not path:
        return {"path": None, "version": None}
    try:
        output = subprocess.run(
            [command, *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        output = ""
    return {"path": path, "version": output.splitlines()[0] if output else None}


def cmd_status() -> CommandResult:
    root = env.home()
    data_dir = env.data_dir()
    catalog = index.catalog_status()
    boards = index.board_records()
    templates_path = root / "services" / "structure-cad" / "templates" / "manifest.json"
    cad_templates = []
    try:
        manifest = json.loads(templates_path.read_text(encoding="utf-8"))
        cad_templates = [
            {"id": item["id"], "title": item["title"], "revision": item.get("revision")}
            for item in manifest.get("templates", [])
        ]
    except (OSError, ValueError, KeyError):
        pass

    deps = {
        "pydantic": _version("pydantic"),
        "fastapi": _version("fastapi"),
        "httpx": _version("httpx"),
        "fontTools": _version("fonttools"),
        "cadquery": _version("cadquery"),
        "cadquery-ocp": _version("cadquery-ocp"),
        "numpy": _version("numpy"),
        "matplotlib": _version("matplotlib"),
    }
    font = root / "resources" / "fonts" / "NotoSansSC.ttf"
    warnings = []
    if catalog["stale"]:
        warnings.append(
            f"目录缓存 {catalog['count']} 条 / 磁盘 {catalog['scanCount']} 包；搜索以磁盘为准，未自动刷新。"
        )
    if not deps["cadquery"]["installed"]:
        warnings.append("未安装 CadQuery；structure 子命令不可用。")
    if not deps["fontTools"]["installed"]:
        warnings.append("未安装 fontTools；激光文字和模板刻字不可用。")
    if not font.is_file():
        warnings.append(f"缺少中文字体：{font}")
    if not shutil.which("pyrcli"):
        warnings.append("PATH 中没有 pyrcli；设备上传/运行/刷机请先安装 Pyrite CLI。")
    if not deps["pydantic"]["installed"] or not deps["fastapi"]["installed"]:
        warnings.append("掌问核心依赖不完整；hardware/code 命令可能无法运行。")

    data = {
        "skillVersion": __import__("zw_cli").__version__,
        "zwHome": str(root),
        "dataDir": str(data_dir),
        "python": sys.executable,
        "pythonSource": os.environ.get("ZW_PYTHON_SOURCE", "unknown"),
        "uv": shutil.which("uv"),
        "node": _command_version("node"),
        "pyrcli": _command_version("pyrcli", ("scan", "-V")),
        "cache": catalog,
        "deps": deps,
        "font": {"path": str(font), "exists": font.is_file()},
        "templates": {
            "laser": ["plate", "round-tag", "panel-box", "finger-box", "rounded-box"],
            "cad": cad_templates,
        },
        "boards": [
            {
                "componentId": item["componentId"],
                "skillName": item["skillName"],
                "displayName": item["displayName"],
                "hasBoardSkill": item["hasBoardSkill"],
                "programmingSkill": (item["programmingSkill"] or {}).get("name"),
                "firmwareInstalled": bool(item["firmware"] and item["firmware"].get("installed")),
            }
            for item in boards
        ],
        "packageWarnings": len(index.package_warnings()),
    }
    return CommandResult(data=data, warnings=warnings)
