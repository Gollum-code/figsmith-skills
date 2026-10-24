# FigSmith Cookbook · 常见任务配方

> 每道配方都是「输入 → 命令 → 验收」，可直接复制运行。
> 所有命令在仓库根目录执行。方法论的唯一来源是 `core/METHOD.md`。

---

## 0. 环境自检（30 秒）

```bash
python -m core.ir examples/arch-diagram/layered-arch/arch.ir.json
python -m backends.svg examples/arch-diagram/layered-arch/arch.ir.json -o /tmp/t.svg
python -m core.verify.check_contrast examples/arch-diagram/layered-arch/arch.png
python -m core.tokens.loader --check
python tests/test_verify.py
python tools/regress.py
```

全绿 = 环境就绪。任一失败看报错，先修环境再画图。

---

## 1. 一条命令跑通：intent → 出图 → 验收

**用它当**：不想手动串五个命令。

```bash
python -m tools.figsmith pipeline "三层架构图" -o out/arch
```

它做四件事：`route`（语义路由）→ `scaffold`（生成起点）→ `render`（选对后端）→ `verify`（三查）。

**诚实原则**：统计图意图会**停下来要数据**（退出码 2），而不是编造数字：

```bash
$ python -m tools.figsmith pipeline "论文里的分组柱状图" -o out/bar
blocked: statistical scaffold needs real data before it can render (no numbers are invented).
```

填好数据源后再 `render` + `verify`。

拆开用：

```bash
python -m tools.figsmith route "社媒 banner"        # 只路由
python -m tools.figsmith scaffold "分层架构图" -o out/x   # 只生成骨架
python -m tools.figsmith render out/x.ir.json -o out/x    # 只渲染
python -m tools.figsmith verify out/x.ir.json            # 只验收
```

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
# 冻结表 → columns 声明 → SVG/PNG，全程 mpl2svg
python -m backends.mpl2svg figure.ir.json -o figure.svg --png figure.png
```

IR 的数据层只声明列名，不写数字：

```jsonc
"data": {
  "source": "data/trials.csv",
  "series": [
    { "name": "Experiment",
      "columns": { "x": "condition", "y": "mean", "yerr": "sd" },
      "error_kind": "SD" }
  ],
  "units": { "x": "condition", "y": "a.u." }
}
```

**要点**：
- 数据先冻进 CSV/表，**图上不手挪点**。声明了 `source` 又内联数字会被校验器拒绝。
- 超宽图有 4000px 宽度守门，超了拆成多面板。
- 统计图**不要**走 `backends.svg.py`（topology 为空，会得到空画布）。路由见配方 6。
- 冻结纪律与常见报错：`domains/paper-figure/references/data-freeze.md`。

---

## 3. 做一页幻灯片 / 海报 / 信息图（HTML/CSS 路线）

**用它当**：文字流为主、CSS 布局强于手算坐标的版面。

```bash
# 页面尺寸体现在 --size（CSS px）；PDF 的 @page 会按此精确设页
python -m backends.html2pdf slide.html -o slide.pdf --png slide.png --size 1280x720

# 验收：PDF 必须单页、文字矢量；PNG 代理三查
python tools/pdf_check.py slide.pdf          # pages=1 且 text_ops>0 且 vector=True
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
python -m domains.docs-diagram.scripts.parse_drawio input.drawio -o out.ir.json
python -m backends.svg out.ir.json -o out.svg --scale 12
python -m backends.png out.svg -o out.png --width 1600
```

**要点**：
- **解析后必须重渲染，绝不透传**——IR 是唯一的风格载体。
- drawio 支持**压缩格式**（deflate+base64，draw.io 默认保存方式），不限于手写的明文 XML。
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
| 令牌解析不出来 | token 路径写错 | `python -m core.tokens.loader --check` 查结构与对比度 |
| 三个脚本全过但看着不对 | 几何查不了「审美」 | 派视觉裁判，见下 |

### 8.1 派视觉裁判（三查之后才派）

```bash
# 1) 组装派发（元素清单自动从 IR 生成，验收标准自动从 SKILL.md 取原文）
python -m core.verify.judge build out/arch.png --ir out/arch.ir.json \
    --domain arch-diagram --chart-type layered --intent "分层架构图" > dispatch.md

# 2) 把 dispatch.md 喂给宿主的视觉模型，把它的 JSON 回复存成 reply.json

# 3) 回收裁定
python -m core.verify.judge collect out/arch.png --verdict-file reply.json \
    --out verify-results/records.jsonl
```

**铁律：没有回复 = PENDING，绝不伪造 PASS。** 派发协议原文见 `python -m core.verify.judge protocol`。

| 情况 | 结果 |
|---|---|
| 没给 `--verdict-file` | `PENDING`（视觉验收待完成） |
| 回复不是合法 JSON | `PENDING` |
| 回复 `PASS` 但列了 major issue | 按协议改判 `FAIL` |
| 回复 `PASS` 且 issues 为空 | `PASS` |

**原则**：按根因修，不做局部补丁；修完定向复检，不重跑全量。

---

## 9. 回归、令牌与 CI

```bash
python tests/test_verify.py          # 验收契约单测（14 项）
python tests/test_parse_drawio.py    # drawio 解析（含压缩）
python tools/regress.py              # 回归套件
python tools/regress.py --blessed    # 重录基线（确认改动是预期的之后再跑）
python -m core.tokens.loader --check # 令牌一致性（结构硬失败，对比度/字体为告警）
python -m tools.catalog merge        # 重建 gallery/catalog.json
python -m tools.build_gallery        # 重建 gallery/index.html（自包含，可双击）
```

**CI 门禁**（`.github/workflows/ci.yml`，push/PR 触发）依次跑：每个 IR 校验 → 单测 → 回归 → 四出一致性 → 令牌一致性 → 无内联 hex → 画廊同步。本地等价命令就是上面这几条。改动前先本地跑一遍，别让 CI 替你发现。

---

## 10. 加一个新的域包

1. `domains/<新域>/SKILL.md`——frontmatter 只写 `name` + `description`（跨宿主最小公共集）。
2. `domains/<新域>/references/catalog.json`——`schema` 用 `figsmith.catalog/1.0`。
3. `python -m tools.catalog merge`——新域自动进索引与画廊。
4. `examples/<新域>/`——至少一个可重生成案例。
5. 加进 `tools/catalog.py` 的 `domain_priority` 与 `README.md` 域清单。

**没有 SKILL.md 的域不算存在。**

