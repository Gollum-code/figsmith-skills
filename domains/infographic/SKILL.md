---
name: infographic
description: 信息图域。数据故事、时间轴、对比、流程的可视化。当任务涉及信息图、数据故事、长图、时间轴时使用。
---

# infographic · 信息图域

> 两条路线二选一：**参数化 SVG**（结构为主）或 **HTML/CSS → PDF**（文字流为主）。

---

## 1. 路由

```
用户要信息图
  ├─ 结构为主（时间轴、对比、流程）→ 参数化 SVG（backends/svg.py）
  │      可复用 paper-figure 的结构图型 ID
  ├─ 文字流为主（数据故事、长图）→ HTML/CSS（backends/html2pdf.py）
  └─ 有数据 → 图块走 backends/mpl2svg.py，嵌进版式
```

## 2. 图型

| ID | 图型 | 路线 | 说明 |
|---|---|---|---|
| `timeline_v` | 纵向时间轴 | SVG | 中轴 + 交错节点 |
| `timeline_h` | 横向时间轴 | SVG | 单排 + 上下标签 |
| `comparison_ab` | AB 对比 | SVG | 左右等分 + 中线 |
| `process_steps` | 步骤条 | SVG | 编号 + 等宽卡 |
| `stat_callout` | 数据大字 | HTML | 大数字 + 说明 |
| `story_scroll` | 滚动长图 | HTML | 分段叙事 |
| `icon_grid` | 图标网格 | HTML | 等距网格 + 图标 |

## 3. 设计语言

- **先结构后装饰。** 信息图的骨架是信息层级，不是配色。
- 数字类元素用大字号 + 小字说明的组合（大小比 ≥3:1）。
- 图标网格严格等距，图标尺寸统一。
- 配色用 `palette` 的 CVD 安全色板；强调 ≤3。
- 长图分段：每段一个 `band` 背景色交替，视觉上分隔但不用边框。

## 4. 验收标准

- [ ] SVG 路线：IR 合法 + overflow/contrast/tiling 三查
- [ ] HTML 路线：`tools/pdf_check.py` 单页 + 文字矢量，PNG 代理 contrast/tiling 两查
- [ ] 数据块与源数据一致（有数据时）
- [ ] 视觉裁判 PASS
- [ ] 同源可重生成

## 5. 什么时候停下来问人

- 数据没有来源 → 问，不许编数字
- 长图超过 8000px → 探针显示仍可读，但问是否需要分段
- 图标来源不明 → 问是否有授权素材

## 6. 快速入口

```bash
# SVG 路线
python -m backends.svg infographic.ir.json -o out.svg --scale 12
# HTML 路线（--size 必须等于页面实际尺寸；本例 page 是 1200x760）
python -m backends.html2pdf infographic.html -o out.pdf --png out.png --size 1200x760
python tools/pdf_check.py out.pdf
```
