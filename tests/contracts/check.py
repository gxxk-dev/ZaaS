#!/usr/bin/env python3
"""Contract checks for the zhangwen skill. Read-only except for a temp dir."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ZW = ROOT / "scripts" / "zw"
EXPECTED = json.loads((Path(__file__).resolve().parent / "expected.json").read_text(encoding="utf-8"))


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def run(*args: str) -> tuple[int, dict]:
    proc = subprocess.run(
        [str(ZW), *args, "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        fail(f"非 JSON 输出：zw {' '.join(args)}\nstdout={proc.stdout[:500]}\nstderr={proc.stderr[:500]}")
    return proc.returncode, payload


def expect_ok(name: str, payload: dict) -> dict:
    if not payload.get("ok") or payload.get("schema") != EXPECTED["schema"]:
        fail(f"{name} 信封无效：{payload}")
    return payload.get("data") or {}


def _write_request(directory: Path, name: str, payload: dict) -> Path:
    path = directory / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _error_code(payload: dict) -> str:
    return (payload.get("error") or {}).get("code")


def _check_firmware() -> None:
    case = EXPECTED["firmware"]
    code, payload = run("firmware", "list")
    data = expect_ok("firmware list", payload)
    if code != 0 or data.get("count") != EXPECTED["boards"]:
        fail(f"firmware list count={data.get('count')} exit={code}")
    rows = {item.get("boardId"): item for item in data.get("firmware") or []}
    if case["boardId"] not in rows:
        fail(f"firmware list 缺少 {case['boardId']}")
    if rows[case["boardId"]].get("chip") is None:
        fail("firmware list 缺少 chip")
    print("ok firmware list")

    code, payload = run("firmware", "get", case["board"])
    data = expect_ok("firmware get", payload)
    if code != 0 or (data.get("profile") or {}).get("boardId") != case["boardId"]:
        fail(f"firmware get 不符：exit={code} profile={data.get('profile')}")
    local_path = (rows[case["boardId"]].get("localPath"))
    if local_path:
        code, payload = run("firmware", "verify", case["board"], "--file", local_path)
        data = expect_ok("firmware verify", payload)
        if code != 0 or not data.get("matched") or payload.get("writes"):
            fail(f"firmware verify 正例不符：exit={code} writes={payload.get('writes')}")
        print("ok firmware verify")
    else:
        print("skip firmware verify (local image missing)")

    with tempfile.TemporaryDirectory(prefix="zw-firmware-") as tmp:
        bad = Path(tmp) / "bad.bin"
        bad.write_bytes(b"not-the-pinned-image")
        code, payload = run("firmware", "verify", case["board"], "--file", str(bad))
        if code != 4 or _error_code(payload) != "FIRMWARE_MISMATCH":
            fail(f"firmware mismatch 负例不符：exit={code} code={_error_code(payload)}")
        if payload.get("writes"):
            fail("firmware verify 负例写盘")
        link = Path(tmp) / "link.bin"
        try:
            link.symlink_to(local_path or bad)
        except OSError:
            link = None
        if link is not None:
            code, payload = run("firmware", "verify", case["board"], "--file", str(link))
            if code != 4 or _error_code(payload) != "FILE_INVALID":
                fail(f"firmware symlink 负例不符：exit={code} code={_error_code(payload)}")
        print("ok firmware negatives")


def _check_board_skills() -> None:
    case = EXPECTED["boardSkills"]
    code, payload = run("boards", "--board", case["strictBoard"], "--full")
    data = expect_ok("boards full strict", payload)
    skill = data.get("skill") or {}
    if code != 0 or skill.get("layout") != "strict" or skill.get("verified") is not True:
        fail(f"boards --full strict 不符：exit={code} skill={skill.get('layout')}/{skill.get('verified')}")
    if not data.get("entry") or not data["entry"].get("content"):
        fail("boards --full 缺少 entry")
    if not data.get("programmingContext"):
        fail("boards --full 缺少 programmingContext")
    print("ok boards full strict")

    code, payload = run(
        "boards", "--board", case["strictBoard"], "--full", "--file", case["file"],
    )
    data = expect_ok("boards full file", payload)
    file_item = data.get("file") or {}
    if code != 0 or file_item.get("path") != case["file"] or not file_item.get("content"):
        fail(f"boards --full --file 不符：exit={code} file={file_item.get('path')}")
    print("ok boards full file")

    code, payload = run("boards", "--board", case["legacyBoard"], "--full")
    data = expect_ok("boards full legacy", payload)
    skill = data.get("skill") or {}
    if code != 0 or skill.get("layout") != "legacy" or skill.get("verified") is not False:
        fail(f"boards legacy 不符：exit={code} skill={skill.get('layout')}/{skill.get('verified')}")
    if not any("legacy" in item for item in payload.get("warnings") or []):
        fail("boards legacy 缺少 warning")
    print("ok boards full legacy")

    code, payload = run("boards", "--board", "mpython3", "--full")
    data = expect_ok("boards full no skill", payload)
    if code != 0 or data.get("skill") is not None or not data.get("programmingContext"):
        fail(f"boards 无 Board Skill 降级不符：exit={code}")
    print("ok boards full without skill")

    code, payload = run("boards", "--board", case["strictBoard"], "--context", case["contextQuery"])
    data = expect_ok("boards context", payload)
    package = data.get("package") or {}
    if code != 0 or package.get("profileId") != case["contextProfile"]:
        fail(f"boards --context 不符：exit={code} package={package}")
    if not data.get("references") or not data.get("templates"):
        fail("boards --context 缺少参考/模板")
    print("ok boards context")

    code, payload = run("boards", "--board", case["legacyBoard"], "--context", "GPIO")
    if code != 4 or _error_code(payload) != "BOARD_SKILL_CONTEXT_UNAVAILABLE":
        fail(f"boards legacy context 负例不符：exit={code} code={_error_code(payload)}")
    code, payload = run("boards", "--full")
    if code != 2 or _error_code(payload) != "REQUEST_INVALID":
        fail(f"boards --full 无 board 负例不符：exit={code} code={_error_code(payload)}")
    code, payload = run("boards", "--board", "mpython3", "--full", "--file", "SKILL.md")
    if code != 3 or _error_code(payload) != "FILE_NOT_FOUND":
        fail(f"boards --file 无 skill 负例不符：exit={code} code={_error_code(payload)}")
    print("ok boards negatives")

    code, payload = run(
        "hardware", "guide", case["guideId"], "--board", case["strictBoard"],
        "--kind", case["guideKind"],
    )
    data = expect_ok("guide kind", payload)
    if code != 0 or (data.get("guide") or {}).get("kind") != case["guideKind"]:
        fail(f"hardware guide --kind 正例不符：exit={code}")
    code, payload = run(
        "hardware", "guide", case["guideId"], "--board", case["strictBoard"], "--kind", "functional",
    )
    if code != 4 or _error_code(payload) != "GUIDE_KIND_MISMATCH":
        fail(f"hardware guide --kind 负例不符：exit={code} code={_error_code(payload)}")
    print("ok guide kind")


def _launcher_requirements(*args: str) -> str:
    proc = subprocess.run(
        [str(ZW), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "ZW_LAUNCH_DEBUG_REQUIREMENTS": "1"},
    )
    if proc.returncode != 0:
        fail(f"launcher debug 失败：zw {' '.join(args)} exit={proc.returncode} stderr={proc.stderr[:300]}")
    return proc.stdout.strip()


def _check_structure_catalog() -> None:
    case = EXPECTED["structureTemplates"]
    code, payload = run("structure", "templates")
    data = expect_ok("structure templates", payload)
    templates = {item.get("id"): item for item in data.get("templates") or []}
    if code != 0 or data.get("count") != len(case["packaged"]) + len(case["designSpec"]):
        fail(f"structure templates count={data.get('count')} exit={code}")
    for identifier in case["packaged"]:
        if templates.get(identifier, {}).get("source") != "packaged":
            fail(f"structure templates 缺少打包模板 {identifier}")
    for identifier in case["designSpec"]:
        if templates.get(identifier, {}).get("source") != "design-spec":
            fail(f"structure templates 缺少 design-spec 模板 {identifier}")
    defaults = {
        item.get("name"): item.get("default")
        for item in templates.get("box", {}).get("parameters") or []
    }
    if defaults != case["boxDefaults"]:
        fail(f"structure templates box 参数默认值不符：{defaults}")
    if not payload.get("readOnly") or payload.get("writes"):
        fail("structure templates 不是只读")
    print("ok structure templates")

    code, payload = run("enclosure", "profiles")
    data = expect_ok("enclosure profiles", payload)
    profiles = data.get("profiles") or []
    by_id = {item.get("profileId"): item for item in profiles}
    expected = EXPECTED["enclosureProfiles"]
    if code != 0 or expected["trusted"] not in by_id:
        fail(f"enclosure profiles 缺少 trusted profile：exit={code}")
    package = by_id.get(expected["packageProfile"])
    if not package or package.get("source") != "package-mechanical":
        fail(f"enclosure profiles 缺少资料包 profile：{expected['packageProfile']}")
    if package.get("componentId") != expected["packageComponent"]:
        fail(f"enclosure profiles componentId 不符：{package}")
    if not payload.get("readOnly") or payload.get("writes"):
        fail("enclosure profiles 不是只读")
    print("ok enclosure profiles")

    routes = {
        ("structure", "templates"): "core",
        ("structure", "library"): "core",
        ("enclosure", "profiles"): "core",
        ("enclosure", "plan"): "core",
        ("structure", "template"): "cad",
        ("structure", "solid"): "cad",
        ("structure", "freeform", "plan"): "core",
        ("structure", "freeform", "build"): "cad",
        ("enclosure", "build"): "cad",
    }
    for args, expected_route in routes.items():
        actual = _launcher_requirements(*args)
        if actual != expected_route:
            fail(f"launcher 分流 {args} = {actual!r}，期望 {expected_route!r}")
    print("ok launcher requirements")


def _check_library() -> None:
    case = EXPECTED["legacyLibrary"]
    code, payload = run("structure", "library")
    data = expect_ok("structure library", payload)
    profiles = data.get("profiles") or []
    if code != 0 or not profiles or data.get("count") != len(profiles):
        fail(f"structure library 列表不符：exit={code} count={data.get('count')}")
    if data.get("source") != "legacy-hardware-library":
        fail("structure library 缺少 source")
    required = {
        "id", "name", "category", "roles", "dimensions_mm",
        "thumbnail_url", "source_status", "integration_status",
    }
    if not required <= set(profiles[0]):
        fail(f"structure library 列表字段不完整：{sorted(set(profiles[0]))}")
    if not any("enclosure profiles" in warning for warning in payload.get("warnings") or []):
        fail("structure library 缺少 legacy/enclosure warning")
    if not payload.get("readOnly") or payload.get("writes"):
        fail("structure library 不是只读")
    print("ok structure library")

    code, payload = run("structure", "library", "--category", case["category"])
    data = expect_ok("structure library category", payload)
    rows = data.get("profiles") or []
    if code != 0 or not rows or any(item.get("category") != case["category"] for item in rows):
        fail(f"structure library --category 不符：exit={code} rows={len(rows)}")
    print("ok structure library category")

    code, payload = run("structure", "library", "--query", case["query"])
    data = expect_ok("structure library query", payload)
    rows = data.get("profiles") or []
    needle = case["query"].lower()
    if code != 0 or not rows or any(
        needle not in item["id"].lower() and needle not in item["name"].lower()
        for item in rows
    ):
        fail(f"structure library --query 不符：exit={code} rows={len(rows)}")
    print("ok structure library query")

    code, payload = run("structure", "library", case["profile"])
    data = expect_ok("structure library profile", payload)
    profile = data.get("profile") or {}
    if code != 0 or profile.get("id") != case["profile"]:
        fail(f"structure library profile 不符：exit={code} id={profile.get('id')}")
    if (data.get("library") or {}).get("units") != "mm":
        fail("structure library 单条缺少 library.units")
    if not isinstance(profile.get("dimensions_mm"), dict):
        fail("structure library 单条缺少 dimensions_mm")
    print("ok structure library profile")

    code, payload = run("structure", "library", case["profile"], "--category", "sensor")
    if code != 2 or _error_code(payload) != "REQUEST_INVALID":
        fail(f"structure library 互斥负例不符：exit={code} code={_error_code(payload)}")
    code, payload = run("structure", "library", case["missing"])
    if code != 3 or _error_code(payload) != "PROFILE_NOT_FOUND":
        fail(f"structure library 缺 profile 负例不符：exit={code} code={_error_code(payload)}")
    code, payload = run("structure", "library", "--category", "no_such_category")
    data = expect_ok("structure library empty", payload)
    if code != 0 or data.get("count") != 0 or not payload.get("warnings"):
        fail(f"structure library 空过滤不符：exit={code} count={data.get('count')}")
    print("ok structure library negatives")


def _canonical_sha256(value: dict) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _check_freeform() -> None:
    case = EXPECTED["freeform"]
    with tempfile.TemporaryDirectory(prefix="zw-freeform-") as tmp:
        root = Path(tmp)
        request = _write_request(root, "request.json", case["request"])

        code, payload = run("structure", "freeform", "plan", "--request", str(request))
        data = expect_ok("freeform plan", payload)
        if code != 0 or not payload.get("readOnly") or payload.get("writes"):
            fail(f"freeform plan 不是只读：exit={code} writes={payload.get('writes')}")
        if data.get("design_id") != case["request"]["design_id"]:
            fail(f"freeform plan design_id={data.get('design_id')}")
        if data.get("template") != "freeform_structure" or data.get("template_revision") != "freeform-structure.v1":
            fail(f"freeform plan 模板不符：{data.get('template')}/{data.get('template_revision')}")
        primitives = (data.get("spec") or {}).get("freeform_geometry", {}).get("primitives") or []
        if len(primitives) != len(case["request"]["operations"]):
            fail(f"freeform plan primitives={len(primitives)}")
        if not (data.get("validation") or {}).get("ok"):
            fail("freeform plan validation 未通过")

        code, again = run("structure", "freeform", "plan", "--request", str(request))
        again_data = expect_ok("freeform plan repeat", again)
        if json.dumps(data.get("spec"), sort_keys=True) != json.dumps(again_data.get("spec"), sort_keys=True):
            fail("freeform plan 两次 spec 不一致")
        print("ok freeform plan")

        for name, body in case["negatives"].items():
            path = _write_request(root, f"{name}.json", body)
            code, payload = run("structure", "freeform", "plan", "--request", str(path))
            if code != 2 or _error_code(payload) != "REQUEST_INVALID":
                fail(f"freeform {name} 负例不符：exit={code} code={_error_code(payload)}")
        print("ok freeform negatives")

        text_request = _write_request(root, "text.json", case["textRequest"])
        code, payload = run("structure", "freeform", "plan", "--request", str(text_request))
        data = expect_ok("freeform text plan", payload)
        operations = data.get("textOperations") or []
        if code != 0 or len(operations) != 1:
            fail(f"freeform text plan textOperations={operations}")
        operation = operations[0]
        if operation.get("text") != "掌问" or operation.get("operation") != "cut" or operation.get("fontSize") != 6:
            fail(f"freeform text plan 操作不符：{operation}")
        primitives = (data.get("spec") or {}).get("freeform_geometry", {}).get("primitives") or []
        if len(primitives) != 1:
            fail(f"freeform text plan 不应把 text 计入几何 primitives：{len(primitives)}")

        glyph = _write_request(root, "bad-glyph.json", case["badGlyphRequest"])
        code, payload = run("structure", "freeform", "plan", "--request", str(glyph))
        if code != 4 or _error_code(payload) != "TEXT_INVALID":
            fail(f"freeform 缺字负例不符：exit={code} code={_error_code(payload)}")
        print("ok freeform text plan")

        nonempty = root / "nonempty"
        nonempty.mkdir()
        (nonempty / "keep.txt").write_text("keep", encoding="utf-8")
        code, payload = run(
            "structure", "freeform", "build", "--request", str(request), "--out", str(nonempty),
        )
        if code != 6 or _error_code(payload) != "OUT_NOT_EMPTY":
            fail(f"freeform OUT_NOT_EMPTY 负例不符：exit={code} code={_error_code(payload)}")
        if not (nonempty / "keep.txt").is_file():
            fail("freeform 非空目录负例改动了原文件")

        code, payload = run("structure", "freeform", "build", "--out", str(root / "no-mode"))
        if code != 2 or _error_code(payload) != "REQUEST_INVALID":
            fail(f"freeform 缺少输入负例不符：exit={code} code={_error_code(payload)}")
        print("ok freeform out boundary")

        if os.environ.get("ZW_CONTRACT_CAD") == "1":
            out = root / "cad-out"
            code, payload = run(
                "structure", "freeform", "build", "--request", str(request), "--out", str(out),
            )
            data = expect_ok("freeform build", payload)
            if code != 0:
                fail(f"freeform build exit={code}")
            missing = [name for name in case["cadBuildFiles"] if not (out / name).is_file()]
            if missing:
                fail(f"freeform build 缺少文件：{missing}")
            reported = data.get("files") or []
            for name in ("manifest.json", "spec.json", "request.json"):
                if name not in reported:
                    fail(f"freeform build files 未报告 {name}")
            if len(payload.get("writes") or []) != len(reported):
                fail("freeform build writes 与 files 数量不一致")
            if data.get("design_id") != case["request"]["design_id"] or data.get("template") != "freeform_structure":
                fail(f"freeform build 标识不符：{data.get('design_id')}/{data.get('template')}")
            spec_doc = json.loads((out / "spec.json").read_text(encoding="utf-8"))
            if spec_doc.get("schema") != "zw.freeform-spec/v1" or spec_doc.get("textOperations") != []:
                fail(f"freeform spec.json 包装不符：{spec_doc.get('schema')}")
            spec = spec_doc.get("spec") or {}
            if spec.get("template") != "freeform_structure" or spec.get("template_revision") != "freeform-structure.v1":
                fail(f"freeform spec.json 模板不符：{spec.get('template')}/{spec.get('template_revision')}")
            digest = _canonical_sha256(spec_doc)
            if data.get("specSha256") != digest:
                fail(f"freeform specSha256 不符：{data.get('specSha256')} != {digest}")
            if (data.get("manifest") or {}).get("spec_sha256") != digest:
                fail("freeform manifest.spec_sha256 与 spec.json 不一致")
            request_doc = json.loads((out / "request.json").read_text(encoding="utf-8"))
            if request_doc.get("design_id") != case["request"]["design_id"]:
                fail("freeform request.json design_id 不符")

            second = root / "cad-rebuild"
            code, payload = run(
                "structure", "freeform", "build", "--spec", str(out / "spec.json"), "--out", str(second),
            )
            rebuild = expect_ok("freeform rebuild", payload)
            if code != 0 or rebuild.get("specSha256") != digest:
                fail(f"freeform rebuild sha 不一致：{digest} != {rebuild.get('specSha256')}")
            if (second / "request.json").exists():
                fail("freeform --spec 不应写 request.json")
            if not (rebuild.get("validation") or {}).get("ok"):
                fail("freeform rebuild validation 未通过")

            text_out = root / "text-out"
            code, payload = run(
                "structure", "freeform", "build", "--request", str(text_request), "--out", str(text_out),
            )
            data = expect_ok("freeform text build", payload)
            if code != 0:
                fail(f"freeform text build exit={code}")
            missing = [name for name in case["cadBuildFiles"] if not (text_out / name).is_file()]
            if missing:
                fail(f"freeform text build 缺少文件：{missing}")
            if not (data.get("validation") or {}).get("ok"):
                fail("freeform text build validation 未通过")
            parts = (data.get("geometrySummary") or {}).get("parts") or []
            if len(parts) != 1 or parts[0].get("solid_count") != 1:
                fail(f"freeform text build parts={parts}")
            volume = float(parts[0].get("volume_mm3") or 0)
            if not 0 < case["textBaseVolume"] - volume < 100:
                fail(f"freeform text cut 体积不符：{volume}")
            text_spec = json.loads((text_out / "spec.json").read_text(encoding="utf-8"))
            if len(text_spec.get("textOperations") or []) != 1:
                fail(f"freeform text spec.json 缺少 textOperations：{text_spec}")
            text_digest = _canonical_sha256(text_spec)
            if data.get("specSha256") != text_digest:
                fail(f"freeform text specSha256 不符：{data.get('specSha256')} != {text_digest}")
            text_request_doc = json.loads((text_out / "request.json").read_text(encoding="utf-8"))
            text_rows = [
                item for item in text_request_doc.get("operations") or []
                if item.get("shape") == "text"
            ]
            if len(text_rows) != 1 or text_rows[0].get("text") != "掌问":
                fail(f"freeform text request.json 不符：{text_rows}")

            text_rebuild = root / "text-rebuild"
            code, payload = run(
                "structure", "freeform", "build",
                "--spec", str(text_out / "spec.json"), "--out", str(text_rebuild),
            )
            rebuild = expect_ok("freeform text rebuild", payload)
            if code != 0 or rebuild.get("specSha256") != text_digest:
                fail(f"freeform text rebuild sha 不一致：{text_digest} != {rebuild.get('specSha256')}")
            rebuilt_parts = (rebuild.get("geometrySummary") or {}).get("parts") or []
            rebuilt_volume = float(rebuilt_parts[0].get("volume_mm3") or 0)
            if abs(rebuilt_volume - volume) > 1e-6:
                fail(f"freeform text rebuild 体积不一致：{volume} != {rebuilt_volume}")

            off_body = _write_request(root, "text-off.json", case["textNoEffectRequest"])
            code, payload = run(
                "structure", "freeform", "build",
                "--request", str(off_body), "--out", str(root / "text-off-out"),
            )
            if code != 4 or _error_code(payload) != "TEXT_NO_EFFECT":
                fail(f"freeform TEXT_NO_EFFECT 负例不符：exit={code} code={_error_code(payload)}")
            print("ok freeform text cad build")
        else:
            print("skip freeform cad build (ZW_CONTRACT_CAD != 1)")


def _check_enclosure(case: dict) -> None:
    with tempfile.TemporaryDirectory(prefix="zw-enclosure-") as tmp:
        root = Path(tmp)
        box_request = _write_request(root, "box.json", case["boxRequest"])

        code, payload = run("enclosure", "plan", "--request", str(box_request))
        data = expect_ok("enclosure plan", payload)
        if code != 0:
            fail(f"enclosure plan exit={code}")
        if not payload.get("readOnly") or payload.get("writes"):
            fail(f"enclosure plan 不是只读：{payload.get('writes')}")
        if data.get("template") != "box_with_lid":
            fail(f"enclosure plan template={data.get('template')}")
        if not data.get("validation", {}).get("ok"):
            fail("enclosure plan validation 未通过")
        spec = data.get("spec") or {}
        if len(spec.get("hardware") or []) != 2:
            fail("enclosure plan hardware 数量不符")
        enclosure = spec.get("enclosure") or {}
        for key, minimum in (
            ("inner_length_x", 30),
            ("inner_width_y", 30),
            ("inner_height_z", 12),
        ):
            if float(enclosure.get(key, 0)) < minimum:
                fail(f"enclosure plan {key}={enclosure.get(key)}")

        code, again = run("enclosure", "plan", "--request", str(box_request))
        again_data = expect_ok("enclosure plan repeat", again)
        if json.dumps(data.get("spec"), sort_keys=True) != json.dumps(again_data.get("spec"), sort_keys=True):
            fail("enclosure plan 两次 spec 不一致")
        print("ok enclosure plan")

        needs = _write_request(
            root,
            "needs.json",
            {"components": [{"component_id": case["needsInputComponent"]}]},
        )
        code, payload = run("enclosure", "plan", "--request", str(needs))
        if code != 4 or _error_code(payload) != "NEEDS_INPUT":
            fail(f"enclosure NEEDS_INPUT 负例不符：exit={code} code={_error_code(payload)}")
        questions = (payload.get("error", {}).get("details") or {}).get("questions") or []
        if not questions:
            fail("enclosure NEEDS_INPUT 没有 questions")
        print("ok enclosure needs input")

        conflict = _write_request(root, "k10-conflict.json", case["k10ConflictRequest"])
        code, payload = run("enclosure", "plan", "--request", str(conflict))
        if code != 4 or _error_code(payload) != "MOUNT_CONFLICT":
            fail(f"enclosure MOUNT_CONFLICT 负例不符：exit={code} code={_error_code(payload)}")
        print("ok enclosure mount conflict")

        derived = _write_request(root, "k10-derived.json", case["k10DerivedRequest"])
        code, payload = run("enclosure", "plan", "--request", str(derived))
        data = expect_ok("enclosure derive", payload)
        if code != 0:
            fail(f"enclosure derive exit={code}")
        provenance = data.get("provenance") or []
        if not provenance or provenance[0].get("source") != "derived":
            fail(f"enclosure derive provenance={provenance}")
        profile_ids = [item.get("profile_id") for item in (data.get("spec") or {}).get("profiles", [])]
        if not any(str(name).startswith("unihiker_k10_derived_") for name in profile_ids):
            fail(f"enclosure derive profile_ids={profile_ids}")
        if not any("派生" in item for item in payload.get("warnings") or []):
            fail("enclosure derive 缺少派生 warning")
        print("ok enclosure derive mount")

        mount = _write_request(root, "mount.json", case["componentMountRequest"])
        code, payload = run("enclosure", "plan", "--request", str(mount))
        data = expect_ok("enclosure component_mount", payload)
        if code != 0 or data.get("template") != "component_mount":
            fail(f"enclosure component_mount 模板不符：exit={code}")
        hardware = (data.get("layout") or {}).get("hardware") or []
        if len(hardware) != 1 or hardware[0].get("surface") != "external":
            fail(f"enclosure component_mount hardware={hardware}")
        center_z = float((hardware[0].get("center") or {}).get("z", 0))
        if abs(center_z - case["componentMountCenterZ"]) > 1e-6:
            fail(f"enclosure component_mount center.z={center_z}")
        if not data.get("validation", {}).get("ok"):
            fail("enclosure component_mount validation 未通过")
        print("ok enclosure component_mount")

        two = {"template": "component_mount", "components": [
            {"profile_id": "xiao_esp32s3"},
            {"profile_id": "grove_button"},
        ]}
        path = _write_request(root, "mount-two.json", two)
        code, payload = run("enclosure", "plan", "--request", str(path))
        if code != 2 or _error_code(payload) != "REQUEST_INVALID":
            fail(f"enclosure component_mount 双器件负例不符：exit={code} code={_error_code(payload)}")

        standoff = {"template": "component_mount", "components": [{"profile_id": "xiao_esp32s3"}], "standoffs": [
            {"standoff_id": "post", "center": {"x": 0, "y": 0},
             "outer_diameter": 5, "bore_diameter": 2, "height": 4},
        ]}
        path = _write_request(root, "mount-standoff.json", standoff)
        code, payload = run("enclosure", "plan", "--request", str(path))
        if code != 2 or _error_code(payload) != "REQUEST_INVALID":
            fail(f"enclosure component_mount standoff 负例不符：exit={code}")
        print("ok enclosure template negatives")

        left = _write_request(root, "left.json", case["leftNeedsCenterRequest"])
        code, payload = run("enclosure", "plan", "--request", str(left))
        if code != 4 or _error_code(payload) != "NEEDS_INPUT":
            fail(f"enclosure left 负例不符：exit={code} code={_error_code(payload)}")
        questions = (payload.get("error", {}).get("details") or {}).get("questions") or []
        if not any(item.get("field") == "center" for item in questions):
            fail(f"enclosure left questions={questions}")
        print("ok enclosure left center")

        bad_spec = _write_request(root, "bad-spec.json", case["invalidSpec"])
        bad_out = root / "bad-spec-out"
        code, payload = run(
            "enclosure", "build", "--spec", str(bad_spec), "--out", str(bad_out),
        )
        if code != 2 or _error_code(payload) != "SPEC_INVALID":
            fail(f"enclosure SPEC_INVALID 负例不符：exit={code} code={_error_code(payload)}")
        if bad_out.exists():
            fail("enclosure 无效 spec 创建了输出目录")
        print("ok enclosure spec negative")

        nonempty = root / "nonempty"
        nonempty.mkdir()
        (nonempty / "keep.txt").write_text("keep", encoding="utf-8")
        code, payload = run(
            "enclosure", "build", "--request", str(box_request), "--out", str(nonempty),
        )
        if code != 6 or _error_code(payload) != "OUT_NOT_EMPTY":
            fail(f"enclosure OUT_NOT_EMPTY 负例不符：exit={code} code={_error_code(payload)}")
        if not (nonempty / "keep.txt").is_file():
            fail("enclosure 非空目录负例改动了原文件")
        print("ok enclosure out boundary")

        if os.environ.get("ZW_CONTRACT_CAD") == "1":
            out = root / "cad-out"
            code, payload = run(
                "enclosure", "build", "--request", str(box_request), "--out", str(out),
            )
            data = expect_ok("enclosure build", payload)
            if code != 0:
                fail(f"enclosure build exit={code}")
            for name in case["cadBuildFiles"]:
                if not (out / name).is_file():
                    fail(f"enclosure build 缺少 {name}")
            first_sha = data.get("specSha256")
            second_out = root / "cad-out-2"
            code, payload = run(
                "enclosure", "build", "--spec", str(out / "spec.json"), "--out", str(second_out),
            )
            data = expect_ok("enclosure rebuild", payload)
            if code != 0 or data.get("specSha256") != first_sha:
                fail(f"enclosure rebuild sha 不一致：{first_sha} != {data.get('specSha256')}")
            print("ok enclosure cad build")
        else:
            print("skip enclosure cad build (ZW_CONTRACT_CAD!=1)")


def main() -> int:
    code, payload = run("status")
    data = expect_ok("status", payload)
    if code != 0:
        fail(f"status exit={code}")
    if len(data.get("boards", [])) != EXPECTED["boards"]:
        fail(f"主控数量 {len(data.get('boards', []))} != {EXPECTED['boards']}")
    for key in ("laser", "cad"):
        actual = data.get("templates", {}).get(key, [])
        ids = {item.get("id") if isinstance(item, dict) else item for item in actual}
        missing = set(EXPECTED[f"{key}Templates"]) - ids
        if missing:
            fail(f"{key} 模板缺失：{sorted(missing)}")
    version_path = Path(os.environ.get("ZW_HOME", "/mnt/dev-cold/zhangwen")) / "version.json"
    if version_path.is_file():
        expected_version = json.loads(version_path.read_text(encoding="utf-8")).get("version")
        if data.get("zhangwenVersion") != expected_version:
            fail(f"掌问版本 {data.get('zhangwenVersion')} != {expected_version}")
    print("ok status")

    code, payload = run("boards")
    data = expect_ok("boards", payload)
    if len(data.get("boards", [])) != EXPECTED["boards"]:
        fail("boards 数量不符")
    print("ok boards")

    case = EXPECTED["dfr0026"]
    code, payload = run("hardware", "search", case["query"], "--board", case["board"])
    data = expect_ok("search", payload)
    results = data.get("results", [])
    if not results:
        fail("search 无结果")
    first = results[0]
    if first.get("skillName") != case["recommended"] or not first.get("recommended"):
        fail(f"search 首项不是板级推荐：{first}")
    if first.get("verificationStatus") != case["verification"]:
        fail(f"search verificationStatus={first.get('verificationStatus')}")
    print("ok search")

    code, payload = run("hardware", "get", "hw_dfrobot_dfr0026_k10")
    data = expect_ok("get", payload)
    if data.get("verificationStatus") != case["verification"]:
        fail("get verificationStatus 不符")
    if len(data.get("guides", [])) != 5:
        fail(f"get guides={len(data.get('guides', []))}")
    print("ok get")

    code, payload = run("hardware", "guide", "hw_dfrobot_dfr0026_k10", "--board", case["board"])
    data = expect_ok("guide", payload)
    wiring = next((item for item in data.get("wiring", []) if item.get("signal") == case["wiringSignal"]), None)
    if wiring is None:
        fail(f"guide 缺少信号 {case['wiringSignal']}")
    if not str(wiring.get("targetLabel", "")).startswith(case["wiringLabelPrefix"]):
        fail(f"guide 信号标签未解析：{wiring}")
    print("ok guide")

    code, payload = run("hardware", "validate", "hw_seed_unihiker_k10", "hw_dfrobot_dfr0026_k10")
    data = expect_ok("validate", payload)
    if code != 0 or data.get("overall") == "FAIL":
        fail(f"validate overall={data.get('overall')} exit={code}")
    print("ok validate")

    _check_firmware()
    _check_board_skills()
    _check_structure_catalog()
    _check_library()
    _check_freeform()

    with tempfile.TemporaryDirectory(prefix="zw-contract-") as tmp:
        tmp_dir = Path(tmp)
        bad = Path(tmp) / "bad.py"
        bad.write_text(EXPECTED["k10BadCode"]["source"], encoding="utf-8")
        code, payload = run("code", "check", "--board", "k10", "--file", str(bad))
        if code != EXPECTED["k10BadCode"]["exit"]:
            fail(f"code check exit={code}")
        codes = {item.get("code") for item in (payload.get("data") or {}).get("diagnostics", [])}
        if EXPECTED["k10BadCode"]["diagnostic"] not in codes:
            fail(f"code check 诊断缺失：{codes}")
        print("ok code check")

        fix_source = tmp_dir / "fix.py"
        fix_source.write_text(EXPECTED["k10BadCode"]["source"], encoding="utf-8")
        code, payload = run("code", "fix", "--board", "k10", "--file", str(fix_source))
        data = expect_ok("code fix", payload)
        applied = [item.get("repair") for item in data.get("applied") or []]
        if code != 0 or not data.get("changed") or "k10-screen" not in applied:
            fail(f"code fix 结果不符：exit={code} data={data}")
        if payload.get("writes") or not payload.get("readOnly"):
            fail(f"code fix 默认不是只读：writes={payload.get('writes')}")
        if "screen.text(" in (data.get("after") or ""):
            fail("code fix 未替换 screen.text")
        if not data.get("diff"):
            fail("code fix 缺少 diff")
        print("ok code fix")

        pins_source = tmp_dir / "pins.py"
        pins_source.write_text(EXPECTED["codeFix"]["mpythonSource"], encoding="utf-8")
        code, payload = run("code", "fix", "--board", "mpython", "--file", str(pins_source))
        data = expect_ok("code fix pins", payload)
        if code != 0 or "mpython-pins" not in [item.get("repair") for item in data.get("applied") or []]:
            fail(f"code fix pins 结果不符：exit={code}")
        if "Pin(33)" not in (data.get("after") or ""):
            fail("code fix pins 未映射 GPIO33")
        print("ok code fix pins")

        refusal_source = tmp_dir / "refusal.py"
        refusal_source.write_text(EXPECTED["codeFix"]["badArgsSource"], encoding="utf-8")
        code, payload = run("code", "fix", "--board", "k10", "--file", str(refusal_source))
        data = expect_ok("code fix refusal", payload)
        if code != 0 or data.get("changed") or data.get("skipped") != [
            {"repair": "k10-screen", "reason": "此处文字参数无法可靠转换，请按官方draw_text关键字参数手动修改；原代码保留。"}
        ]:
            fail(f"code fix 拒绝路径不符：exit={code} data={data}")
        if not any(item.get("repair") == "k10-screen" for item in data.get("remaining") or []):
            fail("code fix 拒绝路径未保留 remaining")
        print("ok code fix refusal")

        out_file = tmp_dir / "fixed.py"
        code, payload = run(
            "code", "fix", "--board", "k10", "--file", str(fix_source), "--out", str(out_file),
        )
        data = expect_ok("code fix out", payload)
        if code != 0 or payload.get("readOnly") or str(out_file) not in (payload.get("writes") or []):
            fail(f"code fix --out 结果不符：exit={code} writes={payload.get('writes')}")
        if out_file.read_text(encoding="utf-8") != data.get("after"):
            fail("code fix --out 内容与 after 不一致")
        before = out_file.read_text(encoding="utf-8")
        code, payload = run(
            "code", "fix", "--board", "k10", "--file", str(fix_source), "--out", str(out_file),
        )
        if code != 6 or _error_code(payload) != "OUT_EXISTS":
            fail(f"code fix OUT_EXISTS 负例不符：exit={code} code={_error_code(payload)}")
        if out_file.read_text(encoding="utf-8") != before:
            fail("code fix OUT_EXISTS 改动了原文件")
        print("ok code fix out boundary")

        syntax_source = tmp_dir / "syntax.py"
        syntax_source.write_text(EXPECTED["codeFix"]["syntaxSource"], encoding="utf-8")
        code, payload = run("code", "fix", "--board", "k10", "--file", str(syntax_source))
        if code != 4 or _error_code(payload) != "CODE_INVALID":
            fail(f"code fix syntax 负例不符：exit={code} code={_error_code(payload)}")
        print("ok code fix syntax negative")

        laser = EXPECTED["laserPlate"]
        out = Path(tmp) / "laser"
        code, payload = run(
            "laser", "build", "--template", laser["template"],
            "--params", json.dumps(laser["params"]), "--out", str(out),
        )
        data = expect_ok("laser", payload)
        if code != 0:
            fail(f"laser exit={code}")
        drawing = data.get("drawing") or {}
        for key, value in laser["drawing"].items():
            if abs(float(drawing.get(key, -1)) - value) > 1e-6:
                fail(f"laser drawing.{key}={drawing.get(key)}")
        for name in laser["files"]:
            if not (out / name).is_file():
                fail(f"laser 缺少 {name}")
        print("ok laser")

        bad_out = Path(tmp) / "laser-bad"
        code, payload = run(
            "laser", "build", "--template", "plate",
            "--params", '{"not_a_param":1}', "--out", str(bad_out),
        )
        if code != 2 or (payload.get("error") or {}).get("code") != "PARAM_UNKNOWN":
            fail(f"laser 负例不符：exit={code} {payload}")
        if bad_out.exists():
            fail("laser 负例创建了输出目录")
        print("ok laser negative")

        text = EXPECTED["laserText"]
        code, payload = run("laser", "text", "--text", text["text"])
        data = expect_ok("laser text", payload)
        if code != 0 or not payload.get("readOnly") or payload.get("writes"):
            fail(f"laser text 默认不是只读：exit={code} writes={payload.get('writes')}")
        if float(data.get("textWidth") or 0) <= 0 or (data.get("drawing") or {}).get("shapes") != 1:
            fail(f"laser text 图纸不符：{data}")
        text_out = tmp_dir / "laser-text"
        code, payload = run(
            "laser", "text", "--text", text["text"], "--out", str(text_out),
        )
        data = expect_ok("laser text out", payload)
        if code != 0 or payload.get("readOnly"):
            fail(f"laser text --out 不是写入：exit={code}")
        for name in text["files"]:
            if not (text_out / name).is_file():
                fail(f"laser text 缺少 {name}")
        design = json.loads((text_out / "design.json").read_text(encoding="utf-8"))
        if design.get("template") != "text" or design["params"].get("size") != text["size"]:
            fail(f"laser text design.json 不符：{design.get('template')}")
        print("ok laser text")

        code, payload = run("laser", "text", "--text", "")
        if code != 4 or _error_code(payload) != "TEXT_INVALID":
            fail(f"laser text 空文字负例不符：exit={code} code={_error_code(payload)}")
        print("ok laser text negative")

        rounded = EXPECTED["laserRounded"]
        v1_out = tmp_dir / "laser-rounded-v1"
        v1_params = {**rounded["params"], "pattern_version": 1}
        code, payload = run(
            "laser", "build", "--template", "rounded-box",
            "--params", json.dumps(v1_params), "--out", str(v1_out),
        )
        expect_ok("laser rounded v1", payload)
        if code != 0:
            fail(f"laser rounded v1 exit={code}")
        v1_design = json.loads((v1_out / "design.json").read_text(encoding="utf-8"))
        if v1_design["params"].get("pattern_version") != 1:
            fail(f"laser rounded v1 参数不符：{v1_design['params']}")
        v2_out = tmp_dir / "laser-rounded-v2"
        v2_params = {**rounded["params"], "pattern_version": 2}
        code, payload = run(
            "laser", "build", "--template", "rounded-box",
            "--params", json.dumps(v2_params), "--out", str(v2_out),
        )
        expect_ok("laser rounded v2", payload)
        if code != 0:
            fail(f"laser rounded v2 exit={code}")
        if (v1_out / "cut.svg").read_bytes() == (v2_out / "cut.svg").read_bytes():
            fail("rounded-box v1 与 v2 输出相同")
        print("ok laser rounded v1")

        code, payload = run("laser", "templates")
        data = expect_ok("laser templates", payload)
        templates = {item.get("id"): item for item in data.get("templates") or []}
        if code != 0 or data.get("count") != 5:
            fail(f"laser templates count={data.get('count')} exit={code}")
        if templates.get("rounded-box", {}).get("patternVersions") != [1, 2]:
            fail("laser templates 缺少 rounded-box patternVersions")
        if not any(item.get("name") == "pattern_version" for item in templates.get("rounded-box", {}).get("parameters") or []):
            fail("laser templates 缺少 pattern_version")
        print("ok laser templates")

        if os.environ.get("ZW_CONTRACT_CAD") == "1":
            box = EXPECTED["designSpecBox"]
            box_out = tmp_dir / "solid-box"
            code, payload = run(
                "structure", "solid", "--template", "box",
                "--params", json.dumps(box["params"]), "--out", str(box_out),
            )
            data = expect_ok("structure solid template", payload)
            if code != 0 or data.get("template") != "box" or data.get("title") != box["title"]:
                fail(f"structure solid template 不符：exit={code} data={data}")
            missing = [name for name in box["files"] if not (box_out / name).is_file()]
            if missing:
                fail(f"structure solid template 缺少文件：{missing}")
            design = json.loads((box_out / "design-spec.json").read_text(encoding="utf-8"))
            if design.get("spec", {}).get("title") != box["title"]:
                fail("structure solid design-spec.json 标题不符")
            code, payload = run(
                "structure", "solid", "--template", "nope",
                "--params", "{}", "--out", str(tmp_dir / "solid-nope"),
            )
            if code != 3 or _error_code(payload) != "TEMPLATE_NOT_FOUND":
                fail(f"structure solid 未知模板负例不符：exit={code} code={_error_code(payload)}")
            code, payload = run(
                "structure", "solid", "--template", "box",
                "--params", '{"thickness":0}', "--out", str(tmp_dir / "solid-zero"),
            )
            if code != 4 or _error_code(payload) != "PARAM_INVALID":
                fail(f"structure solid 非法参数负例不符：exit={code} code={_error_code(payload)}")
            print("ok structure solid template")
        else:
            print("skip structure solid template (ZW_CONTRACT_CAD != 1)")


    _check_enclosure(EXPECTED["enclosure"])

    print("all contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
