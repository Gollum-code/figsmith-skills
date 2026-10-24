# paper-figure · 数据冻结纪律

> 统计图的数字只有一个来源：**冻结表**。IR 里不写数字，只写「从哪张表的哪几列取」。
> 这条规则的机器执行点在 `backends/mpl2svg.resolve_series()` 与 `core/ir.py` 校验器。

---

## 1. 为什么冻结

图表被手改一次，就再也没法和数据对账。图上的每个点都必须能追溯回一行数据：

```
冻结表（CSV） → columns 声明 → mpl2svg 取数 → SVG/PNG/PDF/PPTX
```

IR 里内联 `x`/`y` 的写法已不被接受：校验器会直接报错（IR 2.6）。原因很简单——
声明了 `source` 却内联数字，等于「数据源」是装饰，图表可以在没人注意时漂移。

## 2. 最小可用形态

`data/trials.csv`：

```csv
condition,experiment_mean,experiment_sd,control_mean,control_sd,n
baseline,0.121,0.031,0.118,0.029,32
low_dose,0.284,0.042,0.131,0.034,32
```

IR：

```jsonc
"data": {
  "source": "data/trials.csv",                  // 相对本 IR 文件解析，换目录也能再生
  "categories": ["baseline", "low_dose"],       // 可省略：x 列是分类名时自动取
  "series": [
    { "name": "Experiment",
      "columns": { "x": "condition", "y": "experiment_mean", "yerr": "experiment_sd" },
      "error_kind": "SD" }
  ]
}
```

## 3. 三条硬规则

1. **`columns` 至少声明 `x` 与 `y`。** 有误差棒时 `yerr` 也必填，且 `error_kind`
   必须是 `CI` / `SD` / `SE` 之一——校验器不放行缺 `error_kind` 的 `yerr`。
2. **分类列自动按位置取数。** `x` 列是字符串（`baseline`、`low_dose`）时按行序
   映射为 0..n-1，并把原值作为刻度标签；是数字时按数值定位。
3. **表变了就重跑。** 改 CSV 后必须重新渲染，产物才算数与源一致。不要手工挪点。

## 4. 常见失败

| 报错 | 根因 | 修法 |
|---|---|---|
| `columns ... not in data.csv` | 列名拼错 | 对照 CSV 表头 |
| `column 'x' is not numeric` | x 列本意是分类，却被当成数值列用 | 无需修：分类列会自动按位置取数；若是真数值列则检查数据 |
| `inlines x/y while data.source is declared` | IR 里既有 source 又有数字 | 删掉内联数组，改用 `columns` |
| `declares columns but data.source is unset` | 只有列名没有表 | 补 `data.source` |
| `data.source not found` | 相对路径基准错 | 路径相对 IR 文件，不是相对 cwd |

## 5. 验收

```bash
python -m core.ir figure.ir.json          # 数据层结构 + 冻结表声明
python -m backends.mpl2svg figure.ir.json -o figure.svg --png figure.png
python -m core.verify.check_contrast figure.png
python -m core.verify.check_overflow figure.ir.json
```

数值、单位、样本量、显著性标注仍然**人工核对**——脚本只能证明图和表一致，
不能证明表本身是对的。
