# freeform 声明式实体

`zw structure freeform` 把一个小型 JSON 配方翻译成掌问 `cad_engine` 的
`CadBuildSpec(template="freeform_structure", template_revision="freeform-structure.v1")`。
它适合没有固定模板、也没有机械 profile 的自定义支架/底座；带开孔和上盖的外壳用
`zw enclosure`，固定模板改造用 `zw structure template --edit`。

- `plan` 只校验请求、布局和引擎设计规则，**不需要 CadQuery**。
- `build` 才调用 CadQuery/OCP 生成 STEP/STL/GLB。
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
| `operations` | 1–32 个；按顺序布尔；第一个必须是 `add` |

### 操作字段

| 字段 | 约束 |
|---|---|
| `primitive_id` | 必填，`^[a-z][a-z0-9_-]{0,63}$`，全局唯一 |
| `op` | `add` / `cut` |
| `shape` | `box` / `rounded_box` / `cylinder` |
| `center` | 必填，`[x, y, z]` 三个有限数值（毫米） |
| `rotation_z_deg` | `0` / `90` / `180` / `270`，默认 0；`cylinder` 只允许 0 |
| `role` | `body` / `pcb` / `connector` / `sensor` / `feature`，默认 `body` |

形状字段：

| `shape` | 必填 | 可选 | 不允许 |
|---|---|---|---|
| `box` | `size: [x, y, z]` | `rotation_z_deg` | `corner_radius`、`diameter`、`height` |
| `rounded_box` | `size: [x, y, z]` | `corner_radius`（默认 0）、`rotation_z_deg` | `diameter`、`height` |
| `cylinder` | `diameter`、`height` | — | `size`、`corner_radius`、非零 `rotation_z_deg` |

任何未声明的字段、类型错误、非有限数值、重复 ID、首个 `cut` 都返回 exit 2
`REQUEST_INVALID`，并在 `details` 中给出具体 `primitive_id` / 字段 / 未知键。

## plan 输出

```json
{
  "design_id": "sensor_stand",
  "template": "freeform_structure",
  "template_revision": "freeform-structure.v1",
  "spec": {"...": "CadBuildSpec"},
  "layout": {"...": "resolve_layout 结果"},
  "validation": {"ok": true, "checks": []}
}
```

同一请求运行两次，`spec` 与 `validation` 必须完全一致。`validation.ok=false` 时
exit 4 `DESIGN_INVALID`，`details.validation` 给出失败项。

## build 输出与 spec 回建

`--request` 模式先按 `plan` 的规则校验，再构建；产物由引擎 manifest 决定，另写：

| 文件 | 内容 |
|---|---|
| `spec.json` | `{"schema":"zw.freeform-spec/v1","spec":<CadBuildSpec>,"textOperations":[]}` |
| `request.json` | 规范化后的请求（不是原始输入文本） |

无文字操作时，`build --spec ./out/spec.json` 可以复现同一构建，`specSha256` 不变。
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
| 缺 CadQuery/OCP | `CAD_RUNTIME_MISSING` | 5 |
| 输出目录非空或在 `$ZW_HOME` 内 | `OUT_NOT_EMPTY` / `OUT_IN_REPO` | 6 |
| 写入产物失败 | `BUILD_IO_FAILED` | 7 |
| 其他上游异常 | `BUILD_FAILED` | 7 |

`build` 仍可能因“未形成单一连通实体”“`cut` 未与实体相交”“`cut` 删空实体”失败；
`plan` 通过不代表几何可构建。
