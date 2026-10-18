# paper-figure · 踩坑库

> 只记**跨案例可迁移**的缺陷。一次性问题写进那个案例的注释就够。

---

## 1. SVG `<style>` 覆盖 presentation attribute

- **现象**：彩色标题渲染成近黑
- **根因**：CSS 里写了 `text{fill: #000}`，覆盖了元素上的 `fill="#0072B2"`
- **修法**：`fill` 一律不写进 CSS。颜色逐元素设，或从包裹 `<g fill>` 继承。
- **回归**：`tests/blessed/paper-title-color.png`

## 2. 发丝线对比度损失

- **现象**：judge 报「无边框」，实际有 1.2px 线
- **根因**：1.2px 线理论对比 Δ50，抗锯齿渲染后 Δ12
- **修法**：按**实际渲染像素**选色，要求灰度差 ≥40。用 `check_contrast.py` 在 PNG 上量，不靠 hex 数学。
- **回归**：`tests/blessed/paper-hairline-contrast.png`

## 3. tspan 继承斜体

- **现象**：数学下标被斜体化，如 *x*ᵢ 变成 *xᵢ*
- **根因**：父 `<text font-style="italic">` 被 tspan 继承
- **修法**：下标显式 `font-style="normal"`。生成下标时强制加。
- **回归**：`tests/blessed/paper-math-subscript.png`

## 4. 误差棒类型混用

- **现象**：同一张图里有的 series 用 SD、有的用 SE，图例没写
- **根因**：IR 的 `data.series[].error_kind` 没逐 series 声明
- **修法**：校验器强制要求 `yerr` 存在时 `error_kind` 必填。混用必须在图例写明。
- **回归**：`tests/blessed/paper-errorbar-kind.png`

## 5. 参考图几何漂移

- **现象**：照着参考图重绘，框位置偏了 33px，judge 判 FAIL
- **根因**：肉眼估坐标，没用探针
- **修法**：先跑 `core/probe/probe_geometry.py`，据实测 margin/band/column 写 IR。
  真实位置从**对齐关系**反推，不是目测。
- **回归**：`tests/blessed/paper-probe-layered.png`

## 6. 全页截图静默拼接

- **现象**：长图截图出现 4 份重复内容
- **根因**：`fullPage: true` 截超一屏页面
- **修法**：先量 `scrollWidth/Height` → 视口精确对齐（≤3840×2160）→ 普通截图 →
  `check_tiling.py` 复验。
- **回归**：`tests/blessed/paper-tiling.png`

## 7. 条形图基线不为 0

- **现象**：差异被视觉放大 3 倍
- **根因**：y 轴从 0.8 起
- **修法**：条形图基线强制 0。要放大差异用折线或点图，并明确标注截断。
- **回归**：`tests/blessed/paper-bar-baseline.png`

## 8. 数据点被「顺手美化」

- **现象**：曲线比源数据更平滑
- **根因**：手动画路径，或对数据做了插值/平滑但没声明
- **修法**：统计路线只走 matplotlib，数据直读冻结表。任何平滑必须在图例或脚注写明。
- **回归**：`tests/blessed/paper-data-fidelity.png`
