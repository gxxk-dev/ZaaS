"""zw command-line entry point."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

from . import code, doctor, env, hardware
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

    boards = groups.add_parser("boards", parents=[common], help="列出 5 块主控")
    boards.set_defaults(func=lambda a: hardware.cmd_boards(), command="boards")

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
    guide.add_argument("--set", dest="setup", action="append", default=[], metavar="KEY=VALUE")
    guide.set_defaults(
        func=lambda a: hardware.cmd_guide(a.identifier, board=a.board, setup_pairs=a.setup),
        command="hardware guide",
    )

    validate = hard_sub.add_parser("validate", parents=[common], help="电气规则校验")
    validate.add_argument("board")
    validate.add_argument("components", nargs="*")
    validate.set_defaults(func=lambda a: hardware.cmd_validate(a.board, a.components), command="hardware validate")

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

    laser = groups.add_parser("laser", help="激光切割图纸")
    laser_sub = laser.add_subparsers(dest="laser_command", required=True)
    build = laser_sub.add_parser("build", parents=[common], help="生成 SVG/DXF")
    build.add_argument("--template", required=True)
    build.add_argument("--params", default="{}", help="JSON，或 @file")
    build.add_argument("--out", required=True)
    build.add_argument("--force", action="store_true")
    build.add_argument("--allow-in-repo", action="store_true")
    build.set_defaults(func=_laser_build, command="laser build")

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
        print(f"数据目录: {data.get('dataDir')}")
        print(f"Python: {data.get('python')} ({data.get('pythonSource')})")
        print(f"目录缓存: {data.get('cache', {}).get('count')} / 磁盘 {data.get('cache', {}).get('scanCount')} 包")
        print("依赖: " + ", ".join(f"{name}={item.get('version') or 'missing'}" for name, item in (data.get("deps") or {}).items()))
        print(f"主控: {len(data.get('boards') or [])}  激光模板: {len(data.get('templates', {}).get('laser') or [])}  3D 模板: {len(data.get('templates', {}).get('cad') or [])}")
    elif command == "boards":
        for item in data.get("boards", []):
            marks = []
            marks.append("board" if item.get("hasBoardSkill") else "no-board")
            marks.append("prog" if item.get("programmingSkill") else "no-prog")
            marks.append("fw" if item.get("firmwareInstalled") else "no-fw")
            print(f"{item['componentId']:<36} {item['displayName']:<28} {item.get('skillName') or '-':<34} {'/'.join(marks)}")
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
    elif command == "code check":
        print(f"{'PASS' if data.get('valid') else 'FAIL'}  {data.get('source')}  sha256={data.get('checksum', '')[:12]}")
        for item in data.get("diagnostics", []):
            line = f" line {item['line']}" if item.get("line") else ""
            print(f"  [{item['severity']}] {item['code']}{line}: {item['message']}")
        for item in data.get("hardwareChecks", []):
            print(f"  [{item['severity']}] {item['dimension']}: {item['message']}")
    elif command == "structure template" and "parameters" in data:
        template = data.get("template", {})
        print(f"{template.get('title')} ({template.get('id')})")
        print("可改参数:")
        for item in data.get("parameters", []):
            print(f"  {item['name']} = {item['default']}")
        print("部件:")
        for item in data.get("parts", []):
            print(f"  {item['id']}  {item['label']}  printable={item['printable']}")
    else:
        title = data.get("title") or data.get("template", {}).get("title") or command
        print(str(title))
        for path in payload.get("writes") or []:
            print(f"  {path}")
    for warning in warnings:
        print(f"警告: {warning}", file=sys.stderr)


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
