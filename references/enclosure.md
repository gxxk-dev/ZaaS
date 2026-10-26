# 确定性外壳管线（`zw enclosure`）

`zw enclosure` 是上游掌问 `zhangwen.cad_engine` 的薄包装：把“已选硬件 + 安装面”解析成 `CadBuildSpec`，补上引擎没有的自动盒体尺寸，再调用引擎的 `resolve_layout()` → `validate_design()` → `build_cad_artifacts()` 生成 STEP/STL/GLB。

- 不调用模型 API，不跑 Node，不刷新缓存，不写 `$ZW_HOME`。
- `plan` 只读，不需要 CadQuery；`build` 需要 CadQuery/OCP。
- 产物是**名义几何**：引擎只做 AABB/参数校验，不做打印公差、材料收缩、强度、防水或实物装配验证。
- 请求管线只包装 `box_with_lid` 与 `component_mount`；`freeform_structure` / `unihiker_k10_photo_album` 用 `--spec` 直接构建。

## 命令

```bash
zw enclosure profiles [--json]
zw enclosure plan  --request FILE|- [--json]
zw enclosure build --request FILE|- --out DIR [--json]
zw enclosure build --spec FILE|-   --out DIR [--json]
```

| 命令 | 写盘 | 依赖 | 说明 |
|---|---|---|---|
| `profiles` | 无 | pydantic + `zhangwen.cad_engine` | 列出 trusted 与资料包机械 profile；不读取 legacy 几何资料库 |
| `plan` | 无 | pydantic + `zhangwen.cad_engine` | 解析请求、自动尺寸、布局与校验；返回最终 spec |
| `build --request` | 只写 `--out` | 再加 CadQuery/OCP | 规划后构建全套产物，并写 `spec.json` |
| `build --spec` | 只写 `--out` | 再加 CadQuery/OCP | 直接构建已确认/微调过的 `CadBuildSpec` |

`profiles` 输出 `count/profiles`。每项给 `profileId/displayName/category/roles/source/revision/dimensions/mounting/modelKind`；资料包来源另有 `componentId/skillName/verificationStatus/ambiguous/shadowed`。`ambiguous: true` 表示同一 `profile_id` 在多个资料包中内容不一致，`enclosure` 会拒绝该 id。`shadowed: true` 表示该 id 已被 trusted profile 覆盖，资料包条目只作参考。`verificationStatus` 是包级声明，不等于实测。

旧版 `services/structure-cad/server/data/hardware-library.json` 的几何资料**不是** `HardwareProfile`，`enclosure` 不读取它；本命令也不会混入这些条目。需要查看旧资料库时用只读的 `zw structure library`（见 `references/cad.md`），不要把旧资料库当作可用的安装 profile。

`--out` 必须不存在或为空；**没有 `--force`**，也不允许 `--allow-in-repo`。`resolve_out` 会拒绝非空目录和 `$ZW_HOME` 内的路径（exit 6）。

## 请求 schema（`zw.enclosure-request/v1`）

```json
{
  "schema": "zw.enclosure-request/v1",
  "design_id": "k10_sensor_box",
  "template": "box_with_lid",
  "auto_size": true,
  "enclosure": {"wall_thickness": 2.4, "hardware_gap": 5},
  "components": [
    {"profile_id": "xiao_esp32s3", "surface": "base_floor"},
    {"profile_id": "grove_oled_096", "surface": "lid_inner"},
    {"component_id": "hw_seed_unihiker_k10", "surface": "lid_inner", "derive_mount": true},
    {"profile": {"profile_id": "custom_sensor", "source": "declared", "…": "…"}}
  ],
  "standoffs": [],
  "openings": []
}
```

所有请求模型 `extra="forbid"`；未知字段 exit 2 `REQUEST_INVALID`。

| 字段 | 约束 |
|---|---|
| `schema` | 可选；出现时必须是 `zw.enclosure-request/v1` |
| `design_id` | 可选；必须匹配 `^[a-z][a-z0-9_-]{0,63}$`；省略时用 `enclosure` |
| `template` | `box_with_lid`（默认）或 `component_mount` |
| `auto_size` | bool 或对象；只对 `box_with_lid` 生效 |
| `enclosure` | `BoxWithLidParameters` 的 partial；`box_with_lid` 用 |
| `component_mount` | `ComponentMountParameters` 的 partial；`component_mount` 用 |
| `components` | 最多 32 个；每项三选一提供 `profile` / `profile_id` / `component_id` |
| `standoffs` / `openings` | 透传上游同名校验；`component_mount` 不允许 |

`auto_size` 对象：

```json
{
  "enabled": true,
  "axes": ["length", "width", "height"],
  "grid_mm": 0.5,
  "max_iterations": 8,
  "clearance_margin_mm": 0
}
```

`components[]` 可选字段：`instance_id`、`surface`、`center`、`rotation_z_deg`（0/90/180/270）、`include_reference_geometry`、`derive_mount`。显式 `design_id` / `instance_id` 不合法直接 exit 2；自动 ID 做确定性 sanitize 和后缀去重。

### center 语义

| surface | center | 说明 |
|---|---|---|
| `base_floor` / `lid_inner` / `lid_outer` | `[x, y]` | z 由地板/上盖和 standoff 推算 |
| `front_inner` / `back_inner` | `[x, z]` | y 由壁厚和器件厚度推算 |
| `left_inner` / `right_inner` | `[y, z]` | **必须显式给出**；引擎自动行打包在该面轴向不一致 |
| `external` | `[x, y, z]` | 必须显式三维坐标；不会自动推算 |

`external` 硬件必须位于盒体 AABB 之外；否则引擎 `hardware_bounds` 失败（exit 4 `DESIGN_INVALID`）。自动尺寸不会为了“把 external 器件包进去”而增长。

### `box_with_lid` 与 `component_mount`

- `box_with_lid`：多器件；引擎生成底壳、上盖、唇边、4 个螺丝柱和器件开孔/孔位。每个 profile 的 `mounting.mode` 决定它必须放在哪个面。
- `component_mount`：恰好 1 个 component；固定 `external` 放置，生成安装底座 + 压框（产物里仍叫 `lid`）。没有上盖语义，也不做自动尺寸；`center` 省略时补 `x=y=0`、`z = base_thickness + height_z/2`。`auto_size`、`derive_mount` 在该模式下被忽略并 warning。

## Profile 解析优先级

1. inline `profile`：只允许 `source="declared"`、`model_kind="envelope"`；不能占用 trusted profile_id 或资料包已声明的 profile_id（exit 2 `PROFILE_CONFLICT`）。
2. `profile_id` → `cad_engine.trusted_profile()`。内置 5 个：
   `unihiker_k10`、`unihiker_ultrasonic_distance_sensor`、`xiao_esp32s3`、`grove_oled_096`、`grove_button`。
3. `profile_id` → 资料包 `mechanical.md` 中的 `profile_id`。只读扫描 `references/mechanical.md`；同 id 多包内容不一致时 exit 3 `PROFILE_AMBIGUOUS`。
4. `profile_id` 作为 `component_id` fallback。
5. `component_id` → `hardware get` 的 `mechanical`。

**机械数据覆盖率很低**：260 个包中只有 5 个有 `references/mechanical.md`，其中只有 K10 包实际给出 `mechanicalProfile`。其余组件必须提供 inline `profile`，否则：

```text
exit 4 NEEDS_INPUT
error.details.questions = [{field, instance_id, component_id, message, hint}]
```

不要猜尺寸，也不要把电气参数当机械尺寸。

### K10 与 `derive_mount`

K10 的 trusted profile 是 `external_independent_module`，默认只能放在 `external`。请求 `lid_inner` / `base_floor` 等内部面时：

- 未设 `derive_mount`：exit 4 `MOUNT_CONFLICT`。
- 设 `derive_mount: true`：包装层把 profile 复制成 `unihiker_k10_derived_<surface>`，`source=declared`、`model_kind=envelope`、安装策略改为 `none`，并给出 warning。这是**包装层推断**，不是原厂声明，必须实物验证。

`derive_mount` 也可把内部 profile 派生到 `external`（mode 会变成 `external_independent_module`）。派生 profile 的 `mounting.holes` 会保留，可能需要在实物上复核。

### `component_mount` 的孔位陷阱

引擎会检查 profile 的安装孔是否完全落在器件外形内（`component_mount_profile_holes`）。trusted 的 `grove_oled_096` 孔位在 `x=±20` / `y=±10` 的边界上，`abs(center)+radius > half`，因此 **`component_mount` + `grove_oled_096` 会 exit 4**。这是上游 profile 与模板约束的冲突，不要通过改孔位或放宽校验绕过。可用 `xiao_esp32s3`（无孔）或孔位完全在内侧的 profile。

## 自动盒体尺寸

只在 `template=box_with_lid` 且 `auto_size.enabled` 时填补缺失的 `inner_length_x/width_y/height_z`。显式值一律保留；不在 `axes` 中的缺失轴使用引擎默认 100/70/40。

1. **初始估算**（确定性）：
   - 每个水平面（`base_floor` / `lid_inner` / `lid_outer`）按 `(-length, instance_id)` 排序做行打包；`gap=hardware_gap`，边缘留 `max(edge_clearance, profile.mounting.clearance)`。
   - `front_inner` / `back_inner` 也自动行打包；`left_inner` / `right_inner` 拒绝自动打包，要求显式 `center`。
   - 垂直：`base_floor` 最大高度（含 standoff / edge_retainer 支撑）+ `lid_inner` 最大深度 + `hardware_gap` + 0.5mm 安全间隔。
   - 螺丝柱预留：存在水平自动器件且 `lid_fasteners.enabled` 时，`edge_clearance >= edge_inset + post_outer_diameter/2 + max(clearance_margin_mm, 0.5)`；不足时自动抬高并 warning。上盖内有器件时还会预留唇边厚度。
   - 满足引擎参数约束：30/30/12 下界、圆角、唇边、螺丝柱、`corner_radius`；尺寸向上取整到 `grid_mm`。
   - 没有内部组件时回退 100×70×40 并 warning。
2. **Engine-as-oracle 有界增长**：
   - 用 provisional spec 跑 `resolve_layout()` + `validate_design()`。
   - 仅对容量/越界/干涉/开口边缘/支撑间隙类失败增长自动轴；顺序固定 `length → width → height`，最多 `max_iterations` 轮，上限 800/800/400mm。
   - 结构性失败（壁厚、安装完整性、开口-支柱冲突）直接 exit 4 `DESIGN_INVALID`；达到增长上限或触顶则 exit 4 `AUTO_SIZE_LIMIT`。
   - 存在 `external` 器件时，`hardware_bounds` 不自动增长（external 坐标是用户显式给定的）。

自动尺寸是 `zw` 包装层行为，不是上游引擎行为；`plan` 返回的 `autoSize.final` / `iterations` / `warnings` 要转述给用户。

## 产物

引擎固定写：

```text
assembly.step  base.step  base.stl  lid.step  lid.stl  preview.glb
parameters.json  profiles.json  validation.json  geometry-summary.json  manifest.json
```

包装层再写 `spec.json`（最终 `CadBuildSpec`，可再次 `build --spec`）。`component_mount` 的 `lid.step/.stl` 实际是压框。

- `writes` = manifest 文件 + `manifest.json` + `spec.json`。
- 几何阶段失败时，已落盘文件会放进 `error.writes`；不会清理。
- 同一 spec 重复构建的 `manifest.spec_sha256` 应一致（`python3 -m pytest -o addopts="" -m cad` 会检查）。
- STL 保留装配坐标（上盖/压框未归零到 `z=0`）；`keepout` 只校验不挖空；硬件参考体只在 assembly/preview。

## 错误映射

| 情况 | code | exit |
|---|---|---|
| 请求 JSON 非法、未知字段、ID 非法、center 语义错 | `REQUEST_INVALID` / `JSON_INVALID` | 2 |
| `template` 不支持、`component_mount` 组件数≠1 / 带 standoffs/openings / 非 external | `REQUEST_INVALID` | 2 |
| `--spec` 非法、未知模板或 pydantic 校验失败 | `SPEC_INVALID` | 2 |
| `profile_id` / `component_id` 查不到 | `PROFILE_NOT_FOUND` / `HARDWARE_NOT_FOUND` | 3 |
| 同 profile_id 内容冲突 / 多包歧义 | `PROFILE_CONFLICT` / `PROFILE_AMBIGUOUS` | 2 / 3 |
| 包存在但无 `mechanicalProfile`、left/right 缺 center、external 缺 center | `NEEDS_INPUT` | 4 |
| external-only profile 放腔内且未 derive | `MOUNT_CONFLICT` | 4 |
| 自动尺寸超限 / 引擎校验 FAIL | `AUTO_SIZE_LIMIT` / `DESIGN_INVALID` | 4 |
| 引擎 `CadDesignRejected` / `CadGeometryRejected` / 几何 ValueError | `DESIGN_INVALID` / `GEOMETRY_INVALID` | 4 |
| 缺 `zhangwen.cad_engine` / CadQuery / OCP | `DEPENDENCY_MISSING` / `CAD_RUNTIME_MISSING` | 5 |
| out 非空 / 在 `$ZW_HOME` 内 | `OUT_NOT_EMPTY` / `OUT_IN_REPO` | 6 |
| IO / 未知异常 | `BUILD_IO_FAILED` / `BUILD_FAILED` | 7 |

## 示例

```bash
# 多器件盒子：自动尺寸，只读规划
zw enclosure plan --request - --json <<'JSON'
{"design_id":"xiao_oled_box","components":[
  {"profile_id":"xiao_esp32s3","surface":"base_floor"},
  {"profile_id":"grove_oled_096","surface":"lid_inner"}
],"auto_size":true}
JSON

# 单器件安装座
zw enclosure plan --request - --json <<'JSON'
{"design_id":"xiao_mount","template":"component_mount",
 "components":[{"profile_id":"xiao_esp32s3"}]}
JSON

# 构建，再回建
zw enclosure build --request request.json --out ./enc-out --json
zw enclosure build --spec ./enc-out/spec.json --out ./enc-out-2 --json

# 直接构建四个上游模板之一
zw enclosure build --spec spec.json --out ./direct-out --json

# 上游固定 K10 相册支架（无 enclosure/components/freeform）
zw enclosure build --spec - --out ./album-out --json <<'JSON'
{"design_id":"k10_photo_album",
 "template":"unihiker_k10_photo_album",
 "template_revision":"unihiker-k10-photo-album.v1"}
JSON
```

`unihiker_k10_photo_album` 与打包的 `photo-stand` 是不同几何；后者用 `zw structure template photo-stand`，前者只能用 `--spec` 整体构建。

## 限制

- 只做 AABB/参数校验：不检查线缆弯折、卡扣、壁厚实测、打印方向、螺钉长度或装配顺序。
- 机械数据覆盖率低；大多数器件需要用户提供 inline profile。
- `derive_mount` 与 `component_mount` 的 external 中心是推断/显式输入，必须实物验证。
- 左侧/右侧自动打包被禁用（上游引擎轴向 bug）；必须给 `center=[y,z]`。
- STL 上盖/压框未归零；v1 只 warning，不做后处理。
- `cad_engine` 属于掌问 1021；旧版缺失时 exit 5，先升级掌问。
