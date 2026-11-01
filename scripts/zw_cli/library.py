"""Read-only view of the split legacy structure hardware library.

Data comes from ``resources/hardware-resources.json`` (the ``structure``
block) plus the per-profile ``profile.json`` files it references.  The
profiles are old Node-side reference data with their original snake_case
field names.  They are not a ``HardwareProfile`` catalog and the Python
``enclosure`` engine never reads them.  The CLI output schema is unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from . import env
from .envelope import CommandResult, ZwError

RESOURCES_PARTS = ("resources", "hardware-resources.json")
RESOURCES_SCHEMA = "zhangwen.hardware-resources/v1"
LIST_FIELDS = (
    "id",
    "name",
    "category",
    "roles",
    "dimensions_mm",
    "thumbnail_url",
    "source_status",
    "integration_status",
)
LEGACY_WARNING = (
    "legacy 资料仅供只读参考；字段未经过 cad_engine HardwareProfile 校验，"
    "enclosure 不读取这份资料库；同名 id 的 enclosure 解析以 `zw enclosure profiles` 为准。"
)


def _invalid(message: str, detail: str = "") -> ZwError:
    return ZwError(
        "LIBRARY_INVALID",
        message,
        detail or "检查 ZW_HOME 中 resources/hardware-resources.json 与各 structure profile 文件；不要修改掌问安装。",
        7,
    )


def _profile_path(resources: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise _invalid(f"structure profile 路径无效：{value!r}")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise _invalid(f"structure profile 路径无效：{value!r}")
    candidate = resources.joinpath(*relative.parts)
    try:
        root = resources.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise _invalid(f"structure profile 文件不存在：{value}", str(exc)) from exc
    if not resolved.is_relative_to(root) or candidate.is_symlink() or not candidate.is_file():
        raise _invalid(f"structure profile 不是 resources 内的普通文件：{value}")
    for parent in candidate.parents:
        if parent == resources:
            break
        if parent.is_symlink():
            raise _invalid(f"structure profile 路径包含符号链接：{value}")
    return candidate


def _load() -> tuple[dict[str, Any], Path]:
    root = env.home()
    path = root.joinpath(*RESOURCES_PARTS)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ZwError(
            "LIBRARY_MISSING",
            f"结构资料索引不存在：{path}",
            "确认 ZW_HOME 指向完整掌问安装；索引位于 resources/hardware-resources.json。",
            5,
        ) from exc
    except OSError as exc:
        raise _invalid(f"无法读取结构资料索引：{path}", str(exc)) from exc
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise _invalid(f"结构资料索引不是有效 JSON：{path}", str(exc)) from exc
    if not isinstance(payload, dict) or payload.get("schema") != RESOURCES_SCHEMA:
        raise _invalid("结构资料索引 schema 无效。")
    structure = payload.get("structure")
    if not isinstance(structure, dict):
        raise _invalid("结构资料索引缺少 structure 对象。")
    if not isinstance(structure.get("version"), str) or not isinstance(structure.get("units"), str):
        raise _invalid("structure 块缺少 version/units 字符串。")
    if not isinstance(structure.get("coordinate_system"), dict):
        raise _invalid("structure 块缺少 coordinate_system 对象。")
    if not isinstance(structure.get("migration"), dict):
        raise _invalid("structure 块缺少 migration 对象。")
    entries = structure.get("profiles")
    if not isinstance(entries, list):
        raise _invalid("structure 块缺少 profiles 数组。")

    resources = root / "resources"
    profiles: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise _invalid(f"structure.profiles[{position}] 不是对象。")
        identifier = entry.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            raise _invalid(f"structure.profiles[{position}] 缺少非空字符串 id。")
        if identifier in identifiers:
            raise _invalid(f"结构资料存在重复 profile id：{identifier}。")
        profile_path = _profile_path(resources, entry.get("path"))
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise _invalid(f"无法读取 structure profile：{entry.get('path')}", str(exc)) from exc
        except ValueError as exc:
            raise _invalid(f"structure profile 不是有效 JSON：{entry.get('path')}", str(exc)) from exc
        if not isinstance(profile, dict):
            raise _invalid(f"structure profile 顶层必须是对象：{entry.get('path')}")
        if profile.get("id") != identifier:
            raise _invalid(f"structure profile id 与索引不一致：{identifier}。")
        for key in ("id", "name", "category"):
            if not isinstance(profile.get(key), str) or not profile[key].strip():
                raise _invalid(f"structure profile 缺少非空字符串 {key}：{identifier}。")
        identifiers.add(identifier)
        profiles.append(profile)

    normalized = {
        "version": structure["version"],
        "units": structure["units"],
        "coordinate_system": structure["coordinate_system"],
        "migration": structure["migration"],
        "profiles": profiles,
    }
    return normalized, path


def _library(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": payload["version"],
        "units": payload["units"],
        "coordinateSystem": payload["coordinate_system"],
        "migration": payload["migration"],
    }


def cmd_library(
    profile_id: str | None = None,
    *,
    category: str | None = None,
    query: str | None = None,
) -> CommandResult:
    if profile_id is not None and (category is not None or query is not None):
        raise ZwError(
            "REQUEST_INVALID",
            "profile_id 与 --category/--query 不能同时使用。",
            "要么按 id 查单条，要么用过滤条件列列表。",
            2,
        )
    payload, _ = _load()
    warnings = [LEGACY_WARNING]
    library = _library(payload)
    profiles = payload["profiles"]

    if profile_id is not None:
        match = next((item for item in profiles if item["id"] == profile_id), None)
        if match is None:
            raise ZwError(
                "PROFILE_NOT_FOUND",
                f"legacy 资料库中没有 profile：{profile_id}",
                "用 zw structure library --query 搜索 id/name；这不是 enclosure 的 profile_id。",
                3,
            )
        return CommandResult(
            data={"profile": match, "library": library, "source": "legacy-hardware-library"},
            warnings=warnings,
        )

    selected = profiles
    if category is not None:
        wanted = category.strip().lower()
        selected = [
            item for item in selected if item["category"].lower() == wanted
        ]
    if query is not None:
        needle = query.strip().lower()
        selected = [
            item
            for item in selected
            if needle in item["id"].lower() or needle in item["name"].lower()
        ]
    items = [{key: item.get(key) for key in LIST_FIELDS} for item in selected]
    if not items:
        warnings.append("过滤条件没有匹配的 legacy profile。")
    return CommandResult(
        data={
            "count": len(items),
            "profiles": items,
            "source": "legacy-hardware-library",
        },
        warnings=warnings,
    )
