---
name: docs-diagram
description: 文档图表域。mermaid / drawio 解析为 FigSmith IR，再按本体系风格重渲染。当任务涉及流程图、ER 图、UML、网络拓扑，或用户给了 mermaid/drawio 源文件时使用。
---

# docs-diagram · 文档图表域

> 决策流程 + 本域设计语言 + 验收标准。细节在 `references/`。

---

## 1. 路由

```
用户给了一份 mermaid / drawio
  │
  ├─ 是 mermaid 文本吗？
  │    └─ 是 → scripts/parse_mermaid.py → IR → backends/svg.py
  │
  ├─ 是 .drawio / mxfile XML 吗？
  │    └─ 是 → scripts/parse_drawio.py → IR → backends/svg.py
  │
  └─ 是截图 / 图片吗？
       └─ core/probe/probe_geometry.py 先探几何，再手工建 IR
```

**核心原则：解析后必须重渲染，绝不透传。**
mermaid 和 drawio 各有自己的默认样式，透传会让 FigSmith 的风格体系崩坏。
IR 是唯一的风格载体。

---

## 2. 本域设计语言

继承 academic / web tokens，另加两条本域规则：

### 2.1 语义映射

| mermaid / drawio 概念 | IR 映射 |
|---|---|
| 普通节点 | `box` |
| 决策菱形 | `box` + `style.emphasis`（或 `radius.chip`） |
| 分组 / subgraph / container | `band` |
| 连线 | `arrow`（`edge.kind`） |
| 连线标签 | `content.labels[edge.label]` |
| 泳道 | `band` + `row_span` |

### 2.2 重渲染后的统一处理

- 所有节点统一 `box_h`（同排等高）
- 所有箭头统一灰色 `colors.border`
- 所有文字统一走 token 路径
- 分组用 `band` 提供底色，不用 drawio 的彩色容器

---

## 3. 域级验收标准

- [ ] **往返一致**：mermaid/drawio 的节点与连接，一个不少地出现在 IR 里
- [ ] 连接方向与源文件一致，不反向
- [ ] 节点标签文字与源文件一致，不「顺手改顺」
- [ ] `check_overflow.py` / `check_contrast.py` / `check_tiling.py` 全 PASS
- [ ] 视觉裁判 PASS
- [ ] 源文件与产物一起留存，源文件不改

---

## 4. 什么时候停下来问人

- 源文件里有 FigSmith 不支持的图元（如自定义 SVG 节点）→ 问是否降级为 box
- drawio 的复杂样式（渐变、图标字体）→ 说明会丢失，问是否接受
- 同一份源文件既要 mermaid 风格又要 FigSmith 风格 → 说明只能二选一

---

## 5. 快速入口

```bash
# mermaid -> IR -> SVG -> PNG
python -m domains.docs-diagram.scripts.parse_mermaid input.mmd -o out.ir.json
python -m backends.svg out.ir.json -o out.svg --scale 12
python -m backends.png out.svg -o out.png --width 1600

# drawio -> IR -> SVG
python -m domains.docs-diagram.scripts.parse_drawio input.drawio -o out.ir.json
```
