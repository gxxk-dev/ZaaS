"""Read-only hardware commands."""

from __future__ import annotations

import re

from . import env, index
from .envelope import CommandResult, ZwError

_CONTROLLERS = None
_REPOSITORY = None


def _upstream():
    global _CONTROLLERS
    try:
        from zhangwen.hardware.hardware_skills import (
            HardwareSkillNotFoundError,
            HardwareSkillRepository,
            HardwareSkillValidationError,
        )
        from zhangwen.hardware.rule_engine import validate_components
        from zhangwen.web import module_guides
        from zhangwen.web.hardware import WEB_CONTROLLERS, WebHardwareRepository
    except ImportError as exc:
        raise ZwError(
            "DEPENDENCY_MISSING",
            f"无法导入掌问模块：{exc}",
            "确认 ZW_HOME 完整，并安装 requirements-core.txt。",
            5,
        ) from exc
    _CONTROLLERS = WEB_CONTROLLERS
    return {
        "Repository": HardwareSkillRepository,
        "NotFound": HardwareSkillNotFoundError,
        "Invalid": HardwareSkillValidationError,
        "validate": validate_components,
        "guides": module_guides,
        "web": WebHardwareRepository,
        "controllers": WEB_CONTROLLERS,
    }


def _repo():
    global _REPOSITORY
    if _REPOSITORY is None:
        mods = _upstream()
        data = env.data_dir()
        _REPOSITORY = mods["Repository"](data, data / "projects" / "zhangwen.sqlite3")
    return _REPOSITORY


def _detail(value: str):
    mods = _upstream()
    package = index.find_package(value)
    try:
        detail = _repo().get_skill(package["skillName"])
    except mods["NotFound"] as exc:
        raise ZwError("HARDWARE_NOT_FOUND", f"资料包未激活或不存在：{package['skillName']}", str(exc), 3) from exc
    except mods["Invalid"] as exc:
        raise ZwError("PACKAGE_INVALID", f"资料包校验失败：{package['skillName']}", str(exc), 7) from exc
    return package, detail


def _media(detail) -> list[dict]:
    root = env.data_dir() / "hardware-skills" / detail.skillName
    items = []
    for asset in detail.media:
        record = asset.model_dump(mode="json")
        local = root / record.get("path", "")
        record["localPath"] = str(local) if local.is_file() else None
        items.append(record)
    return items


def _catalog(detail) -> dict:
    mods = _upstream()
    try:
        return mods["web"].catalog_metadata(None, detail)
    except Exception:
        return {
            "brand": "",
            "moduleType": "",
            "sourceUrl": detail.specification.sourceIds[0] if detail.specification.sourceIds else "",
            "programmingSupport": "existing",
            "electricalVerified": detail.verificationStatus != "UNVERIFIED",
        }


def _wrapper(method, detail, fallback):
    mods = _upstream()
    try:
        return getattr(mods["web"], method)(detail)
    except Exception:
        return fallback


def _guides(detail) -> list[dict]:
    mods = _upstream()
    try:
        return mods["guides"].guides(detail, mods["controllers"])
    except mods["Invalid"] as exc:
        raise ZwError("PACKAGE_INVALID", f"模块指南格式无效：{detail.skillName}", str(exc), 7) from exc


def _render(value, selected: dict):
    if isinstance(value, str):
        def replace(match):
            key = match.group(1)
            if key not in selected:
                raise ZwError("TEMPLATE_VALUE_MISSING", f"接线模板缺少参数：{key}", "", 2)
            return str(selected[key])

        return re.sub(r"\{\{([A-Za-z0-9_]+)\}\}", replace, value)
    if isinstance(value, list):
        return [_render(item, selected) for item in value]
    if isinstance(value, dict):
        return {key: _render(item, selected) for key, item in value.items()}
    return value


def _display_values(guide, selected: dict) -> dict:
    """Map raw option values to their human-facing labels for wiring text."""
    display = dict(selected)
    for field in guide.get("fields", []):
        key = field.get("key")
        if key not in display:
            continue
        label = next(
            (choice.get("label") for choice in field.get("options", []) if choice.get("value") == display[key]),
            None,
        )
        if label:
            display[key] = label
    return display


def cmd_search(query: str, *, board: str | None, category: str | None, limit: int) -> CommandResult:
    record = env.resolve_board(board) if board else None
    results, warnings = index.search(query, board=record, category=category, limit=limit)
    catalog = index.catalog_status()
    if catalog["stale"]:
        warnings.append(
            f"目录缓存 {catalog['count']} 条 / 磁盘 {catalog['scanCount']} 包；搜索以磁盘 manifest 为准，未刷新缓存。"
        )
    warnings.extend(index.package_warnings())
    data = {
        "query": query,
        "board": record["componentId"] if record else None,
        "category": category,
        "count": len(results),
        "results": results,
        "catalog": catalog,
    }
    return CommandResult(data=data, warnings=warnings)


def cmd_get(identifier: str, *, full: bool, file_path: str | None) -> CommandResult:
    package, detail = _detail(identifier)
    warnings = []
    if package["verificationStatus"] != "OFFICIAL_DOC_VERIFIED":
        warnings.append(
            f"verificationStatus={package['verificationStatus']}；结论必须标注未联调/待实物验证。"
        )
    electrical = detail.specification.electrical.model_dump(mode="json")
    if electrical.get("voltage") == 0:
        warnings.append("voltage=0 表示未知，不是 0V。")
    if electrical.get("peakCurrent") == 0:
        warnings.append("peakCurrent=0 表示未知，不是 0A。")

    if file_path:
        target = next((item for item in detail.files if item.path == file_path), None)
        if target is None:
            raise ZwError(
                "FILE_NOT_FOUND",
                f"资料包中没有文件：{file_path}",
                "可用文件：" + ", ".join(item.path for item in detail.files),
                3,
            )
        data = {
            "componentId": detail.componentId,
            "skillName": detail.skillName,
            "displayName": detail.displayName,
            "file": {"path": target.path, "title": target.title, "kind": target.kind, "content": target.content},
        }
        return CommandResult(data=data, warnings=warnings)

    files = []
    for item in detail.files:
        record = {"path": item.path, "title": item.title, "kind": item.kind, "bytes": len(item.content.encode("utf-8"))}
        if full:
            record["content"] = item.content
        files.append(record)

    examples = _wrapper("local_examples", detail, [])
    if not full:
        examples = [
            {key: value for key, value in item.items() if key != "code"}
            for item in examples
        ]

    supported = _wrapper("supported_boards", detail, None)
    verified = _wrapper("verified_boards", detail, [])
    guides = _guides(detail)
    i2c = None
    if any(guide.get("fields") for guide in guides):
        try:
            i2c = _upstream()["guides"].i2c_info(detail, _upstream()["controllers"])
        except Exception:
            i2c = None

    data = {
        "componentId": detail.componentId,
        "skillName": detail.skillName,
        "displayName": detail.displayName,
        "description": detail.description,
        "category": detail.category.value if hasattr(detail.category, "value") else str(detail.category),
        "status": detail.status.value if hasattr(detail.status, "value") else str(detail.status),
        "sourceKind": detail.sourceKind.value if hasattr(detail.sourceKind, "value") else str(detail.sourceKind),
        "revision": detail.revision,
        "updatedAt": detail.updatedAt,
        "verificationStatus": detail.verificationStatus,
        "electrical": electrical,
        "stock": detail.specification.stock,
        "price": detail.specification.price,
        "ageRecommendation": detail.specification.ageRecommendation,
        "safetyTags": list(detail.specification.safetyTags),
        "notes": detail.specification.notes,
        "sourceIds": list(detail.specification.sourceIds),
        "rules": [rule.model_dump(mode="json") for rule in detail.rules],
        "mechanical": detail.mechanicalProfile,
        "catalog": _catalog(detail),
        "media": _media(detail),
        "supportedBoardIds": supported,
        "verifiedBoardIds": verified,
        "localExamples": examples,
        "guides": [
            {key: guide.get(key) for key in ("boardId", "kind", "title", "summary")}
            for guide in guides
        ],
        "i2c": i2c,
        "files": files,
        "sourcePath": package["path"],
    }
    return CommandResult(data=data, warnings=warnings)


def cmd_guide(
    identifier: str,
    *,
    board: str,
    setup_pairs: list[str],
    kind: str | None = None,
) -> CommandResult:
    mods = _upstream()
    record = env.resolve_board(board)
    package, detail = _detail(identifier)
    guides = _guides(detail)
    guide = next((item for item in guides if item.get("boardId") == record["componentId"]), None)
    if guide is None:
        available = [
            {"boardId": item.get("boardId"), "title": item.get("title")}
            for item in guides
        ]
        raise ZwError(
            "GUIDE_NOT_FOUND",
            f"{detail.displayName} 没有 {record['displayName']} 的模块指南。",
            "该资料包只提供以下主控指南：" + ", ".join(item["boardId"] for item in available),
            3,
            details={"availableBoards": available},
        )
    if kind is not None:
        if kind not in {"functional", "diagnostic", "reference"}:
            raise ZwError(
                "REQUEST_INVALID",
                f"--kind 必须是 functional/diagnostic/reference：{kind}",
                "",
                2,
            )
        actual = str(guide.get("kind"))
        if actual != kind:
            raise ZwError(
                "GUIDE_KIND_MISMATCH",
                f"{detail.displayName} 在 {record['displayName']} 上只有 {actual} 指南，没有 {kind}。",
                "去掉 --kind 读取现有指南，或改用匹配的种类。",
                4,
                details={
                    "requested": kind,
                    "available": {"kind": actual, "title": guide.get("title")},
                    "availableBoardIds": [item.get("boardId") for item in guides],
                },
            )

    setup = {}
    for pair in setup_pairs:
        key, separator, value = pair.partition("=")
        if not separator or not key:
            raise ZwError("SET_INVALID", f"--set 需要 key=value：{pair}", "", 2)
        setup[key] = value
    try:
        selected = mods["guides"].values(guide, setup)
        code = mods["guides"].render(guide, setup)
        setup_text = mods["guides"].setup_text(guide, setup)
    except mods["Invalid"] as exc:
        raise ZwError("SET_INVALID", str(exc), "用 --set key=value 选择 fields 中的值。", 2) from exc

    i2c = None
    try:
        i2c = mods["guides"].i2c_info(detail, mods["controllers"])
    except Exception:
        i2c = None
    verified = _wrapper("verified_boards", detail, [])
    warnings = [
        f"verificationStatus={package['verificationStatus']}；保存、语法检查及串口回读均不代表实物测量通过。"
    ]
    if package["verificationStatus"] != "OFFICIAL_DOC_VERIFIED":
        warnings.append("该包不是 OFFICIAL_DOC_VERIFIED，接线与代码需实物验证。")
    wiring = _render(guide.get("connections", []), selected)
    labeled = _render(guide.get("connections", []), _display_values(guide, selected))
    for raw, shown in zip(wiring, labeled):
        raw["targetLabel"] = shown.get("target", raw.get("target"))
    data = {
        "componentId": detail.componentId,
        "skillName": detail.skillName,
        "displayName": detail.displayName,
        "board": {
            "componentId": record["componentId"],
            "displayName": record["displayName"],
            "skillName": record["skillName"],
        },
        "guide": {
            **{key: _render(guide.get(key), selected) for key in ("boardId", "kind", "title", "summary")},
            "fields": guide.get("fields", []),
            "connections": _render(guide.get("connections", []), selected),
            "notes": _render(guide.get("notes", []), selected),
            "sources": guide.get("sources", []),
            "codeTemplate": guide.get("codeTemplate", ""),
        },
        "setup": selected,
        "setupText": setup_text,
        "wiring": wiring,
        "code": code,
        "i2c": i2c,
        "verification": {
            "packageStatus": package["verificationStatus"],
            "boardReportedVerified": record["componentId"] in (verified or []),
            "note": "报告记录不是自动实测；仍需按实物核对供电、共地与信号电平。",
        },
        "sources": guide.get("sources", []),
    }
    return CommandResult(data=data, warnings=warnings)


def cmd_validate(board: str, identifiers: list[str]) -> CommandResult:
    mods = _upstream()
    record = env.resolve_board(board)
    if not identifiers:
        raise ZwError("COMPONENT_REQUIRED", "至少提供一个模块 componentId。", "例如 zw hardware validate k10 hw_dfrobot_dfr0026_k10", 2)
    requested = [record["componentId"], *identifiers]
    seen: set[str] = set()
    components = []
    rules = []
    records = []
    warnings = []
    for value in requested:
        package, detail = _detail(value)
        if detail.componentId in seen:
            continue
        seen.add(detail.componentId)
        try:
            components.append(_repo().component_from_detail(detail))
        except mods["NotFound"] as exc:
            raise ZwError("HARDWARE_NOT_FOUND", f"资料包未激活：{detail.skillName}", str(exc), 3) from exc
        rules.extend(detail.rules)
        records.append(
            {
                "componentId": detail.componentId,
                "skillName": detail.skillName,
                "displayName": detail.displayName,
                "category": detail.category.value if hasattr(detail.category, "value") else str(detail.category),
                "verificationStatus": detail.verificationStatus,
            }
        )
        if detail.verificationStatus != "OFFICIAL_DOC_VERIFIED":
            warnings.append(f"{detail.skillName}: verificationStatus={detail.verificationStatus}，不能表述为已实测。")

    try:
        result = mods["validate"](components, rules=rules) if rules else mods["validate"](components)
    except Exception as exc:
        raise ZwError("VALIDATION_ERROR", f"规则引擎执行失败：{exc}", "", 7) from exc

    checks = []
    for check in result.checks:
        severity = check.severity.value if hasattr(check.severity, "value") else str(check.severity)
        checks.append(
            {
                "dimension": check.dimension,
                "severity": severity,
                "message": check.message,
                "details": check.details,
            }
        )
    overall = result.overall.value if hasattr(result.overall, "value") else str(result.overall)
    valid = overall != "FAIL"
    if not valid:
        warnings.append("电气校验存在 FAIL；不要继续接线或上电，先处理失败项。")
    data = {
        "board": {
            "componentId": record["componentId"],
            "skillName": record["skillName"],
            "displayName": record["displayName"],
        },
        "components": records,
        "valid": valid,
        "overall": overall,
        "message": result.message,
        "checks": checks,
    }
    return CommandResult(data=data, warnings=warnings, exit_code=0 if valid else 4)
