# freeform 声明式实体

`zw structure freeform` 把一个小型 JSON 配方翻译成掌问 `cad_engine` 的
`CadBuildSpec(template="freeform_structure", template_revision="freeform-structure.v1")`。
它适合没有固定模板、也没有机械 profile 的自定义支架/底座；带开孔和上盖的外壳用
`zw enclosure`，固定模板改造用 `zw structure template --edit`。

- `plan` 只校验请求、布局、引擎设计规则和文字字段，**不需要 CadQuery**。
- `build` 才调用 CadQuery/OCP 生成 STEP/STL/GLB，并应用文字刻字/浮雕。
- 主要用途是让 Claude 只写声明式 JSON；CLI 不执行模型生成的 Python。

## 命令

```bash
zw structure freeform plan  --request FILE|- --json
zw structure freeform build --request FILE|- --out DIR --json
zw structure freeform build --spec FILE|-   --out DIR --json
```

- `--request` 与 `--spec` 互斥，且 `build` 必须提供其中之一；否则 exit 2 `REQUEST_INVALID`。
- `plan` 只读，走 core 依赖；`build` 走 CAD 依赖。
- `--out` 必须为空或不存在；没有 `--force`，位于 `$ZW_HOME` 内时拒绝（exit 6）。
- `plan` 的 warning 明确说明：连通性、`cut` 是否与实体相交只有 `build` 才能确认。产物是名义几何，未做打印公差/强度/实物装配验证。

## 请求 schema `zw.freeform-request/v1`

```json
{
  "schema": "zw.freeform-request/v1",
  "design_id": "sensor_stand",
  "operations": [
    {"primitive_id": "base", "op": "add", "shape": "rounded_box",
     "size": [60, 40, 6], "center": [0, 0, 3], "corner_radius": 4},
    {"primitive_id": "post", "op": "add", "shape": "cylinder",
     "diameter": 8, "height": 30, "center": [0, 0, 20.9]},
    {"primitive_id": "hole", "op": "cut", "shape": "cylinder",
     "diameter": 4, "height": 10, "center": [0, 0, 25]}
  ]
}
```

顶层只允许 `schema` / `design_id` / `operations`。

| 字段 | 约束 |
|---|---|
| `schema` | 可省略，默认 `zw.freeform-request/v1`；出现时必须完全一致 |
| `design_id` | `^[a-z][a-z0-9_-]{0,63}$`，默认 `freeform_structure` |
| `operations` | 1–32 个；几何操作按顺序布尔，文字操作在全部几何之后按顺序应用；第一个**几何**操作必须是 `add` |

### 操作字段

| 字段 | 约束 |
|---|---|
| `primitive_id` | 必填，`^[a-z][a-z0-9_-]{0,63}$`，全局唯一 |
| `op` | `add` / `cut` |
| `shape` | `box` / `rounded_box` / `cylinder` / `text` |
| `center` | 必填，`[x, y, z]` 三个有限数值（毫米） |
| `rotation_z_deg` | `0` / `90` / `180` / `270`，默认 0；`cylinder` 只允许 0 |
| `role` | `body` / `pcb` / `connector` / `sensor` / `feature`，默认 `body` |

形状字段：

| `shape` | 必填 | 可选 | 不允许 |
|---|---|---|---|
| `box` | `size: [x, y, z]` | `rotation_z_deg` | `corner_radius`、`diameter`、`height` |
| `rounded_box` | `size: [x, y, z]` | `corner_radius`（默认 0）、`rotation_z_deg` | `diameter`、`height` |
| `cylinder` | `diameter`、`height` | — | `size`、`corner_radius`、非零 `rotation_z_deg` |

### 文字操作

```json
{"primitive_id": "label", "op": "cut", "shape": "text", "text": "掌问",
 "font_size": 8, "depth": 0.6, "center": [0, 0, 6], "face": "top", "angle": 0}
```

| 字段 | 约束 |
|---|---|
| `primitive_id` | 与几何操作共用命名空间，全局唯一 |
| `op` | `cut`（凹刻）/ `add`（浮雕） |
| `text` | 1–20 个字符；使用随包 NotoSansSC，字体缺字直接报错 |
| `font_size` | 2–80（实际字高 mm） |
| `depth` | 0.1–10（刻入/凸出深度 mm），应小于所在板厚 |
| `center` | `[x, y, z]`，文字平面中心 |
| `face` | `top` / `bottom` / `front` / `back` / `left` / `right` |
| `angle` | 面内旋转，−360–360，默认 0 |

- 文字操作在**所有几何 primitive 之后**按请求中的相对顺序应用；即使与几何操作交错，也不会改变几何布尔顺序。
- 文字宽度上限 300mm；`plan` 会加载随包字体检查缺字与轮廓，不需要 CadQuery。
- `build` 时每次 `cut` 必须减少体积、`add` 必须增加体积，否则 exit 4 `TEXT_NO_EFFECT`；每次操作后必须仍是单一连通实体。
- 请求至少要有一个几何操作；只有文字不能构成实体。
- 文字坐标是建模坐标，不是打印坐标；写出前确认面方向与深度。

任何未声明的字段、类型错误、非有限数值、重复 ID、首个**几何**操作为 `cut` 都返回 exit 2
`REQUEST_INVALID`，并在 `details` 中给出具体 `primitive_id` / 字段 / 未知键。文字内容、字体缺字、
尺寸范围等由上游 `TextOperation` 校验，失败返回 exit 4 `TEXT_INVALID`。

## plan 输出

```json
{
  "design_id": "sensor_stand",
  "template": "freeform_structure",
  "template_revision": "freeform-structure.v1",
  "spec": {"...": "CadBuildSpec"},
  "layout": {"...": "resolve_layout 结果"},
  "validation": {"ok": true, "checks": []},
  "textOperations": []
}
```

`textOperations` 是规范化后的文字操作（camelCase 字段）；没有文字时为空数组。
同一请求运行两次，`spec`、`validation` 与 `textOperations` 必须完全一致。`validation.ok=false` 时
exit 4 `DESIGN_INVALID`，`details.validation` 给出失败项；文字校验失败 exit 4 `TEXT_INVALID`。

## build 输出与 spec 回建

`--request` 模式先按 `plan` 的规则校验，再构建；产物由引擎 manifest 决定，另写：

| 文件 | 内容 |
|---|---|
| `spec.json` | `{"schema":"zw.freeform-spec/v1","spec":<CadBuildSpec>,"textOperations":[...]}` |
| `request.json` | 规范化后的请求（不是原始输入文本；`--spec` 模式不写） |

`textOperations` 保存规范化后的文字操作，因此带文字的设计也能从 `spec.json` 回建。
`build --spec ./out/spec.json` 可以复现同一构建，`specSha256` 和体积不变。
`specSha256` 是上述包装的 canonical JSON（`sort_keys`、紧凑分隔符、UTF-8）的
SHA-256；`manifest.json` 的 `spec_sha256` 与响应中的 `specSha256` 必须一致。
响应还包含 `files`、`manifest`、`validation`、`geometrySummary`、`spec`、`request`。

## 错误映射

| 情况 | code | exit |
|---|---|---|
| 请求字段/ID/范围错误 | `REQUEST_INVALID` | 2 |
| `--spec` 包装或模板/revision 不符 | `SPEC_INVALID` | 2 |
| 引擎设计校验失败 | `DESIGN_INVALID` | 4 |
| 几何构建/导出校验失败、布尔无效 | `GEOMETRY_INVALID` | 4 |
| 文字无效/字体缺字/文字宽度超限 | `TEXT_INVALID` | 4 |
| 文字布尔无体积变化 | `TEXT_NO_EFFECT` | 4 |
| 缺 CadQuery/OCP | `CAD_RUNTIME_MISSING` | 5 |
| 缺随包字体 | `DEPENDENCY_MISSING` | 5 |
| 输出目录非空或在 `$ZW_HOME` 内 | `OUT_NOT_EMPTY` / `OUT_IN_REPO` | 6 |
| 写入产物失败 | `BUILD_IO_FAILED` | 7 |
| 其他上游异常 | `BUILD_FAILED` | 7 |

`build` 仍可能因“未形成单一连通实体”“`cut` 未与实体相交”“`cut` 删空实体”失败；
`plan` 通过不代表几何可构建。
