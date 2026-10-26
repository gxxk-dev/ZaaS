"""Read-only firmware catalog and local image verification."""

from __future__ import annotations

import hashlib
from pathlib import Path

from . import env
from .envelope import CommandResult, ZwError


def _upstream():
    try:
        from zhangwen.web.firmware import PROFILES, firmware_profile
    except ImportError as exc:
        raise ZwError(
            "DEPENDENCY_MISSING",
            f"无法导入固件模块：{exc}",
            "确认 ZW_HOME 完整，并安装 requirements-core.txt。",
            5,
        ) from exc
    return {"PROFILES": PROFILES, "firmware_profile": firmware_profile}


def _profile(component_id: str) -> tuple[dict | None, str | None]:
    """Return the upstream profile or a human-readable reason it is unavailable."""
    try:
        return _upstream()["firmware_profile"](component_id), None
    except KeyError:
        return None, f"掌问固件模块没有该主控的画像：{component_id}"
    except (OSError, ValueError) as exc:
        return None, f"固件清单不可读：{exc}"


def _row(record: dict) -> tuple[dict, str | None]:
    firmware = record.get("firmware") or {}
    profile, error = _profile(record["componentId"])
    image = profile.get("image") if profile else None
    unavailable = profile.get("unavailable") if profile else None
    if error and not unavailable:
        unavailable = error
    row = {
        "boardId": record["componentId"],
        "skillName": record.get("skillName"),
        "displayName": record.get("displayName"),
        "chip": profile.get("chip") if profile else None,
        "offset": profile.get("offset") if profile else firmware.get("offset"),
        "documentation": profile.get("documentation") if profile else None,
        "image": image,
        "installed": bool(firmware.get("installed")),
        "localPath": firmware.get("localPath"),
        "unavailable": unavailable,
        "error": error,
    }
    warning = None
    if unavailable:
        warning = f"{record.get('displayName') or record['componentId']} 的固件镜像不可用：{unavailable}"
    return row, warning


def cmd_list(*, board: str | None = None) -> CommandResult:
    records = [env.resolve_board(board)] if board else env.board_records()
    rows: list[dict] = []
    warnings: list[str] = []
    for record in records:
        row, warning = _row(record)
        rows.append(row)
        if warning:
            warnings.append(warning)
    return CommandResult(data={"count": len(rows), "firmware": rows}, warnings=warnings)


def cmd_get(board: str) -> CommandResult:
    record = env.resolve_board(board)
    profile, error = _profile(record["componentId"])
    warnings: list[str] = []
    if profile is None:
        profile = {
            "boardId": record["componentId"],
            "unavailable": error or "暂无已核实的默认固件。",
            "error": error,
        }
        warnings.append(f"{record['displayName']} 的固件画像不可用：{error}")
    elif profile.get("unavailable"):
        warnings.append(f"{record['displayName']} 的固件镜像不可用：{profile['unavailable']}")
    board_data = {key: value for key, value in record.items() if key != "lookup"}
    return CommandResult(data={"board": board_data, "profile": profile}, warnings=warnings)


def cmd_verify(board: str, *, file: str) -> CommandResult:
    record = env.resolve_board(board)
    profile, error = _profile(record["componentId"])
    if profile is None or not profile.get("image"):
        raise ZwError(
            "FIRMWARE_UNAVAILABLE",
            f"{record['displayName']} 没有可校验的固件镜像。",
            "先用 zw firmware get <board> 查看可用镜像；不要猜测或刷写未核实的文件。",
            4,
            details={
                "boardId": record["componentId"],
                "unavailable": (profile or {}).get("unavailable") or error,
            },
        )

    path = Path(file).expanduser()
    if path.is_symlink():
        raise ZwError(
            "FILE_INVALID",
            f"固件文件不能是符号链接：{path}",
            "传入普通文件；verify 只读比对，不会下载或刷写。",
            4,
        )
    if not path.exists():
        raise ZwError("FILE_NOT_FOUND", f"固件文件不存在：{path}", "", 3)
    if not path.is_file():
        raise ZwError("FILE_INVALID", f"固件路径不是普通文件：{path}", "", 4)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ZwError("FILE_READ_FAILED", f"无法读取固件文件：{path}", str(exc), 7) from exc

    image = profile["image"]
    expected_size = int(image["size"])
    expected_sha256 = str(image["sha256"])
    actual_size = len(data)
    actual_sha256 = hashlib.sha256(data).hexdigest()
    if actual_size != expected_size or actual_sha256 != expected_sha256:
        raise ZwError(
            "FIRMWARE_MISMATCH",
            f"固件文件与 {record['displayName']} 的固定镜像不匹配。",
            "核对文件名与版本；不要用不匹配的镜像刷写设备。",
            4,
            details={
                "boardId": record["componentId"],
                "file": str(path),
                "expectedSize": expected_size,
                "actualSize": actual_size,
                "expectedSha256": expected_sha256,
                "actualSha256": actual_sha256,
                "image": image,
            },
        )
    return CommandResult(
        data={
            "boardId": record["componentId"],
            "file": str(path),
            "size": actual_size,
            "sha256": actual_sha256,
            "image": image,
            "matched": True,
        }
    )
