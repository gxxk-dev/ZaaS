"""Trusted freeform build: engine artifacts plus ZaaS spec/request sidecars."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from . import env, freeform
from .envelope import CommandResult, ZwError

BUILD_WARNING = (
    "freeform 必须形成单一连通实体；cut 必须与当前实体相交且不能删空。"
    "STL/STEP 使用建模坐标；未做打印公差、强度或实物装配验证。"
)


def _build_upstream() -> dict:
    try:
        from zhangwen.cad_engine import (
            CadBuildSpec,
            CadDesignRejected,
            CadGeometryRejected,
            CadRuntimeUnavailable,
            build_cad_artifacts,
            cadquery_available,
            resolve_layout,
            validate_design,
        )
    except ImportError as exc:
        raise ZwError(
            "DEPENDENCY_MISSING",
            f"本地掌问缺少 zhangwen.cad_engine：{exc}",
            "升级掌问到 V0.4.2026.1021.01 或更新版本；freeform build 依赖该引擎。",
            5,
        ) from exc
    return {
        "CadBuildSpec": CadBuildSpec,
        "CadDesignRejected": CadDesignRejected,
        "CadGeometryRejected": CadGeometryRejected,
        "CadRuntimeUnavailable": CadRuntimeUnavailable,
        "build_cad_artifacts": build_cad_artifacts,
        "cadquery_available": cadquery_available,
        "resolve_layout": resolve_layout,
        "validate_design": validate_design,
    }


def _out_files(out: Path) -> list[str]:
    try:
        if not out.is_dir():
            return []
        return sorted(str(path) for path in out.iterdir() if path.is_file())
    except OSError:
        return []


def _write_json(path: Path, value: Any) -> str:
    try:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise ZwError(
            "BUILD_IO_FAILED",
            f"无法写入 {path.name}：{exc}",
            "检查输出目录权限和磁盘空间。",
            7,
            writes=_out_files(path.parent),
        ) from exc
    return str(path)


def cmd_build(
    *,
    request_value: str | None,
    spec_value: str | None,
    out_value: str,
) -> CommandResult:
    if (request_value is None) == (spec_value is None):
        raise ZwError(
            "REQUEST_INVALID",
            "freeform build 需要且只能提供 --request 或 --spec。",
            "请求模式用 --request，受信规格用 --spec。",
            2,
        )
    upstream = _build_upstream()
    out = env.resolve_out(out_value, force=False, allow_in_repo=False)

    request_payload: dict[str, Any] | None = None
    if request_value is not None:
        raw = env.load_json_file(request_value)
        request_payload = freeform.parse_request(raw)
        spec = freeform.build_spec(upstream, freeform.spec_data(request_payload))
        freeform.plan_spec(upstream, spec)
        text_operations: list[dict[str, Any]] = []
    else:
        raw = env.load_json_file(spec_value or "")
        spec, text_operations = freeform.load_spec(upstream, raw)

    wrapper = freeform.spec_wrapper(spec, text_operations)
    spec_sha256 = sha256(freeform.canonical_json_bytes(wrapper)).hexdigest()
    if not upstream["cadquery_available"]():
        raise ZwError(
            "CAD_RUNTIME_MISSING",
            "未安装 CadQuery/OCP，无法生成 STEP/STL/GLB",
            "用掌问 .venv 或安装 scripts/requirements-cad.txt；zw status --json 可查看依赖。",
            5,
        )

    try:
        artifacts = upstream["build_cad_artifacts"](
            spec,
            out,
            manifest_spec_sha256=spec_sha256,
        )
    except upstream["CadDesignRejected"] as exc:
        raise ZwError(
            "DESIGN_INVALID",
            "freeform 设计未通过引擎校验",
            "读取 validation.checks 中的 FAIL 项并修正输入。",
            4,
            details={"validation": _dump(exc.report), "spec": _dump(spec)},
            writes=_out_files(out),
        ) from exc
    except upstream["CadGeometryRejected"] as exc:
        raise ZwError(
            "GEOMETRY_INVALID",
            "freeform 几何构建或导出校验失败",
            "确认所有 add 连通、cut 与实体相交且没有删空，并读取 validation.checks。",
            4,
            details={"validation": _dump(exc.report), "spec": _dump(spec)},
            writes=_out_files(out),
        ) from exc
    except upstream["CadRuntimeUnavailable"] as exc:
        raise ZwError(
            "CAD_RUNTIME_MISSING",
            "CAD 运行时不可用",
            "用掌问 .venv 或安装 scripts/requirements-cad.txt。",
            5,
            writes=_out_files(out),
        ) from exc
    except ImportError as exc:
        raise ZwError(
            "CAD_RUNTIME_MISSING",
            "CAD 运行时缺少 OCP/CadQuery 组件",
            "用掌问 .venv 或安装 scripts/requirements-cad.txt。",
            5,
            writes=_out_files(out),
        ) from exc
    except FileExistsError as exc:
        raise ZwError(
            "OUT_NOT_EMPTY",
            f"输出目录在构建前已被写入：{out}",
            "换一个空目录；freeform build 不支持 --force。",
            6,
            writes=_out_files(out),
        ) from exc
    except ZwError:
        raise
    except ValueError as exc:
        raise ZwError(
            "GEOMETRY_INVALID",
            f"freeform 几何参数无效：{exc}",
            "检查 primitive 尺寸、坐标和布尔顺序。",
            4,
            details={"spec": _dump(spec)},
            writes=_out_files(out),
        ) from exc
    except OSError as exc:
        raise ZwError(
            "BUILD_IO_FAILED",
            f"写入产物失败：{exc}",
            "检查输出目录权限和磁盘空间。",
            7,
            writes=_out_files(out),
        ) from exc
    except Exception as exc:  # noqa: BLE001 - upstream boundary
        raise ZwError(
            "BUILD_FAILED",
            f"freeform CAD 构建失败：{exc}",
            "设 ZW_DEBUG=1 查看堆栈；不要修改掌问文件。",
            7,
            writes=_out_files(out),
        ) from exc

    spec_file = _write_json(out / "spec.json", wrapper)
    names = [entry.file_name for entry in artifacts.manifest.files] + ["spec.json"]
    request_file = None
    if request_payload is not None:
        request_file = _write_json(out / "request.json", request_payload)
        names.append("request.json")

    data = {
        "design_id": spec.design_id,
        "template": spec.template,
        "out": str(out),
        "files": names,
        "specSha256": artifacts.manifest.spec_sha256,
        "manifest": _dump(artifacts.manifest),
        "validation": _dump(artifacts.validation),
        "geometrySummary": _dump(artifacts.geometry_summary),
        "spec": _dump(spec),
        "request": request_payload,
    }
    writes = [str(out / name) for name in names]
    warnings = [freeform.NOMINAL_WARNING, BUILD_WARNING]
    return CommandResult(data=data, warnings=warnings, writes=writes)


def _dump(model) -> Any:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model
