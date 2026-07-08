# CTFE Quant Intern Utilities

本仓库目前包含因子 IC 统计与绘图工具。

## Cumulative IC 绘图

脚本位置：

```bash
utils/cumulative_ic.py
```

输入 CSV 需要包含两列：

```csv
date,rankic
2026.01.01,0.0123
2026.01.02,-0.0045
```

默认输出目录为：

```bash
output/cumulative_ic_pictures
```

如果不指定 `--output`，默认图片文件名为：

```bash
{factor_name}_cumulative_ic.png
```

其中 `factor_name` 可通过 `--factor-name` 指定；未指定时，单个 CSV 默认使用 CSV 文件名去掉扩展名，多个 CSV 默认使用各文件名用 `_` 拼接。

### 单个因子

```bash
python utils/cumulative_ic.py factor_a.csv \
  --date-format %Y.%m.%d \
  --start 2024.01.01 \
  --end 2026.06.30
```

上面的命令会输出：

```bash
output/cumulative_ic_pictures/factor_a_cumulative_ic.png
```

### 指定因子名

```bash
python utils/cumulative_ic.py factor_a.csv \
  --factor-name my_factor \
  --date-format %Y.%m.%d
```

输出：

```bash
output/cumulative_ic_pictures/my_factor_cumulative_ic.png
```

### 多个因子对比

```bash
python utils/cumulative_ic.py factor_a.csv factor_b.csv factor_c.csv \
  --labels factor_a factor_b factor_c \
  --factor-name factor_compare \
  --date-format %Y.%m.%d \
  --start 2024.01.01 \
  --end 2026.06.30
```

输出：

```bash
output/cumulative_ic_pictures/factor_compare_cumulative_ic.png
```

### 指定完整输出路径

`--output` 会覆盖默认目录和默认文件名：

```bash
python utils/cumulative_ic.py factor_a.csv \
  --output output/custom_name.png
```

### 参数说明

- `csv_files`：一个或多个输入 CSV 文件，必须包含 `date`、`rankic` 两列。
- `--start`：起始日期，包含该日期。
- `--end`：终止日期，包含该日期。
- `--date-format`：日期格式，例如 `%Y.%m.%d`。
- `--labels`：多个因子曲线的显示名称，可用空格或逗号分隔；默认使用 CSV 文件名。
- `--factor-name`：默认输出文件名中的因子名。
- `--output-dir`：默认输出目录，默认为 `output/cumulative_ic_pictures`。
- `--output`：完整输出图片路径。
- `--flip-sign`：使用 `-rankic` 作为 IC。
