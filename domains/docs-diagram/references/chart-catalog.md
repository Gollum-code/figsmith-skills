# docs-diagram · 图型目录

> 本域**不是**自己发明图型，而是把 mermaid / drawio 源消化成 IR，再用 FigSmith 风格重渲染。
> 选型看「源格式 + 要强调的关系类型」。

---

## 0. 总原则

**解析后必须重渲染，绝不透传。**

mermaid / drawio 自带样式体系，直接导出会破坏 FigSmith 的令牌一致性。
IR 是唯一的风格载体——所有颜色走 token 路径，所有框统一 `box_h`，所有线统一 `colors.border`。

源文件与产物**一起留存**，源文件不改。

---

## 1. 源格式支持矩阵

| 源格式 | 解析脚本 | 支持图型 | 备注 |
|---|---|---|---|
| mermaid:flowchart | `scripts/parse_mermaid.py` | flowchart | 菱形决策→`box`+`emphasis` |
| mermaid:sequenceDiagram | `scripts/parse_mermaid.py` | sequence | 生命线手排 |
| mermaid:stateDiagram-v2 | `scripts/parse_mermaid.py` | state | 自循环单独处理 |
| mermaid:classDiagram / erDiagram / requirementDiagram | `scripts/parse_mermaid.py` | class / er / requirement | 部分语句支持 |
| mermaid:gantt / journey / gitGraph / mindmap / timeline / pie / quadrant | `scripts/parse_mermaid.py` | 对应图型 | 见下 |
| drawio (.drawio / .xml) | `scripts/parse_drawio.py` | 任意容器/节点/连线 | 复杂样式降级为 box |
| 截图 / 图片 | `core/probe/probe_geometry.py` 探几何后手工建 IR | — | 无源文本时 |

---

## 2. 重渲染后的统一处理

| 源概念 | IR 映射 |
|---|---|
| 普通节点 | `box` |
| 决策菱形 | `box` + `style.emphasis`（或 `radius.chip`） |
| 分组 / subgraph / container | `band` |
| 连线 | `arrow`（`edge.kind`） |
| 连线标签 | `content.labels[edge.label]` |
| 泳道 | `band` + `row_span` |
| 生命线（sequence） | `band` 竖排 + 顶部参与者 |
| 自循环 | `edge` 回边，箭头回到节点自身右侧 |
| 返回消息 | 虚线 `stroke-dasharray` |

**硬规则**：
- 同排 box 等高（`box_h` 一致）
- 所有箭头统一灰色 `colors.border`
- 所有文字走 token 路径（不内联 hex、不进 CSS `fill`）
- 分组用 `band` 底色，不用 drawio 的彩色容器

---

## 3. 验收标准（域级）

- [ ] **往返一致**：源文件的节点与连接一个不少地出现在 IR
- [ ] 连接方向与源文件一致，不反向
- [ ] 节点标签文字与源文件一致，不「顺手改顺」
- [ ] `check_overflow.py` / `check_contrast.py` / `check_tiling.py` 全 PASS
- [ ] 视觉裁判 PASS
- [ ] 源文件与产物一起留存，源文件不改

---

## 4. 什么时候停下来问人

- 源文件有 FigSmith 不支持的图元（自定义 SVG 节点）→ 问是否降级为 box
- drawio 复杂样式（渐变、图标字体）→ 说明会丢失，问是否接受
- 同一份源既要 mermaid 风格又要 FigSmith 风格 → 说明只能二选一
