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

    print("all contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
