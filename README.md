# FigSmith · 图匠

> 让 AI Agent 像工匠一样，稳定产出印刷级配图

面向 AI Agent 的配图技能体系 —— 把「画图」从像素操作改写成**声明式代码生成**，再用独立验收闭环兜底。

**状态：可用。** 七大域、七后端、验收闭环俱全，回归套件 `4/4` 通过。常见任务见 [`docs/cookbook.md`](docs/cookbook.md)。

---

## 要解决的问题

「照着参考图画一张 Figure 1」是 AI 出图最容易翻车的任务 —— 字体不对、布局漂移、数据点被手挪、**还没法验证**。

FigSmith 把解决它的完整工作流打包成可插拔技能：**多领域覆盖，一条验收闭环兜底。**

## 七条生成路线

| 图性质 | 前端 | 后端 | 为什么 |
|---|---|---|---|
| 结构化图（框/线/箭头） | 声明式 IR | `backends/svg.py` | 完全可控、矢量、可编辑 |
| 统计/数据图 | JSON spec | `backends/mpl2svg.py` | 数据不能手画，点必须来自冻结表 |
| 布局类（海报/幻灯片/信息图） | HTML/CSS | `backends/html2pdf.py` | CSS 布局强于手算坐标 |
| 文档图（mermaid/drawio） | 解析 → IR 重渲染 | `backends/svg.py` | 不透传，保持风格体系 |
| 可编辑汇报 | IR | `backends/pptx.py` | PPTX 交付 |
| 互操作图 | IR ↔ XML | `backends/drawio.py` | DrawIO 往返 |
| 矢量 PDF | IR / spec | `backends/pdf.py` | 印刷交付，文字矢量 |

## 核心方法论

**图 = 声明。** 脚本是源，SVG/PNG 只是产物。

1. **四层分离** —— 内容 / 拓扑 / 布局 / 样式各自声明，互不混写
2. **语义色板** —— 颜色查字典，不硬编码；强调色全文 ≤3 种
3. **图元 ≤5 个** —— box / arrow / polyline / band / label
4. **无量纲坐标系** —— 抽象单位设计，物理尺寸交给渲染器
5. **网格节奏** —— 等距列、统一框尺寸、统一行距
6. **重复结构循环化** —— 加一个节点 = 加一行数据
7. **克制** —— 细线、灰箭头、无阴影渐变 3D
8. **源与产物分离** —— 源在，图永远能再生

## 验收闭环

```
几何自检 → 数据一致性 → 视觉裁判 → 按像素证据修根因 → 定向复检
```

- **不伪造 PASS** —— 没有视觉工具就明确标「视觉验收待完成」
- **按根因修，不做局部补丁**
- 定向复检只查 FAIL 项 + 回归点，不重跑全量

## 目录结构

```
figsmith-skills/
├── core/            # 内核：方法论 / IR / 样式令牌 / 参考图探测 / 验收工具
├── domains/         # 域包：paper-figure / arch-diagram / deck-slides / ...
├── backends/        # 输出后端：svg / png / mpl2svg / pdf / drawio / pptx / html2pdf
├── examples/        # 可重生成案例
├── tools/           # 路由 / 回归 / 画廊 / 四出一致性
└── gallery/         # 离线图型画廊（自包含 index.html）
```

每个域包自带 `SKILL.md`（路由 + 设计语言 + 验收标准）、`references/`（图型目录 + 踩坑库）、`examples/`（可运行案例），可独立安装。

## 七大域

| 域 | 路线 | 典型产物 |
|---|---|---|
| `paper-figure` | SVG / MPL | 论文结构图 + 统计图（65 图型） |
| `arch-diagram` | SVG | 分层 / 流水线 / 状态机 / 时序 / 部署 / 组件 |
| `docs-diagram` | SVG（解析重渲染） | mermaid / drawio 源消化成统一风格 |
| `infographic` | SVG / HTML | 时间轴 / 对比 / 步骤 / 数据大字 / 长图 |
| `deck-slides` | HTML→PDF | 标题页 / 内容页 / 过渡页 / 结尾页 |
| `poster-flyer` | HTML→PDF | 学术海报 / 传单 / 社媒 banner |
| `icon-logo` | SVG | 2px 网格对齐的图标 / 标识 |

目录共 **116 图型条目（跨 7 域）**，用语义路由 `python -m tools.catalog route "..."` 一句话定位。

## 兼容性

技能采用通用 `SKILL.md` 格式，适用于 opencode / Claude Code / Codex 等支持该格式的 Agent。安装见 [`AGENTS.md`](AGENTS.md)。

## 快速开始

```bash
./install.sh --target ~/.claude/skills            # 或 .\install.ps1，安装

python -m core.ir examples/arch-diagram/layered-arch/arch.ir.json   # 校验 IR
python -m backends.svg examples/arch-diagram/layered-arch/arch.ir.json -o out.svg
python -m tools.catalog route "论文里的分组柱状图"                    # 语义路由
python tools/regress.py                                            # 回归套件
```

详见 [`docs/cookbook.md`](docs/cookbook.md)。

## 许可

[MIT](LICENSE)
