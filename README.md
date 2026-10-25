# ZaaS — ZhangWen as a Skill

把本地掌问 / ZhangWen 安装封装成 Claude Code skill：硬件资料检索、选型、接线、电气校验、MicroPython 检查、激光切割图纸、Python CAD 与固定外壳模板改造。本仓库即 skill 源码；运行时读取用户本机的掌问安装。

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

当前已在掌问 **V0.4.2026.1021.01**（`2e75546`）上验证。`zw status` 会读取 `$ZW_HOME/version.json` 报告 `zhangwenVersion` 和 release notes；上游升级后先跑 `zw status --json`，再跑 `python3 tests/contracts/check.py` 检查契约。

## 依赖

- 只读/激光：`scripts/requirements-core.txt`（pydantic、fastapi、httpx、fonttools、PyYAML）。
- CAD：`scripts/requirements-cad.txt`（再加 cadquery、cadquery-ocp、numpy、matplotlib）。
- 设备层：本地 `pyrcli`（Pyrite 项目），不由本 skill 安装。
- 不依赖 Node。

优先复用 `$ZW_HOME/.venv`，零安装。`scripts/mise.toml` 只用于开发排障。

## 命令

```bash
zw status --json
zw boards --json
zw hardware search <q> [--board B] [--category C] --json
zw hardware get <id> [--full] [--file PATH] --json
zw hardware guide <id> --board B [--set k=v] --json
zw hardware validate <board> <id...> --json
zw code check --board B --file main.py [--component ID] --json
zw laser build --template ID --params JSON --out DIR --json
zw structure template <id> [--edit plan.json] --out DIR --json
zw structure template <id> --list-params --json
zw structure solid --spec spec.json --out DIR --json
```

完整契约见 `references/cli.md`。

## 边界

- 只读掌问数据；除 `--out` 外不写盘。
- 不启动 FastAPI、不调用模型 API、不刷新目录缓存、不迁移 SQLite。
- v1 不调用 Node 自动外壳管线；只做 5 个固定模板与参数化实体。
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
references/cad.md       固定模板、改造、参数化实体
references/device.md    pyrcli 命令与分工
scripts/zw              bash 启动器
scripts/zw_cli/         确定性 CLI
tests/contracts/        JSON 契约快照
```

## 版权与许可

skill 包内只包含自写文档与 CLI 代码。掌问的硬件包、图片、固件、字体、模板均不随附；运行时通过 import 和只读文件访问本地安装。若将来复制掌问原创代码，需附 `LICENSE`/`NOTICE` 并标注修改。

本项目使用 AGPL-3.0，见 [LICENSE](LICENSE)。
