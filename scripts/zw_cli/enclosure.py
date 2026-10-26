"""``zw enclosure plan/build``: a thin deterministic wrapper over cad_engine.

No model API, no Node, and no writes outside ``--out``.  The request layer is
in :mod:`zw_cli.enclosure_spec`; automatic box dimensioning is in
:mod:`zw_cli.enclosure_sizing`; STEP/STL/GLB building stays upstream.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from . import enclosure_sizing, enclosure_spec, env
from .envelope import CommandResult, ZwError

NOMINAL_WARNINGS = (
    "产物是名义几何；引擎只做 AABB/参数校验，不做打印公差、强度、防水或实物装配验证。",
    "STL 保留装配坐标（上盖/压框未归零到 z=0）。",
    "keepout 只参与校验，不会被挖空。",
    "硬件参考体只出现在 assembly/preview，不是可打印部件。",
)


def _upstream():
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
            "本地掌问缺少 zhangwen.cad_engine",
            "升级掌问到 V0.4.2026.1021.01 或更新版本；enclosure 依赖该引擎。",
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


def cmd_plan(request_value: str) -> CommandResult:
    upstream = _upstream()
    raw = env.load_json_file(request_value)
    request = enclosure_spec.parse_request(raw)
    prepared = enclosure_spec.prepare_request(request)
    plan, _ = _plan(prepared, upstream)
    warnings = _warnings(prepared, plan["autoSize"])
    return CommandResult(data=plan, warnings=warnings)


def cmd_build(
    *,
    request_value: str | None,
    spec_value: str | None,
    out_value: str,
) -> CommandResult:
    upstream = _upstream()
    if (request_value is None) == (spec_value is None):
        raise ZwError(
            "REQUEST_INVALID",
            "build 需要且只能提供 --request 或 --spec",
            "请求模式用 --request，直接构建用 --spec。",
            2,
        )
    out = env.resolve_out(out_value, force=False, allow_in_repo=False)

    if request_value is not None:
        raw = env.load_json_file(request_value)
        request = enclosure_spec.parse_request(raw)
        prepared = enclosure_spec.prepare_request(request)
        plan, spec = _plan(prepared, upstream)
        warnings = _warnings(prepared, plan["autoSize"])
        provenance = plan["provenance"]
        auto_size = plan["autoSize"]
    else:
        spec, layout, report = _spec_from_file(spec_value, upstream)
        plan = _payload_from_spec(spec, layout, report)
        warnings = list(NOMINAL_WARNINGS)
        provenance = []
        auto_size = None

    if not plan["validation"]["ok"]:
        raise _design_error(plan, writes=_out_files(out))

    if not upstream["cadquery_available"]():
        raise ZwError(
            "CAD_RUNTIME_MISSING",
            "未安装 CadQuery/OCP，无法生成 STEP/STL/GLB",
            "用掌问 .venv 或安装 scripts/requirements-cad.txt；zw status --json 可查看依赖。",
            5,
        )

    artifacts = None
    try:
        artifacts = upstream["build_cad_artifacts"](spec, out)
    except upstream["CadDesignRejected"] as exc:
        raise ZwError(
            "DESIGN_INVALID",
            "设计未通过引擎校验",
            "读取 validation.checks 中的 FAIL 项并修正输入。",
            4,
            details={"validation": _dump(exc.report), "spec": _dump(spec)},
            writes=_out_files(out),
        ) from exc
    except upstream["CadGeometryRejected"] as exc:
        raise ZwError(
            "GEOMETRY_INVALID",
            "几何构建或导出校验失败",
            "读取 validation.checks；可能需要放宽参数或更换模板。",
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
            "换一个空目录；enclosure 不支持 --force。",
            6,
            writes=_out_files(out),
        ) from exc
    except ZwError:
        raise
    except ValueError as exc:
        raise ZwError(
            "GEOMETRY_INVALID",
            f"几何参数无效：{exc}",
            "检查尺寸、开孔和放置参数。",
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
            f"CAD 构建失败：{exc}",
            "设 ZW_DEBUG=1 查看堆栈；不要修改掌问文件。",
            7,
            writes=_out_files(out),
        ) from exc

    spec_path = out / "spec.json"
    try:
        spec_path.write_text(
            json.dumps(_dump(spec), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise ZwError(
            "BUILD_IO_FAILED",
            f"无法写入 spec.json：{spec_path}",
            "检查输出目录权限。",
            7,
            writes=_out_files(out),
        ) from exc

    manifest = artifacts.manifest
    names = [entry.file_name for entry in manifest.files] + ["manifest.json", "spec.json"]
    writes = [str(out / name) for name in names]
    data = {
        "design_id": spec.design_id,
        "template": spec.template,
        "out": str(out),
        "files": names,
        "specSha256": manifest.spec_sha256,
        "manifest": _dump(manifest),
        "validation": _dump(artifacts.validation),
        "geometrySummary": _dump(artifacts.geometry_summary),
        "spec": _dump(spec),
        "provenance": provenance,
        "autoSize": auto_size,
    }
    return CommandResult(data=data, warnings=warnings, writes=writes)


def _plan(prepared: enclosure_spec.PreparedRequest, upstream) -> tuple[dict[str, Any], Any]:
    if prepared.template == "component_mount":
        spec = _build_spec(prepared)
        layout, report = _layout_and_validate(upstream, spec)
        payload = _payload_from_spec(spec, layout, report)
        payload["provenance"] = prepared.provenance
        payload["autoSize"] = None
        if not report.ok:
            raise _design_error(payload)
        return payload, spec

    # Fail fast on engine contract problems (disallowed surfaces, duplicate
    # identifiers, unknown standoff targets) before auto-sizing.
    _build_spec(prepared, prepared.enclosure)
    sizing = enclosure_sizing.size_box(
        prepared.enclosure,
        components=[
            enclosure_sizing.SizingComponent(
                profile=component.profile,
                instance_id=component.instance_id,
                surface=component.surface,
                center=component.center,
                rotation_z_deg=component.rotation_z_deg,
            )
            for component in prepared.components
        ],
        standoffs=prepared.standoffs,
        missing=prepared.auto_missing,
        explicit=prepared.auto_explicit,
        options=enclosure_sizing.SizingOptions(
            enabled=prepared.auto_enabled,
            axes=tuple(prepared.auto_size.axes),
            grid_mm=prepared.auto_size.grid_mm,
            max_iterations=prepared.auto_size.max_iterations,
            clearance_margin_mm=prepared.auto_size.clearance_margin_mm,
        ),
        build_spec=lambda parameters: _build_spec(prepared, parameters),
        evaluate=lambda spec: _evaluate(upstream, spec),
    )
    auto_size = {
        "enabled": prepared.auto_enabled,
        "applied": bool(prepared.auto_enabled and any(prepared.auto_missing.values())),
        "axes": list(prepared.auto_size.axes),
        "grid_mm": prepared.auto_size.grid_mm,
        "max_iterations": prepared.auto_size.max_iterations,
        "clearance_margin_mm": prepared.auto_size.clearance_margin_mm,
        "missing": prepared.auto_missing,
        "explicit": prepared.auto_explicit,
        "iterations": sizing.iterations,
        "final": sizing.dimensions,
        "warnings": sizing.warnings,
    }
    if not sizing.ok:
        auto_size["failingChecks"] = sorted(sizing.failing_checks)
        details = {
            "autoSize": auto_size,
            "provenance": prepared.provenance,
            "failingChecks": sorted(sizing.failing_checks),
            "dimensions": sizing.dimensions,
        }
        if sizing.last_report is not None:
            details["validation"] = _dump(sizing.last_report)
        if sizing.limit_reached:
            raise ZwError(
                "AUTO_SIZE_LIMIT",
                "自动尺寸达到增长上限仍未通过校验",
                "显式给出更大的 inner_length_x/width_y/height_z，或减少器件/调整安装面。",
                4,
                details=details,
            )
        raise ZwError(
            "DESIGN_INVALID",
            "自动尺寸未能通过引擎校验："
            + (", ".join(sorted(sizing.failing_checks)) or "unknown"),
            "读取 details 中的校验/尺寸；结构性失败不要靠继续加大盒体掩盖。",
            4,
            details=details,
        )

    spec = _build_spec(prepared, sizing.parameters)
    layout, report = _layout_and_validate(upstream, spec)
    payload = _payload_from_spec(spec, layout, report)
    payload["provenance"] = prepared.provenance
    payload["autoSize"] = auto_size
    if not report.ok:
        raise _design_error(payload)
    return payload, spec


def _layout_and_validate(upstream, spec):
    try:
        layout = upstream["resolve_layout"](spec)
        return layout, upstream["validate_design"](spec, layout)
    except ValueError as exc:
        raise ZwError(
            "REQUEST_INVALID",
            f"布局约束不兼容：{exc}",
            "检查 surface/center/standoffs 是否满足引擎约束。",
            2,
            details={"spec": _dump(spec)},
        ) from exc


def _evaluate(upstream, spec):
    return _layout_and_validate(upstream, spec)[1]


def _build_spec(prepared: enclosure_spec.PreparedRequest, parameters: Any | None = None):
    try:
        return enclosure_spec.build_cad_spec(prepared, parameters)
    except ValidationError as exc:
        raise ZwError(
            "REQUEST_INVALID",
            "外壳规格与引擎约束不一致",
            "检查 surface 是否被 profile 允许、标识符是否重复、standoffs 引用是否存在。",
            2,
            details={"errors": enclosure_spec._error_details(exc)},
        ) from exc


def _spec_from_file(spec_value: str | None, upstream):
    raw = env.load_json_file(spec_value or "")
    try:
        spec = upstream["CadBuildSpec"].model_validate(raw)
    except ValidationError as exc:
        raise ZwError(
            "SPEC_INVALID",
            "CadBuildSpec 无效",
            "按掌问 cad_engine 的 CadBuildSpec schema 修正；请求模式请用 --request。",
            2,
            details={"errors": enclosure_spec._error_details(exc)},
        ) from exc
    try:
        layout = upstream["resolve_layout"](spec)
        report = upstream["validate_design"](spec, layout)
    except ValueError as exc:
        raise ZwError(
            "SPEC_INVALID",
            f"CadBuildSpec 与布局约束不兼容：{exc}",
            "检查 surface/center/standoffs 是否满足引擎约束。",
            2,
            details={"spec": _dump(spec)},
        ) from exc
    return spec, layout, report


def _payload_from_spec(spec, layout, report) -> dict[str, Any]:
    return {
        "design_id": spec.design_id,
        "template": spec.template,
        "spec": _dump(spec),
        "layout": _dump(layout),
        "validation": _dump(report),
        "questions": [],
    }


def _design_error(plan: dict[str, Any], *, writes: list[str] | None = None) -> ZwError:
    failing = [
        check.get("check_id")
        for check in (plan.get("validation") or {}).get("checks", [])
        if str(check.get("status")) == "fail"
    ]
    return ZwError(
        "DESIGN_INVALID",
        "设计未通过引擎校验：" + (", ".join(failing) or "unknown"),
        "读取 validation.checks 中的 FAIL 项并修正输入；不要靠加大盒体掩盖结构性失败。",
        4,
        details={
            "validation": plan.get("validation"),
            "spec": plan.get("spec"),
            "autoSize": plan.get("autoSize"),
            "provenance": plan.get("provenance"),
        },
        writes=writes,
    )


def _warnings(prepared: enclosure_spec.PreparedRequest, auto_size: dict[str, Any] | None) -> list[str]:
    values = list(NOMINAL_WARNINGS)
    values.extend(prepared.warnings)
    if auto_size and auto_size.get("warnings"):
        values.extend(auto_size["warnings"])
    if prepared.template == "component_mount":
        values.append("component_mount 的 lid 实际是压框（retainer），不是上盖。")
    if any(component.derived for component in prepared.components):
        values.append("派生安装方式由包装层推断，必须实物验证。")
    if auto_size and auto_size.get("applied"):
        values.append("自动尺寸是 zw 包装层行为，不是上游引擎行为。")
    seen: set[str] = set()
    unique = []
    for value in values:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def _dump(model) -> Any:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model


def _out_files(out: Path) -> list[str]:
    try:
        if not out.is_dir():
            return []
        return sorted(str(path) for path in out.iterdir() if path.is_file())
    except OSError:
        return []


def _profile_payload(profile, *, source: str) -> dict[str, Any]:
    model_kind = getattr(profile, "model_kind", None)
    return {
        "profileId": profile.profile_id,
        "displayName": profile.display_name,
        "category": profile.category,
        "roles": list(profile.roles),
        "source": source,
        "revision": profile.revision,
        "dimensions": _dump(profile.dimensions),
        "mounting": _dump(profile.mounting),
        "modelKind": getattr(model_kind, "value", model_kind),
    }


def cmd_profiles() -> CommandResult:
    """List only profiles the enclosure engine can actually resolve."""
    try:
        from zhangwen.cad_engine.profiles import trusted_profiles
    except ImportError as exc:
        raise ZwError(
            "DEPENDENCY_MISSING",
            f"无法导入 zhangwen.cad_engine.profiles：{exc}",
            "升级掌问到 V0.4.2026.1021.01 或更新版本。",
            5,
        ) from exc

    warnings: list[str] = []
    trusted = list(trusted_profiles())
    trusted_ids = {profile.profile_id for profile in trusted}
    profiles = [
        _profile_payload(profile, source="trusted") for profile in trusted
    ]
    try:
        mechanical = enclosure_spec._mechanical_index(warnings)
    except ImportError as exc:
        raise ZwError(
            "DEPENDENCY_MISSING",
            f"无法读取资料包机械 profile：{exc}",
            "检查掌问核心依赖与资料包索引。",
            5,
        ) from exc

    shadowed_ids: set[str] = set()
    for profile_id in sorted(mechanical):
        entries = mechanical[profile_id]
        signatures = {
            json.dumps(profile.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
            for _, profile in entries
        }
        ambiguous = len(signatures) > 1
        if ambiguous:
            packages = ", ".join(
                str(package.get("skillName")) for package, _ in entries
            )
            warnings.append(
                f"profile_id {profile_id} 在多个资料包中内容不一致（{packages}）；"
                "enclosure 会拒绝该 id，请改用 component_id 或内联 profile。"
            )
        if profile_id in trusted_ids:
            shadowed_ids.add(profile_id)
        for package, profile in sorted(
            entries, key=lambda item: str(item[0].get("skillName") or "")
        ):
            item = _profile_payload(profile, source="package-mechanical")
            item.update(
                {
                    "componentId": package.get("componentId"),
                    "skillName": package.get("skillName"),
                    "verificationStatus": package.get("verificationStatus"),
                    "ambiguous": ambiguous,
                    "shadowed": profile_id in trusted_ids,
                }
            )
            profiles.append(item)

    if shadowed_ids:
        warnings.append(
            "以下 profile_id 同时由 trusted 与资料包声明："
            + ", ".join(sorted(shadowed_ids))
            + "；enclosure 优先使用 trusted，资料包条目仅作参考。"
        )
    warnings.append("verificationStatus 是资料包的声明值，不等同于已实测或已联调。")
    if not profiles:
        warnings.append("没有可用的 enclosure profile。")
    return CommandResult(data={"count": len(profiles), "profiles": profiles}, warnings=warnings)
