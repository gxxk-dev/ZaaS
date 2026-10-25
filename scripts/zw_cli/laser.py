"""Laser-cut drawing generation from the bounded ZhangWen templates."""

from __future__ import annotations

import json

from . import env
from .envelope import CommandResult, ZwError

LASER_TEMPLATES = {
    "plate": {"width", "depth", "thickness"},
    "round-tag": {"width", "thickness"},
    "panel-box": {"width", "depth", "height", "thickness"},
    "finger-box": {"width", "depth", "height", "thickness", "material", "panelTexts"},
    "rounded-box": {
        "width",
        "depth",
        "height",
        "thickness",
        "corner_radius",
        "tab_width",
        "slot_spacing",
        "slot_bridge",
        "slot_rows",
        "top_lid",
        "bottom_lid",
        "material",
    },
}

DEFAULTS = {
    "width": 80,
    "depth": 60,
    "height": 40,
    "thickness": 3,
    "material": "待确认材料",
}

ROUNDED_DEFAULTS = {
    "width": 50,
    "depth": 50,
    "height": 50,
    "thickness": 3,
    "corner_radius": 12,
    "tab_width": 5,
    "slot_spacing": 1.2,
    "slot_bridge": 2,
    "slot_rows": 2,
    "top_lid": 1,
    "bottom_lid": 1,
}


def _params(value: str) -> dict:
    try:
        if value.startswith("@"):
            data = json.loads(open(value[1:], encoding="utf-8").read())
        else:
            data = json.loads(value)
    except OSError as exc:
        raise ZwError("PARAMS_READ_FAILED", f"无法读取参数文件：{value[1:]}", str(exc), 7) from exc
    except ValueError as exc:
        raise ZwError("PARAMS_INVALID", f"--params 不是有效 JSON：{exc}", "", 2) from exc
    if not isinstance(data, dict):
        raise ZwError("PARAMS_INVALID", "--params 必须是 JSON 对象。", "", 2)
    return data


def _resolved(template: str, params: dict) -> dict:
    if template == "rounded-box":
        base = {**ROUNDED_DEFAULTS, "material": DEFAULTS["material"]}
    elif template == "finger-box":
        base = dict(DEFAULTS)
    elif template == "plate":
        base = {key: DEFAULTS[key] for key in ("width", "depth", "thickness")}
    elif template == "round-tag":
        base = {key: DEFAULTS[key] for key in ("width", "thickness")}
    else:
        base = {key: DEFAULTS[key] for key in ("width", "depth", "height", "thickness")}
    return {**base, **params}


def cmd_build(template: str, *, params: str, out_value: str, force: bool, allow_in_repo: bool) -> CommandResult:
    if template not in LASER_TEMPLATES:
        raise ZwError(
            "TEMPLATE_NOT_FOUND",
            f"未知激光模板：{template}",
            "可用模板：" + ", ".join(LASER_TEMPLATES),
            3,
        )
    values = _params(params)
    unknown = sorted(set(values) - LASER_TEMPLATES[template])
    if unknown:
        raise ZwError(
            "PARAM_UNKNOWN",
            f"模板 {template} 不接受参数：{', '.join(unknown)}",
            "可用参数：" + ", ".join(sorted(LASER_TEMPLATES[template])),
            2,
        )

    try:
        from fastapi import HTTPException
        from pydantic import ValidationError
        from zhangwen.web.design_specs import dxf, svg, template_spec

        spec = template_spec(template, values)
        spec.check_kind("laser")
    except ImportError as exc:
        raise ZwError("DEPENDENCY_MISSING", f"无法导入激光模板模块：{exc}", "安装 requirements-core.txt。", 5) from exc
    except ValidationError as exc:
        detail = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in exc.errors()
        )
        raise ZwError("PARAMS_INVALID", f"激光参数无效：{detail}", "", 2) from exc
    except HTTPException as exc:
        raise ZwError("PARAMS_INVALID", str(exc.detail), "", 2) from exc
    except ValueError as exc:
        raise ZwError("TEMPLATE_INVALID", f"激光图纸生成失败：{exc}", "", 2) from exc

    out = env.resolve_out(out_value, force=force, allow_in_repo=allow_in_repo)
    env.prepare_out(out)
    drawing = spec.drawing
    resolved = _resolved(template, values)
    design = {
        "schema": "zw.laser/v1",
        "template": template,
        "params": resolved,
        "spec": spec.model_dump(mode="json"),
        "notice": "名义尺寸；未做刀缝补偿、材料弯折或实物装配验证。",
    }
    writes = [
        env.write_text(out, "cut.svg", svg(drawing)),
        env.write_text(out, "preview.svg", svg(drawing, preview=True)),
        env.write_text(out, "cut.dxf", dxf(drawing), encoding="ascii"),
        env.write_text(out, "design.json", json.dumps(design, ensure_ascii=False, indent=2) + "\n"),
    ]
    warnings = [
        "输出为名义尺寸，未做刀缝补偿；切割前先在加工软件中补偿并试切。",
        "几何文件不代表材料弯折、榫接配合或实物装配已验收。",
    ]
    if resolved.get("material") in (None, "", "待确认材料"):
        warnings.append("material 未确认；填充率、弯折与切割参数需按实际板材决定。")
    data = {
        "template": template,
        "title": spec.title,
        "summary": spec.summary,
        "drawing": {
            "width": drawing.width,
            "height": drawing.height,
            "thickness": drawing.thickness,
            "material": drawing.material,
            "shapes": len(drawing.shapes),
        },
        "exports": {
            "cutSvg": str(out / "cut.svg"),
            "cutDxf": str(out / "cut.dxf"),
            "previewSvg": str(out / "preview.svg"),
            "design": str(out / "design.json"),
        },
    }
    return CommandResult(data=data, warnings=warnings, writes=writes)
