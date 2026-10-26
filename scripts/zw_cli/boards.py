"""Board list and read-only Board Skill details."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import env
from .envelope import CommandResult, ZwError

ENTRY_MAX_CHARS = 16_000
FILE_MAX_CHARS = 200_000
LEGACY_REQUIRED = "CHECKSUMS.sha256"


@dataclass
class SkillView:
    data: dict
    layout: str
    package: object | None = None
    repo: object | None = None
    profile_id: str | None = None
    directory: Path | None = None
    declared: object | None = None


def _board_skills():
    try:
        from zhangwen.hardware.board_skills import (
            BoardSkillNotFoundError,
            BoardSkillRepository,
            BoardSkillValidationError,
        )
    except ImportError as exc:
        raise ZwError(
            "DEPENDENCY_MISSING",
            f"无法导入 Board Skill 模块：{exc}",
            "确认 ZW_HOME 完整，并安装 requirements-core.txt。",
            5,
        ) from exc
    return {
        "Repository": BoardSkillRepository,
        "NotFound": BoardSkillNotFoundError,
        "Invalid": BoardSkillValidationError,
    }


def _board_data(record: dict) -> dict:
    return {key: value for key, value in record.items() if key != "lookup"}


def _safe_legacy_path(directory: Path, value: object) -> tuple[str, Path]:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError(f"非法路径：{value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"非法路径：{value!r}")
    candidate = directory.joinpath(*path.parts)
    try:
        resolved = candidate.resolve(strict=True)
        root = directory.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"文件不存在：{value}") from exc
    if not resolved.is_relative_to(root) or candidate.is_symlink() or not candidate.is_file():
        raise ValueError(f"不是包内普通文件：{value}")
    for parent in candidate.parents:
        if parent == directory:
            break
        if parent.is_symlink():
            raise ValueError(f"目录包含符号链接：{value}")
    return path.as_posix(), candidate


def _legacy_view(package_dir: Path) -> SkillView:
    manifest_path = package_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ZwError(
            "BOARD_SKILL_INVALID",
            f"Board Skill manifest 无效：{package_dir.name}",
            str(exc),
            7,
        ) from exc
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ZwError(
            "BOARD_SKILL_INVALID",
            f"Board Skill manifest 缺少 files：{package_dir.name}",
            "旧版 manifest 的 files 必须是非空字符串列表。",
            7,
        )
    declared: dict[str, Path] = {}
    files: list[dict] = []
    for value in raw_files:
        try:
            relative, candidate = _safe_legacy_path(package_dir, value)
            content = candidate.read_bytes()
        except ValueError as exc:
            raise ZwError(
                "BOARD_SKILL_INVALID",
                f"Board Skill 文件无效：{package_dir.name}",
                str(exc),
                7,
            ) from exc
        except OSError as exc:
            raise ZwError(
                "BOARD_SKILL_INVALID",
                f"Board Skill 文件不可读：{package_dir.name}",
                str(exc),
                7,
            ) from exc
        declared[relative] = candidate
        files.append(
            {
                "path": relative,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )

    paths = [item["path"] for item in files]
    reference_count = sum(
        1 for path in paths if path.startswith("references/") and path.endswith(".md")
    )
    template_count = sum(
        1 for path in paths if path.startswith("templates/") and path.endswith(".py")
    )
    example_count = len(
        {
            PurePosixPath(path).parts[1]
            for path in paths
            if path.startswith("examples/") and path.endswith("/main.py")
        }
    )
    revision = manifest.get("revision") or manifest.get("version") or ""
    summary = {
        "id": manifest.get("skillName") or package_dir.name,
        "name": manifest.get("skillName") or package_dir.name,
        "version": revision,
        "profileId": package_dir.name,
        "target": manifest.get("displayName") or manifest.get("componentId") or "",
        "runtime": "MicroPython",
        "referenceCount": reference_count,
        "templateCount": template_count,
        "exampleCount": example_count,
        "syntaxValidated": False,
        "hardwareValidated": False,
        "revision": revision,
        "status": manifest.get("status"),
        "sourceKind": manifest.get("sourceKind"),
        "description": manifest.get("description", ""),
    }
    return SkillView(
        data={
            "layout": "legacy",
            "verified": False,
            "summary": summary,
            "manifest": manifest,
            "files": files,
        },
        layout="legacy",
        directory=package_dir,
        declared=declared,
    )


def _load_skill(record: dict, warnings: list[str]) -> SkillView | None:
    board_skill_path = record.get("boardSkillPath")
    if not board_skill_path:
        warnings.append(f"{record['displayName']} 没有 Board Skill。")
        return None
    entry_path = Path(board_skill_path)
    package_dir = entry_path.parent
    if not (package_dir / LEGACY_REQUIRED).is_file():
        view = _legacy_view(package_dir)
        warnings.append(
            f"{record['displayName']} 的 Board Skill 是 legacy 布局：没有 CHECKSUMS.sha256，"
            "只能按清单计算摘要，verified=false。"
        )
        return view

    mods = _board_skills()
    repo = mods["Repository"](root=package_dir.parent)
    profile_id = package_dir.name
    try:
        package = repo.package_for_profile(profile_id)
    except mods["NotFound"]:
        warnings.append(f"{record['displayName']} 没有可用的 Board Skill 包。")
        return None
    except mods["Invalid"] as exc:
        raise ZwError(
            "BOARD_SKILL_INVALID",
            f"Board Skill 校验失败：{profile_id}",
            str(exc),
            7,
        ) from exc
    return SkillView(
        data={
            "layout": "strict",
            "verified": True,
            "summary": package.summary.model_dump(mode="json"),
            "manifest": package.manifest.model_dump(mode="json"),
            "files": [item.model_dump(mode="json") for item in package.manifest.files],
        },
        layout="strict",
        package=package,
        repo=repo,
        profile_id=profile_id,
        directory=package_dir,
        declared=package.declared_paths,
    )


def _read_declared(view: SkillView, path: str, *, max_chars: int) -> str:
    if view.layout == "strict":
        if path not in (view.declared or set()):
            raise ZwError("FILE_NOT_FOUND", f"Board Skill 中没有文件：{path}", "", 3)
        mods = _board_skills()
        try:
            return view.package.read_text(path, max_chars=max_chars)
        except mods["Invalid"] as exc:
            message = str(exc)
            if "UTF-8" in message or "上限" in message:
                raise ZwError("FILE_INVALID", f"Board Skill 文件无法读取：{path}", message, 4) from exc
            if "不存在" in message:
                raise ZwError("FILE_READ_FAILED", f"Board Skill 文件读取失败：{path}", message, 7) from exc
            raise ZwError("BOARD_SKILL_INVALID", f"Board Skill 文件校验失败：{path}", message, 7) from exc

    declared = view.declared or {}
    candidate = declared.get(path)
    if candidate is None:
        raise ZwError("FILE_NOT_FOUND", f"Board Skill 中没有文件：{path}", "", 3)
    try:
        content = candidate.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ZwError("FILE_INVALID", f"Board Skill 文件不是 UTF-8：{path}", str(exc), 4) from exc
    except OSError as exc:
        raise ZwError("FILE_READ_FAILED", f"Board Skill 文件读取失败：{path}", str(exc), 7) from exc
    if len(content) > max_chars:
        raise ZwError(
            "FILE_INVALID",
            f"Board Skill 文件超过上限：{path}",
            f"上限 {max_chars} 字符。",
            4,
        )
    return content


def _entry(view: SkillView, warnings: list[str]) -> dict | None:
    try:
        content = _read_declared(view, "SKILL.md", max_chars=ENTRY_MAX_CHARS)
    except ZwError as exc:
        warnings.append(f"Board Skill 入口不可用：{exc.message}")
        return None
    return {
        "path": "SKILL.md",
        "content": content,
        "bytes": len(content.encode("utf-8")),
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }


def _file(view: SkillView, path: str) -> dict:
    content = _read_declared(view, path, max_chars=FILE_MAX_CHARS)
    return {
        "path": path,
        "content": content,
        "bytes": len(content.encode("utf-8")),
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }


def _programming_context(record: dict, warnings: list[str]) -> dict | None:
    try:
        from zhangwen.web.programming import programming_context
    except ImportError as exc:
        raise ZwError(
            "DEPENDENCY_MISSING",
            f"无法导入编程参考模块：{exc}",
            "确认 ZW_HOME 完整。",
            5,
        ) from exc
    try:
        markdown = programming_context(record["componentId"])
    except OSError as exc:
        warnings.append(f"{record['displayName']} 的编程参考不可用：{exc}")
        return None
    if not markdown:
        warnings.append(f"{record['displayName']} 没有板级编程参考。")
        return None
    encoded = markdown.encode("utf-8")
    return {
        "markdown": markdown,
        "bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _full(record: dict, *, file_path: str | None) -> CommandResult:
    warnings: list[str] = []
    view = _load_skill(record, warnings)
    entry = _entry(view, warnings) if view else None
    file_record = None
    if file_path:
        if view is None:
            raise ZwError(
                "FILE_NOT_FOUND",
                f"{record['displayName']} 没有 Board Skill，不能读取文件：{file_path}",
                "先查看 zw boards --json 的 hasBoardSkill。",
                3,
            )
        file_record = _file(view, file_path)
    context = _programming_context(record, warnings)
    data = {
        "board": _board_data(record),
        "skill": view.data if view else None,
        "entry": entry,
        "file": file_record,
        "programmingContext": context,
    }
    return CommandResult(data=data, warnings=warnings)


def _context(record: dict, query: str) -> CommandResult:
    warnings: list[str] = []
    view = _load_skill(record, warnings)
    if view is None or view.layout != "strict":
        layout = view.layout if view else None
        raise ZwError(
            "BOARD_SKILL_CONTEXT_UNAVAILABLE",
            f"{record['displayName']} 没有可用的 strict Board Skill 上下文。",
            "K10/XIAO 使用 strict 布局；legacy 包只支持 --full/--file。",
            4,
            details={"layout": layout},
        )
    mods = _board_skills()
    try:
        payload = view.repo.build_context(view.profile_id, query)
    except mods["NotFound"] as exc:
        raise ZwError(
            "BOARD_SKILL_CONTEXT_UNAVAILABLE",
            f"{record['displayName']} 没有可用的 Board Skill 上下文。",
            "先检查 Board Skill 包是否完整。",
            4,
            details={"layout": view.layout},
        ) from exc
    except mods["Invalid"] as exc:
        raise ZwError(
            "BOARD_SKILL_INVALID",
            f"Board Skill 上下文校验失败：{view.profile_id}",
            str(exc),
            7,
        ) from exc
    return CommandResult(
        data={"board": _board_data(record), "query": query, **payload},
        warnings=warnings,
    )


def cmd_boards(
    *,
    board: str | None = None,
    full: bool = False,
    file_path: str | None = None,
    context: str | None = None,
) -> CommandResult:
    if file_path and not full:
        raise ZwError("REQUEST_INVALID", "--file 必须与 --full 同用。", "", 2)
    if (full or file_path or context) and not board:
        raise ZwError("REQUEST_INVALID", "--full/--file/--context 必须与 --board 同用。", "", 2)
    if context and (full or file_path):
        raise ZwError("REQUEST_INVALID", "--context 不能与 --full/--file 同用。", "", 2)

    if not full and not file_path and not context:
        records = [env.resolve_board(board)] if board else env.board_records()
        warnings = []
        for record in records:
            if not record["skillName"]:
                warnings.append(f"{record['displayName']} 缺少硬件资料包（{record['componentId']}）。")
            if record["firmware"] and not record["firmware"].get("installed"):
                warnings.append(f"{record['displayName']} 的固件镜像未下载到 resources/firmware。")
        data = {
            "count": len(records),
            "boards": [_board_data(record) for record in records],
        }
        return CommandResult(data=data, warnings=warnings)

    record = env.resolve_board(board or "")
    if context is not None:
        return _context(record, context)
    return _full(record, file_path=file_path)
