"""Strict request models and profile resolution for ``zw enclosure``.

The request layer is deliberately thinner than the upstream CAD engine: it
only turns component identifiers into reviewed ``HardwareProfile`` objects,
applies the documented centre/surface semantics, and refuses to invent
mechanical dimensions.  All geometry stays in :mod:`zhangwen.cad_engine`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from . import hardware, index
from .envelope import ZwError

REQUEST_SCHEMA = "zw.enclosure-request/v1"
IDENTIFIER_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"
_IDENTIFIER_RE = re.compile(IDENTIFIER_PATTERN)

Template = Literal["box_with_lid", "component_mount"]
Surface = Literal[
    "base_floor",
    "lid_inner",
    "lid_outer",
    "front_inner",
    "back_inner",
    "left_inner",
    "right_inner",
    "external",
]

MODE_TO_SURFACE = {
    "external_independent_module": "external",
    "base_floor": "base_floor",
    "lid_inner": "lid_inner",
    "lid_outer": "lid_outer",
    "front_inner": "front_inner",
    "back_inner": "back_inner",
    "left_inner": "left_inner",
    "right_inner": "right_inner",
}

HORIZONTAL_SURFACES = {"base_floor", "lid_inner", "lid_outer"}


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class AutoSizeRequest(RequestModel):
    enabled: bool = True
    axes: tuple[Literal["length", "width", "height"], ...] = ("length", "width", "height")
    grid_mm: float = Field(default=0.5, ge=0.1, le=5.0)
    max_iterations: int = Field(default=8, ge=1, le=32)
    clearance_margin_mm: float = Field(default=0.0, ge=0.0, le=20.0)


class LidFastenerOverrides(RequestModel):
    enabled: bool | None = None
    post_outer_diameter: float | None = Field(default=None, ge=4.0, le=20.0)
    hole_diameter: float | None = Field(default=None, ge=1.0, le=8.0)
    edge_inset: float | None = Field(default=None, ge=3.0, le=40.0)
    top_clearance: float | None = Field(default=None, ge=0.1, le=4.0)


class EnclosureOverrides(RequestModel):
    inner_length_x: float | None = Field(default=None, ge=30.0, le=800.0)
    inner_width_y: float | None = Field(default=None, ge=30.0, le=800.0)
    inner_height_z: float | None = Field(default=None, ge=12.0, le=400.0)
    wall_thickness: float | None = Field(default=None, ge=0.8, le=12.0)
    floor_thickness: float | None = Field(default=None, ge=0.8, le=12.0)
    lid_thickness: float | None = Field(default=None, ge=0.8, le=12.0)
    lid_lip_height: float | None = Field(default=None, ge=1.0, le=20.0)
    lid_lip_thickness: float | None = Field(default=None, ge=0.8, le=8.0)
    lid_clearance: float | None = Field(default=None, ge=0.1, le=2.0)
    corner_radius: float | None = Field(default=None, ge=0.0, le=40.0)
    min_wall_thickness: float | None = Field(default=None, ge=0.8, le=6.0)
    hardware_gap: float | None = Field(default=None, ge=0.0, le=30.0)
    edge_clearance: float | None = Field(default=None, ge=0.0, le=40.0)
    lid_fasteners: LidFastenerOverrides | None = None

    def is_empty(self) -> bool:
        return not self.model_dump(exclude_none=True)


class ComponentMountOverrides(RequestModel):
    base_thickness: float | None = Field(default=None, ge=1.2, le=12.0)
    edge_margin: float | None = Field(default=None, ge=4.0, le=30.0)
    component_clearance: float | None = Field(default=None, ge=0.2, le=5.0)
    retainer_height: float | None = Field(default=None, ge=1.0, le=20.0)
    fastener_hole_diameter: float | None = Field(default=None, ge=1.5, le=8.0)
    corner_radius: float | None = Field(default=None, ge=0.0, le=20.0)

    def is_empty(self) -> bool:
        return not self.model_dump(exclude_none=True)


class RequestComponent(RequestModel):
    component_id: str | None = None
    profile_id: str | None = None
    profile: dict[str, Any] | None = None
    instance_id: str | None = None
    surface: Surface | None = None
    center: tuple[float, ...] | None = None
    rotation_z_deg: Literal[0, 90, 180, 270] = 0
    include_reference_geometry: bool = True
    derive_mount: bool = False

    @model_validator(mode="after")
    def validate_identity(self) -> "RequestComponent":
        literals = [
            self.component_id is not None,
            self.profile_id is not None,
            self.profile is not None,
        ]
        if sum(literals) != 1:
            raise ValueError("component_id、profile_id、profile 必须且只能提供一个")
        for value, label in (
            (self.component_id, "component_id"),
            (self.profile_id, "profile_id"),
            (self.instance_id, "instance_id"),
        ):
            if value is not None and not str(value).strip():
                raise ValueError(f"{label} 不能为空")
        if self.center is not None and len(self.center) not in (2, 3):
            raise ValueError("center 必须包含 2 个或 3 个数值")
        return self


class EnclosureRequest(RequestModel):
    schema_name: str | None = Field(default=None, alias="schema")
    design_id: str | None = None
    template: Template = "box_with_lid"
    auto_size: bool | AutoSizeRequest = True
    enclosure: EnclosureOverrides = Field(default_factory=EnclosureOverrides)
    component_mount: ComponentMountOverrides = Field(default_factory=ComponentMountOverrides)
    components: tuple[RequestComponent, ...] = ()
    standoffs: tuple[dict[str, Any], ...] = ()
    openings: tuple[dict[str, Any], ...] = ()

    @model_validator(mode="after")
    def validate_request(self) -> "EnclosureRequest":
        if self.schema_name is not None and self.schema_name != REQUEST_SCHEMA:
            raise ValueError(f"schema 必须是 {REQUEST_SCHEMA}")
        if self.template == "component_mount":
            if len(self.components) != 1:
                raise ValueError("component_mount 模板必须恰好包含 1 个 component")
            if self.standoffs:
                raise ValueError("component_mount 模板不支持 standoffs")
            if self.openings:
                raise ValueError("component_mount 模板不支持 openings")
            if not self.enclosure.is_empty():
                raise ValueError("component_mount 模板不支持 enclosure 参数")
            for component in self.components:
                if component.surface is not None and component.surface != "external":
                    raise ValueError("component_mount 模板要求 external 放置")
        else:
            if not self.component_mount.is_empty():
                raise ValueError("box_with_lid 模板不支持 component_mount 参数")
        return self


@dataclass
class PreparedComponent:
    profile: Any  # HardwareProfile, imported lazily by the caller-facing helpers
    instance_id: str
    surface: str
    center: tuple[float, ...] | None
    rotation_z_deg: int
    include_reference_geometry: bool
    provenance: dict[str, Any]
    derived: bool = False


@dataclass
class PreparedRequest:
    request: EnclosureRequest
    design_id: str
    template: str
    auto_size: AutoSizeRequest
    enclosure: Any | None  # BoxWithLidParameters
    component_mount: Any | None  # ComponentMountParameters
    components: list[PreparedComponent] = field(default_factory=list)
    profiles: list[Any] = field(default_factory=list)  # HardwareProfile, first-appearance order
    hardware: list[Any] = field(default_factory=list)  # HardwareInstance
    standoffs: list[Any] = field(default_factory=list)  # StandoffSpec
    openings: list[Any] = field(default_factory=list)  # OpeningSpec
    warnings: list[str] = field(default_factory=list)
    provenance: list[dict[str, Any]] = field(default_factory=list)
    auto_missing: dict[str, bool] = field(default_factory=dict)
    auto_enabled: bool = True
    auto_explicit: dict[str, float | None] = field(default_factory=dict)
    questions: list[dict[str, Any]] = field(default_factory=list)


def parse_request(raw: Any) -> EnclosureRequest:
    if not isinstance(raw, dict):
        raise ZwError(
            "REQUEST_INVALID",
            "外壳请求必须是 JSON 对象",
            "检查请求文件顶层结构。",
            2,
        )
    try:
        return EnclosureRequest.model_validate(raw)
    except ValidationError as exc:
        raise ZwError(
            "REQUEST_INVALID",
            "外壳请求字段无效",
            "按 references/enclosure.md 的 zw.enclosure-request/v1 修正字段。",
            2,
            details={"errors": _error_details(exc)},
        ) from exc


def prepare_request(request: EnclosureRequest) -> PreparedRequest:
    from zhangwen.cad_engine.models import (
        BoxWithLidParameters,
        ComponentMountParameters,
        ExternalPlacement,
        HardwareInstance,
        HardwareProfile,
        LidFastenerPattern,
        Point2,
        Point3,
        StandoffSpec,
        SurfacePlacement,
    )
    from zhangwen.cad_engine.models import OpeningSpec  # type: ignore[attr-defined]

    warnings: list[str] = []
    auto_size = _normalise_auto_size(request.auto_size)
    prepared = PreparedRequest(
        request=request,
        design_id=_design_id(request.design_id),
        template=request.template,
        auto_size=auto_size,
        enclosure=None,
        component_mount=None,
        warnings=warnings,
        auto_enabled=auto_size.enabled,
    )

    if request.template == "component_mount":
        if auto_size.enabled:
            warnings.append("component_mount 模板不做自动尺寸；auto_size 已忽略。")
        prepared.auto_enabled = False
        prepared.component_mount = _component_mount_parameters(request.component_mount, ComponentMountParameters)
    else:
        prepared.enclosure = _box_parameters(
            request.enclosure,
            BoxWithLidParameters,
            LidFastenerPattern,
        )

    used_ids: set[str] = set()
    resolved: list[PreparedComponent] = []
    unresolved: list[dict[str, Any]] = []

    for index_, component in enumerate(request.components):
        instance_id = _instance_id(component, index_, used_ids)
        surface = component.surface
        if request.template == "component_mount":
            surface = "external"
        try:
            resolved_component = _resolve_component(
                component,
                instance_id=instance_id,
                template=request.template,
                surface=surface,
                warnings=warnings,
                unresolved=unresolved,
                HardwareProfile=HardwareProfile,
            )
        except ZwError:
            raise
        if resolved_component is not None:
            resolved.append(resolved_component)

    if unresolved:
        prepared.questions = unresolved
        prepared.provenance = [item.provenance for item in resolved]
        raise ZwError(
            "NEEDS_INPUT",
            "缺少可确定外壳的机械数据",
            "补齐 questions 中的机械尺寸/安装面，或改用 profile 提供完整声明。",
            4,
            details={
                "questions": unresolved,
                "provenance": prepared.provenance,
                "template": prepared.template,
            },
        )

    prepared.components = resolved
    _build_instances(
        prepared,
        request=request,
        HardwareInstance=HardwareInstance,
        SurfacePlacement=SurfacePlacement,
        ExternalPlacement=ExternalPlacement,
        Point2=Point2,
        Point3=Point3,
        ComponentMountParameters=ComponentMountParameters,
        warnings=warnings,
        questions=prepared.questions,
    )
    if prepared.questions:
        prepared.provenance = [item.provenance for item in resolved]
        raise ZwError(
            "NEEDS_INPUT",
            "缺少可确定放置位置的输入",
            "补齐 questions 中的 center/surface 设置。",
            4,
            details={
                "questions": prepared.questions,
                "provenance": prepared.provenance,
                "template": prepared.template,
            },
        )

    prepared.standoffs = _parse_models(request.standoffs, StandoffSpec, "standoffs")
    prepared.openings = _parse_models(request.openings, OpeningSpec, "openings")
    prepared.provenance = [item.provenance for item in prepared.components]
    _record_auto_axes(prepared, request.enclosure)
    return prepared


def build_cad_spec(prepared: PreparedRequest, enclosure: Any | None = None):
    from zhangwen.cad_engine.models import CadBuildSpec

    if prepared.template == "component_mount":
        return CadBuildSpec(
            design_id=prepared.design_id,
            template="component_mount",
            component_mount=prepared.component_mount,
            profiles=tuple(prepared.profiles),
            hardware=tuple(prepared.hardware),
        )
    return CadBuildSpec(
        design_id=prepared.design_id,
        template="box_with_lid",
        enclosure=enclosure or prepared.enclosure,
        standoffs=tuple(prepared.standoffs),
        openings=tuple(prepared.openings),
        profiles=tuple(prepared.profiles),
        hardware=tuple(prepared.hardware),
    )


# ---------------------------------------------------------------------------
# Request normalisation


def _normalise_auto_size(value: bool | AutoSizeRequest) -> AutoSizeRequest:
    if isinstance(value, bool):
        return AutoSizeRequest(enabled=value)
    return AutoSizeRequest.model_validate(value.model_dump())


def _box_parameters(overrides: EnclosureOverrides, model, fastener_model):
    payload: dict[str, Any] = overrides.model_dump(exclude_none=True)
    fasteners = payload.pop("lid_fasteners", None)
    if fasteners is not None:
        current = fastener_model().model_dump()
        current.update({key: value for key, value in fasteners.items() if value is not None})
        payload["lid_fasteners"] = current
    try:
        return model(**payload)
    except ValidationError as exc:
        raise _override_error(exc, "enclosure") from exc


def _component_mount_parameters(overrides: ComponentMountOverrides, model):
    payload = overrides.model_dump(exclude_none=True)
    try:
        return model(**payload)
    except ValidationError as exc:
        raise _override_error(exc, "component_mount") from exc


def _override_error(exc: ValidationError, label: str) -> ZwError:
    return ZwError(
        "REQUEST_INVALID",
        f"{label} 参数无效",
        "参数范围见 references/enclosure.md。",
        2,
        details={"errors": _error_details(exc)},
    )


def _design_id(value: str | None) -> str:
    if value is None:
        return "enclosure"
    if not _IDENTIFIER_RE.match(value):
        raise ZwError(
            "REQUEST_INVALID",
            f"design_id 不合法：{value}",
            "design_id 必须匹配 ^[a-z][a-z0-9_-]{0,63}$。",
            2,
        )
    return value


def _instance_id(component: RequestComponent, position: int, used: set[str]) -> str:
    if component.instance_id is not None:
        if not _IDENTIFIER_RE.match(component.instance_id):
            raise ZwError(
                "REQUEST_INVALID",
                f"instance_id 不合法：{component.instance_id}",
                "instance_id 必须匹配 ^[a-z][a-z0-9_-]{0,63}$。",
                2,
            )
        if component.instance_id in used:
            raise ZwError(
                "REQUEST_INVALID",
                f"instance_id 重复：{component.instance_id}",
                "每个 component 的 instance_id 必须唯一。",
                2,
            )
        used.add(component.instance_id)
        return component.instance_id
    raw = component.component_id or component.profile_id
    if raw is None and component.profile is not None:
        raw = component.profile.get("profile_id") if isinstance(component.profile, dict) else None
    base = _sanitise_id(str(raw or "component"))
    candidate = base
    suffix = 2
    while candidate in used:
        tail = f"_{suffix}"
        candidate = base[: 64 - len(tail)] + tail
        suffix += 1
    used.add(candidate)
    return candidate


def _sanitise_id(value: str, fallback: str = "component") -> str:
    text = re.sub(r"[^a-z0-9_-]+", "_", value.lower()).strip("_-")
    text = re.sub(r"_{2,}", "_", text)
    if not text:
        text = fallback
    if not text[0].isalpha():
        text = f"{fallback}_{text}"
    text = text[:64].rstrip("_-")
    return text or fallback


def _error_details(exc: ValidationError) -> list[dict[str, Any]]:
    details = []
    for item in exc.errors(include_url=False):
        details.append(
            {
                "loc": ".".join(str(part) for part in item.get("loc", ())),
                "message": item.get("msg", ""),
                "type": item.get("type", ""),
            }
        )
    return details


# ---------------------------------------------------------------------------
# Profile resolution


_TRUSTED_CACHE: set[str] | None = None
_MECHANICAL_CACHE: dict[str, list[tuple[dict[str, Any], Any]]] | None = None


def _trusted_ids() -> set[str]:
    global _TRUSTED_CACHE
    if _TRUSTED_CACHE is None:
        from zhangwen.cad_engine.profiles import trusted_profiles

        _TRUSTED_CACHE = {profile.profile_id for profile in trusted_profiles()}
    return _TRUSTED_CACHE


def _mechanical_index(warnings: list[str]) -> dict[str, list[tuple[dict[str, Any], Any]]]:
    global _MECHANICAL_CACHE
    from zhangwen.cad_engine.models import HardwareProfile

    if _MECHANICAL_CACHE is not None:
        return _MECHANICAL_CACHE
    mapping: dict[str, list[tuple[dict[str, Any], Any]]] = {}
    for package in index.packages():
        if package.get("status") != "ACTIVE":
            continue
        mechanical = Path(package["path"]) / "references" / "mechanical.md"
        if not mechanical.is_file():
            continue
        try:
            _, detail = hardware._detail(str(package["skillName"]))
        except ZwError as exc:
            warnings.append(f"跳过 {package['skillName']} 的机械档案：{exc.message}")
            continue
        raw = getattr(detail, "mechanicalProfile", None)
        if not raw:
            continue
        try:
            profile = HardwareProfile.model_validate(raw)
        except ValidationError as exc:
            warnings.append(
                f"跳过 {package['skillName']} 的无效机械档案：{_error_details(exc)[:1]}"
            )
            continue
        mapping.setdefault(profile.profile_id, []).append((package, profile))
    _MECHANICAL_CACHE = mapping
    return mapping


def _resolve_component(
    component: RequestComponent,
    *,
    instance_id: str,
    template: str,
    surface: str | None,
    warnings: list[str],
    unresolved: list[dict[str, Any]],
    HardwareProfile,
) -> PreparedComponent | None:
    package: dict[str, Any] | None = None
    verification: str | None = None

    if component.profile is not None:
        profile = _inline_profile(
            component.profile,
            warnings=warnings,
            HardwareProfile=HardwareProfile,
        )
        source = "inline"
    elif component.profile_id is not None:
        profile, package, source = _profile_by_id(
            component.profile_id,
            warnings=warnings,
            HardwareProfile=HardwareProfile,
        )
        verification = package.get("verificationStatus") if package else None
    else:
        assert component.component_id is not None
        resolved = _profile_by_component(
            component.component_id,
            warnings=warnings,
            HardwareProfile=HardwareProfile,
            unresolved=unresolved,
            instance_id=instance_id,
        )
        if resolved is None:
            return None
        profile, package = resolved
        source = "package-mechanical"
        verification = package.get("verificationStatus") if package else None

    target_surface, derived, derive_warning = _placement_surface(
        profile,
        requested=surface,
        template=template,
        derive=component.derive_mount,
    )
    if template == "component_mount" and component.derive_mount:
        warnings.append(
            f"{profile.profile_id} 在 component_mount 模式下固定 external 放置；derive_mount 已忽略。"
        )
    if derive_warning:
        warnings.append(derive_warning)
    if derived:
        profile = _derive_profile(profile, target_surface, warnings=warnings)

    provenance = {
        "instance_id": instance_id,
        "profile_id": profile.profile_id,
        "revision": profile.revision,
        "display_name": profile.display_name,
        "source": "derived" if derived else source,
        "component_id": component.component_id,
        "package": package.get("skillName") if package else None,
        "verification_status": verification,
        "derived_from": profile.profile_id.rsplit("_derived_", 1)[0] if derived else None,
        "surface": target_surface,
        "mechanical_profile": True,
    }
    return PreparedComponent(
        profile=profile,
        instance_id=instance_id,
        surface=target_surface,
        center=component.center,
        rotation_z_deg=component.rotation_z_deg,
        include_reference_geometry=component.include_reference_geometry,
        provenance=provenance,
        derived=derived,
    )


def _inline_profile(raw: dict[str, Any], *, warnings: list[str], HardwareProfile):
    profile_id = raw.get("profile_id")
    if isinstance(profile_id, str) and profile_id in _trusted_ids():
        raise ZwError(
            "PROFILE_CONFLICT",
            f"inline profile 不能占用 trusted profile_id：{profile_id}",
            "内置/受信 profile 请直接用 profile_id 引用，不要内联覆盖。",
            2,
        )
    if isinstance(profile_id, str) and profile_id in _mechanical_index(warnings):
        raise ZwError(
            "PROFILE_CONFLICT",
            f"inline profile 不能占用资料包已声明的 profile_id：{profile_id}",
            "用 profile_id 引用资料包机械档案，或换一个自定义 profile_id。",
            2,
        )
    if raw.get("source", "declared") != "declared":
        raise ZwError(
            "PROFILE_CONFLICT",
            "inline profile 只允许 source=declared",
            "trusted 档案只能通过 profile_id 引用。",
            2,
        )
    if raw.get("model_kind", "envelope") != "envelope":
        raise ZwError(
            "PROFILE_CONFLICT",
            "inline profile 只允许 model_kind=envelope",
            "特殊参考几何只能通过内置 profile_id 使用。",
            2,
        )
    try:
        return HardwareProfile.model_validate(raw)
    except ValidationError as exc:
        raise ZwError(
            "REQUEST_INVALID",
            "inline profile 无效",
            "按 HardwareProfile schema 补齐尺寸、坐标系和 mounting。",
            2,
            details={"errors": _error_details(exc)},
        ) from exc


def _profile_by_id(profile_id: str, *, warnings: list[str], HardwareProfile):
    try:
        from zhangwen.cad_engine.profiles import trusted_profile

        trusted = trusted_profile(profile_id)
    except KeyError:
        trusted = None
    if trusted is not None:
        return trusted, None, "trusted"

    entries = _mechanical_index(warnings).get(profile_id, [])
    if entries:
        signatures = {_profile_signature(item[1]) for item in entries}
        if len(signatures) > 1:
            packages = ", ".join(item[0]["skillName"] for item in entries)
            raise ZwError(
                "PROFILE_AMBIGUOUS",
                f"profile_id {profile_id} 在多个资料包中内容不一致：{packages}",
                "改用 component_id 或 inline profile 明确来源。",
                3,
            )
        package, profile = sorted(entries, key=lambda item: item[0]["skillName"])[0]
        return profile, package, "package-mechanical"

    resolved = _profile_by_component(
        profile_id,
        warnings=warnings,
        HardwareProfile=HardwareProfile,
        unresolved=[],
        instance_id=profile_id,
        allow_missing=False,
    )
    if resolved is None:
        raise ZwError(
            "PROFILE_NOT_FOUND",
            f"未找到 profile：{profile_id}",
            "可用内置 profile_id、资料包 mechanical profile，或内联 profile。",
            3,
            details={"trusted": sorted(_trusted_ids())},
        )
    profile, package = resolved
    return profile, package, "package-mechanical"


def _profile_by_component(
    component_id: str,
    *,
    warnings: list[str],
    HardwareProfile,
    unresolved: list[dict[str, Any]],
    instance_id: str,
    allow_missing: bool = True,
):
    try:
        detail = hardware._detail(component_id)
    except ZwError as exc:
        if exc.code != "HARDWARE_NOT_FOUND":
            raise
        if not allow_missing:
            return None
        raise ZwError(
            "PROFILE_NOT_FOUND",
            f"未找到 profile 或硬件资料包：{component_id}",
            "用 zw hardware search 查 componentId，或改用内置 profile_id。",
            3,
        ) from exc
    raw = getattr(detail, "mechanicalProfile", None)
    if not raw:
        if allow_missing:
            unresolved.append(
                {
                    "field": "profile",
                    "instance_id": instance_id,
                    "component_id": component_id,
                    "message": f"{component_id} 没有声明 mechanical profile，无法确定外形/安装尺寸。",
                    "hint": "提供 profile_id（内置/资料包）或 inline profile（source=declared）。",
                }
            )
            return None
        return None
    try:
        profile = HardwareProfile.model_validate(raw)
    except ValidationError as exc:
        if allow_missing:
            unresolved.append(
                {
                    "field": "profile",
                    "instance_id": instance_id,
                    "component_id": component_id,
                    "message": "资料包的 mechanical profile 无效：" + _error_details(exc)[:1].__str__(),
                    "hint": "提供 inline profile，或修正资料包（不在本 skill 内改上游数据）。",
                }
            )
            return None
        raise ZwError(
            "PROFILE_NOT_FOUND",
            f"{component_id} 的 mechanical profile 无效",
            "提供 inline profile，或修正上游资料包。",
            3,
        ) from exc
    package = index.find_package(component_id)
    return profile, package


def _profile_signature(profile) -> str:
    return json.dumps(profile.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)


def _placement_surface(
    profile,
    *,
    requested: str | None,
    template: str,
    derive: bool,
) -> tuple[str, bool, str | None]:
    mode = profile.mounting.mode
    required = MODE_TO_SURFACE.get(mode)
    if template == "component_mount":
        return "external", False, None
    target = requested or profile.mounting.preferred_surface.value
    if required is None or target == required:
        return target, False, None
    if not derive:
        raise ZwError(
            "MOUNT_CONFLICT",
            f"{profile.profile_id} 的 mounting.mode={mode} 要求 {required}，请求却是 {target}",
            "改用匹配的 surface；确需推断安装方式时显式设置 derive_mount=true 并做实物验证。",
            4,
            details={"profile_id": profile.profile_id, "required_surface": required, "requested_surface": target},
        )
    return target, True, (
        f"{profile.profile_id} 原 mounting.mode={mode} 要求 {required}；"
        f"derive_mount 已按 {target} 推断安装方式，必须实物验证。"
    )


def _derive_profile(profile, target_surface: str, *, warnings: list[str]):
    from zhangwen.cad_engine.models import (
        HardwareModelKind,
        HardwareMounting,
        HardwareProfile,
        ProfileSource,
    )

    derived_id = _sanitise_id(f"{profile.profile_id}_derived_{target_surface}")
    mounting_mode = (
        "external_independent_module" if target_surface == "external" else target_surface
    )
    mounting = HardwareMounting(
        mode=mounting_mode,
        preferred_surface=target_surface,
        strategy="none",
        clearance=profile.mounting.clearance,
        holes=tuple(profile.mounting.holes),
    )
    payload = profile.model_dump(mode="json")
    payload.update(
        {
            "profile_id": derived_id,
            "revision": f"{profile.revision}-derived-{target_surface}"[:160],
            "display_name": f"{profile.display_name}（派生 {target_surface} 安装）"[:120],
            "mounting": mounting.model_dump(mode="json"),
            "model_kind": HardwareModelKind.ENVELOPE.value,
            "source": ProfileSource.DECLARED.value,
        }
    )
    warnings.append(
        f"{profile.profile_id} 已派生为 {derived_id}：安装方式由包装层推断，不是原厂声明。"
    )
    return HardwareProfile.model_validate(payload)


# ---------------------------------------------------------------------------
# Instance construction


def _build_instances(
    prepared: PreparedRequest,
    *,
    request: EnclosureRequest,
    HardwareInstance,
    SurfacePlacement,
    ExternalPlacement,
    Point2,
    Point3,
    ComponentMountParameters,
    warnings: list[str],
    questions: list[dict[str, Any]],
) -> None:
    profiles_by_id: dict[str, Any] = {}
    for component in prepared.components:
        profile = component.profile
        existing = profiles_by_id.get(profile.profile_id)
        if existing is not None:
            if _profile_signature(existing) != _profile_signature(profile):
                raise ZwError(
                    "PROFILE_CONFLICT",
                    f"profile_id {profile.profile_id} 被解析成不同内容",
                    "同一 profile_id 只能对应一份机械定义。",
                    2,
                )
        else:
            profiles_by_id[profile.profile_id] = profile
            prepared.profiles.append(profile)

        center = component.center
        if prepared.template == "component_mount":
            base_thickness = prepared.component_mount.base_thickness
            if center is None:
                center = (
                    0.0,
                    0.0,
                    round(base_thickness + profile.dimensions.height_z / 2, 6),
                )
            elif len(center) != 3:
                raise ZwError(
                    "REQUEST_INVALID",
                    f"{component.instance_id} 的 external center 必须包含 x/y/z",
                    "component_mount 的器件中心需要三个坐标。",
                    2,
                )
            placement = ExternalPlacement(
                surface="external",
                center=Point3(x=float(center[0]), y=float(center[1]), z=float(center[2])),
            )
        else:
            placement = _box_placement(
                component,
                center=center,
                SurfacePlacement=SurfacePlacement,
                ExternalPlacement=ExternalPlacement,
                Point2=Point2,
                Point3=Point3,
                questions=questions,
            )
            if placement is None:
                continue
        prepared.hardware.append(
            HardwareInstance(
                instance_id=component.instance_id,
                profile_id=profile.profile_id,
                placement=placement,
                rotation_z_deg=component.rotation_z_deg,
                include_reference_geometry=component.include_reference_geometry,
            )
        )


def _box_placement(
    component: PreparedComponent,
    *,
    center: tuple[float, ...] | None,
    SurfacePlacement,
    ExternalPlacement,
    Point2,
    Point3,
    questions: list[dict[str, Any]],
):
    surface = component.surface
    if surface == "external":
        if center is None or len(center) != 3:
            questions.append(
                {
                    "field": "center",
                    "instance_id": component.instance_id,
                    "message": f"{component.instance_id} 在 external 面需要明确的 x/y/z center。",
                    "hint": "external 放置不会自动推算坐标。",
                }
            )
            return None
        return ExternalPlacement(
            surface="external",
            center=Point3(x=float(center[0]), y=float(center[1]), z=float(center[2])),
        )
    if surface in {"left_inner", "right_inner"} and center is None:
        questions.append(
            {
                "field": "center",
                "instance_id": component.instance_id,
                "surface": surface,
                "message": f"{surface} 目前要求显式 center=[y, z]；引擎自动行打包在该面轴向不一致。",
                "hint": "提供 center=[y,z]，例如 [0, 20]。",
            }
        )
        return None
    if center is not None and len(center) != 2:
        raise ZwError(
            "REQUEST_INVALID",
            f"{component.instance_id} 的 {surface} center 必须是 2 个数值",
            "内部安装面使用 [u,v]；external 使用 [x,y,z]。",
            2,
        )
    if center is None:
        return SurfacePlacement(surface=surface, center=None)
    return SurfacePlacement(
        surface=surface,
        center=Point2(x=float(center[0]), y=float(center[1])),
    )


def _parse_models(values: tuple[dict[str, Any], ...], model, label: str) -> list[Any]:
    parsed = []
    for position, value in enumerate(values):
        try:
            parsed.append(model.model_validate(value))
        except ValidationError as exc:
            raise ZwError(
                "REQUEST_INVALID",
                f"{label}[{position}] 无效",
                "按掌问 cad_engine 的同名 schema 修正字段。",
                2,
                details={"errors": _error_details(exc)},
            ) from exc
    return parsed


def _record_auto_axes(prepared: PreparedRequest, overrides: EnclosureOverrides) -> None:
    prepared.auto_missing = {
        "length": overrides.inner_length_x is None,
        "width": overrides.inner_width_y is None,
        "height": overrides.inner_height_z is None,
    }
    prepared.auto_explicit = {
        "length": overrides.inner_length_x,
        "width": overrides.inner_width_y,
        "height": overrides.inner_height_z,
    }
