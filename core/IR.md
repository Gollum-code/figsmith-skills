# FigSmith IR · 领域无关中间表示

> 一条声明 = 一张图。所有域、所有后端都吃这个 IR。
> IR 是纯数据（JSON 可序列化），不含任何渲染细节。

---

## 1. 设计原则

**四层分离**在 IR 里体现为四个独立字段：`content` / `topology` / `layout` / `style`。
改文字不动布局，改配色不动拓扑。

```
IR
├── meta        # 域、图型、token 集、版本
├── content     # 文字层：所有出现在图上的字符串
├── topology    # 拓扑层：节点与连接（不含坐标）
├── layout      # 布局层：坐标、尺寸、网格
├── style       # 样式层：色、字体、线宽（引用 token 路径）
└── data        # 数据层：统计图的冻结数据表（可选）
```

---

## 2. Schema

### 2.1 顶层

```jsonc
{
  "schema": "figsmith.ir/1.0",
  "meta": {
    "domain": "arch-diagram",      // 域包名
    "chart_type": "layered",       // 本域图型 ID（见 references/catalog.json）
    "tokens": "academic",          // token 集名
    "title": "系统分层架构",        // 可省略；文档元数据（PPTX 标题/文件名），不画进图里
    "width_unit": 100              // 无量纲坐标系宽度（画布高度由 layout 反推）
  },
  "content": { ... },              // §2.2
  "topology": { ... },             // §2.3
  "layout": { ... },               // §2.4
  "style": { ... },                // §2.5
  "data": { ... }                  // §2.6 可选
}
```

### 2.2 content（文字层）

**所有字符串集中在此。** 节点标签、轴标签、图例、脚注都在这。

```jsonc
"content": {
  "labels": {
    "n1": "输入层",                // key 引用，节点只存 key
    "n2": "处理层"
  },
  "axis": {
    "x": "时间 (s)",
    "y": "响应幅度 (a.u.)"
  },
  "legend": ["实验组", "对照组"],
  "footnote": "数据来源：内部测试集 n=240"
}
```

规则：
- 同一个字符串在多处出现时，只定义一次，其余处引用 key。
- 换语言 = 换这个 dict，不动其他层。

### 2.3 topology（拓扑层）

```jsonc
"topology": {
  "nodes": [
    { "id": "n1", "kind": "box" },        // kind ∈ {box, arrow, polyline, band, label}
    { "id": "n2", "kind": "box" }
  ],
  "edges": [
    { "from": "n1", "to": "n2", "label": "e1", "kind": "arrow" }
  ]
}
```

规则：
- 不含任何坐标。坐标全在 `layout`。
- `kind` 只能是五个图元之一（METHOD §1 原则 3）。
- 重复结构用循环生成，不手写第二条相同边。

### 2.4 layout（布局层）

```jsonc
"layout": {
  "canvas": { "w": 100, "h": 80, "margin": 4 },
  "grid": { "columns": 3, "gap_x": 3.0, "gap_y": 4.0, "box_w": 24, "box_h": 10 },
  "nodes": {
    "n1": { "col": 0, "row": 0 },
    "n2": { "col": 1, "row": 0 }
  }
}
```

规则：
- 坐标全部无量纲，由 `grid` 推导，**不手填绝对坐标**。
- 同一行的节点共享 `row`，同一列共享 `col` —— 网格节奏由结构保证。
- 画布随内容收紧：`canvas` 由 grid 反算，不是先定画布再塞内容。

### 2.5 style（样式层）

```jsonc
"style": {
  "fill": {
    "n1": "colors.surface_band",     // token 路径，不是 hex
    "n2": "colors.surface_band"
  },
  "stroke": {
    "default": "colors.border",      // 箭头用灰不用黑
    "width": "stroke.thin"
  },
  "text": {
    "default": "fonts.role.axis_label",
    "size": "fonts.size_pt.tick_label",
    "color": "colors.ink"
  },
  "emphasis": ["n1"]                 // 强调元素，≤3
}
```

规则：
- 值一律是 **token 路径字符串**，由 `core/tokens/loader.py` 解析。
- 强调元素总数 ≤3。多出来的降级成默认样式。
- `fill` 不进 CSS（METHOD §5 硬坑第一条）。

### 2.6 data（数据层，统计图专用）

```jsonc
"data": {
  "source": "data/trials.csv",       // 冻结数据表路径（相对本 IR 文件解析）
  "categories": ["baseline", "low", "high"],   // 可选：分类轴标签
  "series": [
    { "name": "实验组", "columns": {"x": "condition", "y": "mean", "yerr": "sd"},
      "error_kind": "SD" }
  ],
  "units": { "x": "s", "y": "a.u." },
  "statistics": { "test": "two-sided t-test", "alpha": 0.05, "n": 240 }
}
```

规则：
- 数据必须来自冻结表（CSV/JSON）。`series[].columns` 指定列名，渲染时由
  `backends/mpl2svg.resolve_series()` 读表取数；**不手写在 IR 里**。
  校验器拒绝「声明了 `source` 却内联 `x/y`」的 IR —— 那样图表会悄悄偏离数据。
- `columns` 至少声明 `x` 与 `y`；有误差棒时 `yerr` 必填，`error_kind` 必须显式声明
  CI / SD / SE，不许省略。
- `x` 列是分类名时按位置取数，标签自动成为刻度文字。
- 统计检验的方法、α、样本量必须记录。没有这些信息的图不许进论文。

---

## 3. 校验

`python -m core.ir <file.json>` 检查：
- 必需字段齐全
- `topology.nodes` 的 id 在 `content.labels` 或 `layout.nodes` 有对应
- `style` 里的 token 路径可解析
- `data.series[].error_kind` 已声明；`data.series[].x/y` 等长
- 声明了 `data.source` 的 series 必须用 `columns` 读表，不许内联数据
- `layout.nodes` 的 id 全部存在于 `topology.nodes`

---

## 4. 示例

```jsonc
{
  "schema": "figsmith.ir/1.0",
  "meta": { "domain": "arch-diagram", "chart_type": "layered",
            "tokens": "academic", "width_unit": 100 },
  "content": { "labels": { "n1": "输入层", "n2": "处理层", "n3": "输出层" } },
  "topology": {
    "nodes": [ {"id": "n1", "kind": "box"}, {"id": "n2", "kind": "box"}, {"id": "n3", "kind": "box"} ],
    "edges": [ {"from": "n1", "to": "n2", "kind": "arrow"},
               {"from": "n2", "to": "n3", "kind": "arrow"} ]
  },
  "layout": {
    "canvas": { "w": 100, "h": 80, "margin": 4 },
    "grid": { "columns": 3, "gap_x": 3.0, "gap_y": 4.0, "box_w": 24, "box_h": 12 },
    "nodes": { "n1": {"col": 0, "row": 0}, "n2": {"col": 1, "row": 0}, "n3": {"col": 2, "row": 0} }
  },
  "style": {
    "fill": { "default": "colors.surface_band" },
    "stroke": { "default": "colors.border", "width": "stroke.thin" },
    "text": { "default": "fonts.role.panel_label", "size": "fonts.size_pt.panel_label",
              "color": "colors.ink" },
    "emphasis": []
  }
}
```

画布高度不写进 IR：`width_unit` 与 grid 决定宽度，高度由 layout 反算后加上对称边距
（METHOD §2.3）。所以 `meta.height_unit` 不存在，写了也不被读取。
```
