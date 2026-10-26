# ZaaS — ZhangWen as a Skill

把本地掌问 / ZhangWen 安装封装成 Claude Code skill：硬件资料检索、选型、接线、电气校验、MicroPython 检查与确定性修复、固件元数据/本地校验、板级 Skill 资料、激光切割图纸、Python CAD、固定外壳模板改造、freeform 声明式实体与刻字，以及由已选硬件确定性生成带开孔/上盖/螺丝柱的外壳与单器件安装座。本仓库即 skill 源码；运行时读取用户本机的掌问安装。

**非官方**：本项目不是掌问官方发行物，与掌问项目无隶属关系。运行时读取用户本机的掌问安装，不复制、不捆绑其硬件包、图片、固件、字体或 CAD 模板。

## 安装

```bash
git clone https://github.com/gxxk-dev/ZaaS ~/ZaaS
mkdir -p ~/.claude/skills
ln -s ~/ZaaS ~/.claude/skills/zhangwen
```

确保本地掌问安装在（默认）：

```bash
export ZW_HOME=/mnt/dev-cold/zhangwen
~/ZaaS/scripts/zw status --json
```

`ZW_HOME` 必须包含 `services/local-api/zhangwen/` 和 `.data/hardware-skills/`。没有 `.venv` 时，启动器会用 `uv run --no-project --python 3.13 --with-requirements ...` 建临时环境；CAD 命令需要 CadQuery/OCP。

当前已在掌问 **V0.4.2026.1021.01**（`2e75546`）上验证。`zw status` 会读取 `$ZW_HOME/version.json` 报告 `zhangwenVersion` 和 release notes；上游升级后先跑 `zw status --json`，再跑 `python3 -m pytest` 检查契约。

## 依赖

- 只读/激光：`scripts/requirements-core.txt`（pydantic、fastapi、httpx、fonttools、PyYAML）。
- CAD：`scripts/requirements-cad.txt`（再加 cadquery、cadquery-ocp、numpy、matplotlib）。
- 设备层：本地 `pyrcli`（Pyrite 项目），不由本 skill 安装。
- 不依赖 Node。

优先复用 `$ZW_HOME/.venv`，零安装。`scripts/mise.toml` 只用于开发排障。

## 测试

```bash
python3 -m pytest                         # core，默认不跑 CAD
python3 -m pytest -o addopts="" -m cad    # CAD 构建
python3 -m pytest -o addopts=""           # core + CAD
```

测试进程只需要 pytest（`scripts/requirements-dev.txt`），通过 `scripts/zw` 子进程复用 `$ZW_HOME/.venv`；不要把 pytest 装进掌问 `.venv`。没有 pytest 时用 `python3 -m pip install -r scripts/requirements-dev.txt`，或 `uv run --no-project --python 3.13 --with-requirements scripts/requirements-dev.txt pytest`。

## 命令

```bash
zw status --json
zw boards --json
zw boards --board B [--full [--file PATH] | --context QUERY] --json
zw hardware search <q> [--board B] [--category C] --json
zw hardware get <id> [--full] [--file PATH] --json
zw hardware guide <id> --board B [--kind K] [--set k=v] --json
zw hardware validate <board> <id...> --json
zw firmware list [--board B] --json
zw firmware get <board> --json
zw firmware verify <board> --file PATH --json
zw code check --board B --file main.py [--component ID] --json
zw code fix --board B --file main.py [--out FILE] --json
zw laser build --template ID --params JSON --out DIR --json
zw laser text --text "掌问" [--out DIR] --json
zw laser templates --json
zw structure templates --json
zw structure library [--category C] [--query Q] --json
zw structure template <id> [--edit plan.json] --out DIR --json
zw structure template <id> --list-params --json
zw structure solid --spec spec.json --out DIR --json
zw structure solid --template box|cup|bracket [--params JSON] --out DIR --json
zw structure freeform plan  --request FILE|- --json
zw structure freeform build --request FILE|- --out DIR --json
zw structure freeform build --spec FILE|-   --out DIR --json
zw enclosure profiles --json
zw enclosure plan  --request FILE|- --json
zw enclosure build --request FILE|- --out DIR --json
zw enclosure build --spec FILE|-   --out DIR --json
```

完整契约见 `references/cli.md`。

## 边界

- 只读掌问数据；除 `--out` 外不写盘。
- 不启动 FastAPI、不调用模型 API、不刷新目录缓存、不迁移 SQLite。
- 固件命令只读元数据并做本地文件大小/SHA-256 校验；不下载、不刷写。
- `structure library` 是 structure-cad 的 legacy 只读资料，不是 `HardwareProfile`，`enclosure` 不读取。
- v1 不调用 Node 自动外壳管线；外壳与 freeform 由 Python 的 `zhangwen.cad_engine` 确定性生成。
- `enclosure` 缺机械数据时返回 `NEEDS_INPUT` 提问，不猜尺寸；`enclosure build`/`structure freeform build` 的 `--out` 必须为空或不存在，没有 `--force`。
- freeform 的 `plan` 不需要 CadQuery；`build` 需要。文字刻字固定使用随包字体，文字无效或布尔无体积变化会明确报错。
- 设备 I/O 交给 `pyrcli`；不在本 skill 内实现串口协议。
- 激光/CAD 输出为名义几何，不含刀缝补偿、打印公差或实物验证。

## 结构

```
SKILL.md                触发与工作流
references/cli.md       命令、JSON、退出码、写入边界
references/boards.md    5 块主控差异
references/hardware.md  资料包字段与指南
references/code.md      MicroPython 约定与检查
references/laser.md     5 类激光模板
references/cad.md       固定模板、改造、design-spec 模板、参数化实体
references/freeform.md  freeform 请求、spec 包装、文字刻字
references/enclosure.md 自动外壳请求、profile、尺寸与产物
references/device.md    pyrcli 命令与分工
scripts/zw              bash 启动器
scripts/zw_cli/         确定性 CLI
tests/                  pytest 契约测试与 tests/data/expected.json
pytest.ini              pytest 配置（默认排除 cad marker）
```

## 版权与许可

skill 包内只包含自写文档与 CLI 代码。掌问的硬件包、图片、固件、字体、模板均不随附；运行时通过 import 和只读文件访问本地安装。若将来复制掌问原创代码，需附 `LICENSE`/`NOTICE` 并标注修改。

本项目使用 AGPL-3.0，见 [LICENSE](LICENSE)。
