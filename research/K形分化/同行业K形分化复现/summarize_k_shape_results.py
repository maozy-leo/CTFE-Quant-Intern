from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent


def setup_plot_style() -> None:
    plt.rcParams["font.sans-serif"] = [
        "Arial Unicode MS",
        "PingFang SC",
        "Heiti SC",
        "SimHei",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.dpi"] = 140


def load_data(output_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summary = pd.read_csv(output_dir / "industry_k_shape_summary.csv", parse_dates=["date"])
    latest = pd.read_csv(output_dir / "industry_k_shape_latest_summary.csv", parse_dates=["date"])
    constituents = pd.read_csv(output_dir / "industry_k_shape_latest_constituents.csv", parse_dates=["date"])
    return summary, latest, constituents


def top_latest_table(latest: pd.DataFrame, window: int, n: int = 10) -> pd.DataFrame:
    cols = [
        "date",
        "window",
        "industry",
        "n_stock",
        "industry_ret",
        "top_mean_excess",
        "bottom_mean_excess",
        "k_score",
        "k_pct",
        "k_zscore",
        "positive_ratio",
        "negative_ratio",
    ]
    data = latest.loc[latest["window"].eq(window)].copy()
    return data.sort_values(["k_pct", "k_score"], ascending=[False, False]).head(n)[cols]


def plot_latest_bars(latest: pd.DataFrame, fig_dir: Path) -> Path:
    windows = sorted(latest["window"].unique())
    fig, axes = plt.subplots(len(windows), 1, figsize=(10, 4.2 * len(windows)), constrained_layout=True)
    if len(windows) == 1:
        axes = [axes]

    for ax, window in zip(axes, windows):
        data = top_latest_table(latest, window, n=12).sort_values("k_score")
        colors = ["#4C78A8" if pct < 1 else "#E45756" for pct in data["k_pct"]]
        ax.barh(data["industry"], data["k_score"], color=colors)
        ax.set_title(f"Latest Top K-Shape Industries, {window}D Window")
        ax.set_xlabel("k_score")
        ax.grid(axis="x", alpha=0.25)
        for y, (_, row) in enumerate(data.iterrows()):
            ax.text(row["k_score"], y, f"  pct={row['k_pct']:.2f}", va="center", fontsize=8)

    path = fig_dir / "latest_top_k_shape_industries.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_breadth(summary: pd.DataFrame, fig_dir: Path) -> Path:
    breadth = (
        summary.assign(
            high_k=lambda x: (x["k_score"].gt(0) & x["k_pct"].ge(0.9) & x["k_zscore"].ge(2)).astype(int)
        )
        .groupby(["date", "window"], as_index=False)
        .agg(high_industries=("high_k", "sum"), median_k_score=("k_score", "median"))
    )

    windows = sorted(breadth["window"].unique())
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True, constrained_layout=True)

    for window in windows:
        data = breadth.loc[breadth["window"].eq(window)]
        axes[0].plot(data["date"], data["high_industries"], label=f"{window}D")
        axes[1].plot(data["date"], data["median_k_score"], label=f"{window}D")

    axes[0].set_title("Breadth of Strong K-Shape Divergence")
    axes[0].set_ylabel("# industries")
    axes[0].grid(alpha=0.25)
    axes[0].legend()
    axes[1].set_title("Cross-Industry Median k_score")
    axes[1].set_ylabel("median k_score")
    axes[1].grid(alpha=0.25)
    axes[1].legend()

    path = fig_dir / "k_shape_breadth_timeseries.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_top_industry_timeseries(summary: pd.DataFrame, latest: pd.DataFrame, fig_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for window in sorted(summary["window"].unique()):
        top_inds = top_latest_table(latest, window, n=6)["industry"].tolist()
        data = summary.loc[summary["window"].eq(window) & summary["industry"].isin(top_inds)]

        fig, ax = plt.subplots(figsize=(11, 5), constrained_layout=True)
        for industry, group in data.groupby("industry"):
            group = group.sort_values("date")
            ax.plot(group["date"], group["k_score"], label=industry, linewidth=1.7)

        ax.set_title(f"k_score Time Series for Latest Top Industries, {window}D Window")
        ax.set_ylabel("k_score")
        ax.grid(alpha=0.25)
        ax.legend(ncol=2, fontsize=8)

        path = fig_dir / f"k_score_timeseries_top_industries_{window}d.png"
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        paths.append(path)
    return paths


def format_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def write_report(
    summary: pd.DataFrame,
    latest: pd.DataFrame,
    constituents: pd.DataFrame,
    figure_paths: list[Path],
    report_path: Path,
) -> None:
    date_min = summary["date"].min().strftime("%Y-%m-%d")
    date_max = summary["date"].max().strftime("%Y-%m-%d")
    windows = ", ".join(str(x) for x in sorted(summary["window"].unique()))

    lines: list[str] = [
        "# 同行业 K 形分化结果速览",
        "",
        f"- 样本区间：{date_min} 至 {date_max}",
        f"- 窗口：{windows} 个交易日",
        f"- 行业数/窗口/日期记录：{len(summary):,} 行",
        f"- 最新截面日期：{latest['date'].max().strftime('%Y-%m-%d')}",
        "",
        "## 最新截面头部行业",
        "",
    ]

    for window in sorted(latest["window"].unique()):
        top = top_latest_table(latest, window, n=10)
        high_count = latest.loc[
            latest["window"].eq(window)
            & latest["k_score"].gt(0)
            & latest["k_pct"].ge(0.9)
            & latest["k_zscore"].ge(2)
        ].shape[0]
        lines.append(f"### {window}D")
        lines.append("")
        lines.append(f"- 强 K 形行业数：{high_count}")
        lines.append("")
        lines.append("| rank | industry | n | k_score | k_pct | k_zscore | top_excess | bottom_excess | industry_ret |")
        lines.append("| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for rank, (_, row) in enumerate(top.iterrows(), start=1):
            lines.append(
                "| "
                f"{rank} | {row['industry']} | {int(row['n_stock'])} | "
                f"{row['k_score']:.4f} | {row['k_pct']:.3f} | {row['k_zscore']:.2f} | "
                f"{format_pct(row['top_mean_excess'])} | {format_pct(row['bottom_mean_excess'])} | "
                f"{format_pct(row['industry_ret'])} |"
            )
        lines.append("")

    lines.extend(["## 最新头部行业的股票腿", ""])
    for window in sorted(latest["window"].unique()):
        first_industry = top_latest_table(latest, window, n=1)["industry"].iloc[0]
        subset = constituents.loc[
            constituents["window"].eq(window) & constituents["industry"].eq(first_industry)
        ].copy()
        top_leg = subset.loc[subset["group"].eq("top")].sort_values("excess_ret", ascending=False).head(5)
        bottom_leg = subset.loc[subset["group"].eq("bottom")].sort_values("excess_ret").head(5)
        lines.append(f"### {window}D：{first_industry}")
        lines.append("")
        lines.append("Top leg: " + ", ".join(f"{r.secid}({format_pct(r.excess_ret)})" for r in top_leg.itertuples()))
        lines.append("")
        lines.append("Bottom leg: " + ", ".join(f"{r.secid}({format_pct(r.excess_ret)})" for r in bottom_leg.itertuples()))
        lines.append("")

    lines.extend(["## 图表", ""])
    for path in figure_paths:
        lines.append(f"- {path.name}")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize and plot K-shape divergence CSV outputs.")
    parser.add_argument(
        "--output-dir",
        default=str(BASE_DIR / "output"),
        help="Directory containing industry_k_shape_*.csv and receiving figures/report.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    fig_dir = output_dir / "figures"
    report_path = output_dir / "k_shape_summary.md"

    setup_plot_style()
    fig_dir.mkdir(parents=True, exist_ok=True)

    summary, latest, constituents = load_data(output_dir)
    figure_paths = [
        plot_latest_bars(latest, fig_dir),
        plot_breadth(summary, fig_dir),
        *plot_top_industry_timeseries(summary, latest, fig_dir),
    ]
    write_report(summary, latest, constituents, figure_paths, report_path)

    print(f"wrote report: {report_path}")
    for path in figure_paths:
        print(f"wrote figure: {path}")


if __name__ == "__main__":
    main()
