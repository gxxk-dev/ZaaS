"""zw command-line entry point."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

from . import boards as boards_cli
from . import code, doctor, env, firmware, hardware, laser as laser_cli
from .envelope import CommandResult, ZwError, failure, ok, print_json


def _common() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--json", action="store_true", help="输出 zw.cli/v1 JSON")
    return parser


def _parser() -> argparse.ArgumentParser:
    common = _common()
    parser = argparse.ArgumentParser(prog="zw", description="掌问本地确定性 CLI")
    groups = parser.add_subparsers(dest="group", required=True)

    status = groups.add_parser("status", parents=[common], help="自检安装、依赖与数据")
    status.set_defaults(func=lambda a: doctor.cmd_status(), command="status")
    doctor_parser = groups.add_parser("doctor", parents=[common], help="同 status")
    doctor_parser.set_defaults(func=lambda a: doctor.cmd_status(), command="doctor")

    boards = groups.add_parser("boards", parents=[common], help="列出主控或读取 Board Skill")
    boards.add_argument("--board", help="只看指定主控")
    boards.add_argument("--full", action="store_true", help="读取 Board Skill 元数据与入口")
    boards.add_argument("--file", dest="file_path", help="读取 Board Skill 中的一个文件（需 --full）")
    boards.add_argument("--context", help="按查询筛选 Board Skill 上下文")
    boards.set_defaults(
        func=lambda a: boards_cli.cmd_boards(
            board=a.board,
            full=a.full,
            file_path=a.file_path,
            context=a.context,
        ),
        command="boards",
    )

    hard = groups.add_parser("hardware", help="硬件资料与模块指南")
    hard_sub = hard.add_subparsers(dest="hardware_command", required=True)

    search = hard_sub.add_parser("search", parents=[common], help="搜索硬件资料包")
    search.add_argument("query")
    search.add_argument("--board", help="主控别名或 componentId")
    search.add_argument("--category", help="SENSOR/ACTUATOR/MCU/DISPLAY/POWER")
    search.add_argument("--limit", type=int, default=20)
    search.set_defaults(
        func=lambda a: hardware.cmd_search(a.query, board=a.board, category=a.category, limit=a.limit),
        command="hardware search",
    )

    get = hard_sub.add_parser("get", parents=[common], help="读取资料包详情")
    get.add_argument("identifier", help="componentId、skillName 或显示名")
    get.add_argument("--full", action="store_true", help="包含全部文件正文")
    get.add_argument("--file", dest="file_path", help="只输出指定文件")
    get.set_defaults(
        func=lambda a: hardware.cmd_get(a.identifier, full=a.full, file_path=a.file_path),
        command="hardware get",
    )

    guide = hard_sub.add_parser("guide", parents=[common], help="按主控渲染模块指南")
    guide.add_argument("identifier")
    guide.add_argument("--board", required=True)
    guide.add_argument("--kind", help="断言指南种类：functional/diagnostic/reference")
    guide.add_argument("--set", dest="setup", action="append", default=[], metavar="KEY=VALUE")
    guide.set_defaults(
        func=lambda a: hardware.cmd_guide(
            a.identifier,
            board=a.board,
            setup_pairs=a.setup,
            kind=a.kind,
        ),
        command="hardware guide",
    )

    validate = hard_sub.add_parser("validate", parents=[common], help="电气规则校验")
    validate.add_argument("board")
    validate.add_argument("components", nargs="*")
    validate.set_defaults(func=lambda a: hardware.cmd_validate(a.board, a.components), command="hardware validate")

    fw = groups.add_parser("firmware", help="固件目录与本地镜像校验")
    fw_sub = fw.add_subparsers(dest="firmware_command", required=True)

    fw_list = fw_sub.add_parser("list", parents=[common], help="列出主控固件元数据")
    fw_list.add_argument("--board", help="只列指定主控")
    fw_list.set_defaults(func=lambda a: firmware.cmd_list(board=a.board), command="firmware list")

    fw_get = fw_sub.add_parser("get", parents=[common], help="读取主控固件详情")
    fw_get.add_argument("board_id", help="主控别名、显示名或 componentId")
    fw_get.set_defaults(func=lambda a: firmware.cmd_get(a.board_id), command="firmware get")

    fw_verify = fw_sub.add_parser("verify", parents=[common], help="只读校验本地固件镜像")
    fw_verify.add_argument("board_id", help="主控别名、显示名或 componentId")
    fw_verify.add_argument("--file", required=True, help="本地固件文件")
    fw_verify.set_defaults(
        func=lambda a: firmware.cmd_verify(a.board_id, file=a.file),
        command="firmware verify",
    )

    coding = groups.add_parser("code", help="MicroPython 检查")
    code_sub = coding.add_subparsers(dest="code_command", required=True)
    check = code_sub.add_parser("check", parents=[common], help="语法、板级 API 与可选电气检查")
    check.add_argument("--board", required=True)
    check.add_argument("--file", required=True, help="源文件，或 - 读 stdin")
    check.add_argument("--component", action="append", default=[])
    check.set_defaults(
        func=lambda a: code.cmd_check(a.board, file=a.file, components=a.component),
        command="code check",
    )

    fix = code_sub.add_parser("fix", parents=[common], help="确定性修复已知板级问题（只读，可选 --out）")
    fix.add_argument("--board", required=True)
    fix.add_argument("--file", required=True, help="源文件，或 - 读 stdin")
    fix.add_argument("--out", dest="out_path", help="把修复结果写入不存在的文件")
    fix.set_defaults(
        func=lambda a: code.cmd_fix(a.board, file=a.file, out_value=a.out_path),
        command="code fix",
    )

    laser = groups.add_parser("laser", help="激光切割图纸")
    laser_sub = laser.add_subparsers(dest="laser_command", required=True)
    build = laser_sub.add_parser("build", parents=[common], help="生成 SVG/DXF")
    build.add_argument("--template", required=True)
    build.add_argument("--params", default="{}", help="JSON，或 @file")
    build.add_argument("--out", required=True)
    build.add_argument("--force", action="store_true")
    build.add_argument("--allow-in-repo", action="store_true")
    build.set_defaults(func=_laser_build, command="laser build")

    laser_templates = laser_sub.add_parser("templates", parents=[common], help="列出激光模板与参数")
    laser_templates.set_defaults(func=lambda a: laser_cli.cmd_templates(), command="laser templates")

    laser_text = laser_sub.add_parser("text", parents=[common], help="生成文字雕刻图纸")
    laser_text.add_argument("--text", required=True)
    laser_text.add_argument("--size", type=float, default=10, help="文字实际高度，毫米")
    laser_text.add_argument("--margin", type=float, default=5, help="四周留白，毫米")
    laser_text.add_argument("--out")
    laser_text.add_argument("--force", action="store_true")
    laser_text.add_argument("--allow-in-repo", action="store_true")
    laser_text.set_defaults(
        func=lambda a: laser_cli.cmd_text(
            a.text,
            size=a.size,
            margin=a.margin,
            out_value=a.out,
            force=a.force,
            allow_in_repo=a.allow_in_repo,
        ),
        command="laser text",
    )

    structure = groups.add_parser("structure", help="Python CAD")
    structure_sub = structure.add_subparsers(dest="structure_command", required=True)
    template = structure_sub.add_parser("template", parents=[common], help="固定模板与受约束改造")
    template.add_argument("identifier")
    template.add_argument("--edit", help="TemplateEditSpec JSON 文件，或 -")
    template.add_argument("--list-params", action="store_true", help="只列出可改参数与部件")
    template.add_argument("--out")
    template.add_argument("--force", action="store_true")
    template.add_argument("--allow-in-repo", action="store_true")
    template.set_defaults(func=_structure_template, command="structure template")

    solid = structure_sub.add_parser("solid", parents=[common], help="参数化 DesignSpec")
    solid.add_argument("--spec", required=True, help="DesignSpec JSON 文件，或 -")
    solid.add_argument("--out", required=True)
    solid.add_argument("--force", action="store_true")
    solid.add_argument("--allow-in-repo", action="store_true")
    solid.set_defaults(func=_structure_solid, command="structure solid")

    enclosure = groups.add_parser("enclosure", help="确定性外壳管线")
    enclosure_sub = enclosure.add_subparsers(dest="enclosure_command", required=True)
    enc_plan = enclosure_sub.add_parser("plan", parents=[common], help="解析请求并规划（只读）")
    enc_plan.add_argument("--request", required=True, help="请求 JSON 文件，或 -")
    enc_plan.set_defaults(func=_enclosure_plan, command="enclosure plan")

    enc_build = enclosure_sub.add_parser("build", parents=[common], help="生成 STEP/STL/GLB")
    enc_source = enc_build.add_mutually_exclusive_group(required=True)
    enc_source.add_argument("--request", help="请求 JSON 文件，或 -")
    enc_source.add_argument("--spec", help="CadBuildSpec JSON 文件，或 -")
    enc_build.add_argument("--out", required=True)
    enc_build.set_defaults(func=_enclosure_build, command="enclosure build")
    return parser


def _laser_build(args) -> CommandResult:
    from . import laser

    return laser.cmd_build(
        args.template,
        params=args.params,
        out_value=args.out,
        force=args.force,
        allow_in_repo=args.allow_in_repo,
    )


def _structure_template(args) -> CommandResult:
    from . import cad

    return cad.cmd_template(
        args.identifier,
        edit=args.edit,
        out_value=args.out,
        force=args.force,
        allow_in_repo=args.allow_in_repo,
        list_params=args.list_params,
    )


def _structure_solid(args) -> CommandResult:
    from . import cad

    return cad.cmd_solid(
        args.spec,
        out_value=args.out,
        force=args.force,
        allow_in_repo=args.allow_in_repo,
    )


def _enclosure_plan(args) -> CommandResult:
    from . import enclosure

    return enclosure.cmd_plan(args.request)


def _enclosure_build(args) -> CommandResult:
    from . import enclosure

    return enclosure.cmd_build(
        request_value=args.request,
        spec_value=args.spec,
        out_value=args.out,
    )


def _human(command: str, payload: dict) -> None:
    if not payload.get("ok"):
        error = payload.get("error", {})
        print(f"zw: {error.get('message', '失败')}", file=sys.stderr)
        if error.get("hint"):
            print(f"提示: {error['hint']}", file=sys.stderr)
        return
    data = payload.get("data") or {}
    warnings = payload.get("warnings") or []

    if command in {"status", "doctor"}:
        print(f"ZW_HOME: {data.get('zwHome')}")
        print(f"掌问版本: {data.get('zhangwenVersion') or 'unknown'}")
        print(f"数据目录: {data.get('dataDir')}")
        print(f"Python: {data.get('python')} ({data.get('pythonSource')})")
        print(f"目录缓存: {data.get('cache', {}).get('count')} / 磁盘 {data.get('cache', {}).get('scanCount')} 包")
        print("依赖: " + ", ".join(
            f"{name}={item.get('version') or ('ok' if item.get('installed') else 'missing')}"
            for name, item in (data.get("deps") or {}).items()
        ))
        print(f"主控: {len(data.get('boards') or [])}  激光模板: {len(data.get('templates', {}).get('laser') or [])}  3D 模板: {len(data.get('templates', {}).get('cad') or [])}")
    elif command == "boards":
        if "boards" in data:
            for item in data.get("boards", []):
                marks = []
                marks.append("board" if item.get("hasBoardSkill") else "no-board")
                marks.append("prog" if item.get("programmingSkill") else "no-prog")
                marks.append("fw" if item.get("firmwareInstalled") else "no-fw")
                print(f"{item['componentId']:<36} {item['displayName']:<28} {item.get('skillName') or '-':<34} {'/'.join(marks)}")
        elif "instructions" in data:
            board = data.get("board") or {}
            package = data.get("package") or {}
            print(f"{board.get('displayName')} ({board.get('componentId')})  context: {data.get('query')}")
            print(f"Board Skill: {package.get('id')}  {package.get('version')}  profile={package.get('profileId')}")
            print(f"instructions: {len(data.get('instructions') or '')} chars")
            print(f"references: {len(data.get('references') or [])}  templates: {len(data.get('templates') or [])}")
        else:
            board = data.get("board") or {}
            skill = data.get("skill")
            print(f"{board.get('displayName')} ({board.get('componentId')})")
            if skill:
                summary = skill.get("summary") or {}
                print(f"Board Skill: {summary.get('id')}  layout={skill.get('layout')} verified={skill.get('verified')}")
                print(f"profile={summary.get('profileId')}  files={len(skill.get('files') or [])}")
            else:
                print("Board Skill: 无")
            entry = data.get("entry")
            if entry:
                print(f"entry: {entry.get('path')}  {entry.get('bytes')} bytes")
            file_item = data.get("file")
            if file_item:
                print(f"file: {file_item.get('path')}  {file_item.get('bytes')} bytes")
            programming = data.get("programmingContext")
            print(f"programmingContext: {'yes' if programming else 'no'}")
    elif command == "hardware search":
        for item in data.get("results", []):
            marks = []
            if item.get("recommended"):
                marks.append("推荐")
            if item.get("boardSpecific"):
                marks.append("板级")
            suffix = f" [{'/'.join(marks)}]" if marks else ""
            print(f"{item['componentId']:<36} {item['displayName']}{suffix}")
            print(f"   {item['skillName']}  {item['category']}  {item['verificationStatus']}")
    elif command == "hardware get":
        print(f"{data.get('displayName')} ({data.get('componentId')})")
        print(f"skill: {data.get('skillName')}  category: {data.get('category')}  status: {data.get('status')}")
        print(f"verification: {data.get('verificationStatus')}")
        electrical = data.get("electrical") or {}
        peak = electrical.get("peakCurrent")
        print(f"voltage: {electrical.get('voltage')} V  logic: {electrical.get('logicLevel')} V  protocol: {electrical.get('communicationProtocol')}  peak: {'unknown' if peak == 0 else peak}")
        print("guides: " + ", ".join(item.get("boardId", "") for item in data.get("guides") or []))
        print(f"files: {len(data.get('files') or [])}（--full 查看正文）")
    elif command == "hardware guide":
        print(f"{data.get('displayName')} → {data['board']['displayName']}: {data['guide'].get('title')}")
        print(f"设置: {data.get('setupText')}")
        print("接线:")
        for item in data.get("wiring", []):
            print(f"  {item.get('signal')} → {item.get('targetLabel') or item.get('target')}")
        print("代码:")
        print(data.get("code", ""))
    elif command == "hardware validate":
        print(f"{data.get('overall')}: {data.get('message')}")
        for item in data.get("checks", []):
            print(f"  [{item['severity']}] {item['dimension']}: {item['message']}")
    elif command == "firmware list":
        print(f"固件 {data.get('count', 0)} 条")
        for item in data.get("firmware", []):
            image = item.get("image") or {}
            state = "已安装" if item.get("installed") else ("镜像不可用" if item.get("unavailable") else "未下载")
            print(
                f"{item.get('boardId'):<36} {item.get('chip') or '-':<8} "
                f"offset={item.get('offset')} {state}  {image.get('version') or ''}".rstrip()
            )
    elif command == "firmware get":
        board = data.get("board") or {}
        profile = data.get("profile") or {}
        print(f"{board.get('displayName')} ({board.get('componentId')})")
        print(f"chip: {profile.get('chip') or '-'}  offset: {profile.get('offset')}")
        print(f"documentation: {profile.get('documentation') or '-'}")
        image = profile.get("image")
        if image:
            print(f"image: {image.get('name')}  {image.get('version')}  {image.get('size')} bytes")
            print(f"sha256: {image.get('sha256')}")
            print(f"installed: {(board.get('firmware') or {}).get('installed')}  path: {(board.get('firmware') or {}).get('localPath')}")
        else:
            print(f"unavailable: {profile.get('unavailable') or profile.get('error') or '-'}")
    elif command == "firmware verify":
        mark = "MATCH" if data.get("matched") else "MISMATCH"
        print(f"{mark}  {data.get('boardId')}  {data.get('file')}  {data.get('size')} bytes")
        print(f"sha256: {data.get('sha256')}")
    elif command == "code check":
        print(f"{'PASS' if data.get('valid') else 'FAIL'}  {data.get('source')}  sha256={data.get('checksum', '')[:12]}")
        for item in data.get("diagnostics", []):
            line = f" line {item['line']}" if item.get("line") else ""
            print(f"  [{item['severity']}] {item['code']}{line}: {item['message']}")
        for item in data.get("hardwareChecks", []):
            print(f"  [{item['severity']}] {item['dimension']}: {item['message']}")
    elif command == "code fix":
        print(f"{'CHANGED' if data.get('changed') else 'NO CHANGE'}  {data.get('source')}  sha256={data.get('afterSha256', '')[:12]}")
        for item in data.get("applied", []):
            print(f"  applied: {item.get('repair')}")
        for item in data.get("skipped", []):
            print(f"  skipped: {item.get('repair')} — {item.get('reason')}")
        for item in data.get("remaining", []):
            line = f" line {item['line']}" if item.get("line") else ""
            print(f"  remaining [{item.get('severity')}] {item.get('repair') or 'programming'}{line}: {item.get('message')}")
        if data.get("out"):
            print(f"输出: {data.get('out')}")
    elif command == "laser templates":
        print(f"激光模板 {data.get('count', 0)} 个")
        for item in data.get("templates", []):
            params = ", ".join(
                f"{param.get('name')}={param.get('default')}" for param in item.get("parameters") or []
            )
            print(f"  {item.get('id'):<14} {item.get('title')}  [{params}]")
    elif command == "laser text":
        canvas = data.get("canvas") or {}
        print(f"{data.get('title')}  textWidth={data.get('textWidth')}mm")
        print(f"画布: {canvas.get('width')} × {canvas.get('height')} mm")
        for key, path in (data.get("exports") or {}).items():
            print(f"  {key}: {path}")
    elif command == "structure template" and "parameters" in data:
        template = data.get("template", {})
        print(f"{template.get('title')} ({template.get('id')})")
        print("可改参数:")
        for item in data.get("parameters", []):
            print(f"  {item['name']} = {item['default']}")
        print("部件:")
        for item in data.get("parts", []):
            print(f"  {item['id']}  {item['label']}  printable={item['printable']}")
    elif command in {"enclosure plan", "enclosure build"}:
        _human_enclosure(command, data, payload)
    else:
        title = data.get("title") or data.get("template", {}).get("title") or command
        print(str(title))
        for path in payload.get("writes") or []:
            print(f"  {path}")
    for warning in warnings:
        print(f"警告: {warning}", file=sys.stderr)


def _human_enclosure(command: str, data: dict, payload: dict) -> None:
    print(f"{data.get('template')}  {data.get('design_id')}")
    spec = data.get("spec") or {}
    enclosure = spec.get("enclosure") or {}
    if enclosure:
        print(
            "内腔: "
            f"{enclosure.get('inner_length_x')} × {enclosure.get('inner_width_y')} × "
            f"{enclosure.get('inner_height_z')} mm"
        )
    component_mount = spec.get("component_mount") or {}
    if component_mount:
        print(
            "底座: "
            f"base_thickness={component_mount.get('base_thickness')} "
            f"edge_margin={component_mount.get('edge_margin')}"
        )
    auto = data.get("autoSize")
    if auto:
        final = auto.get("final") or {}
        print(
            "自动尺寸: "
            f"enabled={auto.get('enabled')} applied={auto.get('applied')} "
            f"iterations={auto.get('iterations')} "
            f"final={final.get('length')}×{final.get('width')}×{final.get('height')}"
        )
    for item in data.get("provenance") or []:
        print(
            f"  {item.get('instance_id')} → {item.get('profile_id')} "
            f"[{item.get('source')}] {item.get('surface')}"
        )
    validation = data.get("validation") or {}
    failing = [
        item.get("check_id")
        for item in validation.get("checks", [])
        if str(item.get("status")) == "fail"
    ]
    print(f"校验: {'PASS' if validation.get('ok') else 'FAIL'}" + (f" ({', '.join(failing)})" if failing else ""))
    if command == "enclosure build":
        print(f"输出: {data.get('out')}")
        for name in data.get("files") or []:
            print(f"  {name}")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    command = args.command
    as_json = getattr(args, "json", False)
    source = env.source_info()
    try:
        result = args.func(args)
    except ZwError as error:
        payload = failure(command, error, source=source)
        if as_json:
            print_json(payload)
        else:
            _human(command, payload)
        return error.exit_code
    except Exception as error:  # bounded CLI: never leak a traceback into JSON
        if os.environ.get("ZW_DEBUG"):
            traceback.print_exc()
        wrapped = ZwError("INTERNAL", f"{type(error).__name__}: {error}", "设置 ZW_DEBUG=1 查看堆栈。", 7)
        payload = failure(command, wrapped, source=source)
        if as_json:
            print_json(payload)
        else:
            _human(command, payload)
        return wrapped.exit_code

    payload = ok(
        command,
        result.data,
        writes=result.writes,
        warnings=result.warnings,
        source=source,
    )
    if as_json:
        print_json(payload)
    else:
        _human(command, payload)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
