"""Python-side CAD: packaged templates, bounded edits and parametric solids."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

from . import env
from .envelope import CommandResult, ZwError


def _upstream():
    try:
        from pydantic import ValidationError
        from zhangwen.web import solid_worker, template_worker
        from zhangwen.web.builtin_templates import TEMPLATES, checked_source
        from zhangwen.web.design_specs import DesignSpec, solid_code
        from zhangwen.web.template_edits import (
            TemplateEditSpec,
            checked_spec,
            effective_plan,
            numeric_parameters,
            render_source,
        )
    except ImportError as exc:
        raise ZwError(
            "DEPENDENCY_MISSING",
            f"无法导入 CadQuery 模板模块：{exc}",
            "在 ZW_HOME/.venv 或 requirements-cad.txt 中安装 CadQuery。",
            5,
        ) from exc
    return {
        "ValidationError": ValidationError,
        "solid_worker": solid_worker,
        "template_worker": template_worker,
        "TEMPLATES": TEMPLATES,
        "checked_source": checked_source,
        "DesignSpec": DesignSpec,
        "solid_code": solid_code,
        "TemplateEditSpec": TemplateEditSpec,
        "checked_spec": checked_spec,
        "effective_plan": effective_plan,
        "numeric_parameters": numeric_parameters,
        "render_source": render_source,
    }


def _json_from_stdout(text: str) -> dict:
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    raise ZwError("BUILD_REPORT_INVALID", "CAD worker 未返回结构化结果。", text[-500:], 7)


def _output_files(out: Path, patterns: tuple[str, ...]) -> list[str]:
    found = []
    for pattern in patterns:
        found.extend(str(path) for path in sorted(out.glob(pattern)))
    return found


def cmd_template(
    identifier: str,
    *,
    edit: str | None,
    out_value: str | None,
    force: bool,
    allow_in_repo: bool,
    list_params: bool = False,
) -> CommandResult:
    mods = _upstream()
    item = mods["TEMPLATES"].get(identifier)
    if item is None:
        raise ZwError(
            "TEMPLATE_NOT_FOUND",
            f"未知 3D 固定模板：{identifier}",
            "可用模板：" + ", ".join(mods["TEMPLATES"]),
            3,
        )
    try:
        source_path = mods["checked_source"](item)
        source = source_path.read_text(encoding="utf-8-sig")
    except ValueError as exc:
        raise ZwError("TEMPLATE_INTEGRITY", f"模板源码校验失败：{identifier}", str(exc), 7) from exc
    except OSError as exc:
        raise ZwError("TEMPLATE_READ_FAILED", f"无法读取模板源码：{identifier}", str(exc), 7) from exc

    if list_params:
        if edit or out_value:
            raise ZwError("ARGS_CONFLICT", "--list-params 不能与 --edit/--out 同用。", "", 2)
        parameters = mods["numeric_parameters"](source)
        data = {
            "template": {
                "id": item["id"],
                "title": item["title"],
                "description": item.get("description", ""),
                "revision": item.get("revision"),
                "size": item.get("size"),
                "notes": item.get("notes", []),
            },
            "parameters": [
                {"name": name, "default": value}
                for name, (value, _) in parameters.items()
            ],
            "parts": [
                {key: part[key] for key in ("id", "label", "printable")}
                for part in item.get("parts", [])
            ],
            "rules": "parameterOverrides 只能使用 parameters 中的名字；partOperations 只能作用于 printable=true 部件。",
        }
        return CommandResult(data=data)

    if not out_value:
        raise ZwError("OUT_REQUIRED", "结构模板生成需要 --out DIR。", "或用 --list-params 只查看参数。", 2)
    if edit:
        raw = env.load_json_file(edit)
        try:
            spec = mods["checked_spec"](raw, item, source)
        except mods["ValidationError"] as exc:
            detail = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            )
            raise ZwError("EDIT_INVALID", f"模板改造方案无效：{detail}", "", 2) from exc
        except ValueError as exc:
            raise ZwError("EDIT_INVALID", f"模板改造方案无效：{exc}", "", 2) from exc
    else:
        spec = mods["TemplateEditSpec"](title=item["title"])

    if spec.questions:
        raise ZwError(
            "EDIT_NEEDS_INPUT",
            "模板改造方案还有待确认问题，未生成模型。",
            "先回答 questions，再重新生成 plan.json。",
            4,
            details={"questions": spec.questions, "summary": spec.summary},
        )
    try:
        rendered = mods["render_source"](source, spec, item)
    except ValueError as exc:
        raise ZwError("EDIT_INVALID", f"模板改造无法渲染：{exc}", "", 2) from exc

    out = env.resolve_out(out_value, force=force, allow_in_repo=allow_in_repo)
    env.prepare_out(out)
    writes = [
        env.write_text(out, "template-edit.json", spec.model_dump_json(indent=2) + "\n"),
        env.write_text(out, "cadquery.py", rendered),
    ]
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            mods["template_worker"].build(identifier, out)
    except ValueError as exc:
        message = str(exc)
        code = "TEMPLATE_INTEGRITY" if "摘要不符" in message or "安装" in message else "GEOMETRY_INVALID"
        exit_code = 7 if code == "TEMPLATE_INTEGRITY" else 4
        hint = "检查操作中心/尺寸是否与原实体相交；刻字深度必须小于板厚。" if exit_code == 4 else "重新安装或修复掌问模板文件。"
        raise ZwError(code, f"模板生成失败：{message}", hint, exit_code, writes=writes) from exc
    except Exception as exc:
        raise ZwError(
            "BUILD_FAILED",
            f"模板生成失败：{type(exc).__name__}: {exc}",
            "检查 CadQuery/OCP 安装；设置 ZW_DEBUG=1 查看堆栈。",
            7,
            writes=writes,
        ) from exc
    report = _json_from_stdout(buffer.getvalue())
    writes = _output_files(out, ("template-*.step", "template-*.stl"))
    writes += [str(out / "cadquery.py"), str(out / "template-edit.json")]
    plan = mods["effective_plan"](spec, source)
    data = {
        "template": {
            "id": item["id"],
            "title": item["title"],
            "description": item.get("description", ""),
            "revision": item.get("revision"),
            "size": item.get("size"),
            "notes": item.get("notes", []),
            "parts": [
                {key: part[key] for key in ("id", "label", "printable")}
                for part in item.get("parts", [])
            ],
        },
        "parts": report.get("parts", []),
        "printableCount": report.get("printableCount"),
        "size": report.get("size"),
        "edit": plan,
        "files": writes,
    }
    warnings = [
        "输出为原模板装配坐标下的名义几何；导出前各部件才归零到 z=0。",
        "未做打印公差、材料收缩或实物装配验证。",
        *[str(note) for note in item.get("notes", [])],
    ]
    return CommandResult(data=data, warnings=warnings, writes=writes)


def cmd_solid(
    spec_value: str,
    *,
    out_value: str,
    force: bool,
    allow_in_repo: bool,
) -> CommandResult:
    mods = _upstream()
    raw = env.load_json_file(spec_value)
    if isinstance(raw, dict) and isinstance(raw.get("spec"), dict):
        spec_data = raw["spec"]
        scale = raw.get("scale", 1)
    else:
        spec_data = raw
        scale = 1
    if not isinstance(scale, (int, float)) or not 0.1 <= scale <= 5:
        raise ZwError("SCALE_INVALID", "scale 必须是 0.1 到 5 的数值。", "", 2)
    try:
        spec = mods["DesignSpec"].model_validate(spec_data)
        spec.check_kind("model")
    except mods["ValidationError"] as exc:
        detail = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise ZwError("SPEC_INVALID", f"DesignSpec 无效：{detail}", "", 2) from exc
    except ValueError as exc:
        raise ZwError("SPEC_INVALID", f"DesignSpec 无效：{exc}", "", 2) from exc
    if spec.questions:
        raise ZwError(
            "SPEC_NEEDS_INPUT",
            "DesignSpec 还有待确认问题，未生成模型。",
            "先回答 questions，再重新生成 spec.json。",
            4,
            details={"questions": spec.questions, "summary": spec.summary},
        )

    out = env.resolve_out(out_value, force=force, allow_in_repo=allow_in_repo)
    env.prepare_out(out)
    writes = [
        env.write_text(out, "design-spec.json", json.dumps({"spec": spec.model_dump(mode="json"), "scale": scale}, ensure_ascii=False, indent=2) + "\n"),
        env.write_text(out, "cadquery.py", mods["solid_code"](spec, scale)),
    ]
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            mods["solid_worker"].build(spec, out, scale)
    except ValueError as exc:
        raise ZwError(
            "GEOMETRY_INVALID",
            f"实体生成失败：{exc}",
            "检查实体是否从 add 开始、cut 是否与实体相交，以及尺寸上限。",
            4,
            writes=writes,
        ) from exc
    except Exception as exc:
        raise ZwError(
            "BUILD_FAILED",
            f"实体生成失败：{type(exc).__name__}: {exc}",
            "检查 CadQuery/OCP 安装；设置 ZW_DEBUG=1 查看堆栈。",
            7,
            writes=writes,
        ) from exc
    report = _json_from_stdout(buffer.getvalue())
    writes = [str(out / "model.step"), str(out / "model.stl"), str(out / "design-spec.json"), str(out / "cadquery.py")]
    data = {
        "title": spec.title,
        "summary": spec.summary,
        "scale": scale,
        "size": report.get("size"),
        "volume": report.get("volume"),
        "solids": report.get("solids"),
        "files": writes,
    }
    warnings = [
        "输出为名义几何；未做打印公差、材料收缩或实物装配验证。",
        "几何有效性不代表强度、承重或打印成功率。",
    ]
    return CommandResult(data=data, warnings=warnings, writes=writes)
