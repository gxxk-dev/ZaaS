# 5 块主控

`zw` 接受显示名、`componentId`、`skillName` 和常用别名；`--board` 会归一化。拿不准时先跑 `zw boards --json`。

| 显示名 | componentId | 硬件包 skillName | Board Skill | 编程参考 | 固件 |
|---|---|---|---|---|---|
| 行空板 K10 | `hw_seed_unihiker_k10` | `k10` | `unihiker-k10` | `unihiker-k10` | `k10-download.bin`，V0.9.8，offset 0 |
| XIAO ESP32S3 Sense | `hw_seeed_xiao_esp32s3_sense` | `seeed-studio-xiao-esp32s3-sense` | `xiao-esp32s3-sense` | 无 | `xiao-s3.bin`，MicroPython v1.29.0，offset 0 |
| ESP32-C3 通用 | `hw_esp32_generic_c3` | `esp32-generic-c3` | `esp32-generic-c3` | 无 | `esp32-c3.bin`，MicroPython v1.29.0，offset 0 |
| 掌控板 2.0 | `hw_labplus_mpython_v2` | `labplus-mpython-v2` | `labplus-mpython-v2` | `mpython-v2` | `mpython2.bin`，mPython v2.6.0，offset 0 |
| 掌控板 3.0 | `hw_labplus_mpython_esp32s3_v3` | `labplus-mpython-esp32s3-v3` | 无 | `mpython-v3` | `mpython3.bin`，offset 0（镜像以 `resources/firmware/manifest.json` 为准） |

固件镜像都在 `$ZW_HOME/resources/firmware/`，本地存在时 `zw boards` 会标 `firmwareInstalled=true`。镜像的 `sha256`、大小和来源 URL 以 `resources/firmware/manifest.json` 为准。`zw firmware list/get` 只读展示元数据；`zw firmware verify` 只读比对本地文件的大小和 SHA-256，不下载、不刷写。

## 常用别名

- K10：`k10`、`行空板 K10`、`unihiker-k10`
- XIAO：`xiao`、`xiao esp32s3 sense`、`seeed-studio-xiao-esp32s3-sense`
- C3：`c3`、`esp32-c3`、`esp32-generic-c3`
- 掌控板 2.0：`mpython`、`mpython2`、`掌控板 2.0`、`labplus-mpython-v2`
- 掌控板 3.0：`mpython3`、`掌控板 3.0`、`labplus-mpython-esp32s3-v3`

## 板级差异

### 行空板 K10（ESP32-S3 N16R8）

- 官方屏幕流程：`from unihiker_k10 import screen` → 只初始化一次 `screen.init(dir=2)` → `screen.clear()` / `screen.show_bg(...)` → `screen.draw_text(text=..., x=..., y=..., font_size=..., color=...)` → `screen.show_draw()`。
- **不要**使用 `screen.text()`、`unihiker_k10.draw.text()`、`screen.canvas.text()`、`framebuf` 或 M10 的 `pinpong`。`zw code check` 会把这类调用判为 FAIL。
- 绘制/清除前没有 `screen.init(dir=2)`、绘制后没有 `screen.show_draw()` 会给 WARNING。
- ADC 模块的指南可能使用 `from unihiker_k10 import pin`；以 `zw hardware guide` 渲染结果为准，不套用 mPython 的 `MPythonPin`。
- 固件 V0.9.8 的完整 16MiB 镜像从 0x0 写入并覆盖整个 Flash；不要再套用旧文档的 0x1000 偏移。

### Seeed Studio XIAO ESP32S3 Sense

- 档案为 8MB Flash、8MB OPI PSRAM。
- 摄像头、PDM 麦克风、SPI microSD、USB Serial/JTAG 的引脚和 API 必须以当前固件档案/探测为准；没确认就标“能力待确认”，不要编造导入或函数签名。
- SD 启用后 GPIO21 与用户 LED 冲突，不能同时驱动。
- 未在引用资料或当前固件探测中确认的外设 API，不要写成已验证。

### ESP32-C3 通用

- 只代表通用 MicroPython 主控；具体开发板引脚、板载外设、Flash 大小按实物丝印和板级资料核对。
- 不要把其他 ESP32-C3 开发板的引脚表直接套过来。
- 至少需要 4MiB Flash 才能使用当前通用镜像。

### 掌控板 2.0（ESP32，128×64 单色 OLED）

- 显示统一用 `from mpython import oled`，绘制后 `oled.show()`；中文用 `oled.DispChar()`。
- 板上 P0 = GPIO33，P1 = GPIO32。**不要**用 `machine.Pin(0)` / `machine.Pin(1)` 操作板上 P0/P1；需要板级 P 口时用 `MPythonPin(P号, PinMode...)`。`zw code check` 会给出 `mpython-pins` WARNING。
- 不套用掌控板 3.0 的 `lcd`/彩屏接口、K10 的 `screen` 或 Arduino 示例。
- 固件 mPython v2.6.0，镜像从 0x0 写入。

### 掌控板 3.0（ESP32-S3，彩色屏）

- 使用 `mpython.display` 和 `lcd` 颜色对象；**不要**照搬 2.0 的 `oled`/单色流程。
- 没有 Board Skill，只有 `programming-skills/mpython-v3`；不要因 2.0 有实测记录就宣称 3.0 已验收。
- 外接端口以当前硬件资料为准；未知签名先问或让用户在 REPL 中确认。

## 验证语义

`verificationStatus` 是包级声明，不等于本机实测。常见值：

- `OFFICIAL_DOC_VERIFIED`：官方文档核对。
- `SOURCE_VERIFIED_*`：来源核对；`*_WITH_MECHANICAL_CONFLICT` 还带机械冲突。
- `OFFICIAL_API_REFERENCE_UNTESTED`：API 参考已核对，未测试。
- `REQUIREMENT_VERIFIED`：需求/约束核对。
- `MIGRATED_UNVERIFIED`：迁移而来，未联调。
- `UNVERIFIED`：未验证。

除 `OFFICIAL_DOC_VERIFIED` 外，结论都要标注“未联调/待实物验证”。
