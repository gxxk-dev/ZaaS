# zw CLI 契约

`zw` 是掌问仓库的确定性只读封装。Claude 负责理解、生成和解释；`zw` 负责检索、规则校验、模板渲染和几何构建。

## 环境

| 变量 | 作用 | 默认 |
|---|---|---|
| `ZW_HOME` | 掌问安装根目录 | `/mnt/dev-cold/zhangwen` |
| `ZW_DATA_DIR` | 数据目录（`hardware-skills/`、`cache/`） | `$ZW_HOME/.data` |
| `ZW_PYTHON` | 显式指定解释器 | 自动选择 |
| `ZW_DEBUG` | 设为 `1` 时把异常堆栈打到 stderr | 未设置 |

启动器按顺序选解释器：`ZW_PYTHON` → `$ZW_HOME/.venv/bin/python` → `uv run --no-project --python 3.13 --with-requirements ...`。都没有则 exit 5。

所有命令默认只读。只有 `laser build`、`structure template`、`structure solid`、`enclosure build` 会写盘，且只写 `--out`。

## JSON 信封

`--json` 输出：

```json
{
  "schema": "zw.cli/v1",
  "command": "hardware search",
  "ok": true,
  "readOnly": true,
  "writes": [],
  "source": {
    "home": "/mnt/dev-cold/zhangwen",
    "dataDir": "/mnt/dev-cold/zhangwen/.data",
    "catalog": "scan",
    "cacheCount": 255,
    "scanCount": 260,
    "cacheGeneratedAt": "2026-10-22T17:23:15+00:00",
    "stale": true
  },
  "data": {},
  "warnings": []
}
```

失败时没有 `data`，改为：

```json
{"ok": false, "error": {"code": "EDIT_INVALID", "message": "...", "hint": "..."}}
```

`warnings` 必须阅读；它们承载“未实测”“缓存过期”“峰值为未知”等语义。

## 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功（WARNING 也算成功） |
| 2 | 参数、JSON、模板或改造方案错误 |
| 3 | 未找到硬件包、主控、指南或模板 |
| 4 | 校验 FAIL、`needs_input` 或几何无效 |
| 5 | 缺依赖/解释器/CadQuery/字体 |
| 6 | 拒绝写入（非空目录、写入 ZW_HOME） |
| 7 | 子进程、IO、安装完整性或上游数据错误 |

## 只读命令

```bash
zw status --json
zw boards --json
zw boards --board B [--full [--file PATH] | --context QUERY] --json
zw hardware search <关键词> [--board B] [--category C] [--limit N] --json
zw hardware get <componentId|skillName|显示名> [--full] [--file PATH] --json
zw hardware guide <componentId> --board B [--kind functional|diagnostic|reference] [--set key=value ...] --json
zw hardware validate <board> <componentId...> --json
zw firmware list [--board B] --json
zw firmware get <board> --json
zw firmware verify <board> --file PATH --json
zw code check --board B --file main.py [--component ID ...] --json
zw code fix --board B --file main.py [--out FILE] --json
zw structure templates --json
zw structure library [--category C] [--query Q] --json
zw structure library <profile_id> --json
zw enclosure profiles --json
zw enclosure plan --request FILE|- --json
```

- `status` 额外报告 `zhangwenVersion` 与 `zhangwenReleaseNotes`，来自 `$ZW_HOME/version.json`；读不到版本会给出 warning。当前 ZaaS 已在 `V0.4.2026.1021.01` 上验证。
- `hardware get` 默认只给文件元数据和指南摘要；`--full` 才内联全部文件正文；`--file` 只取一个文件。
- `hardware guide` 的 `--set` 只接受该指南 `fields` 中出现的 key 和 value；不接受未知引脚。`--kind` 断言指南种类，不匹配时 exit 4 `GUIDE_KIND_MISMATCH`。
- `boards --full/--file/--context` 必须与 `--board` 同用；`--file` 还需 `--full`，`--context` 与 `--full/--file` 互斥。strict Board Skill 校验和失败 → exit 7 `BOARD_SKILL_INVALID`；legacy 布局 `verified=false`；`--context` 在 legacy/无 Board Skill 时 exit 4 `BOARD_SKILL_CONTEXT_UNAVAILABLE`。
- `hardware validate` 必须显式列模块；CLI 会自动加入主控 MCU 组件。没有主控时上游只给 WARNING。
- `firmware list/get` 只读 `resources/firmware/manifest.json` 与上游 `PROFILES`；镜像未提供时仍 exit 0，给 `unavailable` 和 warning。
- `firmware verify` 只读计算本地文件大小和 SHA-256，与固定镜像比对；不下载、不刷写、不调用 FastAPI 的镜像接口。文件必须是普通文件（拒绝符号链接/目录）。匹配 exit 0，不匹配 exit 4 `FIRMWARE_MISMATCH`，无镜像 exit 4 `FIRMWARE_UNAVAILABLE`。
- `code check --component` 额外做电气规则校验；省略时只做语法和板级 API 检查。
- `code fix` 是只读预览式修复；只有显式 `--out FILE` 才写一个**不存在**的新文件，目标已存在或位于 `$ZW_HOME` 内 → exit 6。exit 0 不表示诊断清零或已实测。
- `structure templates` 只读列出 5 个打包模板与 `box/cup/bracket` 三个 design-spec 模板；不需要 CadQuery。`structure library` 只读暴露 `services/structure-cad/server/data/hardware-library.json` 的 legacy 资料，不是 `HardwareProfile`，`enclosure` 不读取。`enclosure profiles` 只读列出 5 个 trusted profile 与资料包 mechanical profile；不读取 legacy 几何资料库。三者都走 core 依赖。
- `structure library` 的 `<profile_id>` 与 `--category/--query` 互斥；缺文件 exit 5 `LIBRARY_MISSING`，损坏 exit 7 `LIBRARY_INVALID`，id 不存在 exit 3 `PROFILE_NOT_FOUND`，过滤无匹配 exit 0 + warning。
- `enclosure plan` 只读、无 CadQuery 依赖；缺机械数据时 exit 4 `NEEDS_INPUT`，见 `enclosure.md`。

## 产出命令

```bash
zw laser build --template <plate|round-tag|panel-box|finger-box|rounded-box> \
  --params '<JSON>' --out DIR [--json]
zw laser text --text "掌问" [--size MM] [--margin MM] [--out DIR] [--json]
zw laser templates --json

zw structure template <id> [--edit plan.json] --out DIR [--json]
zw structure template <id> --list-params --json
zw structure solid --spec spec.json --out DIR [--json]
zw structure solid --template box|cup|bracket [--params JSON] --out DIR [--json]

zw enclosure build --request FILE|- --out DIR [--json]
zw enclosure build --spec FILE|-   --out DIR [--json]
```

- `--params` 可写内联 JSON 或 `@file.json`；`structure solid` 还接受 `-`。`--spec` 与 `--template` 互斥且必须提供一个；未知模板 exit 3 `TEMPLATE_NOT_FOUND`，非法参数 exit 4 `PARAM_INVALID`。
- `laser text` 默认只读；`--out` 才写 4 个文件。`--size` 1–150mm，`--margin` ≥0；字体固定为随包 NotoSansSC，文字缺字 exit 4 `TEXT_INVALID`。
- `laser templates` 只读列出模板、参数默认值和 `patternVersions`；`rounded-box` 支持 `pattern_version=1|2`，默认 2。
- `--edit` / `--spec` 接受文件路径或 `-`（stdin）。
- `--out` 默认拒绝非空目录；加 `--force` 才覆盖同名文件。
- `--out` 位于 `$ZW_HOME` 内时默认拒绝；只有显式 `--allow-in-repo` 才允许。
- `enclosure build` 例外：`--out` 必须为空或不存在，**没有 `--force`/`--allow-in-repo`**。
- `--list-params` 只读，不写盘，输出该固定模板的全部顶层数值参数和部件。
- `structure template` 会写 `template-<part>.step/.stl`、`cadquery.py`、`template-edit.json`。
- `structure solid` 会写 `model.step`、`model.stl`、`design-spec.json`、`cadquery.py`。
- `enclosure build` 会写 `assembly.step`、`base/lid.step/.stl`、`preview.glb`、`parameters.json`、`profiles.json`、`validation.json`、`geometry-summary.json`、`manifest.json`、`spec.json`。

## 边界

- 不启动 FastAPI，不导入 `zhangwen.web.app`。
- 不实例化 `WebRepository`、`WebHardwareRepository`、`StructureService`、`BoardProfileRepository`。
- 不调用 `list_skills`、`render_context`、`list_active_context_candidates`、`refresh_active_catalog`、任何 `install_*`/`update_*`/`save_*`/`migrate_*`。
- 目录缓存只读；缓存 255 条 vs 磁盘 260 包时只报告 `stale=true`，绝不刷新。
- v1 不调用 Node；`services/structure-cad/worker.mjs` 的自动外壳管线不在 CLI 内。
- `enclosure` 只调用 Python 的 `zhangwen.cad_engine`；不启动 FastAPI，不调用模型 API，不写 `$ZW_HOME`。
- 设备 I/O 不在 `zw` 内；见 `device.md` 的 `pyrcli` 命令。
