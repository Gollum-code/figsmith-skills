# paper-figure · 结构图目录

> 45 类论文结构图。选型看「要表达什么关系」，不看好不好看。
> 机器可读版：`catalog.json`（域根目录）。

---

## 一、流程与因果（12 类）

| ID | 图型 | 适用 | 拓扑要点 |
|---|---|---|---|
| `flow_linear` | 线性流程 | 步骤无分支 | 单列 box + arrow |
| `flow_branch` | 分支流程 | 条件判断 | box + 菱形判定 + 双出口 |
| `flow_loop` | 循环流程 | 迭代优化 | 末节点回连首节点 |
| `flow_parallel` | 并行流程 | 多路同时 | 一入多出，汇合点 |
| `pipeline` | 数据流水线 | ETL / 预处理 | 等宽 box 横排，箭头等长 |
| `funnel` | 漏斗 | 逐级筛选 | 等宽递减或梯形堆叠 |
| `timeline` | 时间轴 | 实验日程 | 横轴 + 节点 + 上下交错标签 |
| `gantt` | 甘特图 | 任务排期 | 横条 + 起止 + 依赖虚线 |
| `cycle` | 循环图 | 周期过程 | 环形排布 + 弧形箭头 |
| `tree` | 树 / 层次 | 分类、归属 | 自上而下，等宽层 |
| `swimlane` | 泳道图 | 多主体协作 | 横向分道 + 跨道箭头 |
| `state_machine` | 状态机 | 状态迁移 | 圆角节点 + 转移标注 |

## 二、组成与层次（10 类）

| ID | 图型 | 适用 | 拓扑要点 |
|---|---|---|---|
| `layered` | 分层架构 | 系统栈 | 横带 + 层内组件 |
| `block_composition` | 方块组成 | 模块拆解 | 嵌套矩形 |
| `exploded_view` | 爆炸图 | 部件关系 | 分散 + 引线 |
| `nested_boxes` | 嵌套包含 | 集合关系 | 同心/嵌套矩形 |
| `part_whole` | 部分整体 | 占比构成 | 母框 + 子框 |
| `hub_spoke` | 星型辐射 | 中心辐射 | 中心 + 放射线 |
| `matrix_grid` | 矩阵网格 | 多维对照 | 网格 + 单元格标注 |
| `sandwich` | 三明治层 | 多层薄膜 | 等宽横条堆叠 |
| `stack` | 堆叠图 | 层叠次序 | 垂直堆叠 + 偏移阴影（仅印刷域） |
| `anatomy` | 解剖图 | 结构标注 | 主体 + 引线标签 |

## 三、对比与关系（10 类）

| ID | 图型 | 适用 | 拓扑要点 |
|---|---|---|---|
| `venn2` | 二集合韦恩 | 两集交叠 | 双圆 + 交叠区标注 |
| `venn3` | 三集合韦恩 | 三集关系 | 三圆 + 各区标注 |
| `upset` | UpSet | 多集交集 | 矩阵 + 条形 |
| `before_after` | 前后对比 | 处理效果 | 左右等分 + 中线 |
| `comparison_table` | 对比表 | 多维属性 | 表格 + 高亮列 |
| `pros_cons` | 优劣对比 | 方案权衡 | 双栏 + 色条 |
| `spectrum` | 光谱条 | 连续过渡 | 渐变色带 + 刻度 |
| `rank_list` | 排名列表 | 有序条目 | 编号 + 条形长度 |
| `pairwise_matrix` | 两两矩阵 | 成对比较 | 三角矩阵 + 数值 |
| `correspondence` | 对应连线 | 跨列匹配 | 双列 + 贝塞尔连线 |

## 四、概念与示意（8 类）

| ID | 图型 | 适用 | 拓扑要点 |
|---|---|---|---|
| `concept_map` | 概念图 | 知识关联 | 节点 + 带标签连线 |
| `mind_map` | 思维导图 | 发散结构 | 中心 + 分支曲线 |
| `metaphor` | 比喻图 | 抽象具象化 | 图形隐喻 + 标注 |
| `schematic` | 原理示意 | 机制说明 | 简化符号 + 箭头 |
| `circuit` | 电路图 | 电子原理 | 标准电气符号 |
| `network_topology` | 网络拓扑 | 节点互联 | 节点 + 连线 + 权重 |
| `phase_diagram` | 相图 | 相态分布 | 坐标 + 分区曲线 |
| `spectrum_plot` | 谱图 | 信号分布 | 曲线 + 峰标注 |

## 五、数据驱动结构图（5 类，走统计路线）

| ID | 图型 | 数据要求 |
|---|---|---|
| `heatmap_struct` | 结构化热图 | 矩阵 + 分类标注 |
| `chord` | 弦图 | 流矩阵 |
| `sankey` | 桑基图 | 流量守恒表 |
| `dendrogram` | 树状图 | 距离矩阵 |
| `treemap` | 矩形树图 | 层级 + 权重 |

---

## 选型速查

| 你想说 | 用 |
|---|---|
| A 导致 B，一步接一步 | `flow_linear` / `pipeline` |
| A 分情况处理 | `flow_branch` / `state_machine` |
| A 由 B、C、D 组成 | `block_composition` / `part_whole` |
| A 和 B 有交集 | `venn2` / `venn3` |
| A 比 B 好在三点 | `comparison_table` / `pros_cons` |
| 随时间推进 | `timeline` / `gantt` |
| 系统分几层 | `layered` / `sandwich` |
| 概念之间怎么连 | `concept_map` / `network_topology` |

---

## 通用约束

- 一张图只说一件事。想说两件事 → 拆成 (a)(b) 两个面板。
- 图元只用 box / arrow / polyline / band / label。
- 同排节点等高，同列节点等宽。
- 编号统一：面板 (a)(b)，步骤 ①②③ 或 1 2 3，别混。
