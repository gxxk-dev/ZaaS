"""Read-only scan of the local Hardware Skill packages.

The on-disk manifests and specification blocks are authoritative.  The web
catalog cache is reported for staleness but never rewritten or trusted over
the packages.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import env
from .envelope import ZwError

SPEC_RE = re.compile(r"```zhangwen:hardware-spec:v1\s*\n(.*?)\n```", re.S)
MODEL_RE = re.compile(r"\b[A-Z]{2,}[0-9]{3,}[A-Z0-9-]*\b")
HEAD_BYTES = 16 * 1024

_PACKAGES: list[dict] | None = None
_PACKAGE_WARNINGS: list[str] = []
_BOARDS: list[dict] | None = None


def _read_head(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            return handle.read(HEAD_BYTES).decode("utf-8", "replace")
    except OSError:
        return ""


def _scan_packages() -> tuple[list[dict], list[str]]:
    root = env.data_dir() / "hardware-skills"
    packages: list[dict] = []
    warnings: list[str] = []
    try:
        entries = sorted(root.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise ZwError("DATA_SCAN_FAILED", f"无法扫描硬件资料包：{root}", str(exc), 7) from exc

    for folder in entries:
        if folder.is_symlink() or not folder.is_dir():
            continue
        manifest_path = folder / "manifest.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            warnings.append(f"跳过缺少 manifest.json 的目录：{folder.name}")
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            warnings.append(f"跳过无法读取的 manifest：{folder.name}（{exc}）")
            continue
        skill_name = manifest.get("skillName")
        component_id = manifest.get("componentId")
        if skill_name != folder.name or not isinstance(component_id, str):
            warnings.append(f"跳过身份不一致的资料包：{folder.name}")
            continue

        spec_path = folder / "references" / "specifications.md"
        spec: dict = {}
        try:
            text = spec_path.read_text(encoding="utf-8-sig")
            match = SPEC_RE.search(text)
            if not match:
                raise ValueError("缺少 hardware-spec 区块")
            spec = json.loads(match.group(1))
        except (OSError, ValueError) as exc:
            warnings.append(f"{folder.name}: 结构化规格不可用（{exc}）")

        electrical = spec.get("electrical") if isinstance(spec.get("electrical"), dict) else {}
        head = _read_head(folder / "SKILL.md")
        notes = spec.get("notes") if isinstance(spec.get("notes"), str) else ""
        description = manifest.get("description", "")
        search_text = "\n".join(
            part
            for part in (
                manifest.get("displayName", ""),
                description,
                spec.get("name", ""),
                spec.get("category", ""),
                notes,
                skill_name,
                component_id,
                head,
            )
            if part
        )
        packages.append(
            {
                "skillName": skill_name,
                "componentId": component_id,
                "displayName": manifest.get("displayName", skill_name),
                "description": description,
                "category": str(spec.get("category") or "UNKNOWN"),
                "status": manifest.get("status", "ACTIVE"),
                "sourceKind": manifest.get("sourceKind", ""),
                "revision": manifest.get("revision", ""),
                "updatedAt": manifest.get("updatedAt", ""),
                "verificationStatus": str(spec.get("verificationStatus") or "UNVERIFIED"),
                "electrical": electrical,
                "stock": spec.get("stock", 0),
                "price": spec.get("price", 0.0),
                "ageRecommendation": spec.get("ageRecommendation"),
                "safetyTags": spec.get("safetyTags") or [],
                "notes": notes,
                "sourceIds": spec.get("sourceIds") or [],
                "media": manifest.get("media") or [],
                "searchText": search_text,
                "path": str(folder),
            }
        )
    return packages, warnings


def packages() -> list[dict]:
    global _PACKAGES, _PACKAGE_WARNINGS
    if _PACKAGES is None:
        _PACKAGES, _PACKAGE_WARNINGS = _scan_packages()
    return _PACKAGES


def package_warnings() -> list[str]:
    packages()
    return list(_PACKAGE_WARNINGS)


def _by_component(component_id: str) -> dict | None:
    return next((item for item in packages() if item["componentId"] == component_id), None)


def board_records() -> list[dict]:
    global _BOARDS
    if _BOARDS is not None:
        return _BOARDS
    root = env.home()
    firmware = env.firmware_manifest().get("images", {})
    records = []
    for definition in env.BOARD_DEFS:
        component_id = definition["componentId"]
        package = _by_component(component_id)
        profile = definition["profile"]
        board_paths = []
        if profile:
            board_paths = [
                root / "services" / "local-api" / "zhangwen" / "hardware" / "board-skills" / profile / "SKILL.md",
                root / "services" / "local-api" / "zhangwen" / "web" / "board-skills" / profile / "SKILL.md",
            ]
        board_skill = next((str(path) for path in board_paths if path.is_file()), None)
        programming = None
        if definition["programming"]:
            path = root / "services" / "local-api" / "zhangwen" / "web" / "programming-skills" / definition["programming"] / "SKILL.md"
            if path.is_file():
                programming = {"name": definition["programming"], "path": str(path)}
        firmware_item = firmware.get(component_id)
        firmware_record = None
        if isinstance(firmware_item, dict):
            firmware_record = dict(firmware_item)
            image_path = root / "resources" / "firmware" / str(firmware_item.get("name", ""))
            firmware_record["localPath"] = str(image_path) if image_path.is_file() else None
            firmware_record["installed"] = image_path.is_file()
        record = {
            "componentId": component_id,
            "skillName": package["skillName"] if package else None,
            "displayName": package["displayName"] if package else component_id,
            "profile": profile,
            "hasBoardSkill": board_skill is not None,
            "boardSkillPath": board_skill,
            "programmingSkill": programming,
            "firmware": firmware_record,
            "aliases": list(definition["aliases"]),
            "lookup": [
                component_id,
                package["skillName"] if package else "",
                package["displayName"] if package else "",
                profile or "",
                *definition["aliases"],
            ],
            "verificationStatus": package["verificationStatus"] if package else "UNVERIFIED",
        }
        records.append(record)
    _BOARDS = records
    return records


def find_package(value: str) -> dict:
    items = packages()
    exact = next((item for item in items if item["skillName"] == value), None)
    if exact:
        return exact
    exact = next((item for item in items if item["componentId"] == value), None)
    if exact:
        return exact
    wanted = env.normalize(value)
    matches = [
        item
        for item in items
        if wanted in {env.normalize(item["skillName"]), env.normalize(item["componentId"]), env.normalize(item["displayName"])}
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        matches.sort(key=lambda item: (-verification_rank(item["verificationStatus"]), item["skillName"]))
        return matches[0]
    raise ZwError(
        "HARDWARE_NOT_FOUND",
        f"未找到硬件资料包：{value}",
        "用 zw hardware search <关键词> 查 componentId 或 skillName。",
        3,
    )


def verification_rank(status: str) -> int:
    if status == "OFFICIAL_DOC_VERIFIED":
        return 4
    if status.startswith("SOURCE_VERIFIED"):
        return 3
    if status in {"OFFICIAL_API_REFERENCE_UNTESTED", "REQUIREMENT_VERIFIED"}:
        return 2
    if status == "MIGRATED_UNVERIFIED":
        return 1
    return 0


def _board_tokens(record: dict) -> set[str]:
    values = {
        record.get("componentId"),
        record.get("skillName"),
        record.get("profile"),
        *(record.get("aliases") or []),
    }
    return {env.normalize(item) for item in values if item}


def _board_specific(package: dict, tokens: set[str]) -> tuple[bool, bool]:
    supported = package["electrical"].get("supportedMCUs") or []
    specific = isinstance(supported, list) and any(env.normalize(str(item)) in tokens for item in supported)
    identity = env.normalize(package["skillName"] + " " + package["componentId"])
    dedicated = any(len(token) >= 3 and token in identity for token in tokens)
    return bool(specific or dedicated), dedicated


def _score(package: dict, query: str) -> int:
    if not query:
        return 1
    wanted = query.strip().lower()
    score = 0
    fields = [
        (package["displayName"], 120),
        (package["componentId"], 110),
        (package["skillName"], 100),
        (package["description"], 60),
        (package["category"], 40),
        (package["notes"], 30),
    ]
    for text, weight in fields:
        lowered = str(text).lower()
        if lowered == wanted:
            score = max(score, weight + 40)
        elif lowered.startswith(wanted):
            score = max(score, weight + 20)
        elif wanted in lowered:
            score = max(score, weight)
    tokens = [token for token in re.split(r"\s+", wanted) if token]
    if tokens:
        search = package["searchText"].lower()
        score += 8 * sum(1 for token in tokens if token in search)
    return score


def search(query: str, *, board: dict | None, category: str | None, limit: int) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    items = [item for item in packages() if item["status"] == "ACTIVE"]
    if category:
        wanted = category.strip().upper()
        items = [item for item in items if item["category"].upper() == wanted]
    tokens = _board_tokens(board) if board else set()

    scored = []
    for package in items:
        score = _score(package, query)
        if query and score <= 0:
            continue
        specific, dedicated = _board_specific(package, tokens) if board else (False, False)
        supported = package["electrical"].get("supportedMCUs") or []
        excludes_board = bool(board and supported and not specific)
        if board:
            score += 70 if dedicated else (40 if specific else (-25 if excludes_board else 0))
        scored.append(
            {
                "package": package,
                "score": score,
                "boardSpecific": specific,
                "dedicated": dedicated,
                "excludesBoard": excludes_board,
                "recommended": False,
            }
        )

    # Mark one recommendation per model token when the library has duplicates.
    groups: dict[str, list[dict]] = {}
    for item in scored:
        match = MODEL_RE.search(item["package"]["displayName"])
        if match:
            groups.setdefault(match.group(0), []).append(item)
    for model, group in groups.items():
        if len(group) < 2:
            continue
        group.sort(
            key=lambda item: (
                item["dedicated"] if board else False,
                verification_rank(item["package"]["verificationStatus"]),
                item["score"],
            ),
            reverse=True,
        )
        group[0]["recommended"] = True
        winner = group[0]["package"]
        others = [item["package"] for item in group[1:]]
        detail = ", ".join(
            f"{item['skillName']}({item['verificationStatus']})" for item in [winner, *others]
        )
        warnings.append(
            f"同一型号 {model} 有 {len(group)} 个资料包；推荐 {winner['skillName']}。核对差异：{detail}"
        )
        for package in others:
            if package["verificationStatus"] != winner["verificationStatus"]:
                warnings.append(
                    f"{package['skillName']} 的 verificationStatus 为 {package['verificationStatus']}，不要当作已实测。"
                )
        if board and group[0]["dedicated"]:
            better = next(
                (item for item in group[1:] if verification_rank(item["package"]["verificationStatus"]) > verification_rank(winner["verificationStatus"])),
                None,
            )
            if better:
                warnings.append(
                    f"推荐板级专用包 {winner['skillName']}；{better['package']['skillName']} 的 verificationStatus 更高，但不是当前主控专用包，机械/接线差异仍需核对。"
                )

    scored.sort(
        key=lambda item: (
            -item["score"],
            -verification_rank(item["package"]["verificationStatus"]),
            item["package"]["displayName"],
        )
    )
    results = []
    for item in scored[:limit]:
        package = item["package"]
        results.append(
            {
                "componentId": package["componentId"],
                "skillName": package["skillName"],
                "displayName": package["displayName"],
                "category": package["category"],
                "verificationStatus": package["verificationStatus"],
                "boardSpecific": item["boardSpecific"],
                "dedicated": item["dedicated"],
                "recommended": item["recommended"],
                "score": item["score"],
                "summary": package["description"][:200],
            }
        )
        if item["excludesBoard"]:
            warnings.append(
                f"{package['skillName']} 未声明支持当前主控（supportedMCUs 不含该板）；接入前需核对。"
            )
        if verification_rank(package["verificationStatus"]) == 0:
            warnings.append(
                f"{package['skillName']} 的 verificationStatus 未知：{package['verificationStatus']}；按最低可信度处理。"
            )
    return results, warnings


def catalog_status() -> dict:
    data = env.data_dir()
    cache_path = data / "cache" / "hardware-catalog-v1.json"
    count = None
    generated = None
    if cache_path.is_file():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            candidates = payload.get("candidates")
            count = len(candidates) if isinstance(candidates, list) else None
            generated = payload.get("generatedAt")
        except (OSError, ValueError):
            count = None
    active = [item for item in packages() if item["status"] == "ACTIVE"]
    return {
        "path": str(cache_path),
        "count": count,
        "scanCount": len(active),
        "generatedAt": generated,
        "stale": count is None or count != len(active),
    }
