# 激光切割图纸

`zw laser build` 用掌问的 5 个确定性模板生成 SVG/DXF，`zw laser text` 生成单行文字雕刻图纸。输出是**名义尺寸**，不做刀缝补偿、材料弯折或装配验证。

## 命令

```bash
zw laser build --template <id> --params '<JSON>' --out DIR [--force] [--json]
zw laser text --text "掌问" [--size MM] [--margin MM] [--out DIR] [--force] [--json]
zw laser templates --json
```

`--params` 也可以是 `@file.json`。未知参数直接 exit 2，不会静默忽略。

`laser text` 默认只读；给 `--out` 才写 `cut.svg`、`preview.svg`、`cut.dxf`、`design.json`。字体固定为随包 `NotoSansSC.ttf`，只支持 1–40 个可显示字符，只雕刻、不切穿；`--size` 是实际字高（1–150mm，默认 10），`--margin` 默认 5mm。`--force`/`--allow-in-repo` 只能与 `--out` 同用。

`laser templates` 只读列出 5 个模板的 id、标题、说明、参数默认值和 `patternVersions`。

输出：

- `cut.svg`：切割/雕刻路径，1:1 毫米。
- `preview.svg`：带底色的预览。
- `cut.dxf`：AutoCAD 2000 ASCII，单位毫米，图层 `CUT`/`ENGRAVE`。
- `design.json`：`zw.laser/v1`，含模板、解析后的参数、完整 `Drawing` 和声明。

## 5 个模板

### `plate` 矩形挂牌

| 参数 | 默认 | 约束 |
|---|---|---|
| `width` | 80 | ≥16 mm（与 `depth` 取小） |
| `depth` | 60 | ≥16 mm |
| `thickness` | 3 | 0.8–30 |

画布 `width+10` × `depth+10`，外轮廓距边 5mm，左上角有直径 4mm 挂孔。

### `round-tag` 圆形挂牌

| 参数 | 默认 | 约束 |
|---|---|---|
| `width` | 80 | ≥16 mm（直径） |
| `thickness` | 3 | 0.8–30 |

画布 `width+10` 正方形；外圆半径 `width/2`，顶部有直径 4mm 挂孔。

### `panel-box` 胶合收纳盒板件

| 参数 | 默认 | 约束 |
|---|---|---|
| `width` / `depth` / `height` | 80 / 60 / 40 | > 2×`thickness` |
| `thickness` | 3 | 0.8–30 |

五块板平铺：底板、两长边、两短边，按板厚扣除搭接。**对接胶合，不是榫卯**；标题和说明里不要写“榫齿/指接”。

### `finger-box` 六面榫齿盒

| 参数 | 默认 | 约束 |
|---|---|---|
| `width` / `depth` / `height` | 80 / 60 / 40 | 每个外尺寸 ≥ 6×`thickness`，且 > 2×`thickness` |
| `thickness` | 3 | 0.8–30 |
| `material` | `待确认材料` | ≤80 字 |
| `panelTexts` | `[]` | ≤16 项 |

`panelTexts` 每项：

```json
{"panel": "front", "x": 6, "y": 10, "text": "掌问", "fontSize": 10}
```

- `panel`：`left`/`right`/`front`/`back`/`bottom`/`top`。
- `x`/`y` 相对该面板左上角，单位 mm；文字必须完全落在四边各扣一倍板厚的矩形内。
- 文字只能雕刻，不能切穿；每项 ≤40 字。

平台生成六块互补榫齿轮廓；不要用六个矩形或圆孔冒充榫卯。

### `rounded-box` 圆角弯折盒

| 参数 | 默认 | 约束 |
|---|---|---|
| `width` / `depth` / `height` | 50 / 50 / 50 | 宽深 ≥ 8×`thickness`；高 ≥ 4×`thickness` + 4×`slot_bridge` |
| `thickness` | 3 | 0.8–12 |
| `corner_radius` | 12 | ≥ 2×`thickness`，≤200；两圆角之间至少留 5×`thickness` 直边 |
| `tab_width` | 5 | >0 |
| `slot_spacing` | 1.2 | 0.6–8 |
| `slot_bridge` | 2 | 0.8–8 |
| `slot_rows` | 2 | 1–6 |
| `top_lid` / `bottom_lid` | true | 布尔值 |
| `material` | `待确认材料` | ≤80 字 |
| `pattern_version` | 2 | 1 或 2 |

`pattern_version=1` 仅用于复现旧检查点的排版；新设计用默认 2。两种排版的切缝不同，不能混用产物。

两块圆角盖板 + 四个弯折区的连续围板，四角切缝交错接到上下边缘并保留连接桥；盖板榫与围板凹槽配对。直边至少为板厚的 5 倍。接缝需胶合，弯折与榫接要先试切。

## 使用规则

- 先问清外尺寸、板厚、材料（如亚克力/椴木/PET）；材料未知时保留 `待确认材料` 并说明切割/弯折参数需按实际板材定。
- 尺寸不能只给一个方向就默认另一方向；缺关键尺寸先问，不要猜。
- `panel-box` 是胶合对接，`finger-box` 才是榫齿；`rounded-box` 是弯折盒。三者不能混称。
- 所有输出均为名义路径，`kerf` 固定 0；切割前在加工软件中做刀缝补偿并试切。
- 文字用随包字体转真实矢量轮廓；不支持换行或文字切穿。`laser text` 只做单行雕刻；需要面板文字时用 `finger-box.panelTexts`。
- 图纸超出画布、路径重复、开放切割折线等会被拒绝（exit 2），不要手工改 `design.json` 绕过。`laser text` 的字体缺字 → exit 4 `TEXT_INVALID`，不猜替代字形。
- 需要模板以外的任意路径时，v1 不支持直接用 `laser build`；可改用 `structure solid` 做 3D，或明确告知用户当前限制。

## 典型调用

```bash
zw laser build --template finger-box \
  --params '{"width":80,"depth":60,"height":40,"thickness":3,"material":"3mm 椴木","panelTexts":[{"panel":"front","x":10,"y":12,"text":"掌问","fontSize":10}]}' \
  --out ./laser-out --json
```

成功返回 `drawing.width/height/thickness/material/shapes` 和 4 个导出路径；`warnings` 必定包含刀缝与装配声明，`material` 未确认时再加一条。
