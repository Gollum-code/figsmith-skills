---
name: poster-flyer
description: 海报传单域。学术海报、活动传单、社媒 banner 的 HTML/CSS 生成。当任务涉及海报、宣传单、banner、社媒配图时使用。
---

# poster-flyer · 海报传单域

> 走 **HTML/CSS → PDF** 路线。文字流式排版是 SVG 弱项，海报以文字为主，所以此路线是主选。

---

## 1. 路由

```
用户要海报/传单
  ├─ 学术海报 → A0/A1 纵向，token 用 academic
  ├─ 活动传单 → A4 单页，token 用 web
  ├─ 社媒 banner → 横向定宽（1080×1350 等），token 用 web
  └─ 多尺寸 → 同一份 HTML 换 --size 重出（源不变）
```

## 2. 尺寸表

| 类型 | CSS px | 物理 |
|---|---|---|
| 学术海报 A1 | 2384×3370 | 594×841mm |
| 学术海报 A0 | 3370×4768 | 841×1189mm |
| A4 传单 | 794×1123 | 210×297mm |
| IG 竖版 | 1080×1350 | — |
| IG 方版 | 1080×1080 | — |
| X/Twitter 头图 | 1500×500 | — |

## 3. 设计语言

- **三栏经典学术海报**：左栏方法、中栏结果、右栏结论；栏间用 band 色条分隔。
- 标题区可横跨全宽；作者/单位紧随其下，字号递减。
- 学术海报正文 ≥ 16px（缩到 A1 仍可读）；传单 ≥ 18px。
- 图表区放 SVG/PNG 图（其他域的产物），不在这里重画。
- 渐变限封面 banner；阴影限卡片浮层（spike 实测会光栅化，别做结构）。

## 4. 验收标准

- [ ] PDF 页数 = 1（多页 = 内容溢出，是缺陷不是特性）
- [ ] 文字矢量；PNG 代理三查全过
- [ ] 打印灰度自查：转灰度后层级可分
- [ ] 同源多尺寸：换 `--size` 重出后内容一致（`tools/four_way_check.py`）
- [ ] 视觉裁判 PASS

## 5. 什么时候停下来问人

- 海报内容超一页 → 问删减策略，不许缩字号硬塞
- 缺 logo/图片素材 → 问，不编造
- 印刷 CMYK 要求 → 说明当前为 RGB，问是否接受

## 6. 快速入口

```bash
python -m backends.html2pdf poster.html -o poster.pdf --png poster.png --size 2384x3370
python -m core.verify.check_contrast poster.png
```
