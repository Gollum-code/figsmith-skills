---
name: arch-diagram
description: 架构图域。分层架构、状态机、时序图、部署拓扑的声明式生成。当任务涉及系统架构、微服务、数据流、状态转换、部署图时使用。
---

# arch-diagram · 架构图域

> 决策流程 + 本域设计语言 + 验收标准。细节在 `references/`。

---

## 1. 路由

```
用户要一张架构图
  │
  ├─ 强调「分几层」   → layered    （stacked-bands）
  ├─ 强调「怎么流转」 → pipeline   （row-n-equal）
  ├─ 强调「状态转换」 → state_machine
  ├─ 强调「谁调谁」   → sequence   （时序图）
  ├─ 强调「部署到哪」 → deployment （拓扑 + 分区）
  └─ 强调「组件关系」 → component  （graph）
```

本域默认走**声明式 SVG**（`backends/svg.py`），不走 matplotlib，也不走 HTML。

---

## 2. 本域设计语言

架构图的专业感来自**结构清晰**，不是装饰。

### 2.1 五个图元的用法

| 图元 | 用途 | 关键约束 |
|---|---|---|
| `box` | 组件 / 层 / 服务 | 同排等高，同列等宽 |
| `band` | 分区 / 泳道 / 层带 | 垫在所有 box 之下，可跨列 |
| `arrow` | 调用 / 数据流 | **灰色**（`colors.border`），不用黑 |
| `polyline` | 折线连接 | 正交优先，转角 90° |
| `label` | 浮动标注 | 白描边 4.5px，跨区可读 |

### 2.2 语义浅底

组件框用 `colors.surface_band` 浅底 + `colors.border` 细边。
**不用深色填充**，不用渐变，不用阴影。分区用 band 提供层次，不是靠框的颜色。

### 2.3 骑缝标题牌（本域招牌）

分区标题牌压在带边界上时：

- 字牌外扩矩形（`band_y ± 16`）是**禁行区**，别的元素不许进
- 带内右上角标基线 `band_y + 26`
- 横向连线走 `band_y + 40` 以下
- 字牌白底，压线仍可读

### 2.4 顺序徽标

多步骤流程用圆形序号（①②③ 或 1 2 3），直径 = 行高 × 0.5，居中于框左上角。
**同一张图只用一种序号体系**，别混 ①②③ 和 (1)(2)(3)。

### 2.5 色条

强调一条路径时用色条（细矩形，宽 3–4px）贴框左侧，颜色取 `colors.accent`。
强调总数 ≤3（METHOD 1.2）。

---

## 3. 本域碰撞缺陷库（6 类）

架构图最常翻车的六种碰撞，全部要在渲染前规避：

| # | 缺陷 | 规避 |
|---|---|---|
| 1 | **标题牌压组件** | 字牌外扩矩形成禁行区，见 2.3 |
| 2 | **箭头穿过文字** | 连线走空行/空列，不穿框 |
| 3 | **标签压框边** | 跨区标签白描边 4.5px |
| 4 | **同行框高不等** | 同排 `row` 共享，`box_h` 统一 |
| 5 | **箭头重叠** | 同源多目标时上下错开，间距 ≥8px |
| 6 | **跨层连线无回路** | 反向连线单独走外侧，不与正向重叠 |

---

## 4. 域级验收标准

- [ ] 四层分离；代码无 hex
- [ ] `check_overflow.py` PASS：无溢出、无重叠（band 除外）、文字预算达标
- [ ] `check_contrast.py` PASS：框边 vs 底、文字 vs 底，灰度差 ≥40
- [ ] `check_tiling.py` PASS
- [ ] 六类碰撞逐条自查（§3）
- [ ] 视觉裁判 PASS
- [ ] **箭头全部为灰**，无黑色箭头
- [ ] 同一张图序号体系唯一

---

## 5. 什么时候停下来问人

- 架构层级超过 6 层 → 问是否拆成多张
- 单张图组件超过 40 个 → 问是否分组或分页
- 用户没给层名 → 问，不许自己编「应用层/服务层/数据层」这种通用套话
- 连接方向有歧义（双向还是单向）→ 问

---

## 6. 快速入口

```bash
python -m backends.svg <ir.json> -o out.svg --scale 12
python -m backends.png out.svg -o out.png --width 1600
python -m core.verify.check_overflow <ir.json>
python -m core.verify.check_contrast out.png
```

参考图探测：`python -m core.probe.probe_geometry reference.png --suggest-ir skeleton.json`
