---
name: paper-figure
description: 论文配图域。结构图（45 类）与科研统计图（20 类）的声明式生成与验收。当任务涉及期刊图表、Figure 1 重绘、数据可视化、学术海报配图时使用。
---

# paper-figure · 论文配图域

> 决策流程 + 本域设计语言 + 验收标准。细节在 `references/`，按需读，不烧 context。

---

## 1. 路由：先判图性质，再选路线

```
用户要一张论文图
  │
  ├─ 有参考图吗？
  │    └─ 有 → 先跑 core/probe/probe_geometry.py，拿到实测几何
  │            → 据证据写 IR，不凭肉眼估
  │
  ├─ 图里有数据点吗？
  │    ├─ 有 → 统计路线：matplotlib（backends/mpl2svg.py）
  │    │       数据必须来自冻结表，见 references/data-freeze.md
  │    │
  │    └─ 没有 → 结构路线：裸 SVG（backends/svg.py）
  │             框/线/箭头的组合，见 references/structure-catalog.md
  │
  └─ 交付物形态？
       ├─ 期刊投稿 → SVG + PDF（600dpi）+ PNG（300dpi 代理）
       ├─ 审稿回复 → PNG 单图
       └─ 海报 → 走 poster-flyer 域，别在这域硬撑
```

**判错的代价**：把统计图当结构图手画 = 数据点被手挪 = 学术不端。宁可多问一句。

---

## 2. 本域设计语言

结构图（继承 academic tokens）：

- **字体**：轴标签/图例用 Times New Roman；面板标号（a）（b）用 Arial Bold；数学变量斜体，数字下标直立
- **字号**：图题 11pt、面板标号 10pt、轴标签 9pt、刻度 8pt，**低于 7.5pt 不许出现**
- **线宽**：0.8–1.7px。坐标轴 0.8，数据线 1.7，网格 0.5
- **箭头**：灰色（`colors.border`），不用黑
- **留白**：画布 = 内容 + 40px 对称边距，期刊双栏图不超过 1740px

统计图（继承 academic tokens）：

- 分类数据用 CVD 安全色板（`palette.colors.cvd_safe_order`）
- 连续数据用 sequential，有中点用 diverging
- 误差棒必须声明 CI / SD / SE，写进 `data.series[].error_kind`
- 单位必须标；无量纲写 `a.u.`
- 灰度打印自查：转灰度后层级仍可分

布局铁律（METHOD §2 全部适用，本域高频三条）：

1. 文字超宽 → **拆行**，不缩字号
2. 图例距主体 ≈ 一个箭头长度（40–60px）
3. 跨区标签白描边 4.5px，`paint-order="stroke"`

---

## 3. 域级验收标准（acceptance criteria）

### 3.1 结构图

- [ ] 四层分离：IR 里 content / topology / layout / style 不混写
- [ ] 代码无 hex，全部走 token 路径
- [ ] `check_overflow.py` PASS：无溢出、无重叠、文字宽度预算达标
- [ ] `check_contrast.py` PASS：正文与网格灰度差 ≥40（渲染像素上量）
- [ ] `check_tiling.py` PASS：无重复拼接
- [ ] 视觉裁判 PASS（派发格式见 `core/verify/judge_template.md`）
- [ ] 印刷自查：转灰度层级可分

### 3.2 统计图

以上全部，外加：

- [ ] 数据来自冻结表（`data.source` 指向真实文件），IR 不内联数据
- [ ] `error_kind` 已声明；CI/SD/SE 没混用
- [ ] 数值、单位、样本量、显著性标注与源数据一致（**人工核对，不许脚本放行**）
- [ ] **没有一个数据点是手挪的** —— 这是学术红线
- [ ] 图例或直接标注说明了每个 series 的身份

### 3.3 通用

- [ ] 源文件（IR + 数据 + 脚本）在，产物可再生
- [ ] 重跑一遍生成脚本，产物字节级一致（除时间戳）

---

## 4. 什么时候停下来问人

- 参考图分辨率低于目标输出的 1/2 → 探针数据不可靠，问用户要原图
- 数据表缺单位、缺样本量、缺检验方法 → 不许硬猜，问
- 用户说「随便美化一下数据图」→ 拒绝美化数据，只美化样式
- 统计图的误差棒类型用户没指定 → 问，不许默认

---

## 5. 本域踩坑库

见 `references/pitfalls.md`。高频三条：

1. SVG `<style>` 里的 `text{fill}` 会把彩色标题渲染成近黑 —— fill 不进 CSS
2. 发丝线 1.2px 理论对比 Δ50，渲染后 Δ12，judge 读成「无边框」—— 按渲染像素选色
3. tspan 继承斜体，数学下标被斜体化 —— 下标显式 `font-style="normal"`

---

## 6. 快速入口

```bash
# 结构图
python -m backends.svg <ir.json> -o out.svg --scale 8
python -m backends.png out.svg -o out.png --width 1740

# 统计图
python -m backends.mpl2svg <ir.json> -o out.svg --png out.png

# 探针参考图
python -m core.probe.probe_geometry reference.png --report r.json --suggest-ir skeleton.json

# 自检三连
python -m core.verify.check_overflow <ir.json>
python -m core.verify.check_contrast out.png
python -m core.verify.check_tiling out.png
```
