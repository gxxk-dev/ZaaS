"""Deterministic box sizing for ``zw enclosure plan/build``.

The upstream ``box_with_lid`` template requires an explicit inner footprint.
This module fills only the dimensions the request left open, using the same
greedy row packing as the engine, and then treats the engine validator as an
oracle: growth is bounded, axis-ordered, and limited to layout problems.  It
never shrinks an explicit dimension and never hides a structural wall or
mounting failure behind a larger box.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import ValidationError

from .envelope import ZwError

AXIS_FIELD = {
    "length": "inner_length_x",
    "width": "inner_width_y",
    "height": "inner_height_z",
}
AXIS_LIMIT = {"length": 800.0, "width": 800.0, "height": 400.0}
ENGINE_MINIMUM = {"length": 30.0, "width": 30.0, "height": 12.0}
DEFAULT_DIMENSIONS = {"length": 100.0, "width": 70.0, "height": 40.0}

# Failures that a larger cavity may legitimately resolve.
GROWABLE_CHECKS = {
    "layout_surface_capacity",
    "hardware_bounds",
    "hardware_interference",
    "profile_opening_wall_clearance",
    "opening_edge_clearance",
    "support_clearance",
}
# Failures that indicate a bad parameter or incomplete mounting contract.
STRUCTURAL_CHECKS = {
    "minimum_wall_thickness",
    "mounting_completeness",
    "opening_mount_clearance",
}

HORIZONTAL = {"base_floor", "lid_inner", "lid_outer"}
FRONT_BACK = {"front_inner", "back_inner"}


@dataclass(frozen=True)
class SizingComponent:
    profile: Any
    instance_id: str
    surface: str
    center: tuple[float, ...] | None
    rotation_z_deg: int


@dataclass(frozen=True)
class SizingOptions:
    enabled: bool = True
    axes: tuple[str, ...] = ("length", "width", "height")
    grid_mm: float = 0.5
    max_iterations: int = 8
    clearance_margin_mm: float = 0.0


@dataclass
class SizingResult:
    parameters: Any
    iterations: int
    dimensions: dict[str, float]
    warnings: list[str] = field(default_factory=list)
    ok: bool = True
    failing_checks: set[str] = field(default_factory=set)
    limit_reached: bool = False
    last_report: Any | None = None


def size_box(
    parameters: Any,
    *,
    components: list[SizingComponent],
    standoffs: list[Any],
    missing: dict[str, bool],
    explicit: dict[str, float | None],
    options: SizingOptions,
    build_spec: Callable[[Any], Any],
    evaluate: Callable[[Any], Any],
) -> SizingResult:
    """Return validated ``BoxWithLidParameters`` with auto dimensions filled.

    ``build_spec(parameters)`` must construct a full ``CadBuildSpec`` and
    ``evaluate(spec)`` must return the upstream ``ValidationReport``.
    """

    warnings: list[str] = []
    if not options.enabled:
        dimensions = {
            "length": parameters.inner_length_x,
            "width": parameters.inner_width_y,
            "height": parameters.inner_height_z,
        }
        return SizingResult(
            parameters=parameters,
            iterations=0,
            dimensions=dimensions,
            warnings=warnings,
        )

    parameters = _apply_edge_reserve(
        parameters,
        components=components,
        options=options,
        warnings=warnings,
    )

    auto_axes = [
        axis
        for axis in ("length", "width", "height")
        if missing.get(axis) and axis in options.axes
    ]
    has_external = any(component.surface == "external" for component in components)
    growable = GROWABLE_CHECKS - ({"hardware_bounds"} if has_external else set())
    dimensions = _initial_dimensions(
        parameters,
        components=components,
        standoffs=standoffs,
        options=options,
    )
    if not any(component.surface != "external" for component in components):
        warnings.append("没有内部组件；自动尺寸回退引擎默认 100×70×40。")
    # An explicit dimension always wins; an axis outside ``options.axes``
    # falls back to the engine default instead of being auto-sized.
    for axis in ("length", "width", "height"):
        if not missing.get(axis):
            value = explicit.get(axis)
            if value is not None:
                dimensions[axis] = float(value)
        elif axis not in options.axes:
            dimensions[axis] = DEFAULT_DIMENSIONS[axis]
        dimensions[axis] = min(
            AXIS_LIMIT[axis],
            _round_up(dimensions[axis], options.grid_mm),
        )

    try:
        candidate = _validated_parameters(parameters, dimensions)
    except ValidationError:
        candidate = parameters
    last_failing: set[str] = set()
    last_report = None
    iterations = 0
    stop_reason = "unknown"
    while True:
        iterations += 1
        try:
            candidate = _validated_parameters(parameters, dimensions)
            report = evaluate(build_spec(candidate))
            last_report = report
            failing = {
                check.check_id
                for check in report.checks
                if _status(check.status) == "fail"
            }
            ok = bool(report.ok)
        except ValidationError:
            last_report = None
            failing = {"model_validation"}
            ok = False
        last_failing = failing
        if ok:
            return SizingResult(
                parameters=candidate,
                iterations=iterations,
                dimensions=dict(dimensions),
                warnings=warnings,
            )
        if failing & STRUCTURAL_CHECKS:
            stop_reason = "structural"
            break
        if failing - growable - {"model_validation"}:
            stop_reason = "unknown"
            break
        if not auto_axes:
            stop_reason = "no_axes"
            break
        if iterations > options.max_iterations:
            stop_reason = "max_iterations"
            break
        axis = auto_axes[(iterations - 1) % len(auto_axes)]
        step = max(5.0, dimensions[axis] * 0.12)
        grown = min(AXIS_LIMIT[axis], dimensions[axis] + step)
        grown = _round_up(grown, options.grid_mm)
        if grown <= dimensions[axis]:
            stop_reason = "axis_limit"
            break
        dimensions[axis] = grown

    return SizingResult(
        parameters=candidate,
        iterations=iterations,
        dimensions=dict(dimensions),
        warnings=warnings,
        ok=False,
        failing_checks=last_failing,
        limit_reached=stop_reason in {"max_iterations", "axis_limit"},
        last_report=last_report,
    )


def _status(value: Any) -> str:
    return str(getattr(value, "value", value))


def _apply_edge_reserve(
    parameters: Any,
    *,
    components: list[SizingComponent],
    options: SizingOptions,
    warnings: list[str],
):
    fasteners = parameters.lid_fasteners
    has_horizontal_auto = any(
        component.surface in HORIZONTAL and component.center is None
        for component in components
    )
    has_lid_hardware = any(
        component.surface == "lid_inner" for component in components
    )
    reserve = parameters.edge_clearance
    required_edge = parameters.edge_clearance
    if fasteners.enabled and has_horizontal_auto:
        required_edge = max(
            required_edge,
            fasteners.edge_inset
            + fasteners.post_outer_diameter / 2
            + max(options.clearance_margin_mm, 0.5),
        )
    if has_lid_hardware:
        required_edge = max(required_edge, parameters.lid_lip_thickness + 0.5)
    if required_edge > 40.0:
        raise ZwError(
            "AUTO_SIZE_LIMIT",
            "螺丝柱/唇边预留超过 edge_clearance 上限 40mm",
            "减小 lid_fasteners.edge_inset 或关闭 lid_fasteners，或显式给出更大的盒体参数。",
            4,
        )
    if required_edge <= reserve + 1e-9:
        return parameters
    reserve = required_edge
    warnings.append(
        f"自动抬高 edge_clearance：{parameters.edge_clearance:g} → {reserve:g} mm，"
        "为螺丝柱/上盖唇边预留空间。"
    )
    payload = parameters.model_dump()
    payload["edge_clearance"] = reserve
    from zhangwen.cad_engine.models import BoxWithLidParameters

    return BoxWithLidParameters.model_validate(payload)


def _initial_dimensions(
    parameters: Any,
    *,
    components: list[SizingComponent],
    standoffs: list[Any],
    options: SizingOptions,
) -> dict[str, float]:
    margin = options.clearance_margin_mm
    base_edge = parameters.edge_clearance
    if any(component.surface != "external" for component in components):
        length = ENGINE_MINIMUM["length"]
        width = ENGINE_MINIMUM["width"]
        height = ENGINE_MINIMUM["height"]
    else:
        length = DEFAULT_DIMENSIONS["length"]
        width = DEFAULT_DIMENSIONS["width"]
        height = DEFAULT_DIMENSIONS["height"]

    base_heights: list[float] = []
    lid_heights: list[float] = []

    for surface in ("base_floor", "lid_inner", "lid_outer", "front_inner", "back_inner"):
        items = [item for item in components if item.surface == surface]
        if not items:
            continue
        edge = max(
            [base_edge, *(item.profile.mounting.clearance for item in items)]
        )
        automatic = [item for item in items if item.center is None]
        explicit_items = [item for item in items if item.center is not None]
        if automatic:
            pack = _pack_rows(
                automatic,
                gap=parameters.hardware_gap,
                target=_target_usable(automatic, parameters.hardware_gap),
            )
            required_length = pack[0]
            required_width = pack[1]
            if surface in FRONT_BACK:
                length = max(length, required_length + 2 * edge + margin)
                height = max(height, required_width + 2 * edge + margin)
            else:
                length = max(length, required_length + 2 * edge + margin)
                width = max(width, required_width + 2 * edge + margin)
        for item in explicit_items:
            size = _rotated_size(item)
            if surface in FRONT_BACK:
                center_x, center_z = float(item.center[0]), float(item.center[1])
                length = max(length, 2 * (abs(center_x) + size[0] / 2) + margin)
                height = max(height, 2 * (abs(center_z) + size[1] / 2) + margin)
            else:
                center_x, center_y = float(item.center[0]), float(item.center[1])
                length = max(length, 2 * (abs(center_x) + size[0] / 2) + margin)
                width = max(width, 2 * (abs(center_y) + size[1] / 2) + margin)

    for surface in ("left_inner", "right_inner"):
        for item in (component for component in components if component.surface == surface):
            if item.center is None:
                continue
            size = _rotated_size(item)
            center_y, center_z = float(item.center[0]), float(item.center[1])
            width = max(width, 2 * (abs(center_y) + size[1] / 2) + margin)
            height = max(height, 2 * (abs(center_z) + size[0] / 2) + margin)

    standoff_heights: dict[str, float] = {}
    for standoff in standoffs:
        target = getattr(standoff, "supports_instance_id", None)
        if target is not None:
            standoff_heights[target] = max(
                standoff_heights.get(target, 0.0), standoff.height
            )
    bare_standoffs = [
        standoff.height
        for standoff in standoffs
        if getattr(standoff, "supports_instance_id", None) is None
    ]
    for item in components:
        if item.surface == "base_floor":
            support = standoff_heights.get(item.instance_id, 0.0)
            if item.profile.mounting.strategy.value == "edge_retainer":
                support = max(support, parameters.min_wall_thickness)
            base_heights.append(support + item.profile.dimensions.height_z)
        elif item.surface == "lid_inner":
            lid_heights.append(item.profile.dimensions.height_z)

    if base_heights or lid_heights:
        stack = max(base_heights, default=0.0) + max(lid_heights, default=0.0)
        if base_heights and lid_heights:
            # The engine treats hardware_gap as a strict 3D AABB separation;
            # keep half a millimetre so exact-boundary floats cannot fail.
            stack += parameters.hardware_gap + 0.5
        height = max(height, stack + margin)
    if bare_standoffs:
        height = max(height, max(bare_standoffs) + margin)

    # Parameter self-consistency constraints from BoxWithLidParameters.
    wall = parameters.wall_thickness
    corner = parameters.corner_radius
    if corner > 0:
        length = max(length, 2 * corner - 2 * wall + 0.2)
        width = max(width, 2 * corner - 2 * wall + 0.2)
    lip = parameters.lid_lip_thickness * 2 + parameters.lid_clearance * 2 + 0.2
    length = max(length, lip)
    width = max(width, lip)
    fasteners = parameters.lid_fasteners
    if fasteners.enabled:
        fastener_min = (
            2 * (fasteners.edge_inset + fasteners.post_outer_diameter / 2) + 0.2
        )
        length = max(length, fastener_min)
        width = max(width, fastener_min)
        height = max(height, fasteners.top_clearance + 0.5)

    # Respect dimensions the user fixed, even when that means the request
    # cannot fit: the engine report will explain the failure.
    return {"length": length, "width": width, "height": height}


def _validated_parameters(parameters: Any, dimensions: dict[str, float]):
    from zhangwen.cad_engine.models import BoxWithLidParameters

    payload = parameters.model_dump()
    for axis, field_name in AXIS_FIELD.items():
        payload[field_name] = float(dimensions[axis])
    return BoxWithLidParameters.model_validate(payload)


def _rotated_size(component: SizingComponent) -> tuple[float, float, float]:
    dimensions = component.profile.dimensions
    if component.rotation_z_deg in (90, 270):
        return dimensions.width_y, dimensions.length_x, dimensions.height_z
    return dimensions.length_x, dimensions.width_y, dimensions.height_z


def _target_usable(items: list[SizingComponent], gap: float) -> float:
    sizes = [_rotated_size(item) for item in items]
    total = sum(size[0] for size in sizes) + gap * max(0, len(sizes) - 1)
    longest = max(size[0] for size in sizes)
    if len(sizes) <= 1:
        return total
    area = sum(size[0] * size[1] for size in sizes)
    target = max(longest, math.sqrt(area * 1.6))
    return min(total, target)


def _pack_rows(
    items: list[SizingComponent],
    *,
    gap: float,
    target: float,
) -> tuple[float, float]:
    measured = sorted(
        ((item, _rotated_size(item)) for item in items),
        key=lambda pair: (-pair[1][0], pair[0].instance_id),
    )
    usable = max(target, max((size[0] for _, size in measured), default=0.0))
    rows: list[list[tuple[SizingComponent, tuple[float, float, float]]]] = []
    current: list[tuple[SizingComponent, tuple[float, float, float]]] = []
    current_width = 0.0
    for item, size in measured:
        candidate = size[0] if not current else current_width + gap + size[0]
        if current and candidate > usable:
            rows.append(current)
            current = []
            current_width = 0.0
            candidate = size[0]
        current.append((item, size))
        current_width = candidate
    if current:
        rows.append(current)
    required_length = max(
        (
            sum(size[0] for _, size in row) + gap * max(0, len(row) - 1)
            for row in rows
        ),
        default=0.0,
    )
    required_width = sum(
        max(size[1] for _, size in row) for row in rows
    ) + gap * max(0, len(rows) - 1)
    return required_length, required_width


def _round_up(value: float, grid: float) -> float:
    return round(math.ceil((value - 1e-9) / grid) * grid, 6)
