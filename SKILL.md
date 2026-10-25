---
name: zhangwen
description: "Use for ZhangWen/掌问 project work: selecting and validating MicroPython hardware from its local 260-package library, rendering board-specific wiring and module guides for 掌控板 2.0/3.0, 行空板 K10, XIAO ESP32S3 Sense and ESP32-C3, checking generated MicroPython, and producing laser-cut drawings (SVG/DXF) or Python-side CAD models (STL/STEP), including bounded edits of packaged 3D shell templates, through a local ZhangWen install. 适用于掌问项目内的硬件选型、接线、模块资料、代码检查、激光切割与 3D 建模/外壳改造；独立 HandPy/mPython 板级开发用 handpy skill，串口上传/刷机用 pyrcli。"
---

# 掌问（ZhangWen）

把本地掌问安装当成只读事实库与几何引擎：Claude 负责理解需求、生成代码、解释结果；`zw` 负责检索、规则校验、模板渲染和几何构建。**不启动掌问 Web 服务，不调用模型 API，不写掌问数据目录。**

## 前置检查

```bash
~/.claude/skills/zhangwen/scripts/zw status --json
```

`status` 必须显示 `ok: true`，并检查：掌问版本（`zhangwenVersion`）、解释器来源、数据目录、目录缓存（255/260 且 `stale` 属正常）、依赖、5 块主控、激光/CAD 模板数。缺依赖按 `references/cli.md` 的启动器顺序处理；不要自行 `pip install` 到掌问仓库的 `.venv`。

`ZW_HOME` 默认 `/mnt/dev-cold/zhangwen`；其他安装位置用环境变量覆盖。

## 读取顺序

1. 先读 `references/cli.md`：命令、JSON 信封、退出码、写入边界。
2. 按任务读：
   - 选型/资料/接线/校验 → `references/hardware.md`，再查 `references/boards.md`。
   - 生成或检查 MicroPython → `references/code.md` + `references/boards.md`。
   - 激光切割 → `references/laser.md`。
   - 3D 固定模板/改造/参数化实体 → `references/cad.md`。
   - 上板、串口、刷机 → `references/device.md`。
3. 只读需要的 reference；不要一次加载全部。

## 核心工作流

### 1. 选型 + 接线 + 电气校验

```bash
zw hardware search <关键词> --board <板> --json
zw hardware get <componentId> --json
zw hardware guide <componentId> --board <板> --json
zw hardware validate <板> <componentId...> --json
```

- 搜索先看 `recommended` / `boardSpecific` / `verificationStatus`；同名多包时说明差异。
- 接线和示例代码以 `guide` 的 `wiring` / `code` 为准，不凭记忆。
- `validate` 必须 PASS；FAIL 时停止接线/上电，先处理失败项。
- `--set` 只能使用该指南 `fields` 中的 key/value。

### 2. 写代码 + 检查

按 `guide.code` 和 `boards.md` 写 `main.py`，然后：

```bash
zw code check --board <板> --file main.py [--component <id> ...] --json
```

FAIL 必须修；WARNING 必须转述。需要上板时按 `device.md` 调 `pyrcli`，先 `scan --json` 确认串口。

### 3. 激光图纸

```bash
zw laser build --template finger-box \
  --params '{"width":80,"depth":60,"height":40,"thickness":3}' \
  --out ./laser-out --json
```

先问清外尺寸、板厚、材料。`panel-box` 是胶合对接，`finger-box` 是榫齿，`rounded-box` 是弯折盒，不能混称。

### 4. 3D

```bash
# 看模板参数与部件
zw structure template mpython-shell --list-params --json

# 原模板
zw structure template mpython-shell --out ./cad-out --json

# 受约束改造：Claude 只写 JSON
zw structure template mpython-shell --edit plan.json --out ./shell-out --json

# 参数化实体
zw structure solid --spec spec.json --out ./solid-out --json
```

`--edit` 的 `TemplateEditSpec` 只允许改 `--list-params` 中的顶层数值 + 对 printable 部件做受控布尔/刻字。模型不生成 Python，CLI 不执行模型文本。坐标是原模板装配坐标；刻字深度必须小于板厚。

## 硬规则

1. `voltage=0` / `peakCurrent=0` 表示**未知**，不是 0V/0A。
2. `verificationStatus` 非 `OFFICIAL_DOC_VERIFIED` 时，结论必须标注“未联调/待实物验证”；保存、编译、串口回读都不算实测。
3. 电气结论只来自 `zw hardware validate`，不让模型心算电流预算。
4. 掌控板 2.0：板上 P0=GPIO33、P1=GPIO32，不能用 `machine.Pin(0/1)` 代替；显示用 `mpython.oled`。
5. 行空板 K10：屏幕只用 `unihiker_k10.screen` 的 `init(dir=2)` → `draw_text` → `show_draw()` 流程；禁止 `screen.text()`、`framebuf`、M10 `pinpong`。
6. 掌控板 3.0：用 `mpython.display`/`lcd` 彩屏接口，不照搬 2.0 的 `oled`；没有 Board Skill，API 未确认时标“待确认”。
7. 生成的代码不硬编码 Wi-Fi 密码/Token/API Key；用占位符并提示用户填写。
8. 激光/CAD 产物必须声明“名义尺寸，未做刀缝补偿/打印公差/实物装配验证”。
9. 改固定模板优先 `--edit`，保留原模板孔位与装配关系；不要用 `structure solid` 重画来绕过不可改的参数。
10. 只写 `--out`；默认拒绝非空目录，拒绝写入 `$ZW_HOME`（除非用户明确 `--allow-in-repo`）。绝不刷新掌问缓存、迁移数据或调用任何 `install_*`/`update_*`/`save_*`。

## 与 handpy / pyrcli 的分工

- **zhangwen**：掌问资料库、选型、接线、电气校验、代码检查、激光、Python CAD、固定外壳模板改造。
- **handpy**：独立 HandPy/mPython 板级 API 知识、屏幕/按键/内置传感器、`handpy-tool`。
- **pyrcli**：设备扫描、上传、运行、复位、刷固件。两个 skill 共用，不在掌问里重写。
- 用户只做通用 ESP32 或非掌问硬件时，不要强行套掌问资料包。

## 输出要求

- 先给结论，再给接线/代码/文件路径。
- 引用 `componentId`、`displayName`、`verificationStatus`。
- 产出命令后列出实际写入的文件；失败时给退出码对应的原因和下一步。
- 不展示 `zw` 的原始 JSON 全文给用户，提炼关键字段。
- 上板/刷机前确认串口和板型；没有明确同意不执行 `reset`/`flash`/`firmware flash`。

## 故障排查

- `zw` 报 `DEPENDENCY_MISSING` → `zw status --json` 看缺哪个；按 `cli.md` 的解释器顺序处理。
- `exit 3` → 标识符不对；先 `hardware search` 或 `boards --json`。
- `exit 4` → 校验 FAIL、`questions` 非空或几何无效；不要绕过，先修输入。
- `exit 6` → 输出目录非空或位于 `ZW_HOME`；换目录或显式 `--force`/`--allow-in-repo`。
- `exit 7` → 模板 sha256/上游数据/子进程问题；设 `ZW_DEBUG=1` 看堆栈，不要改掌问文件。
