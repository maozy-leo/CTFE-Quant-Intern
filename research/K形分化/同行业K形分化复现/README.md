# 同行业 K 形分化复现

本目录打包了“同行业内股票 K 形分化”研究的完整成果，包括：

- 服务器端计算脚本
- 本地汇总与可视化脚本
- 已生成的 CSV 结果、Markdown 摘要和图片

核心问题是复现观察：近期同一行业内部，不同股票表现出现明显分叉，一部分股票显著跑赢行业，另一部分显著跑输行业。

## 方法概览

对每个交易日、每个行业、每个收益窗口 `W`：

1. 计算个股 `W` 日对数收益：

```text
ret_i = log(price_i,t / price_i,t-W)
```

2. 计算行业收益。默认使用行业内股票的 `FREE_MV` 加权平均收益：

```text
industry_ret = sum(ret_i * FREE_MV_i) / sum(FREE_MV_i)
```

3. 计算个股行业内超额收益：

```text
excess_ret_i = ret_i - industry_ret
```

4. 在行业内部按照 `excess_ret_i` 排序，默认：

```text
top    = 行业内前 20% 股票
bottom = 行业内后 20% 股票
```

5. 定义 K 形分化指标：

```text
k_spread = top_mean_excess - bottom_mean_excess
k_score  = k_spread if top_mean_excess > 0 and bottom_mean_excess < 0 else 0
```

`k_score` 要求行业内部“上分支为正、下分支为负”，更贴近 K 形分化的直觉。

## 数据来源

脚本读取 DolphinDB 的日频数据，并把核心计算下推到 DolphinDB 服务器端完成。
Python 只负责按日期分块提交脚本、接收聚合结果、写本地 CSV。

用到的表：

- `dfs://trade_data_wy/stock_price`
  - `S_DQ_ADJCLOSE`：计算收益，缺失时回退到 `S_DQ_CLOSE`
  - `S_DQ_CLOSE`：收益价格备用字段
  - `FREE_MV`：行业收益加权字段
  - `S_DQ_AMOUNT`：可选流动性过滤
  - `UP_DOWN_LIMIT_STATUS`：可选剔除涨跌停
  - `st`：默认剔除 ST
  - `listed_days`：默认剔除上市未满 60 天股票
- `dfs://trade_data_wy/stock_ind`
  - 默认 `facname=swind2`，即申万二级行业

## 代码说明

### 1. `calc_industry_k_shape.py`

这是主计算脚本，用来连接 DolphinDB、在服务器端计算 K 形分化指标，并把结果表写到本地。

它做的事情：

1. 从 `.env` 读取 DolphinDB 连接信息：`ip`、`port`、`usr`、`pwd`。
2. 按 `--chunk-calendar-days` 拆分输出日期区间，默认每次只计算 31 个自然日，避免一次性读取太多数据。
3. 对每个 chunk 和每个 `window`，在 DolphinDB 服务器端完成：
   - 读取 `stock_price` 和 `stock_ind`
   - 把日频长表聚合成每个 `date × secid` 的宽表
   - 做 ST、上市天数、成交额、涨跌停过滤
   - 用 `move(log(price), window)` 计算窗口收益
   - 计算行业收益、行业内超额收益、行业内分位排名
   - 计算 `k_score`、`k_pct`、`k_zscore` 等指标
   - 筛出最新截面的 top/bottom 股票明细
4. Python 端只接收小的汇总表和明细表，并写成本地 CSV。

常用运行方式：

```bash
conda run --no-capture-output -n CTFE python -u \
  research/K形分化/同行业K形分化复现/calc_industry_k_shape.py \
  --begin-date 20210101 \
  --end-date 20260623 \
  --windows 3 \
  --output-dir research/K形分化/同行业K形分化复现/output/20210101_20260623_w3
```

运行 20 日窗口：

```bash
conda run --no-capture-output -n CTFE python -u \
  research/K形分化/同行业K形分化复现/calc_industry_k_shape.py \
  --begin-date 20210101 \
  --end-date 20260623 \
  --windows 20 \
  --output-dir research/K形分化/同行业K形分化复现/output/20210101_20260623_w20
```

同时运行多个窗口：

```bash
conda run --no-capture-output -n CTFE python -u \
  research/K形分化/同行业K形分化复现/calc_industry_k_shape.py \
  --begin-date 20210101 \
  --end-date 20260623 \
  --windows 3 5 20 \
  --output-dir research/K形分化/同行业K形分化复现/output/20210101_20260623_w3_w5_w20
```

常用参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--begin-date` | 数据最新日前 120 个自然日 | 输出开始日期，格式 `YYYYMMDD` |
| `--end-date` | DolphinDB 最新可用交易日 | 输出结束日期，格式 `YYYYMMDD` |
| `--windows` | `5 20 60` | 收益窗口，单位为交易日 |
| `--industry-facname` | `swind2` | 行业分类字段，可换成 `swind`、`ind`、`ind2` 等 |
| `--top-pct` | `0.20` | 行业内 top/bottom 分组比例 |
| `--min-stocks` | `10` | 行业有效股票数下限 |
| `--hist-lookback` | `252` | `k_pct`、`k_zscore` 的历史窗口长度 |
| `--min-history` | `60` | 历史统计所需最小样本数 |
| `--min-listed-days` | `60` | 上市天数过滤 |
| `--min-amount` | `0` | 成交额过滤，单位按 `S_DQ_AMOUNT` 原字段 |
| `--exclude-limit-status` | 关闭 | 开启后剔除涨跌停状态非 0 的样本 |
| `--buffer-calendar-days` | `540` | 每个 chunk 向前多读取的自然日，用于收益和历史统计 |
| `--chunk-calendar-days` | `31` | 单次 DolphinDB 请求覆盖的输出自然日长度 |
| `--save-all-constituents` | 关闭 | 开启后保存全区间 top/bottom 股票明细 |
| `--output-dir` | `output` | 本地结果输出目录 |

内存管理建议：

- 如果区间很长或服务器压力较大，优先调小 `--chunk-calendar-days`，例如 `10`。
- `--buffer-calendar-days` 不能太短，需要覆盖最大收益窗口和历史统计窗口。
- 默认不会把原始日频面板拉回本地，只返回汇总表和最新 top/bottom 明细。

### 2. `summarize_k_shape_results.py`

这是主汇总和可视化脚本，用来读取 `calc_industry_k_shape.py` 生成的 CSV，并生成报告和基础图表。

它做的事情：

1. 读取：
   - `industry_k_shape_summary.csv`
   - `industry_k_shape_latest_summary.csv`
   - `industry_k_shape_latest_constituents.csv`
2. 生成 `k_shape_summary.md`，包含：
   - 样本区间
   - 最新截面日期
   - 最新强 K 形行业数量
   - 最新 top 行业表格
   - 最新 top 行业的 top/bottom 股票腿
3. 生成基础图片：
   - `figures/latest_top_k_shape_industries.png`
   - `figures/k_shape_breadth_timeseries.png`
   - `figures/k_score_timeseries_top_industries_{window}d.png`

运行方式：

```bash
conda run --no-capture-output -n CTFE python \
  research/K形分化/同行业K形分化复现/summarize_k_shape_results.py \
  --output-dir research/K形分化/同行业K形分化复现/output/20210101_20260623_w3
```

如果是 `window=20` 的结果：

```bash
conda run --no-capture-output -n CTFE python \
  research/K形分化/同行业K形分化复现/summarize_k_shape_results.py \
  --output-dir research/K形分化/同行业K形分化复现/output/20210101_20260623_w20
```

### 3. `plot_k_shape_long_window.py`

这是补充可视化脚本，适合较长样本区间，用来生成月度层面的宽度图和最新 top/bottom 超额收益拆解图。

它生成：

- `figures/monthly_k_shape_breadth.png`
  - 每月平均每天有多少个强 K 形行业
  - 同时画出全行业 `k_score` 中位数
- `figures/latest_top_bottom_excess_split.png`
  - 最新截面 top 行业中，top leg 与 bottom leg 的平均超额收益拆解

运行方式：

```bash
conda run --no-capture-output -n CTFE python \
  research/K形分化/同行业K形分化复现/plot_k_shape_long_window.py \
  --output-dir research/K形分化/同行业K形分化复现/output/20210101_20260623_w20
```

## 输出表说明

每个结果目录都包含三张核心 CSV。

### `industry_k_shape_summary.csv`

全区间行业日度指标。每行是：

```text
date × industry × window
```

重点列：

| 列 | 含义 |
| --- | --- |
| `date` | 交易日 |
| `industry` | 行业名 |
| `window` | 收益窗口 |
| `n_stock` | 行业内有效股票数 |
| `industry_ret` | 行业窗口收益 |
| `top_mean_excess` | 行业内 top 组平均超额收益 |
| `bottom_mean_excess` | 行业内 bottom 组平均超额收益 |
| `k_spread` | `top_mean_excess - bottom_mean_excess` |
| `k_score` | K 形分化强度 |
| `k_pct` | 当前 `k_score` 在历史窗口中的分位数 |
| `k_zscore` | 当前 `k_score` 相对历史均值/波动的标准化值 |
| `positive_ratio` | 行业内超额收益为正的股票比例 |
| `negative_ratio` | 行业内超额收益为负的股票比例 |

### `industry_k_shape_latest_summary.csv`

最新截面行业排名。适合直接看“当前哪些行业分化最强”。

### `industry_k_shape_latest_constituents.csv`

最新截面 top/bottom 股票明细。适合追踪具体是哪批股票构成 K 形两端。

## 已打包结果

### `output/20240101_20260623_w3`

2024-2026、3 日窗口结果。

主要结论：

- 最新截面日期：`2026-06-23`
- 最新强 K 行业数：`27`
- 近期头部行业包括：小金属、橡胶、服装家纺、非金属材料Ⅱ、照明设备Ⅱ

### `output/20210101_20260623_w3`

2021-2026、3 日窗口长样本结果。

主要结论：

- 最新截面强 K 行业数：`27`
- `2026-05`、`2026-06` 分化明显抬升
- 但 3 日窗口下，历史最极端月份仍是 `2024-02`

### `output/20210101_20260623_w20`

2021-2026、20 日窗口结果。

主要结论：

- 最新截面强 K 行业数：`33`
- 最新头部行业包括：服装家纺、小金属、非白酒、商用车、煤炭开采、其他电子Ⅱ、化学制品、轨交设备Ⅱ
- 20 日窗口显示近期分化已经扩散到月度维度
- `2026-06` 是 2021 以来仅次于 `2024-02` 的显著分化期

## 文件结构

```text
同行业K形分化复现/
├── README.md
├── calc_industry_k_shape.py
├── summarize_k_shape_results.py
├── plot_k_shape_long_window.py
└── output/
    ├── README.md
    ├── industry_k_shape_summary.csv
    ├── industry_k_shape_latest_summary.csv
    ├── industry_k_shape_latest_constituents.csv
    ├── k_shape_summary.md
    ├── figures/
    │   ├── latest_top_k_shape_industries.png
    │   ├── k_shape_breadth_timeseries.png
    │   ├── monthly_k_shape_breadth.png
    │   ├── latest_top_bottom_excess_split.png
    │   └── k_score_timeseries_top_industries_3d.png
    ├── 20240101_20260623_w3/
    │   ├── industry_k_shape_summary.csv
    │   ├── industry_k_shape_latest_summary.csv
    │   ├── industry_k_shape_latest_constituents.csv
    │   ├── k_shape_summary.md
    │   └── figures/
    ├── 20210101_20260623_w3/
    │   ├── industry_k_shape_summary.csv
    │   ├── industry_k_shape_latest_summary.csv
    │   ├── industry_k_shape_latest_constituents.csv
    │   ├── k_shape_summary.md
    │   └── figures/
    └── 20210101_20260623_w20/
        ├── industry_k_shape_summary.csv
        ├── industry_k_shape_latest_summary.csv
        ├── industry_k_shape_latest_constituents.csv
        ├── k_shape_summary.md
        └── figures/
```

根目录 `output/` 下直接放着最近一次运行的结果；三个按时间窗口命名的子目录是归档结果，优先使用子目录中的文件。
