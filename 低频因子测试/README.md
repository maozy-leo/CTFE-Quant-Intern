# 低频因子测试

本目录提供三个入口，用于向低频服务发送因子命令：

- `low_freq_factor_test.py`：只发送 `TEST`
- `low_freq_factor_neu.py`：只发送 `NEU`
- `low_freq_factor_pipeline.py`：总控入口，支持 `test`、`neu`、`neu+test`

脚本不负责计算原始因子。原始因子需要已经写入 DolphinDB。

## 环境变量

脚本默认从项目根目录 `.env` 读取：

```dotenv
ip =
port = 
usr =
pwd =

LOW_FREQ_SERVICE_IP=
LOW_FREQ_SERVICE_PORT=
```

- `ip, port, usr, pwd`：DolphinDB 连接参数，会放入消息体。
- `LOW_FREQ_SERVICE_IP, LOW_FREQ_SERVICE_PORT`：低频服务地址。

## 只做 TEST

默认直接测试原始因子库 `dfs://factor_raw_intern`。

```bash
python 低频因子测试/low_freq_factor_test.py \
  --factor cj20260705_ret_overall_20d \
  --begin-date 20150105 \
  --end-date 20250722
```

等价总控写法：

```bash
python 低频因子测试/low_freq_factor_pipeline.py \
  --mode test \
  --factor cj20260705_ret_overall_20d \
  --begin-date 20150105 \
  --end-date 20250722
```

默认 TEST 参数：

- `factor_dbPath`: `dfs://factor_raw_intern`
- `results_dbPath`: `dfs://factor_results_intern`
- `pools`: `market 1000 500 300`
- `num_g`: `10`
- `ret_w`: `20`
- `buy_p`: `t1_open`
- `sell_p`: `t2_open`

## 只做 NEU

把原始因子从 `dfs://factor_raw_intern` 中性化到 `dfs://factor_intern`。

```bash
python 低频因子测试/low_freq_factor_neu.py \
  --factor close_volume_corr \
  --begin-date 20100101 \
  --end-date 20240628
```

等价总控写法：

```bash
python 低频因子测试/low_freq_factor_pipeline.py \
  --mode neu \
  --factor close_volume_corr \
  --begin-date 20100101 \
  --end-date 20240628
```

发送的 NEU 消息格式：

```json
{
  "ip": "192.168.3.99",
  "port": 7902,
  "user": "mzy",
  "passwd": "******",
  "command": "NEU",
  "factor": "close_volume_corr",
  "beginDate": "20100101",
  "endDate": "20240628",
  "factor_raw_dbPath": "dfs://factor_raw_intern",
  "factor_dbPath": "dfs://factor_intern"
}
```

## NEU + TEST

先中性化，再测试中性化后的因子。

```bash
python 低频因子测试/low_freq_factor_pipeline.py \
  --mode neu+test \
  --factor close_volume_corr \
  --begin-date 20100101 \
  --end-date 20240628
```

`neu+test` 的默认行为：

1. 发送 `NEU`：`dfs://factor_raw_intern/{factor}` -> `dfs://factor_intern/{factor}`
2. 发送 `TEST`：测试 `dfs://factor_intern/{factor}`

如果你想在 `neu+test` 中改测试来源，可以使用：

```bash
--test-factor-db-path dfs://factor_raw_intern
```

## 只打印命令

所有入口都支持 `--dry-run`：

```bash
python 低频因子测试/low_freq_factor_pipeline.py \
  --mode neu+test \
  --factor close_volume_corr \
  --begin-date 20100101 \
  --end-date 20240628 \
  --dry-run
```

`--dry-run` 只打印 JSON，不连接低频服务。

## 常用参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--mode` | `test` | 总控脚本模式：`test`、`neu`、`neu+test` |
| `--factor` | 必填 | 因子表名，只允许字母、数字、下划线 |
| `--begin-date` | 可选；NEU 必填 | 开始日期，支持 `YYYYMMDD`、`YYYY-MM-DD`、`YYYY.MM.DD` |
| `--end-date` | 可选；NEU 必填 | 结束日期，支持 `YYYYMMDD`、`YYYY-MM-DD`、`YYYY.MM.DD` |
| `--env-file` | `.env` | 环境变量文件路径 |
| `--factor-raw-db-path` | `dfs://factor_raw_intern` | NEU 的原始因子库；总控 `test` 模式默认也用它作为测试因子库 |
| `--factor-db-path` | `dfs://factor_intern` | NEU 的输出因子库；总控 `neu+test` 模式默认用它作为测试因子库 |
| `--test-factor-db-path` | 见说明 | 仅总控脚本可用，用于覆盖 TEST 使用的因子库 |
| `--factor-db-path` | `dfs://factor_raw_intern` | 仅 `low_freq_factor_test.py` 中可用，表示 TEST 使用的因子库 |
| `--results-db-path` | `dfs://factor_results_intern` | 测试结果库 |
| `--pools` | `market 1000 500 300` | 股票池，可传多个 |
| `--num-g` | `10` | 分组数量 |
| `--ret-w` | `20` | 调仓/持有周期 |
| `--buy-p` | `t1_open` | 买入价格点 |
| `--sell-p` | `t2_open` | 卖出价格点 |
| `--dry-run` | 关闭 | 只打印 JSON，不发送命令 |

## 结果表

测试完成后，结果写入 `dfs://factor_results_intern`。常见后缀：

- `__nav`：分组净值和相对表现
- `__metric`：年度/汇总绩效指标
- `__rankic`：每日 RankIC
- `__port`：组合持仓明细

## 注意事项

- 直接测试原始因子：使用 `low_freq_factor_test.py` 或总控 `--mode test`。
- 测试中性化因子：先跑 `low_freq_factor_neu.py`，再用 `low_freq_factor_test.py --factor-db-path dfs://factor_intern`；或直接使用总控 `--mode neu+test`。
- 低频服务地址不通过命令行传入，统一从 `.env` 的 `LOW_FREQ_SERVICE_IP/LOW_FREQ_SERVICE_PORT` 读取。
