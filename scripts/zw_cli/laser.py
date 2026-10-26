"""Laser-cut drawing generation from the bounded ZhangWen templates."""

from __future__ import annotations

import json
import math

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
        "pattern_version",
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
    "pattern_version": 2,
}


def _upstream_laser():
    try:
        from fastapi import HTTPException
        from zhangwen.web import laser_text
        from zhangwen.web.design_specs import (
            DesignSpec,
            Drawing,
            LaserShape,
            dxf,
            svg,
            template_spec,
        )
        from pydantic import ValidationError
    except ImportError as exc:
        raise ZwError(
            "DEPENDENCY_MISSING",
            f"无法导入激光模板模块：{exc}",
            "安装 requirements-core.txt。",
            5,
        ) from exc
    return {
        "HTTPException": HTTPException,
        "laser_text": laser_text,
        "DesignSpec": DesignSpec,
        "Drawing": Drawing,
        "LaserShape": LaserShape,
        "ValidationError": ValidationError,
        "dxf": dxf,
        "svg": svg,
        "template_spec": template_spec,
    }


def _text_shape(mods, text: str, size: float, margin: float):
    try:
        text_width, _ = mods["laser_text"].outlines(text, size)
    except ValueError as exc:
        raise ZwError("TEXT_INVALID", f"文字无法雕刻：{exc}", "", 4) from exc
    except OSError as exc:
        raise ZwError(
            "DEPENDENCY_MISSING",
            f"无法读取掌问字体：{exc}",
            "确认 $ZW_HOME/resources/fonts/NotoSansSC.ttf 存在。",
            5,
        ) from exc
    width = round(text_width + 2 * margin, 6)
    height = round(size + 2 * margin, 6)
    if width > 1000 or height > 1000:
        raise ZwError(
            "TEXT_INVALID",
            "文字画布超过 1000mm 上限。",
            "减小 --size/--margin 或缩短文字。",
            4,
            details={"textWidth": text_width, "size": size, "margin": margin},
        )
    try:
        spec = mods["DesignSpec"](
            title=f"文字雕刻：{text}",
            summary="激光雕刻文字；仅雕刻，不切穿；名义尺寸，未做刀缝补偿。",
            drawing=mods["Drawing"](
                width=width,
                height=height,
                thickness=3,
                material="待确认材料",
                shapes=[
                    mods["LaserShape"](
                        kind="text",
                        operation="engrave",
                        x=margin,
                        y=margin,
                        text=text,
                        fontSize=size,
                    )
                ],
            ),
        )
        spec.check_kind("laser")
    except mods["ValidationError"] as exc:
        detail = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in exc.errors()
        )
        raise ZwError("TEXT_INVALID", f"文字图纸无效：{detail}", "", 4) from exc
    except ValueError as exc:
        raise ZwError("TEXT_INVALID", f"文字图纸无效：{exc}", "", 4) from exc
    return spec, text_width, width, height



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
    pattern_version = values.get("pattern_version", ROUNDED_DEFAULTS["pattern_version"])
    if template == "rounded-box" and pattern_version not in (1, 2):
        raise ZwError(
            "PARAMS_INVALID",
            f"pattern_version 必须是 1 或 2：{pattern_version}",
            "旧设计用 1 复现排版；新设计用默认 2。",
            2,
        )

    mods = _upstream_laser()
    try:
        spec = mods["template_spec"](template, values)
        if template == "rounded-box" and pattern_version == 1:
            payload = spec.model_dump(mode="json")
            payload["roundedBox"]["pattern_version"] = 1
            payload["drawing"] = None
            payload["summary"] = (
                "旧版圆角盒排版：保留旧检查点的盖板、围板与切缝排布；"
                "新设计请使用默认 pattern_version=2。名义尺寸，未补偿刀缝。"
            )
            spec = mods["DesignSpec"].model_validate(payload)
        spec.check_kind("laser")
    except mods["ValidationError"] as exc:
        detail = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in exc.errors()
        )
        raise ZwError("PARAMS_INVALID", f"激光参数无效：{detail}", "", 2) from exc
    except mods["HTTPException"] as exc:
        raise ZwError("PARAMS_INVALID", str(exc.detail), "", 2) from exc
    except ValueError as exc:
        raise ZwError("TEMPLATE_INVALID", f"激光图纸生成失败：{exc}", "", 2) from exc

    out = env.resolve_out(out_value, force=force, allow_in_repo=allow_in_repo)
    env.prepare_out(out)
    drawing = spec.drawing
    svg = mods["svg"]
    dxf = mods["dxf"]
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
    if template == "rounded-box" and resolved.get("pattern_version") == 1:
        warnings.append(
            "pattern_version=1 仅用于复现旧版圆角盒排版；新设计请用默认 v2，两种排版的切缝不同。"
        )

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


def cmd_templates() -> CommandResult:
    mods = _upstream_laser()
    templates: list[dict] = []
    warnings: list[str] = []
    for template in LASER_TEMPLATES:
        try:
            spec = mods["template_spec"](template, {})
        except (mods["ValidationError"], mods["HTTPException"], ValueError) as exc:
            warnings.append(f"跳过无法生成的激光模板 {template}：{exc}")
            continue
        resolved = _resolved(template, {})
        if template == "finger-box":
            resolved.setdefault("panelTexts", [])
        templates.append(
            {
                "id": template,
                "title": spec.title,
                "summary": spec.summary,
                "parameters": [
                    {"name": name, "default": resolved.get(name)}
                    for name in sorted(LASER_TEMPLATES[template])
                ],
                "patternVersions": [1, 2] if template == "rounded-box" else [],
            }
        )
    return CommandResult(
        data={"count": len(templates), "templates": templates},
        warnings=warnings,
    )


def cmd_text(
    text: str,
    *,
    size: float,
    margin: float,
    out_value: str | None,
    force: bool,
    allow_in_repo: bool,
) -> CommandResult:
    if out_value is None and (force or allow_in_repo):
        raise ZwError(
            "REQUEST_INVALID",
            "--force/--allow-in-repo 只能与 --out 同用。",
            "",
            2,
        )
    if not math.isfinite(size) or not 1 <= size <= 150:
        raise ZwError("TEXT_INVALID", "--size 必须是 1 到 150 毫米。", "", 4)
    if not math.isfinite(margin) or margin < 0:
        raise ZwError("TEXT_INVALID", "--margin 必须大于等于 0。", "", 4)

    mods = _upstream_laser()
    spec, text_width, width, height = _text_shape(mods, text, size, margin)
    drawing = spec.drawing
    data = {
        "title": spec.title,
        "summary": spec.summary,
        "text": text,
        "textWidth": text_width,
        "canvas": {"width": width, "height": height, "margin": margin},
        "spec": spec.model_dump(mode="json"),
        "drawing": {
            "width": drawing.width,
            "height": drawing.height,
            "thickness": drawing.thickness,
            "material": drawing.material,
            "shapes": len(drawing.shapes),
        },
    }
    warnings = [
        "文字只做雕刻，不切穿；输出为名义尺寸，未做刀缝补偿。",
        "字体固定为掌问随包 NotoSansSC.ttf；字体缺字时会直接失败，不替换字形。",
    ]

    if out_value is not None:
        out = env.resolve_out(out_value, force=force, allow_in_repo=allow_in_repo)
        env.prepare_out(out)
        design = {
            "schema": "zw.laser/v1",
            "template": "text",
            "params": {"text": text, "size": size, "margin": margin},
            "spec": spec.model_dump(mode="json"),
            "notice": "名义尺寸；文字仅雕刻，未做刀缝补偿或材料验证。",
        }
        writes = [
            env.write_text(out, "cut.svg", mods["svg"](drawing)),
            env.write_text(out, "preview.svg", mods["svg"](drawing, preview=True)),
            env.write_text(out, "cut.dxf", mods["dxf"](drawing), encoding="ascii"),
            env.write_text(
                out,
                "design.json",
                json.dumps(design, ensure_ascii=False, indent=2) + "\n",
            ),
        ]
        data["exports"] = {
            "cutSvg": str(out / "cut.svg"),
            "cutDxf": str(out / "cut.dxf"),
            "previewSvg": str(out / "preview.svg"),
            "design": str(out / "design.json"),
        }
        return CommandResult(data=data, warnings=warnings, writes=writes)
    return CommandResult(data=data, warnings=warnings)

