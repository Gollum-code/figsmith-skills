---
name: deck-slides
description: 幻灯片域。标题页、图表页、过渡页、结尾页的 HTML/CSS 生成与 PDF 导出。当任务涉及演示文稿、slide、PPT 页面设计时使用。
---

# deck-slides · 幻灯片域

> 走 **HTML/CSS → PDF** 路线（`backends/html2pdf.py`），spike 结论见 `docs/spike-html2vector.md`。

---

## 1. 路由

```
用户要幻灯片
  ├─ 单页导出 → 本域 build.py 一页一 PDF
  ├─ 多页成套 → 每页独立 HTML，同名编号（slide_01.html...）
  └─ 要 PPTX 可编辑 → backends/pptx.py 走 IR（结构页），非布局页
```

## 2. 页面规格

| 页型 | 尺寸（CSS px） | 说明 |
|---|---|---|
| 16:9 标题/内容页 | 1280×720 | 默认 |
| 4:3 | 1024×768 | 老投影仪 |
| 竖版 | 720×1280 | 手机阅读 |

导出时 `--size 1280x720`；PDF 是文字矢量的正式交付物，PNG 只是验收代理。

## 3. 设计语言

- **一页一件事。** 标题 ≤ 12 字，正文 ≤ 6 行，超过就拆页。
- 字号：页题 34px+，正文 15-18px，脚注 13px。投影场景最小 14px。
- token 集：默认 `web`（深色场景用 `tech`）。
- 强调色 ≤3，同一份 deck 全程一致。
- 渐变/阴影**只做点缀**（header bar、封面），不做结构 —— spike 实测它们会被光栅化。
- 每页留白 ≥ 12%；一页塞满 = 拆页信号。

## 4. 验收标准

- [ ] PDF 单页（`/Type /Page` 计数 = 预期页数）
- [ ] 文字为矢量（PDF 有 BT 块）
- [ ] PNG 代理 `check_contrast` PASS
- [ ] PNG 代理 `check_tiling` PASS
- [ ] 视觉裁判 PASS（派发代理 PNG）
- [ ] 源 HTML 与 PDF 同目录留存

## 5. 什么时候停下来问人

- 用户要「动态效果」（动画、转场）→ 超出静态图范围，说明并确认
- 字体没有本地文件 → 问是否允许回退字体
- 内容超一页 → 问拆页策略

## 6. 快速入口

```bash
python -m backends.html2pdf slide.html -o slide.pdf --png slide.png --size 1280x720
python -m core.verify.check_contrast slide.png
```
