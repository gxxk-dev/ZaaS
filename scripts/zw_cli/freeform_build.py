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
            CadBuildArtifacts,
            CadBuildSpec,
            CadDesignRejected,
            CadGeometryRejected,
            CadRuntimeUnavailable,
            build_cad_artifacts,
            cadquery_available,
            resolve_layout,
            validate_design,
        )
        from zhangwen.cad_engine.exports import (
            export_geometry,
            write_manifest,
            write_snapshots,
        )
        from zhangwen.cad_engine.geometry import CadGeometry, GeometryPart, build_geometry
        from zhangwen.cad_engine.validation import (
            merge_validation_reports,
            validate_brep_parts,
            validate_step_round_trip,
            validate_stl_meshes,
        )
        from zhangwen.web import solid_text
    except ImportError as exc:
        raise ZwError(
            "DEPENDENCY_MISSING",
            f"本地掌问缺少 zhangwen.cad_engine：{exc}",
            "升级掌问到 V0.4.2026.1021.01 或更新版本；freeform build 依赖该引擎。",
            5,
        ) from exc
    return {
        "CadBuildArtifacts": CadBuildArtifacts,
        "CadBuildSpec": CadBuildSpec,
        "CadDesignRejected": CadDesignRejected,
        "CadGeometryRejected": CadGeometryRejected,
        "CadRuntimeUnavailable": CadRuntimeUnavailable,
        "build_cad_artifacts": build_cad_artifacts,
        "cadquery_available": cadquery_available,
        "resolve_layout": resolve_layout,
        "validate_design": validate_design,
        "export_geometry": export_geometry,
        "write_manifest": write_manifest,
        "write_snapshots": write_snapshots,
        "CadGeometry": CadGeometry,
        "GeometryPart": GeometryPart,
        "build_geometry": build_geometry,
        "merge_validation_reports": merge_validation_reports,
        "validate_brep_parts": validate_brep_parts,
        "validate_step_round_trip": validate_step_round_trip,
        "validate_stl_meshes": validate_stl_meshes,
        "solid_text": solid_text,
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


def _apply_text_operations(
    upstream: dict,
    geometry,
    operations: list[dict[str, Any]],
    out: Path,
):
    parts = geometry.printable_parts
    if len(parts) != 1:
        raise ZwError(
            "GEOMETRY_INVALID",
            "freeform 文字操作需要恰好一个可打印实体。",
            "先修正几何 operations；文字只作用于唯一的 freeform 实体。",
            4,
            details={"printableParts": len(parts)},
            writes=_out_files(out),
        )
    part = parts[0]
    shape = part.shape
    for operation in operations:
        try:
            text_piece = upstream["solid_text"].piece(operation)
        except OSError as exc:
            raise ZwError(
                "DEPENDENCY_MISSING",
                f"无法读取掌问字体：{exc}",
                "确认 $ZW_HOME/resources/fonts/NotoSansSC.ttf 存在。",
                5,
                writes=_out_files(out),
            ) from exc
        except ValueError as exc:
            raise ZwError(
                "TEXT_INVALID",
                f"文字无法雕刻：{exc}",
                "检查文字内容、字号、深度和位置；不要使用字体缺失的字符。",
                4,
                details={"operation": operation},
                writes=_out_files(out),
            ) from exc
        except Exception as exc:  # noqa: BLE001 - upstream boundary
            raise ZwError(
                "GEOMETRY_INVALID",
                f"文字轮廓生成失败：{exc}",
                "确认文字平面与实体面一致，并读取 validation.checks。",
                4,
                details={"operation": operation},
                writes=_out_files(out),
            ) from exc

        before = float(shape.Volume())
        try:
            cutter = text_piece.val()
            result = (
                shape.cut(cutter)
                if operation["operation"] == "cut"
                else shape.fuse(cutter)
            )
            result = result.clean()
            solids = result.Solids()
            after = float(result.Volume())
        except Exception as exc:  # noqa: BLE001 - upstream boundary
            raise ZwError(
                "GEOMETRY_INVALID",
                f"文字布尔运算失败：{exc}",
                "确认文字落在实体面上、深度小于板厚，并读取 validation.checks。",
                4,
                details={"operation": operation},
                writes=_out_files(out),
            ) from exc
        if len(solids) != 1:
            raise ZwError(
                "GEOMETRY_INVALID",
                "文字操作后不再是单一连通实体。",
                "调整文字位置或改用 cut；freeform 必须保持一个连通实体。",
                4,
                details={"operation": operation, "solidCount": len(solids)},
                writes=_out_files(out),
            )
        if operation["operation"] == "cut" and before - after <= 1e-6:
            raise ZwError(
                "TEXT_NO_EFFECT",
                "文字 cut 没有减少实体体积。",
                "把文字移到实体表面并确认深度足够；不要只让文字悬空。",
                4,
                details={"operation": operation, "before": before, "after": after},
                writes=_out_files(out),
            )
        if operation["operation"] == "add" and after - before <= 1e-6:
            raise ZwError(
                "TEXT_NO_EFFECT",
                "文字 add 没有增加实体体积。",
                "把文字移到实体表面并确认浮雕方向。",
                4,
                details={"operation": operation, "before": before, "after": after},
                writes=_out_files(out),
            )
        shape = result

    new_part = upstream["GeometryPart"](
        part_id=part.part_id,
        role=part.role,
        shape=shape,
        color_rgba=part.color_rgba,
    )
    return upstream["CadGeometry"](printable=(new_part,))


def _build_with_text(
    upstream: dict,
    spec,
    text_operations: list[dict[str, Any]],
    out: Path,
    spec_sha256: str,
):
    layout = upstream["resolve_layout"](spec)
    design_report = upstream["validate_design"](spec, layout)
    if not design_report.ok:
        raise upstream["CadDesignRejected"](design_report)

    if out.exists() and any(out.iterdir()):
        raise FileExistsError("CAD artifact directory must be empty")
    out.mkdir(parents=True, exist_ok=True)

    geometry = upstream["build_geometry"](spec, layout)
    geometry = _apply_text_operations(upstream, geometry, text_operations, out)
    brep_report = upstream["validate_brep_parts"](
        (part.part_id, part.shape) for part in geometry.parts
    )
    if not brep_report.ok:
        raise upstream["CadGeometryRejected"](
            upstream["merge_validation_reports"](design_report, brep_report)
        )

    geometry_exports = upstream["export_geometry"](geometry, out)
    step_report = upstream["validate_step_round_trip"](out / "assembly.step")
    stl_report = upstream["validate_stl_meshes"](
        tuple(out / f"{part.part_id}.stl" for part in geometry.printable_parts)
    )
    final_report = upstream["merge_validation_reports"](
        design_report,
        brep_report,
        step_report,
        stl_report,
    )
    snapshot_files = upstream["write_snapshots"](
        spec=spec,
        report=final_report,
        summary=geometry_exports.summary,
        output_directory=out,
    )
    if not final_report.ok:
        raise upstream["CadGeometryRejected"](final_report)

    manifest_file, manifest = upstream["write_manifest"](
        spec=spec,
        files=(*geometry_exports.files, *snapshot_files),
        output_directory=out,
        manifest_design_id=None,
        manifest_spec_sha256=spec_sha256,
    )
    return upstream["CadBuildArtifacts"](
        output_directory=out,
        manifest_file=manifest_file,
        manifest=manifest,
        validation=final_report,
        geometry_summary=geometry_exports.summary,
        layout=layout,
    )


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
        text_operations = freeform.text_operations(request_payload)
        if text_operations:
            text_operations = freeform.validate_text_operations(
                freeform.text_upstream(), text_operations
            )
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
        if text_operations:
            artifacts = _build_with_text(
                upstream, spec, text_operations, out, spec_sha256
            )
        else:
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

    _write_json(out / "spec.json", wrapper)
    names = [entry.file_name for entry in artifacts.manifest.files] + [
        "manifest.json",
        "spec.json",
    ]
    if request_payload is not None:
        _write_json(out / "request.json", request_payload)
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
