# Python CAD

`zw structure` 有三类输入：**固定模板**（可参数化、可受约束改造）、**design-spec 模板**（`box`/`cup`/`bracket` 的确定性实体）和**参数化实体**（box/cylinder/sphere 的加料/挖料）。三者都只输出名义几何，不做打印公差、材料收缩或强度校验。

由已选硬件自动生成“带开孔、上盖和螺丝柱的封闭盒子”，或单器件安装座，用 `zw enclosure`（见 `references/enclosure.md`），不要用 `structure solid` 手拼。`structure solid` 保留给没有机械 profile 的自定义 CSG。

## 模板目录

```bash
zw structure templates --json
```

只读列出 8 个模板：5 个打包固定模板（`source: "packaged"`）和 3 个 design-spec 模板（`source: "design-spec"`）。每项包含 `id/title/description/revision/size/notes/parts/parameters/image/sha256/assets`。`parameters[].default` 是模板默认值；打包模板的参数名与 `--list-params` 一致。该命令不需要 CadQuery。

## legacy 几何资料库（只读）

```bash
zw structure library [--category C] [--query Q] --json
zw structure library <profile_id> --json
```

直接读取 `$ZW_HOME/services/structure-cad/server/data/hardware-library.json`。这是 structure-cad 服务侧的旧 Node 资料，**不是** `cad_engine` 的 `HardwareProfile`，`enclosure` 不会读取它。

- 列表返回 `count/profiles/source`，每项保留原始 snake_case 字段：`id/name/category/roles/dimensions_mm/thumbnail_url/source_status/integration_status`。
- `dimensions_mm` 原样输出；不同类别的键不同，不能假设一定有 `length_x/width_y/height_z`。
- 单条返回完整原始 profile、`library: {version, units, coordinateSystem, migration}` 和 `source: "legacy-hardware-library"`。
- `--category` 精确匹配 `category`（不区分大小写）；`--query` 对 `id`/`name` 做不区分大小写的子串匹配。两者可同用；与 `<profile_id>` 互斥，同用 exit 2 `REQUEST_INVALID`。
- 文件缺失 exit 5 `LIBRARY_MISSING`；JSON/schema 损坏或 profile id 重复 exit 7 `LIBRARY_INVALID`；id 不存在 exit 3 `PROFILE_NOT_FOUND`；过滤无匹配 exit 0、`count: 0` + warning。
- 每次响应都带 warning：legacy 只读、未经 `HardwareProfile` 校验、同名 id 以 `zw enclosure profiles` 为准。资料条数以本机安装为准，不写死 32。

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
- `photo-stand`（57 项）：底座、斜面角度/长度/厚度、夹持片、侧块、后斜面块、方孔、半圆止挡及一系列圆角参数。多数 `stage_*` 是建模细节，非必要不改。源码另有 6 个含 `epsilon`/`overlap` 的顶层数值，按规则不开放修改。
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

`structure solid` 接受 `--spec`（完整 DesignSpec）或 `--template`（确定性模板），二者互斥且必须提供一个。模板参数可用 `--params` 内联 JSON、`@file.json` 或 `-`。

### design-spec 模板

```bash
zw structure solid --template box \
  --params '{"width":40,"depth":30,"height":20,"thickness":3}' \
  --out DIR --json
```

| id | 形状 | 参数 |
|---|---|---|
| `box` | 开口收纳盒 | `width`/`depth`/`height`/`thickness`，默认 80/60/40/3 |
| `cup` | 圆柱笔筒 | 同上；`width` 是外径，`depth` 不使用 |
| `bracket` | L 形支架 | 同上；底板 + 立板一体 |

- 参数白名单只有 `width/depth/height/thickness`；未知参数 exit 4 `PARAM_INVALID`。
- 尺寸必须大于两倍板厚，板厚 0.8–30mm；违反时 exit 4 `PARAM_INVALID`。
- 未知模板 exit 3 `TEMPLATE_NOT_FOUND`。
- 输出与 `--spec` 相同：`model.step`、`model.stl`、`design-spec.json`、`cadquery.py`。
- `cup` 的 `depth` 不参与几何；不要用它表达直径。

### 自定义 DesignSpec

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

### 上游固定几何 `unihiker_k10_photo_album`

上游还有一个不走 `DesignSpec` 的固定 K10 相册支架。用 `zw enclosure build --spec` 直接构建：

```json
{
  "design_id": "k10_photo_album",
  "template": "unihiker_k10_photo_album",
  "template_revision": "unihiker-k10-photo-album.v1"
}
```

该模板不能带 `enclosure`、`component_mount`、`freeform_geometry`、`standoffs`、`openings`、`profiles` 或 `hardware`。它和打包的 `photo-stand` 模板是两套不同几何：`photo-stand` 走 `structure template`，可改 57 个顶层参数；`unihiker_k10_photo_album` 是上游固定件，只能整体构建。

## 输出与声明

两类命令都会给出 `size`、`volume`/`solids` 和 `warnings`。必须向用户转述：

- 名义几何；未做打印公差、材料收缩、装配或强度验证。
- 几何有效不等于可打印、可承重。
- 固定模板改造沿用原模板孔位；参数改动可能影响未显式检查的配合。
