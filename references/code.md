# MicroPython 代码与检查

## 生成顺序

1. 先拿板级约束：`references/boards.md`，必要时 `zw hardware get <board> --file SKILL.md`。
2. 先拿模块指南：`zw hardware guide <id> --board <板> --json`，直接使用它的接线、`codeTemplate` 和注意事项。
3. 写单文件 `main.py`（或用户指定文件），再跑：

```bash
zw code check --board <板> --file main.py [--component <id> ...] --json
```

4. 有 FAIL 必须修；WARNING 要向用户说明。
5. 上板传输用 `pyrcli`（见 `device.md`），不在 `zw` 内做串口。

## `code check` 做什么

- `compile(source, filename, "exec")`：语法错误 → FAIL。
- `programming_diagnostics(code, board_id)`：板级 API 检查。例如 K10 的 `screen.text()` 误用、绘制前未 `screen.init(dir=2)`、绘制后未 `screen.show_draw()`；mPython 2.0 的 `machine.Pin(0/1)` 与板上 P0/P1 冲突。
- 传 `--component` 时追加电气规则校验（与 `hardware validate` 同引擎）。
- 输出 `checksum`（sha256），便于确认检查的就是将要上传的文件。
- FAIL → exit 4；WARNING/PASS → exit 0。

`code check` 不做运行时验证，也不连接设备。

## 板级 API 速查

### 行空板 K10

```python
from unihiker_k10 import screen
screen.init(dir=2)          # 只初始化一次
screen.clear()
screen.show_bg(color=(0, 0, 0))
screen.draw_text(text="你好", x=10, y=10, font_size=20, color=(255, 255, 255))
screen.show_draw()
```

禁止：`screen.text()`、`unihiker_k10.draw.text()`、`screen.canvas.text()`、`framebuf`、M10 `pinpong`。

### 掌控板 2.0

```python
from mpython import oled
from machine import Pin
from mpython import MPythonPin, PinMode

oled.fill(0)
oled.DispChar("你好", 0, 0)
oled.show()

p0 = MPythonPin(0, PinMode.IN)   # 板上 P0 = GPIO33
```

不要用 `machine.Pin(0)` / `Pin(1)` 代表板上 P0/P1。

### 掌控板 3.0

使用 `mpython.display` / `lcd` 彩屏接口；不要照搬 2.0 的 `oled` 单色流程。没有 Board Skill，API 细节以 `programming-skills/mpython-v3` 与 `hardware guide` 为准。

### XIAO ESP32S3 Sense / ESP32-C3

只用当前固件档案确认过的引脚和 API。摄像头/麦克风/SD 的导入与函数签名未确认时，明确标“待确认”，不要编造。XIAO 启用 SD 后 GPIO21 与用户 LED 冲突。

## 硬规则

- 不硬编码 Wi-Fi 密码、Token、API Key；用 `CONFIG = {"ssid": "..."}` 占位并提示用户填写。
- 引脚号以 `zw hardware guide` 渲染结果为准，不凭记忆。
- 电压/电流结论来自 `hardware validate`；`0` 是未知。
- 不把 `OFFICIAL_API_REFERENCE_UNTESTED` / `MIGRATED_UNVERIFIED` 的 API 写成“已实测”。
- 生成的文件名、路径、上传目标交给 `pyrcli` 时写清楚；不要假设设备已有目录。
- 需要修复而非重写时，保留用户原有结构和注释，只改必要行。
