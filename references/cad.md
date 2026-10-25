# Python CAD

`zw structure` 有两类输入：**固定模板**（可参数化、可受约束改造）和**参数化实体**（box/cylinder/sphere 的加料/挖料）。两者都只输出名义几何，不做打印公差、材料收缩或强度校验。

## 固定模板

5 个模板来自掌问 `services/structure-cad/templates/manifest.json`，源码用 sha256 锚定。模板升级后 `revision`/`sha256` 变化会让 `--edit` 明确失败；此时重新跑 `--list-params` 并同步本文档。

| id | 标题 | 部件（printable） | 典型用途 |
|---|---|---|---|
| `mpython-shell` | 掌控板 3.0 外壳 | `bottom` 底壳（true）、`cover` 上盖（true） | 屏幕开孔、麦克风孔、螺丝柱、背面刻字 |
| `photo-stand` | K10 相册支架 | `stand` 相册支架（true）、`k10` 参考件（false）、`battery` 参考件（false） | K10 斜立支架；参考件只用于装配检查 |
| `servo-side` | 侧式舵机固定座 | `mount`（true） | 侧装舵机 |
| `servo-horizontal` | 卧式舵机固定座 | `mount`（true） | 平放舵机 |
| `servo-vertical` | 立式舵机固定座 | `mount`（true） | 立装舵机 |

查看可改参数：

```bash
zw structure template mpython-shell --list-params --json
```

`parameters[].name` 是唯一允许出现在 `parameterOverrides` 中的键。只识别模板**顶层** `NAME = 数字` 赋值；函数体内部尺寸、字符串/元组常量、以下划线开头或名字含 `epsilon`/`overlap` 的项不可改。

### 模板参数概览

- `mpython-shell`（30 项）：内腔 `inner_size_x/y/height_z`、`wall_thickness`、`bottom_thickness`、`outer_corner_radius`、固定块 `fixing_block_*`、螺丝柱 `screw_boss_*`、上盖 `top_cover_thickness`、屏幕/麦克风/光敏/ LED 开口、上盖螺丝孔与沉孔。
- `photo-stand`（58 项）：底座、斜面角度/长度/厚度、夹持片、侧块、后斜面块、方孔、半圆止挡及一系列圆角参数。多数 `stage_*` 是建模细节，非必要不改。
- `servo-side`（12 项）：底座、立墙、开口、固定孔。
- `servo-horizontal`（10 项）：底座、支撑、内侧间隙、侧孔。
- `servo-vertical`（13 项）：底座、支撑、顶孔、槽宽/槽高。

### 生成原模板

```bash
zw structure template mpython-shell --out DIR --json
```

输出每个 printable 部件的 `template-<part>.step` / `.stl`，以及 `cadquery.py`、`template-edit.json`。非打印参考件也可能导出 STL 供装配参考，但不会被 `--edit` 修改。

## 受约束改造（`--edit`）

只改固定模板，不新增模板，不执行模型生成的 Python。Claude 写 `TemplateEditSpec` JSON，CLI 校验后用原模板源码渲染。

```json
{
  "title": "掌控板 3.0 外壳 · 背面凹字",
  "summary": "底壳外底面居中凹刻“掌问”。",
  "questions": [],
  "parameterOverrides": {},
  "partOperations": [
    {
      "partId": "bottom",
      "operations": [
        {
          "kind": "text",
          "operation": "cut",
          "text": "掌问",
          "fontSize": 8,
          "depth": 0.5,
          "center": [0, -0.75, -1.5],
          "face": "bottom",
          "angle": 0
        }
      ]
    }
  ]
}
```

```bash
zw structure template mpython-shell --edit plan.json --out DIR --json
```

### TemplateEditSpec 字段

| 字段 | 约束 |
|---|---|
| `title` | 1–80 字 |
| `summary` | ≤1200 字 |
| `questions` | ≤3 条；非空时 CLI 只提问，exit 4，不生成模型 |
| `parameterOverrides` | 只能使用 `--list-params` 中的名字；≤150 项；有限数值且 \|v\|≤1000；整数参数必须给整数值 |
| `partOperations` | ≤6 个部件；每个 `partId` 只能出现一次；必须是 `printable: true` 部件 |
| `partOperations[].operations` | ≤16 个操作；`SolidPart` 或 `TextOperation` |

`SolidPart`：

| 字段 | 约束 |
|---|---|
| `kind` | `box` / `cylinder` / `sphere` |
| `operation` | `add`（加料）/ `cut`（挖料） |
| `size` | 三轴完整尺寸，0.1–1000；圆柱 X=Y；球三轴相同 |
| `center` | 实体中心，±1000 |
| `rotation` | 绕世界 XYZ 轴角度，±360 |
| `label` | 可选，≤80 字 |

`TextOperation`：

| 字段 | 约束 |
|---|---|
| `kind` | `"text"` |
| `operation` | `add`（浮雕）/ `cut`（凹刻） |
| `text` | 1–20 字，支持中英文；用随包 NotoSansSC 轮廓，不依赖系统字体 |
| `fontSize` | 2–80（实际字高 mm） |
| `depth` | 0.1–10（刻入/凸出深度 mm） |
| `center` | 文字平面中心，±1000 |
| `face` | `top` / `bottom` / `front` / `back` / `left` / `right` |
| `angle` | 面内旋转，−360–360，默认 0 |

### 坐标与布尔规则

- 坐标是**原模板装配坐标**，不是打印坐标。导出时每个部件才归零到 `z=0`。
- 文字 `center` 必须落在目标面上；`depth` 从表面向内（cut）或向外（add）。
- `cut` 必须与原实体相交；`add` 必须与原实体相连。每次布尔后体积不变即报错（exit 4）。
- 刻字深度必须小于所在板厚。例如 `mpython-shell` 底壳背面刻字，`depth` 应小于 `bottom_thickness`（默认 1.5）。
- 圆柱轴沿 Z；`rotation` 依次绕世界 X/Y/Z 旋转，再平移到 `center`。
- 只能改模板顶层数值；不能改函数体内部数值、非数字常量或部件名，也不能用 `structure solid` 重画来绕过（会丢失原模板孔位与装配关系）。

### 错误映射

| 情况 | 退出码 |
|---|---|
| JSON 非法、未知参数、非打印部件、参数超范围 | 2 |
| `questions` 非空 | 4 |
| 布尔无体积变化、切穿/未相交、文字轮廓无效 | 4 |
| 模板 sha256 不符或文件缺失 | 7 |
| 缺 CadQuery/OCP/字体 | 5 |
| 输出目录非空且未 `--force`，或位于 `$ZW_HOME` 未 `--allow-in-repo` | 6 |

## 参数化实体（`structure solid`）

输入是 `DesignSpec` JSON。只接受 3D：`solid` 非空，且第一个操作必须是 `add`；不能带 `drawing`/`fingerBox`/`roundedBox`。激光图纸用 `laser build`。

```json
{
  "title": "K10 收纳盒",
  "summary": "开口盒，壁厚 3mm。",
  "solid": [
    {"kind": "box", "operation": "add", "size": [80, 60, 40], "center": [0, 0, 20]},
    {"kind": "box", "operation": "cut", "size": [74, 54, 40], "center": [0, 0, 23]}
  ]
}
```

```bash
zw structure solid --spec spec.json --out DIR --json
```

- 最多 32 个实体；`size` 0.1–1000，`center` ±1000，`rotation` ±360。
- `cylinder` 的 X=Y 是直径，Z 是高度；`sphere` 三轴直径相同。
- 可选包装 `{"spec": {...}, "scale": 1.2}`；`scale` 0.1–5，只缩放几何，不改 JSON 中的名义尺寸。
- `questions` 非空 → exit 4。
- 输出 `model.step`、`model.stl`、`design-spec.json`、`cadquery.py`。

## 输出与声明

两类命令都会给出 `size`、`volume`/`solids` 和 `warnings`。必须向用户转述：

- 名义几何；未做打印公差、材料收缩、装配或强度验证。
- 几何有效不等于可打印、可承重。
- 固定模板改造沿用原模板孔位；参数改动可能影响未显式检查的配合。
