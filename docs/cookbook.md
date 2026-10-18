# FigSmith Cookbook · 常见任务配方

> 每道配方都是「输入 → 命令 → 验收」，可直接复制运行。
> 所有命令在仓库根目录执行。方法论的唯一来源是 `core/METHOD.md`。

---

## 0. 环境自检（30 秒）

```bash
python -m core.ir examples/arch-diagram/layered-arch/arch.ir.json
python -m backends.svg examples/arch-diagram/layered-arch/arch.ir.json -o /tmp/t.svg
python -m core.verify.check_contrast examples/arch-diagram/layered-arch/arch.png
python tools/regress.py
```

四条全绿 = 环境就绪。任一失败看报错，先修环境再画图。

---

## 1. 画一张结构图（框 / 线 / 箭头）

**用它当**：流程图、架构图、概念图——任何能用 box + arrow 表达的东西。

```bash
# 1) 先写 IR（四层分离：content / topology / layout / style）
#    骨架可从探针生成，见配方 7
python -m core.ir my.ir.json                 # 校验合法性
python -m backends.svg my.ir.json -o my.svg --scale 12   # scale = px_per_unit
python -m backends.png my.svg -o my.png --width 1600     # 光栅化

# 2) 验收
python -m core.verify.check_overflow my.ir.json
python -m core.verify.check_contrast my.png
python -m core.verify.check_tiling my.png
```

**要点**：
- `width_unit` 是画布宽的唯一权威，别去改 `box_w` 硬凑。
- 长标签**拆行**，不缩字号。
- 代码里不出现 hex，颜色走 `colors.*` 令牌路径。

---

## 2. 画一张统计图（数据来自冻结表）

**用它当**：柱状、折线、散点、箱线——任何数据点必须来自数据表。

```bash
# 数据 → JSON spec → SVG/PNG，全程 mpl2svg
python -m backends.mpl2svg spec.json -o fig.svg --png fig.png
python -m backends.pdf spec.json -o fig.pdf
```

**要点**：
- 数据先冻进 CSV/表，**图上不手挪点**。
- 超宽图有 4000px 宽度守门，超了拆成多面板。
- 统计图**不要**走 `backends.svg.py`（topology 为空，会得到空画布）。路由见配方 6。

---

## 3. 做一页幻灯片 / 海报 / 信息图（HTML/CSS 路线）

**用它当**：文字流为主、CSS 布局强于手算坐标的版面。

```bash
# 页面尺寸体现在 --size（CSS px）；PDF 的 @page 会按此精确设页
python -m backends.html2pdf slide.html -o slide.pdf --png slide.png --size 1280x720

# 验收：PDF 必须单页、文字矢量；PNG 代理三查
python tools/pdf_check.py slide.pdf          # pages=1 且 text_ops=True
python -m core.verify.check_contrast slide.png
python -m core.verify.check_tiling slide.png
```
**要点**：
- **渐变 / 阴影只做点缀**（header bar、封面）：spike 实测它们会被光栅化成图片。
  结构色一律用平涂令牌色。
- 显式设页面尺寸；不给尺寸会悄悄溢出到第二页。
- 高版式（海报）代理截图会按 `--size` 的高度全幅捕获，不会截断。
- 参考案例：`examples/deck-slides/`、`examples/poster-flyer/`、`examples/infographic/`。

---

## 4. 把 mermaid / drawio 变成 FigSmith 风格

**用它当**：已有 mermaid / drawio 源文件，想统一到本体系风格。

```bash
python -m domains.docs-diagram.scripts.parse_mermaid input.mmd -o out.ir.json
python -m backends.svg out.ir.json -o out.svg --scale 12
python -m backends.png out.svg -o out.png --width 1600
```

**要点**：
- **解析后必须重渲染，绝不透传**——IR 是唯一的风格载体。
- 源文件与产物一起留存，源文件不改。
- 往返一致：节点与连接一个不少、方向不反、标签不改顺。
- 域细节见 `domains/docs-diagram/SKILL.md`。

---

## 5. 一份 IR 出多种格式

```bash
python tools/four_way_check.py my.ir.json     # 一 IR 四出 + 一致性比对
```

单独出：

```bash
python -m backends.svg    my.ir.json -o my.svg
python -m backends.pdf    my.ir.json -o my.pdf
python -m backends.png    my.svg     -o my.png --width 1600
python -m backends.pptx   my.ir.json -o my.pptx
python -m backends.drawio my.ir.json -o my.drawio      # 或 drawio2ir 反向
```

**要点**：PDF / PPTX 交付物必须附 PNG 代理（部分宿主 `read` 不接受 PDF）。

---

## 6. 不确定走哪条路线？问路由

```bash
python -m tools.catalog route "论文里的分组柱状图"
```

输出「域 / 图型 / route / backend」，直接告诉你用哪个后端。

| route | 后端 | 何时 |
|---|---|---|
| `structure` | `backends/svg.py` | 只有框/线/箭头，无数据点 |
| `statistical` | `backends/mpl2svg.py` | 任一数据点来自数据集 |
| `html` | `backends/html2pdf.py` | 文字流 / 版面布局为主 |

---

## 7. 照着参考图量几何

**用它当**：手上有参考截图，想复刻它的节奏。

```bash
python -m core.probe.probe_geometry ref.png                 # 报 margin/band/column/pitch
python -m core.probe.probe_geometry ref.png --suggest-ir skeleton.json
```

`skeleton.json` 是可直接填充的 IR 骨架。探针给的是**测量值**，不是猜的。

---

## 8. 验收被卡住怎么办

| 现象 | 根因方向 | 动作 |
|---|---|---|
| `check_contrast` FAIL | 前景/背景灰度差 < 40 | 换令牌色，或加描边；别只调透明度 |
| `check_tiling` FAIL | 有重复拼接块 | 查是不是复制粘贴重复元素 |
| `check_overflow` FAIL | 文字超框 | **拆行**，不缩字号 |
| 统计图渲染成空 | 走错后端 | 有数据必须走 `mpl2svg`，见配方 6 |
| PDF 多页 | 页面尺寸没设 | 给 `html2pdf` 显式 `--size` |
| PNG 截断 | 视口高度不够 | 用 `html2pdf` 的代理（按页高捕获），别用固定窗口 |

**原则**：按根因修，不做局部补丁；不伪造 PASS——没有视觉工具就明说。

---

## 9. 回归与画廊

```bash
python tools/regress.py              # 跑回归套件
python tools/regress.py --blessed    # 重录基线（确认改动是预期的之后再跑）
python -m tools.catalog merge        # 重建 gallery/catalog.json
python -m tools.build_gallery        # 重建 gallery/index.html（自包含，可双击）
```

---

## 10. 加一个新的域包

1. `domains/<新域>/SKILL.md`——frontmatter 只写 `name` + `description`（跨宿主最小公共集）。
2. `domains/<新域>/references/catalog.json`——`schema` 用 `figsmith.catalog/1.0`。
3. `python -m tools.catalog merge`——新域自动进索引与画廊。
4. `examples/<新域>/`——至少一个可重生成案例。
5. 加进 `tools/catalog.py` 的 `domain_priority` 与 `README.md` 域清单。

**没有 SKILL.md 的域不算存在。**

