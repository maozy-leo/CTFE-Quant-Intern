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


def plot_monthly_breadth(summary: pd.DataFrame, fig_dir: Path) -> Path:
    data = summary.copy()
    data["month"] = data["date"].dt.to_period("M").dt.to_timestamp()
    data["strong_k"] = (
        data["k_score"].gt(0) & data["k_pct"].ge(0.9) & data["k_zscore"].ge(2)
    ).astype(int)
    monthly = (
        data.groupby("month", as_index=False)
        .agg(
            avg_strong_industries=("strong_k", "mean"),
            max_strong_industries=("strong_k", "sum"),
            avg_k_score=("k_score", "mean"),
            median_k_score=("k_score", "median"),
        )
    )
    # Convert the monthly mean of indicator across industry-days into average daily count.
    days_per_month = data.groupby("month")["date"].nunique().rename("n_days")
    n_industries = data.groupby("month")["industry"].nunique().rename("n_industries")
    monthly = monthly.merge(days_per_month, on="month").merge(n_industries, on="month")
    monthly["avg_daily_strong_industries"] = monthly["avg_strong_industries"] * monthly["n_industries"]

    fig, ax1 = plt.subplots(figsize=(12, 5), constrained_layout=True)
    ax1.bar(monthly["month"], monthly["avg_daily_strong_industries"], width=20, color="#4C78A8", alpha=0.78)
    ax1.set_ylabel("avg daily # strong K-shape industries")
    ax1.set_title("Monthly Breadth of Strong Same-Industry K-Shape Divergence")
    ax1.grid(axis="y", alpha=0.25)

    ax2 = ax1.twinx()
    ax2.plot(monthly["month"], monthly["median_k_score"], color="#E45756", marker="o", linewidth=1.5)
    ax2.set_ylabel("median k_score")

    path = fig_dir / "monthly_k_shape_breadth.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_latest_excess_split(latest: pd.DataFrame, fig_dir: Path) -> Path:
    data = latest.sort_values(["k_pct", "k_score"], ascending=[False, False]).head(15).copy()
    data = data.sort_values("k_score")
    window_label = ",".join(str(x) for x in sorted(latest["window"].unique()))

    fig, ax = plt.subplots(figsize=(10, 6), constrained_layout=True)
    ax.barh(data["industry"], data["top_mean_excess"], color="#54A24B", label="top mean excess")
    ax.barh(data["industry"], data["bottom_mean_excess"], color="#E45756", label="bottom mean excess")
    ax.axvline(0, color="#333333", linewidth=0.8)
    ax.set_title(f"Latest Top/Bottom Excess Return Split, {window_label}D Window")
    ax.set_xlabel("excess return")
    ax.grid(axis="x", alpha=0.25)
    ax.legend()

    path = fig_dir / "latest_top_bottom_excess_split.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Create long-window supplemental plots for K-shape outputs.")
    parser.add_argument(
        "--output-dir",
        default=str(BASE_DIR / "output"),
        help="Directory containing industry_k_shape_*.csv and receiving figures.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    fig_dir = output_dir / "figures"

    setup_plot_style()
    fig_dir.mkdir(parents=True, exist_ok=True)
    summary = pd.read_csv(output_dir / "industry_k_shape_summary.csv", parse_dates=["date"])
    latest = pd.read_csv(output_dir / "industry_k_shape_latest_summary.csv", parse_dates=["date"])
    paths = [plot_monthly_breadth(summary, fig_dir), plot_latest_excess_split(latest, fig_dir)]
    for path in paths:
        print(f"wrote figure: {path}")


if __name__ == "__main__":
    main()
