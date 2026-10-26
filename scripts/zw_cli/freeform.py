"""``zw structure freeform``: a bounded request wrapper over declarative CSG.

The request layer turns a small JSON recipe into the engine's
``CadBuildSpec(template="freeform_structure")``.  Planning is read-only and
works without CadQuery; building requires CadQuery/OCP.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from pydantic import ValidationError

from . import env
from .envelope import CommandResult, ZwError

REQUEST_SCHEMA = "zw.freeform-request/v1"
SPEC_SCHEMA = "zw.freeform-spec/v1"
TEMPLATE = "freeform_structure"
TEMPLATE_REVISION = "freeform-structure.v1"
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
SHAPES = ("box", "rounded_box", "cylinder", "text")
OPERATIONS = ("add", "cut")
ROLES = ("body", "pcb", "connector", "sensor", "feature")
ROTATIONS = (0, 90, 180, 270)
FACES = ("top", "bottom", "front", "back", "left", "right")
MAX_OPERATIONS = 32
COMMON_FIELDS = {"primitive_id", "op", "shape", "center", "rotation_z_deg", "role"}
TEXT_FIELDS = {"primitive_id", "op", "shape", "text", "font_size", "depth", "center", "face", "angle"}

PLAN_WARNING = "plan 只校验请求、文字字段与布局；连通性、几何/文字 cut 是否与实体相交需 build 才能确认。"
NOMINAL_WARNING = "产物是名义几何；引擎只做参数与几何有效性校验，不做打印公差、强度或实物装配验证。"


def _request_error(message: str, *, details: Any | None = None) -> ZwError:
    return ZwError(
        "REQUEST_INVALID",
        message,
        "按 references/freeform.md 的 zw.freeform-request/v1 修正；不要添加未声明字段。",
        2,
        details=details,
    )


def _spec_error(message: str, *, details: Any | None = None) -> ZwError:
    return ZwError(
        "SPEC_INVALID",
        message,
        "freeform --spec 只接受 zw.freeform-spec/v1 包装或 template=freeform_structure 的 CadBuildSpec。",
        2,
        details=details,
    )


def _validation_detail(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        {
            "loc": ".".join(str(part) for part in error.get("loc", ())),
            "message": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        for error in exc.errors()
    ]


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _triple(value: Any, field: str, primitive_id: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise _request_error(
            f"{primitive_id}.{field} 必须是三个数值的数组。",
            details={"primitive_id": primitive_id, "field": field},
        )
    if not all(_is_number(item) for item in value):
        raise _request_error(
            f"{primitive_id}.{field} 必须是有限数值。",
            details={"primitive_id": primitive_id, "field": field, "value": value},
        )
    return [float(item) for item in value]


def _number(value: Any, field: str, primitive_id: str) -> float:
    if not _is_number(value):
        raise _request_error(
            f"{primitive_id}.{field} 必须是有限数值。",
            details={"primitive_id": primitive_id, "field": field, "value": value},
        )
    return float(value)


def _rotation(value: Any, primitive_id: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value not in ROTATIONS:
        raise _request_error(
            f"{primitive_id}.rotation_z_deg 只能是 0、90、180 或 270。",
            details={"primitive_id": primitive_id, "value": value},
        )
    return value


def _primitive(raw: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _request_error(f"operations[{index}] 必须是对象。")
    primitive_id = raw.get("primitive_id")
    if not isinstance(primitive_id, str) or not IDENTIFIER.fullmatch(primitive_id):
        raise _request_error(
            f"operations[{index}].primitive_id 必须匹配 ^[a-z][a-z0-9_-]{{0,63}}$。",
            details={"index": index, "primitive_id": primitive_id},
        )
    shape = raw.get("shape")
    if shape not in SHAPES:
        raise _request_error(
            f"{primitive_id}.shape 必须是 box、rounded_box、cylinder 或 text。",
            details={"primitive_id": primitive_id, "shape": shape},
        )
    operation = raw.get("op")
    if operation not in OPERATIONS:
        raise _request_error(
            f"{primitive_id}.op 必须是 add 或 cut。",
            details={"primitive_id": primitive_id, "op": operation},
        )
    if shape == "text":
        return _text_primitive(raw, primitive_id, operation)
    if index == 0 and operation != "add":
        raise _request_error(
            "第一个操作必须是 add；freeform 不能从 cut 开始。",
            details={"primitive_id": primitive_id},
        )
    if "center" not in raw:
        raise _request_error(f"{primitive_id} 缺少 center。", details={"primitive_id": primitive_id})
    center = _triple(raw["center"], "center", primitive_id)
    rotation = _rotation(raw.get("rotation_z_deg", 0), primitive_id)
    role = raw.get("role", "body")
    if role not in ROLES:
        raise _request_error(
            f"{primitive_id}.role 必须是 {'/'.join(ROLES)}。",
            details={"primitive_id": primitive_id, "role": role},
        )

    if shape == "cylinder":
        allowed = COMMON_FIELDS | {"diameter", "height"}
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise _request_error(
                f"{primitive_id} 的 cylinder 不支持字段：{', '.join(unknown)}。",
                details={"primitive_id": primitive_id, "unknown": unknown},
            )
        if "diameter" not in raw or "height" not in raw:
            raise _request_error(
                f"{primitive_id} 的 cylinder 需要 diameter 和 height。",
                details={"primitive_id": primitive_id},
            )
        if rotation != 0:
            raise _request_error(
                f"{primitive_id} 的 cylinder 不支持 rotation_z_deg。",
                details={"primitive_id": primitive_id},
            )
        radius = _number(raw["diameter"], "diameter", primitive_id)
        height = _number(raw["height"], "height", primitive_id)
        return {
            "primitive_id": primitive_id,
            "op": operation,
            "shape": shape,
            "center": center,
            "diameter": radius,
            "height": height,
            "rotation_z_deg": 0,
            "role": role,
        }

    allowed = COMMON_FIELDS | {"size"}
    if shape == "rounded_box":
        allowed = allowed | {"corner_radius"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise _request_error(
            f"{primitive_id} 的 {shape} 不支持字段：{', '.join(unknown)}。",
            details={"primitive_id": primitive_id, "unknown": unknown},
        )
    if "size" not in raw:
        raise _request_error(
            f"{primitive_id} 的 {shape} 需要 size。",
            details={"primitive_id": primitive_id},
        )
    size = _triple(raw["size"], "size", primitive_id)
    result = {
        "primitive_id": primitive_id,
        "op": operation,
        "shape": shape,
        "center": center,
        "size": size,
        "rotation_z_deg": rotation,
        "role": role,
    }
    if shape == "rounded_box":
        result["corner_radius"] = _number(
            raw.get("corner_radius", 0), "corner_radius", primitive_id
        )
    return result


def _text_primitive(
    raw: dict[str, Any], primitive_id: str, operation: str
) -> dict[str, Any]:
    unknown = sorted(set(raw) - TEXT_FIELDS)
    if unknown:
        raise _request_error(
            f"{primitive_id} 的 text 不支持字段：{', '.join(unknown)}。",
            details={"primitive_id": primitive_id, "unknown": unknown},
        )
    text = raw.get("text")
    if not isinstance(text, str) or not text or len(text) > 20:
        raise _request_error(
            f"{primitive_id}.text 必须是 1–20 个字符的字符串。",
            details={"primitive_id": primitive_id, "text": text},
        )
    if "center" not in raw:
        raise _request_error(f"{primitive_id} 缺少 center。", details={"primitive_id": primitive_id})
    center = _triple(raw["center"], "center", primitive_id)
    font_size = _number(raw.get("font_size"), "font_size", primitive_id)
    depth = _number(raw.get("depth"), "depth", primitive_id)
    face = raw.get("face")
    if face not in FACES:
        raise _request_error(
            f"{primitive_id}.face 必须是 {'/'.join(FACES)}。",
            details={"primitive_id": primitive_id, "face": face},
        )
    angle = _number(raw.get("angle", 0), "angle", primitive_id)
    return {
        "primitive_id": primitive_id,
        "op": operation,
        "shape": "text",
        "text": text,
        "font_size": font_size,
        "depth": depth,
        "center": center,
        "face": face,
        "angle": angle,
    }


def parse_request(raw: Any) -> dict[str, Any]:
    """Validate a ``zw.freeform-request/v1`` payload and normalize it."""
    if not isinstance(raw, dict):
        raise _request_error("freeform 请求顶层必须是对象。")
    unknown = sorted(set(raw) - {"schema", "design_id", "operations"})
    if unknown:
        raise _request_error(
            "请求包含未支持字段：" + ", ".join(unknown),
            details={"unknown": unknown},
        )
    schema = raw.get("schema", REQUEST_SCHEMA)
    if schema != REQUEST_SCHEMA:
        raise _request_error(
            f"请求 schema 必须是 {REQUEST_SCHEMA}。",
            details={"schema": schema},
        )
    design_id = raw.get("design_id", TEMPLATE)
    if not isinstance(design_id, str) or not IDENTIFIER.fullmatch(design_id):
        raise _request_error(
            "design_id 必须匹配 ^[a-z][a-z0-9_-]{0,63}$。",
            details={"design_id": design_id},
        )
    operations = raw.get("operations")
    if not isinstance(operations, list) or not operations:
        raise _request_error("operations 必须是 1–32 个操作的非空数组。")
    if len(operations) > MAX_OPERATIONS:
        raise _request_error(
            f"operations 最多 {MAX_OPERATIONS} 个，当前 {len(operations)} 个。"
        )
    normalized = [_primitive(item, index) for index, item in enumerate(operations)]
    identifiers = [item["primitive_id"] for item in normalized]
    if len(set(identifiers)) != len(identifiers):
        raise _request_error(
            "primitive_id 必须唯一。",
            details={"duplicates": sorted({item for item in identifiers if identifiers.count(item) > 1})},
        )
    geometry = [item for item in normalized if item["shape"] != "text"]
    if not geometry:
        raise _request_error(
            "请求至少需要一个几何操作（box/rounded_box/cylinder）；text 不能单独构成实体。"
        )
    if geometry[0]["op"] != "add":
        raise _request_error(
            "第一个几何操作必须是 add；freeform 不能从 cut 开始。",
            details={"primitive_id": geometry[0]["primitive_id"]},
        )
    return {
        "schema": REQUEST_SCHEMA,
        "design_id": design_id,
        "operations": normalized,
    }


def spec_data(request: dict[str, Any]) -> dict[str, Any]:
    primitives = []
    for item in request["operations"]:
        if item["shape"] == "text":
            continue
        primitive = {
            "primitive_id": item["primitive_id"],
            "operation": item["op"],
            "kind": item["shape"],
            "center": {"x": item["center"][0], "y": item["center"][1], "z": item["center"][2]},
            "rotation_z_deg": item["rotation_z_deg"],
            "role": item["role"],
        }
        if item["shape"] == "cylinder":
            primitive["diameter"] = item["diameter"]
            primitive["height"] = item["height"]
        else:
            primitive["size"] = {
                "length_x": item["size"][0],
                "width_y": item["size"][1],
                "height_z": item["size"][2],
            }
            if item["shape"] == "rounded_box":
                primitive["corner_radius"] = item["corner_radius"]
        primitives.append(primitive)
    return {
        "design_id": request["design_id"],
        "template": TEMPLATE,
        "template_revision": TEMPLATE_REVISION,
        "freeform_geometry": {"primitives": primitives},
    }


def _plan_upstream():
    try:
        from zhangwen.cad_engine import CadBuildSpec, resolve_layout, validate_design
    except ImportError as exc:
        raise ZwError(
            "DEPENDENCY_MISSING",
            f"本地掌问缺少 zhangwen.cad_engine：{exc}",
            "升级掌问到 V0.4.2026.1021.01 或更新版本；freeform 依赖该引擎。",
            5,
        ) from exc
    return {
        "CadBuildSpec": CadBuildSpec,
        "resolve_layout": resolve_layout,
        "validate_design": validate_design,
    }


def text_upstream():
    try:
        from zhangwen.web.solid_text import TextOperation
    except ImportError as exc:
        raise ZwError(
            "DEPENDENCY_MISSING",
            f"本地掌问缺少 zhangwen.web.solid_text：{exc}",
            "升级掌问到 V0.4.2026.1021.01 或更新版本；freeform 文字操作依赖该模块。",
            5,
        ) from exc
    return TextOperation


def text_operation_data(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "text",
        "operation": item["op"],
        "text": item["text"],
        "fontSize": item["font_size"],
        "depth": item["depth"],
        "center": item["center"],
        "face": item["face"],
        "angle": item["angle"],
    }


def text_operations(request: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        text_operation_data(item)
        for item in request["operations"]
        if item["shape"] == "text"
    ]


def validate_text_operations(
    text_model, operations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    validated = []
    for item in operations:
        try:
            operation = text_model.model_validate(item)
        except ValidationError as exc:
            raise ZwError(
                "TEXT_INVALID",
                "文字操作未通过校验。",
                "检查 text/font_size/depth/center/face/angle；文字需在随包字体中有轮廓。",
                4,
                details={"errors": _validation_detail(exc), "operation": item},
            ) from exc
        except OSError as exc:
            raise ZwError(
                "DEPENDENCY_MISSING",
                f"无法读取掌问字体：{exc}",
                "确认 $ZW_HOME/resources/fonts/NotoSansSC.ttf 存在。",
                5,
            ) from exc
        except ValueError as exc:
            raise ZwError(
                "TEXT_INVALID",
                f"文字无效：{exc}",
                "检查文字内容、字号和深度；不要使用字体缺失的字符。",
                4,
                details={"operation": item},
            ) from exc
        validated.append(operation.model_dump(mode="json"))
    return validated


def build_spec(upstream: dict, data: dict[str, Any]):
    try:
        return upstream["CadBuildSpec"].model_validate(data)
    except ValidationError as exc:
        raise ZwError(
            "DESIGN_INVALID",
            "freeform 规格未通过引擎校验。",
            "检查尺寸、坐标、rotation 和 primitive 组合；不要超出引擎范围。",
            4,
            details={"errors": _validation_detail(exc), "spec": data},
        ) from exc


def plan_spec(upstream: dict, spec) -> dict[str, Any]:
    try:
        layout = upstream["resolve_layout"](spec)
        report = upstream["validate_design"](spec, layout)
    except ValueError as exc:
        raise ZwError(
            "DESIGN_INVALID",
            f"freeform 布局或规格无效：{exc}",
            "检查模板 revision 与声明式几何字段。",
            4,
            details={"spec": spec.model_dump(mode="json")},
        ) from exc
    payload = {
        "design_id": spec.design_id,
        "template": spec.template,
        "template_revision": spec.template_revision,
        "spec": spec.model_dump(mode="json"),
        "layout": layout.model_dump(mode="json"),
        "validation": report.model_dump(mode="json"),
    }
    if not report.ok:
        failing = [check.check_id for check in report.checks if str(check.status) == "fail"]
        raise ZwError(
            "DESIGN_INVALID",
            "freeform 设计未通过引擎校验：" + (", ".join(failing) or "unknown"),
            "读取 validation.checks 中的 FAIL 项并修正输入。",
            4,
            details={"validation": payload["validation"], "spec": payload["spec"]},
        )
    return payload


def cmd_plan(request_value: str) -> CommandResult:
    upstream = _plan_upstream()
    raw = env.load_json_file(request_value)
    request = parse_request(raw)
    spec = build_spec(upstream, spec_data(request))
    plan = plan_spec(upstream, spec)
    operations = text_operations(request)
    plan["textOperations"] = (
        validate_text_operations(text_upstream(), operations) if operations else []
    )
    return CommandResult(data=plan, warnings=[PLAN_WARNING, NOMINAL_WARNING])


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def spec_wrapper(spec, text_operations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": SPEC_SCHEMA,
        "spec": spec.model_dump(mode="json"),
        "textOperations": text_operations,
    }


def load_spec(upstream: dict, raw: Any):
    """Accept the ZaaS wrapper or a bare freeform CadBuildSpec."""
    text_operations: list[dict[str, Any]] = []
    operations: list[Any] = []
    if isinstance(raw, dict) and "schema" in raw and raw.get("schema") != SPEC_SCHEMA:
        raise _spec_error(
            f"freeform spec schema 必须是 {SPEC_SCHEMA}。",
            details={"schema": raw.get("schema")},
        )
    if isinstance(raw, dict) and raw.get("schema") == SPEC_SCHEMA:
        unknown = sorted(set(raw) - {"schema", "spec", "textOperations"})
        if unknown:
            raise _spec_error(
                "freeform spec 包装包含未支持字段：" + ", ".join(unknown),
                details={"unknown": unknown},
            )
        if not isinstance(raw.get("spec"), dict):
            raise _spec_error("freeform spec 包装缺少 spec 对象。")
        operations = raw.get("textOperations", [])
        if not isinstance(operations, list):
            raise _spec_error("textOperations 必须是数组。")
        for index, item in enumerate(operations):
            if not isinstance(item, dict):
                raise _spec_error(f"textOperations[{index}] 必须是对象。")
        data = raw["spec"]
    else:
        data = raw
    if not isinstance(data, dict):
        raise _spec_error("freeform spec 顶层必须是对象。")
    spec = build_spec(upstream, data)
    if spec.template != TEMPLATE:
        raise _spec_error(
            f"freeform --spec 只接受 template={TEMPLATE}，当前 {spec.template}。",
            details={"template": spec.template},
        )
    if spec.template_revision != TEMPLATE_REVISION:
        raise _spec_error(
            f"freeform --spec 需要 template_revision={TEMPLATE_REVISION}，当前 {spec.template_revision}。",
            details={"template_revision": spec.template_revision},
        )
    if operations:
        text_operations = validate_text_operations(text_upstream(), operations)
    return spec, text_operations
