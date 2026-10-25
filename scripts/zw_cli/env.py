"""Locate the local ZhangWen install and resolve shared arguments."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from .envelope import ZwError

DEFAULT_HOME = "/mnt/dev-cold/zhangwen"

BOARD_DEFS = [
    {
        "componentId": "hw_seed_unihiker_k10",
        "profile": "unihiker-k10",
        "programming": "unihiker-k10",
        "aliases": [
            "k10",
            "行空板k10",
            "行空板 k10",
            "unihiker-k10",
            "unihiker_k10",
        ],
    },
    {
        "componentId": "hw_seeed_xiao_esp32s3_sense",
        "profile": "xiao-esp32s3-sense",
        "programming": None,
        "aliases": [
            "xiao",
            "xiao esp32s3",
            "xiao esp32s3 sense",
            "xiao-esp32s3-sense",
            "seeed-studio-xiao-esp32s3-sense",
        ],
    },
    {
        "componentId": "hw_esp32_generic_c3",
        "profile": "esp32-generic-c3",
        "programming": None,
        "aliases": [
            "c3",
            "esp32-c3",
            "esp32 c3",
            "esp32-c3 generic",
            "esp32-generic-c3",
        ],
    },
    {
        "componentId": "hw_labplus_mpython_v2",
        "profile": "labplus-mpython-v2",
        "programming": "mpython-v2",
        "aliases": [
            "mpython",
            "mpython2",
            "mpython v2",
            "掌控板2.0",
            "掌控板 2.0",
            "labplus-mpython-v2",
        ],
    },
    {
        "componentId": "hw_labplus_mpython_esp32s3_v3",
        "profile": None,
        "programming": "mpython-v3",
        "aliases": [
            "mpython3",
            "mpython v3",
            "掌控板3.0",
            "掌控板 3.0",
            "labplus-mpython-esp32s3-v3",
        ],
    },
]


def normalize(value: str) -> str:
    return re.sub(r"[\s_\-·.]+", "", value.strip().lower())


def home() -> Path:
    value = os.environ.get("ZW_HOME", DEFAULT_HOME)
    path = Path(value).expanduser().resolve()
    if not (path / "services" / "local-api" / "zhangwen").is_dir():
        raise ZwError(
            "ZW_HOME_INVALID",
            f"ZW_HOME 不是有效的掌问安装：{path}",
            "设置 ZW_HOME 指向包含 services/local-api/zhangwen 的目录。",
            5,
        )
    return path


def data_dir() -> Path:
    value = os.environ.get("ZW_DATA_DIR")
    path = Path(value).expanduser().resolve() if value else home() / ".data"
    if not (path / "hardware-skills").is_dir():
        raise ZwError(
            "ZW_DATA_INVALID",
            f"掌问数据目录无效：{path}",
            "确认 ZW_HOME 指向完整安装，或设置 ZW_DATA_DIR。",
            5,
        )
    return path


def firmware_manifest() -> dict:
    path = home() / "resources" / "firmware" / "manifest.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def board_records() -> list[dict]:
    from . import index

    return index.board_records()


def resolve_board(value: str) -> dict:
    wanted = normalize(value)
    for record in board_records():
        candidates = {
            record["componentId"],
            record.get("skillName") or "",
            record.get("displayName") or "",
            record.get("profile") or "",
            *record.get("aliases", []),
        }
        if wanted in {normalize(item) for item in candidates if item}:
            return record
    aliases = ", ".join(
        f"{item['displayName']}({item['componentId']})" for item in board_records()
    )
    raise ZwError(
        "BOARD_NOT_FOUND",
        f"未找到主控：{value}",
        f"可用主控：{aliases}",
        3,
    )


def resolve_out(value: str, *, force: bool, allow_in_repo: bool) -> Path:
    out = Path(value).expanduser().resolve()
    root = home()
    if not allow_in_repo and (out == root or root in out.parents):
        raise ZwError(
            "OUT_IN_REPO",
            f"拒绝写入掌问仓库：{out}",
            "换一个输出目录，或显式加 --allow-in-repo。",
            6,
        )
    if out.exists():
        if not out.is_dir():
            raise ZwError("OUT_NOT_DIR", f"输出路径不是目录：{out}", "", 6)
        if any(out.iterdir()) and not force:
            raise ZwError(
                "OUT_NOT_EMPTY",
                f"输出目录非空：{out}",
                "换一个空目录，或显式加 --force 覆盖同名文件。",
                6,
            )
    return out


def prepare_out(out: Path) -> None:
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ZwError("OUT_WRITE_FAILED", f"无法创建输出目录：{out}", str(exc), 7) from exc


def write_text(out: Path, name: str, content: str, *, encoding: str = "utf-8") -> str:
    path = out / name
    try:
        path.write_text(content, encoding=encoding)
    except OSError as exc:
        raise ZwError("OUT_WRITE_FAILED", f"无法写入：{path}", str(exc), 7) from exc
    return str(path)


def load_json_arg(value: str) -> object:
    """Accept inline JSON, @file, or - for stdin."""
    try:
        if value == "-":
            return json.load(sys.stdin)
        if value.startswith("@"):
            return json.loads(Path(value[1:]).expanduser().read_text(encoding="utf-8"))
        return json.loads(value)
    except OSError as exc:
        raise ZwError("JSON_READ_FAILED", f"无法读取 JSON：{value}", str(exc), 7) from exc
    except ValueError as exc:
        raise ZwError("JSON_INVALID", f"JSON 格式无效：{exc}", "检查引号、逗号和括号。", 2) from exc


def load_json_file(value: str) -> object:
    try:
        text = sys.stdin.read() if value == "-" else Path(value).expanduser().read_text(encoding="utf-8")
        return json.loads(text)
    except OSError as exc:
        raise ZwError("JSON_READ_FAILED", f"无法读取 JSON：{value}", str(exc), 7) from exc
    except ValueError as exc:
        raise ZwError("JSON_INVALID", f"JSON 格式无效：{exc}", "检查文件内容。", 2) from exc


def source_info() -> dict:
    """Cheap source metadata; never scan every package here."""
    try:
        root = home()
        data = data_dir()
        cache_path = data / "cache" / "hardware-catalog-v1.json"
        cached = None
        generated = None
        if cache_path.is_file():
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                candidates = payload.get("candidates")
                cached = len(candidates) if isinstance(candidates, list) else None
                generated = payload.get("generatedAt")
            except (OSError, ValueError):
                cached = None
        try:
            scanned = sum(
                1
                for entry in os.scandir(data / "hardware-skills")
                if entry.is_dir() and not entry.is_symlink()
            )
        except OSError:
            scanned = None
        return {
            "home": str(root),
            "dataDir": str(data),
            "catalog": "scan",
            "cacheCount": cached,
            "scanCount": scanned,
            "cacheGeneratedAt": generated,
            "stale": cached is None or scanned is None or cached != scanned,
        }
    except ZwError:
        return {}
