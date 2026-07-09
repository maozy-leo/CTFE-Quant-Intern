# 分化股票对 traction 年度/月度汇总

本目录脚本 `calc_pair_traction_period_avg.py` 用于在 DolphinDB 服务器端计算股票对 `traction` 的年度和月度均值，并为股票对两端分别匹配申万二级行业 `swind2`。

另有快速筛选脚本 `quick_screen_pair_divergence.py`，用于快速找出“长期 traction 较高、短期价格走势分歧”的股票对，并将结果输出到本地 CSV。

## 输入数据

默认读取以下 DolphinDB 表：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--traction-db-path` | `dfs://zxn_traction` | 股票对 traction 数据库路径 |
| `--traction-table` | `TracCorr_DailyRet` | 股票对 traction 表名 |
| `--industry-db-path` | `dfs://trade_data_wy` | 股票行业分类数据库路径 |
| `--industry-table` | `stock_ind` | 股票行业分类表名 |
| `--industry-facname` | `swind2` | 行业分类类型，默认申万二级行业 |

说明：项目现有代码中行业表路径为 `dfs://trade_data_wy` / `stock_ind`。如果服务器上实际使用单独库名 `dfs://trade_data_wy-stock_ind`，运行时可通过 `--industry-db-path dfs://trade_data_wy-stock_ind` 和相应 `--industry-table` 覆盖。

## 输出表

默认写入 `dfs://factor_intern` 下两张表：

| 表名 | 频率 | 主要字段 |
| --- | --- | --- |
| `kshape_pair_traction_yearly_avg` | 年度 | `date, year, secid, secid2, traction_avg, n_obs, secid_facname, secid_facvalue, secid2_facname, secid2_facvalue` |
| `kshape_pair_traction_monthly_avg` | 月度 | `date, year, month, secid, secid2, traction_avg, n_obs, secid_facname, secid_facvalue, secid2_facname, secid2_facvalue` |

字段含义：

| 字段 | 含义 |
| --- | --- |
| `date` | 聚合周期结束日。年度表为该年最后一个源表日期或 12 月 31 日；月度表为该月最后一个源表日期或月末 |
| `year` | 聚合年份 |
| `month` | 聚合月份，仅月度表包含 |
| `secid` | 股票对第一只股票代码 |
| `secid2` | 股票对第二只股票代码 |
| `traction_avg` | 该周期内 `traction` 的均值 |
| `n_obs` | 参与均值计算的有效日度观测数 |
| `secid_facname` | 第一只股票的行业分类类型，默认 `swind2` |
| `secid_facvalue` | 第一只股票的行业名称 |
| `secid2_facname` | 第二只股票的行业分类类型，默认 `swind2` |
| `secid2_facvalue` | 第二只股票的行业名称 |

行业匹配逻辑：脚本在每个年度或月度区间内，取该股票该周期最后一个有效 `facvalue` 作为该期行业。

## 运行前准备

脚本从 `.env` 读取 DolphinDB 连接信息，需要包含：

```dotenv
ip=...
port=...
usr=...
pwd=...
```

需要安装 Python 依赖：

```bash
pip install dolphindb pandas
```

## 基本运行方式

在项目根目录运行：

```bash
python3 "research/K形分化/分化股票对筛选/calc_pair_traction_period_avg.py"
```

默认行为：

- 自动读取 traction 源表的 `min(date)` 和 `max(date)` 作为计算区间。
- 同时生成年度表和月度表。
- 若目标表中已有同一周期 `date` 的数据，默认跳过该周期，只追加缺失周期。
- 所有聚合、行业匹配和写表都在 DolphinDB 服务器端完成。
- 年度表不会直接扫描全年明细，而是先按月聚合 `sum(traction)` 和 `count(traction)`，再合成为年度均值，避免触发 DolphinDB 单次查询 20 亿行限制。

## 常用示例

只计算指定日期范围：

```bash
python3 "research/K形分化/分化股票对筛选/calc_pair_traction_period_avg.py" \
  --begin-date 20150101 \
  --end-date 20251231
```

只计算年度表：

```bash
python3 "research/K形分化/分化股票对筛选/calc_pair_traction_period_avg.py" \
  --only year
```

只计算月度表：

```bash
python3 "research/K形分化/分化股票对筛选/calc_pair_traction_period_avg.py" \
  --only month
```

使用其他行业库路径：

```bash
python3 "research/K形分化/分化股票对筛选/calc_pair_traction_period_avg.py" \
  --industry-db-path "dfs://trade_data_wy-stock_ind" \
  --industry-table "stock_ind"
```

改写输出表名：

```bash
python3 "research/K形分化/分化股票对筛选/calc_pair_traction_period_avg.py" \
  --yearly-table "pair_traction_yearly_avg" \
  --monthly-table "pair_traction_monthly_avg"
```

保留已有同周期数据，直接追加：

```bash
python3 "research/K形分化/分化股票对筛选/calc_pair_traction_period_avg.py" \
  --append-only
```

重算已有周期，先删除同周期旧数据再写入：

```bash
python3 "research/K形分化/分化股票对筛选/calc_pair_traction_period_avg.py" \
  --replace-existing
```

## 参数说明

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `--begin-date` | 源表最早日期 | 计算开始日期，格式 `YYYYMMDD`、`YYYY-MM-DD`、`YYYY.MM.DD` 均可 |
| `--end-date` | 源表最晚日期 | 计算结束日期，格式同上 |
| `--env-file` | `.env` | DolphinDB 连接配置文件 |
| `--traction-db-path` | `dfs://zxn_traction` | traction 源数据库路径 |
| `--traction-table` | `TracCorr_DailyRet` | traction 源表名 |
| `--industry-db-path` | `dfs://trade_data_wy` | 行业分类数据库路径 |
| `--industry-table` | `stock_ind` | 行业分类表名 |
| `--industry-facname` | `swind2` | 用于匹配的行业分类类型 |
| `--output-db-path` | `dfs://factor_intern` | 输出数据库路径 |
| `--yearly-table` | `kshape_pair_traction_yearly_avg` | 年度汇总输出表名 |
| `--monthly-table` | `kshape_pair_traction_monthly_avg` | 月度汇总输出表名 |
| `--only` | `all` | 输出频率，可选 `all`、`year`、`month` |
| `--append-only` | 关闭 | 开启后不检查已有周期、不删除旧数据，直接追加，可能产生重复周期 |
| `--replace-existing` | 关闭 | 开启后删除目标表中同周期旧数据并重算；不能和 `--append-only` 同时使用 |

## 内存管理

脚本按自然年和自然月逐期提交 DolphinDB 任务，不一次性拉取全量数据到 Python。年度表内部进一步按月扫描源表：每个月先得到股票对层面的 `traction_sum` 和 `n_obs`，再滚动合并成年度累计结果，最后计算：

```text
traction_avg = sum(traction_sum) / sum(n_obs)
```

每个周期写表后，会在 DolphinDB 脚本内释放临时变量：

```dolphindb
undef(`tractionAgg`industryRaw`industryLatest`industryLatest2`result, VAR)
```

因此 Python 侧只负责提交脚本和控制日期区间，不承载大表计算结果。

## 快速筛选分歧股票对

`quick_screen_pair_divergence.py` 用于在不等待完整年度/月度结果全部入库的情况下，快速筛出一批候选股票对。

默认逻辑：

- 长期窗口：最近 12 个自然月。
- 长期相似：每月内部再按 5 个自然日分片聚合 `traction_sum` 和 `n_obs`，滚动合并为月度 `traction_avg`；只保留单月 `traction_avg >= 0.60` 且有效观测数不少于 10 的 pair-month。
- 行业约束：默认要求两只股票处于同一 `swind2` 行业。
- 候选压缩：按 `long_score = long_avg_traction * traction_hit_ratio / (1 + long_std_traction)` 选前 5000 对。
- 短期分歧：对候选股票池计算 20 日收益差和 1 年左右价差 z-score。
- 输出：按 `final_score = long_score * abs(spread_z) * abs(ret_diff_short)` 排序，默认输出前 100 对。

运行：

```bash
python3 "research/K形分化/分化股票对筛选/quick_screen_pair_divergence.py"
```

默认输出到：

```text
research/K形分化/分化股票对筛选/output/quick_pair_divergence_YYYYMMDD.csv
```

常用示例：

```bash
python3 "research/K形分化/分化股票对筛选/quick_screen_pair_divergence.py" \
  --end-date 20260630 \
  --long-months 12 \
  --traction-chunk-days 5 \
  --short-window 20 \
  --candidate-limit 5000 \
  --output-limit 100
```

放宽筛选条件：

```bash
python3 "research/K形分化/分化股票对筛选/quick_screen_pair_divergence.py" \
  --min-month-traction 0.50 \
  --min-long-avg-traction 0.60 \
  --min-hit-ratio 0.50 \
  --min-abs-spread-z 1.50 \
  --min-abs-ret-diff 0.03
```

允许跨行业股票对：

```bash
python3 "research/K形分化/分化股票对筛选/quick_screen_pair_divergence.py" \
  --allow-cross-industry
```

快速筛选脚本主要参数：

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `--end-date` | traction 和价格表最新共同日期 | 筛选截止日期 |
| `--output-dir` | `research/K形分化/分化股票对筛选/output` | 本地输出目录 |
| `--output-file` | 自动生成 | 指定本地 CSV 输出路径 |
| `--long-months` | `12` | 长期 traction 观察月数 |
| `--traction-chunk-days` | `5` | traction 源表单次聚合的自然日长度；调小可降低 DolphinDB 单次查询压力 |
| `--price-lookback-days` | `370` | 价差 z-score 使用的自然日回看长度 |
| `--short-window` | `20` | 短期收益差窗口，按交易日计算 |
| `--min-month-traction` | `0.60` | 单月 pair 进入长期候选池的 traction 阈值 |
| `--min-month-obs` | `10` | 单月 pair 最少有效日度观测数 |
| `--min-long-avg-traction` | `0.70` | 长期加权平均 traction 下限 |
| `--min-hit-ratio` | `0.60` | 满足单月 traction 阈值的月份占比下限 |
| `--min-abs-spread-z` | `2.0` | 价差 z-score 绝对值下限 |
| `--min-abs-ret-diff` | `0.05` | 短期收益差绝对值下限 |
| `--candidate-limit` | `5000` | 进入价格分歧计算的长期候选 pair 数量上限 |
| `--output-limit` | `100` | 本地 CSV 输出行数上限 |
| `--allow-cross-industry` | 关闭 | 开启后允许跨行业 pair |

快速筛选输出字段：

| 字段 | 含义 |
| --- | --- |
| `secid, secid2` | 股票对 |
| `secid_facvalue, secid2_facvalue` | 两只股票的行业 |
| `long_avg_traction` | 长期窗口内通过月度阈值的 pair-month 加权 traction 均值 |
| `long_std_traction` | 月度 traction 的标准差 |
| `traction_hit_ratio` | 满足单月阈值的月份数 / `long_months` |
| `n_obs_long` | 长期窗口有效日度观测数合计 |
| `price_date` | 价格分歧计算所用最新价格日期 |
| `ret_short_1, ret_short_2` | 两只股票短期对数收益 |
| `ret_diff_short` | 两只股票短期收益差 |
| `spread_z` | 当前对数价差相对历史价差的 z-score |
| `long_score` | 长期相似度得分 |
| `final_score` | 综合排序分数 |
