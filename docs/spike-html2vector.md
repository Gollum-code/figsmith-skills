# P3-T0 Spike 报告：HTML/CSS → 矢量转换质量验证

> 2026-10-15 实测。环境：Windows 11，Edge headless（`--headless=new`），Python 直调。
> 测试资产：`tests/spike/spike.html`（1200px 宽海报式布局，含 grid、CJK 流式文本、渐变、阴影、混排）。

---

## 1. 测试矩阵

| 能力 | HTML/CSS 渲染 | `--print-to-pdf` 导出 | 结论 |
|---|---|---|---|
| CSS grid 三列等宽 | ✅ 精确均分 | ✅ 保留 | **可用** |
| CJK 流式换行 + 行高 | ✅ 稳定 | ✅ 保留（矢量文字） | **可用** |
| 中英混排基线 | ✅ 稳定 | ✅ 保留 | **可用** |
| 强调色 span | ✅ 正确 | ✅ 保留 | **可用** |
| 骑缝 band + 列表行 | ✅ 正确 | ✅ 保留 | **可用** |
| `linear-gradient` | ✅ 正确 | ⚠️ **光栅化为 2344×316 图像 XObject** | **失真** |
| `box-shadow` | ✅ 正确 | ⚠️ 与渐变一同进图像层 | **失真** |
| 文字选择/复制 | — | ✅ BT/TJ 文本操作符在 | **矢量保留** |

## 2. 关键发现

1. **文字永远是矢量**。Chromium 打印管线把文本放进 PDF 文本对象（BT/TJ），可选择、可搜索。这是最重要的保真点。
2. **渐变与阴影被光栅化成图像 XObject**。PDF 里出现 1 张 2344×316 的位图 —— 正好是渐变条 + 阴影卡片的合成区域。
3. 页数超一页（2 页）：CSS 像素 ≠ PDF 点，1200px 宽 @96dpi ≈ 900pt，超出 A4 纵向。交付时必须显式设 `@page` 尺寸。

## 3. 决策（对 R1 的回答）

**HTML/CSS 路线可用，但守四条边界：**

| 边界 | 执行 |
|---|---|
| ① 文字、框、线走 CSS → PDF，矢量保真 | deck/poster/infographic 主体用此路线 |
| ② 渐变和阴影**只做点缀**，不做结构 | 结构性色块用纯色或 token 色带；渐变限 header bar 一类小元素 |
| ③ 导出用 `--print-to-pdf`，配 `@page` 精确尺寸 | 不用截图 PNG 充当矢量交付物 |
| ④ 验收走 PNG 代理回渲（探针报告 §3.2） | PDF 不能直接 read，一律先转位图判 |

**不采用的备选**：纯 SVG 手算坐标（完全可控但流式文本回退成手排，海报/幻灯片这类以文字为主的图成本暴涨）；`foreignObject` 嵌 HTML（渲染器兼容性参差，印刷厂拒收率高）。

## 4. 对架构的影响

计划 §4 的四条路线维持不变，但 HTML 路线的输出后端明确为：

```
HTML/CSS --print-to-pdf--> PDF (文字矢量 / 点缀光栅) --rasterize--> PNG (验收代理)
```

`backends/png.py` 已具备浏览器光栅化能力；`--print-to-pdf` 作为 `deck-slides` / `poster-flyer` / `infographic` 三个域的正式导出通道，写进各自 SKILL.md。
