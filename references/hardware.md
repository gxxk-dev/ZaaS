# 硬件资料包

## 数据来源

磁盘：`$ZW_DATA_DIR/hardware-skills/<skillName>/`，当前 260 个包。目录缓存：`$ZW_DATA_DIR/cache/hardware-catalog-v1.json`，可能过期（当前 255 条）。`zw` 以磁盘 `manifest.json` 为准，只报告 `stale=true`，不刷新缓存。

`skillName` 已被 slug 化，和显示名/组件 ID 不同。例如：

- 行空板 K10 专用 DFR0026：`dfrobot-dfr0026-k10` / `hw_dfrobot_dfr0026_k10`，`MIGRATED_UNVERIFIED`
- 通用 DFR0026：`dfr0026-ambient-light-sensor` / `hw_dfrobot_dfr0026`，`SOURCE_VERIFIED_WITH_MECHANICAL_CONFLICT`

同一器件可能有多个包；选型时必须看 `verificationStatus`、`supportedBoardIds` 和 `warnings`，不要只按名字取第一个。

## 包结构

```text
<skillName>/
├── manifest.json
├── SKILL.md
├── references/
│   ├── specifications.md        # 含 ```zhangwen:hardware-spec:v1 JSON 块
│   ├── compatibility-rules.md   # 含 ```zhangwen:hardware-rules:v1 JSON 块
│   ├── integration.md
│   ├── safety.md
│   ├── sources.md
│   └── mechanical.md            # 可选
├── examples/usage.md            # 可选
├── tests/validation-cases.md    # 可选
├── models/cadquery.py           # 可选
└── assets/cover.webp            # 可选
```

`zw hardware get` 默认只返回文件清单和指南摘要；要正文用 `--file references/specifications.md` 或 `--full`。不要自行遍历 260 个目录找资料。

## 字段语义

### electrical

| 字段 | 含义 | 陷阱 |
|---|---|---|
| `voltage` | 供电电压 V | `0` = 未知，不是 0V |
| `peakCurrent` | 峰值电流 A | `0` = 未知，不是 0A |
| `logicLevel` | 逻辑电平 V | `0` = 未知 |
| `communicationProtocol` | I2C/SPI/UART/GPIO/ADC 等 | 多接口时以指南为准 |
| `supportedMCUs` | 支持的主控 | 命中不代表有该主控指南 |
| `powerPins` / `signalPins` | 电源/信号引脚 | 以模块丝印和指南为准 |

`hardware validate` 用这些字段算电流预算、电平匹配和接口冲突；不要用模型心算替代。

### verificationStatus

| 值 | 含义 | 可否说“已验证” |
|---|---|---|
| `OFFICIAL_DOC_VERIFIED` | 官方文档逐项核对 | 可以，标注文档来源 |
| `SOURCE_VERIFIED` / `SOURCE_VERIFIED_WITH_MECHANICAL_CONFLICT` | 来源核对；后者有机械冲突 | 只能说明来源核对；冲突必须转述 |
| `OFFICIAL_API_REFERENCE_UNTESTED` | API 参考核对，未跑 | 不可以 |
| `REQUIREMENT_VERIFIED` | 需求/约束核对 | 只对需求成立 |
| `MIGRATED_UNVERIFIED` / `UNVERIFIED` | 未验证 | 不可以 |

保存、编译、`code check`、串口回读都不等于实物测量。除非用户明确说“我实测过”，否则保留“未联调/待实物验证”。

### rules

`compatibility-rules.md` 的 `zhangwen:hardware-rules:v1` 块给出结构化规则（电压范围、电流、接口、引脚、机械等）。`zw hardware validate` 会把这些规则和主控规则合并执行；不要跳过。

## 模块指南

`references/integration.md` 内嵌按主控的指南（当前 253 份）。`zw hardware guide <id> --board B` 渲染：

- `fields`：指南允许用户选择的参数（引脚、地址、模式等）。`--set` 只能取这些值。
- `connections`：信号 → 主控引脚，含 `{{占位符}}`，CLI 已渲染。
- `wiring`：`connections` 的渲染结果，额外带 `targetLabel`（人读标签，如 `P0（直连）`）；`target` 保留固件原始值（如 `0`），用于对照代码。给人看时用 `targetLabel`。
- `notes`、`sources`、`codeTemplate`：注意事项、来源、示例代码。
- `i2c`：可用时给出地址/总线信息。
- `verification`：包级状态与该主控是否在 `verifiedBoardIds` 中。

指南不存在时 `zw` 返回 exit 3 并列出该包支持的主控；不要跨主控硬套。每个资料包对每块主控最多一条指南；`--kind functional|diagnostic|reference` 是断言，种类不符时 exit 4 `GUIDE_KIND_MISMATCH`，不会在多条指南中猜测。

`zw hardware get --full` 已包含 `i2c`、`verifiedBoardIds`、`supportedBoardIds`、`localExamples` 和指南摘要（`boardId/kind/title/summary`）；不再需要额外命令读取这些字段。

## 选型流程

1. `zw hardware search <关键词> --board <板> --json`
2. 看 `recommended`、`boardSpecific`、`verificationStatus`、`warnings`；有多个包时说明差异。
3. `zw hardware get <id> --json` 看电气、机械、规则、媒体。
4. `zw hardware guide <id> --board <板> --json` 拿接线和示例。
5. `zw hardware validate <板> <id...> --json`，必须通过（或明确列出 FAIL 并停止）。
6. 写代码；`zw code check`；需要上板时转 `pyrcli`。

## 机械与媒体

- `mechanical` 来自 `references/mechanical.md`：尺寸、孔位、安装方式。`SOURCE_VERIFIED_WITH_MECHANICAL_CONFLICT` 表示来源之间有冲突，不能当作确定尺寸。
- **覆盖率很低**：260 个包中只有 5 个有 `references/mechanical.md`（K10、DFR0026、SEN0388、RDK-X5、LabPlus ESP32S3），其中只有 K10 包实际给出结构化 `mechanicalProfile`。`zw enclosure` 需要完整 profile；缺数据时返回 exit 4 `NEEDS_INPUT`，必须让用户补尺寸或提供 inline profile，**不要猜**。
- `zw enclosure` 可直接使用 5 个 trusted profile（`unihiker_k10`、`unihiker_ultrasonic_distance_sensor`、`xiao_esp32s3`、`grove_oled_096`、`grove_button`），不需要资料包里有机械档案。详见 `references/enclosure.md`。
- `media` 给 `localPath`（文件存在时）；只引用路径，不复制、不打包。
- 可选 `models/cadquery.py` 是包内 CAD 模型；先用 `hardware get --file models/cadquery.py` 查看，不要直接执行未审阅的第三方代码。
