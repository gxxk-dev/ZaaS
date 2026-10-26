"""Read-only view of the legacy structure-cad hardware library.

The JSON file is old Node-side reference data.  It is not a ``HardwareProfile``
catalog and the Python ``enclosure`` engine never reads it.  This module only
exposes the raw profiles with their original snake_case field names.
"""

from __future__ import annotations

import json
from typing import Any

from . import env
from .envelope import CommandResult, ZwError

LIBRARY_PARTS = ("services", "structure-cad", "server", "data", "hardware-library.json")
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
        detail or "检查 ZW_HOME 中 structure-cad 的 legacy 资料库文件；不要修改掌问安装。",
        7,
    )


def _load() -> tuple[dict[str, Any], Any]:
    path = env.home().joinpath(*LIBRARY_PARTS)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ZwError(
            "LIBRARY_MISSING",
            f"legacy 几何资料库不存在：{path}",
            "确认 ZW_HOME 指向完整掌问安装；该资料库属于 structure-cad 服务数据。",
            5,
        ) from exc
    except OSError as exc:
        raise _invalid(f"无法读取 legacy 几何资料库：{path}", str(exc)) from exc
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise _invalid(f"legacy 几何资料库不是有效 JSON：{path}", str(exc)) from exc
    if not isinstance(payload, dict):
        raise _invalid("legacy 几何资料库顶层必须是对象。")
    if not isinstance(payload.get("version"), str) or not isinstance(payload.get("units"), str):
        raise _invalid("legacy 几何资料库缺少 version/units 字符串。")
    if not isinstance(payload.get("coordinate_system"), dict):
        raise _invalid("legacy 几何资料库缺少 coordinate_system 对象。")
    if not isinstance(payload.get("migration"), dict):
        raise _invalid("legacy 几何资料库缺少 migration 对象。")
    profiles = payload.get("profiles")
    if not isinstance(profiles, list):
        raise _invalid("legacy 几何资料库缺少 profiles 数组。")
    identifiers: set[str] = set()
    for index, profile in enumerate(profiles):
        if not isinstance(profile, dict):
            raise _invalid(f"profiles[{index}] 不是对象。")
        for key in ("id", "name", "category"):
            if not isinstance(profile.get(key), str) or not profile[key].strip():
                raise _invalid(f"profiles[{index}] 缺少非空字符串 {key}。")
        if profile["id"] in identifiers:
            raise _invalid(f"legacy 几何资料库存在重复 profile id：{profile['id']}。")
        identifiers.add(profile["id"])
    return payload, path


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
