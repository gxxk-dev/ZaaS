# 设备层：pyrcli

掌问 skill **不直接操作串口**。设备扫描、上传、运行、复位、刷机统一交给本地 Pyrite 的 `pyrcli`。`zw` 只产出、检查文件；是否上板由用户确认后执行 `pyrcli`。

## 先找设备

```bash
pyrcli scan --json
```

输出 `{"devices": [...], "count": N}`；没有设备时 `count: 0`。需要板子信息时加 `-i`（会连接设备）。也可用 VID/PID/关键字过滤：

```bash
pyrcli scan -k ch340 --all
```

串口别名可避免每次写 `/dev/ttyUSB0`：

```bash
pyrcli board register k10 /dev/ttyUSB0     # 注册/更新
pyrcli board list
pyrcli board resolve @k10
pyrcli board remove k10
```

用 `@k10` 作为 `port` 参数。

## 上传与运行

| 任务 | 命令 |
|---|---|
| 单文件上传 | `pyrcli flash <port> main.py :main.py --check=strict` |
| 整目录上传 | `pyrcli flash-program <port> <dir> :/app` |
| 项目增量同步 | `pyrcli project flash <port> <dir> /app` |
| 查看差异（不上传） | `pyrcli project status <port> <dir> /app --json --diff` |
| 运行测试 | `pyrcli test <port> <test_file>` |
| 看设备文件 | `pyrcli fs ls <port> /`、`fs cat`、`fs tree` |
| 上传/下载单文件 | `pyrcli fs put <port> <local> <remote>`、`fs get <port> <remote> <local>` |
| 软复位 | `pyrcli reset <port>` |
| 交互 REPL | `pyrcli repl <port>` |

`flash` / `flash-program` / `project flash` 都支持 `--dry-run` 预览。注意：部分路径在 `--dry-run` 下仍会先打开串口，不接设备时只能验证参数解析，不能验证目标路径。正式上传前先跑一次确认目标路径和文件清单。`--check=strict` 会在刷入前做兼容性预检查；不要默认 `--no-check`。

`flash` 的 `remote_path` 用 `:main.py` 这类冒号前缀表示设备路径；`flash-program` 用 `:/app`。以 `--help` 的当前输出为准。

## 固件

掌问自带 5 块主控的 MicroPython 镜像，位于：

```
$ZW_HOME/resources/firmware/
```

版本、偏移、sha256、大小以 `$ZW_HOME/resources/firmware/manifest.json` 为准。只读查看与本地校验：

```bash
zw firmware list [--board B] --json
zw firmware get k10 --json
zw firmware verify k10 --file "$ZW_HOME/resources/firmware/k10-download.bin" --json
```

`verify` 只计算本地文件大小和 SHA-256，与 manifest 固定值比对；退出 0 只表示文件与固定镜像一致，不代表已刷写或设备可启动。它不下载、不刷写、不访问设备。`zw boards --json` 只报告 `firmwareInstalled` 和元数据，不校验、不刷写。

`pyrcli firmware flash <port>` 是 **Pyrite 项目的构建产物刷写器**：它读取项目里的 `flash_layout.json`，用 esptool 按布局写入。`--image` 只能替换镜像路径，布局仍来自 `flash_layout.json`。因此：

- 不要用它直接刷掌问的 `k10-download.bin` / `mpython3.bin` 等镜像，除非已确认布局与偏移匹配。
- 掌问镜像的刷写走掌问 Web 工作台，或由用户明确要求后用 esptool 按 manifest 的 offset 手工执行。
- 刷机是高风险管理操作：先确认板型、串口、镜像和偏移；没有用户明确同意不要执行。

## 与 handpy / zhangwen 的分工

- `zhangwen` skill：硬件选型、接线、电气校验、MicroPython 代码生成与 `zw code check`、激光/3D 设计；给出上传命令但不自行占用串口。
- `handpy` skill：独立 HandPy/mPython 板级 API 知识、屏幕/按键/内置传感器示例、`handpy-tool` 能力。
- `pyrcli`：所有设备文件传输、运行、复位、固件刷写。两套 skill 都调用它，不各造一套工具。
- `pyrcli` 缺能力时补 Pyrite 项目 `/home/frez79/Pyrite-Project/pyrite-cli`，不在掌问 skill 内重写。

## 安全边界

- 执行 `reset`、`flash`、`flash-program`、`firmware flash` 前确认串口对应正确板子；多设备时先 `scan --json` 并用别名。
- 不上传含 Wi-Fi 密码、Token、API Key 的本地配置；生成代码用占位符。
- 不删除设备文件（`fs rm`、`rm-batch`）除非用户明确要求并确认路径。
- `--dry-run` 只验证命令拼装，不代表目标设备可写。
