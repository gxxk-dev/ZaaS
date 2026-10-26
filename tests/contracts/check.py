#!/usr/bin/env python3
"""Contract checks for the zhangwen skill. Read-only except for a temp dir."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
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

    with tempfile.TemporaryDirectory(prefix="zw-contract-") as tmp:
        bad = Path(tmp) / "bad.py"
        bad.write_text(EXPECTED["k10BadCode"]["source"], encoding="utf-8")
        code, payload = run("code", "check", "--board", "k10", "--file", str(bad))
        if code != EXPECTED["k10BadCode"]["exit"]:
            fail(f"code check exit={code}")
        codes = {item.get("code") for item in (payload.get("data") or {}).get("diagnostics", [])}
        if EXPECTED["k10BadCode"]["diagnostic"] not in codes:
            fail(f"code check 诊断缺失：{codes}")
        print("ok code check")

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

    _check_enclosure(EXPECTED["enclosure"])

    print("all contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
