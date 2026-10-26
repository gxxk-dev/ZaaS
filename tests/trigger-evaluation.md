# 触发边界清单（24 条）

用于人工检查 `zhangwen` 与 `handpy` 的技能选择边界。实际触发由模型按 description 判断，本表是验收基准，不是自动化测试。

| # | 查询 | 期望 | 理由 |
|---|---|---|---|
| 1 | 掌问里有没有 DFR0026 光照传感器的接线？ | zhangwen | 掌问资料包 + 模块指南 |
| 2 | K10 接 DFR0026，帮我校验电压和电流 | zhangwen | 电气校验 |
| 3 | 从掌问硬件库选一个 I2C 温湿度模块 | zhangwen | 硬件检索/选型 |
| 4 | 给掌控板 2.0 写个 OLED 显示光照的程序 | handpy | 独立 mPython 板级 API |
| 5 | 用掌问的模块指南给 mPython 2.0 接 DFR0026 | zhangwen | 掌问指南 + 接线 |
| 6 | 检查这段 K10 屏幕代码为什么没显示 | zhangwen | K10 板级检查 |
| 7 | 掌控板 3.0 的 lcd 怎么画圆 | handpy | mPython v3 显示 API |
| 8 | 掌问能生成激光切割的榫齿盒吗 | zhangwen | 激光模板 |
| 9 | 画一个 80×60×40 的亚克力盒切割图 | zhangwen | 激光图纸 |
| 10 | 改一下掌问的掌控板外壳，背面刻字 | zhangwen | 固定模板改造 |
| 11 | 用 CadQuery 做个简单的盒子 | 不触发 | 通用 CAD，未要求掌问模板 |
| 12 | pyrcli 怎么把 main.py 传到板子 | 不触发 | 纯设备工具问题，查 pyrcli 文档 |
| 13 | HandPy v2 的 SIoT 怎么用 | handpy | HandPy 专属模块 |
| 14 | mPython 3 的 LVGL 页面切换 | handpy | mPython v3 LVGL |
| 15 | 掌问硬件库里有没有舵机 | zhangwen | 硬件检索 |
| 16 | K10 和 XIAO ESP32S3 的引脚差异 | zhangwen | 5 块主控板级资料 |
| 17 | 帮我验证 DFR0026 和 K10 的电气兼容性 | zhangwen | 电气规则校验 |
| 18 | 掌问的 3D 模板有哪些参数 | zhangwen | `--list-params` |
| 19 | ESP32-C3 通用板怎么点灯 | zhangwen | 掌问主控档案内的 C3 |
| 20 | 掌问项目怎么启动 Web 工作台 | 不触发/说明不在范围 | v1 不做 Web UI |
| 21 | 校验本地 K10 固件镜像的 sha256 | zhangwen | `firmware verify`，只读比对 |
| 22 | K10 代码里的 screen.text 能不能自动修 | zhangwen | `code fix` 确定性修复 |
| 23 | 用掌问做个带刻字的 freeform 支架 | zhangwen | freeform 请求 + 文字操作 |
| 24 | 掌问的 legacy 几何资料库有哪些传感器 | zhangwen | `structure library` 只读目录 |

## 边界说明

- **zhangwen** 的触发词：掌问、ZhangWen、硬件资料包、选型、接线、电气校验、模块指南、固件校验、板级 Skill、代码检查/修复、激光切割、3D 模板/外壳改造、freeform 声明式实体/刻字、legacy 几何资料库。
- **handpy** 的触发词：HandPy、mPython 板级 API、OLED/LCD/LVGL、内置传感器、SIoT、舵机、语音等模块。
- 第 4、5 条是最容易混的：只要用户要的是“掌问资料包里的接线/选型/校验”，走 zhangwen；只要用户要的是“HandPy/mPython 的 API 用法”，走 handpy。
- 第 11、12、20 条用于确认不会过度触发；掌问 skill 不替代通用 CadQuery 教程、pyrcli 文档或 Web 工作台。
