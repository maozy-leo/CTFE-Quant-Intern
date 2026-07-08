from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    import pandas as pd


DEFAULT_OUTPUT_DIR = Path("output/cumulative_ic_pictures")


def _import_pandas():
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "pandas is required to read rankic csv files. "
            "Please install pandas in the Python environment running this script."
        ) from exc
    return pd


def _parse_date_series(series: pd.Series, date_format: str | None = None) -> pd.Series:
    pd = _import_pandas()
    dates = pd.to_datetime(series, format=date_format, errors="coerce")
    if dates.isna().any():
        bad_values = series[dates.isna()].head(5).tolist()
        raise ValueError(f"Cannot parse date values: {bad_values}")
    return dates


def load_rankic_csv(
    csv_path: str | Path,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    date_format: str | None = None,
    flip_sign: bool = False,
) -> pd.DataFrame:
    """Load one rankic csv and calculate filtered IC/cumulative IC series."""
    pd = _import_pandas()
    csv_path = Path(csv_path)
    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    required_columns = {"date", "rankic"}
    missing_columns = required_columns.difference(df.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"{csv_path} is missing required column(s): {missing}")

    out = df.loc[:, ["date", "rankic"]].copy()
    out["date"] = _parse_date_series(out["date"], date_format=date_format)
    out["ic"] = pd.to_numeric(out["rankic"], errors="coerce")
    if out["ic"].isna().any():
        bad_values = out.loc[out["ic"].isna(), "rankic"].head(5).tolist()
        raise ValueError(f"{csv_path} has non-numeric rankic values: {bad_values}")

    if flip_sign:
        out["ic"] = -out["ic"]

    out = out.sort_values("date")
    if start_date:
        start = pd.to_datetime(start_date, format=date_format)
        out = out[out["date"] >= start]
    if end_date:
        end = pd.to_datetime(end_date, format=date_format)
        out = out[out["date"] <= end]

    if out.empty:
        raise ValueError(f"{csv_path} has no rows after applying the date filter")

    out["cumulative_ic"] = out["ic"].cumsum()
    return out.reset_index(drop=True)


def summarize_ic(data: pd.DataFrame, label: str) -> dict[str, float | int | str]:
    mean = data["ic"].mean()
    std = data["ic"].std()
    ir = mean / std if std != 0 else float("nan")
    return {
        "factor": label,
        "mean_ic": mean,
        "std_ic": std,
        "ic_ir": ir,
        "ann_icir": ir * (252**0.5),
        "winrate": (data["ic"] > 0).mean(),
        "n": len(data),
        "sum_ic": data["ic"].sum(),
    }


def plot_ic_series(
    series_list: Sequence[pd.DataFrame],
    labels: Sequence[str],
    output_path: str | Path,
    *,
    title: str = "Rank IC and Cumulative Rank IC",
) -> Path:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "matplotlib is required to draw IC plots. "
            "Please install matplotlib in the Python environment running this script."
        ) from exc

    if len(series_list) != len(labels):
        raise ValueError("series_list and labels must have the same length")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig, (ax_cum, ax_ic) = plt.subplots(
        2,
        1,
        figsize=(13, 8),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1]},
    )

    for data, label in zip(series_list, labels):
        ax_cum.plot(data["date"], data["cumulative_ic"], lw=1.6, label=label)

    ax_cum.set_title(title, fontsize=12)
    ax_cum.set_ylabel("Cumulative IC")
    ax_cum.grid(alpha=0.3)
    ax_cum.axhline(0, color="k", lw=0.8)
    ax_cum.legend(loc="best", fontsize=9)

    if len(series_list) == 1:
        data = series_list[0]
        colors = ["#d1383a" if value < 0 else "#2a9d5c" for value in data["ic"]]
        ax_ic.bar(data["date"], data["ic"], width=1.5, color=colors, alpha=0.7)
    else:
        for data, label in zip(series_list, labels):
            ax_ic.plot(data["date"], data["ic"], lw=1.0, alpha=0.8, label=label)
        ax_ic.legend(loc="best", fontsize=9)

    ax_ic.axhline(0, color="k", lw=0.8)
    ax_ic.set_ylabel("IC")
    ax_ic.grid(alpha=0.3)
    ax_ic.xaxis.set_major_locator(mdates.YearLocator())
    ax_ic.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    plt.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def _labels_from_args(
    csv_paths: Sequence[Path], labels_arg: Sequence[str] | None
) -> list[str]:
    if labels_arg is None:
        return [path.stem for path in csv_paths]

    labels = [
        label.strip()
        for label_group in labels_arg
        for label in label_group.split(",")
        if label.strip()
    ]
    if len(labels) != len(csv_paths):
        raise ValueError("--labels must contain the same number of names as csv files")
    return labels


def _default_factor_name(csv_paths: Sequence[Path]) -> str:
    stems = [path.stem for path in csv_paths]
    if len(stems) == 1:
        return stems[0]
    return "_".join(stems)


def _output_path_from_args(args: argparse.Namespace, csv_paths: Sequence[Path]) -> Path:
    if args.output is not None:
        return args.output

    factor_name = args.factor_name or _default_factor_name(csv_paths)
    return args.output_dir / f"{factor_name}_cumulative_ic.png"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot IC and cumulative IC from one or more csv files.",
    )
    parser.add_argument(
        "csv_files",
        nargs="+",
        type=Path,
        help="Input csv file(s). Required columns: date, rankic.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Full output image path. Overrides --output-dir and --factor-name.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory used when --output is not set. "
        "Default: output/cumulative_ic_pictures",
    )
    parser.add_argument(
        "--factor-name",
        help="Factor name used in the default output filename. "
        "Defaults to the csv file stem; for multiple csv files, stems are joined by '_'.",
    )
    parser.add_argument("--start", dest="start_date", help="Start date, inclusive.")
    parser.add_argument("--end", dest="end_date", help="End date, inclusive.")
    parser.add_argument(
        "--date-format",
        help="Optional pandas datetime format, for example %%Y.%%m.%%d.",
    )
    parser.add_argument(
        "--labels",
        nargs="+",
        help="Factor names, separated by spaces or commas. Defaults to input file stems.",
    )
    parser.add_argument(
        "--flip-sign",
        action="store_true",
        help="Use -rankic as IC to match sign-flipped analysis.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    csv_paths = [Path(path) for path in args.csv_files]
    labels = _labels_from_args(csv_paths, args.labels)
    output_path = _output_path_from_args(args, csv_paths)

    try:
        series_list = [
            load_rankic_csv(
                path,
                start_date=args.start_date,
                end_date=args.end_date,
                date_format=args.date_format,
                flip_sign=args.flip_sign,
            )
            for path in csv_paths
        ]
    except ModuleNotFoundError as exc:
        raise SystemExit(str(exc)) from exc

    title = "Rank IC and Cumulative Rank IC"
    if args.start_date or args.end_date:
        start = args.start_date or series_list[0]["date"].min().strftime("%Y-%m-%d")
        end = args.end_date or series_list[0]["date"].max().strftime("%Y-%m-%d")
        title = f"{title} ({start} to {end})"
    if args.flip_sign:
        title = f"{title} (sign-flipped)"

    try:
        output_path = plot_ic_series(series_list, labels, output_path, title=title)
    except ModuleNotFoundError as exc:
        raise SystemExit(str(exc)) from exc

    pd = _import_pandas()
    summary = pd.DataFrame(
        summarize_ic(data, label) for data, label in zip(series_list, labels)
    )
    print(summary.round(4).to_string(index=False))
    print(f"Saved plot to: {output_path}")


if __name__ == "__main__":
    main()
