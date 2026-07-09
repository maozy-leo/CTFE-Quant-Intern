"""
Measure K-shaped divergence among stocks in the same industry.

Heavy calculation is pushed down to DolphinDB. Python only splits date ranges,
submits DolphinDB scripts, receives compact result tables, and writes CSV files.
"""

from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

try:
    import dolphindb as ddb
except ImportError as exc:  # pragma: no cover - only raised on machines without dolphindb.
    raise SystemExit("Please install dolphindb before running this script.") from exc


TRADE_DB_PATH = "dfs://trade_data_wy"
STOCK_PRICE_TABLE = "stock_price"
STOCK_IND_TABLE = "stock_ind"

PRICE_FACNAMES = [
    "S_DQ_ADJCLOSE",
    "S_DQ_CLOSE",
    "FREE_MV",
    "S_DQ_AMOUNT",
    "UP_DOWN_LIMIT_STATUS",
    "st",
    "listed_days",
]


@dataclass(frozen=True)
class DdbConfig:
    ip: str
    port: int
    user: str
    password: str


@dataclass(frozen=True)
class ServerParams:
    industry_facname: str
    top_pct: float
    min_stocks: int
    hist_lookback: int
    min_history: int
    min_listed_days: int
    min_amount: float
    exclude_limit_status: bool
    buffer_calendar_days: int
    save_all_constituents: bool


def parse_env(path: Path) -> DdbConfig:
    values: dict[str, str | int] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = [part.strip() for part in line.split("=", 1)]
        value = value.strip("\"'")
        values[key] = int(value) if key.lower().endswith("port") else value

    required = {"ip", "port", "usr", "pwd"}
    missing = required - set(values)
    if missing:
        raise ValueError(f"Missing keys in {path}: {sorted(missing)}")

    return DdbConfig(
        ip=str(values["ip"]),
        port=int(values["port"]),
        user=str(values["usr"]),
        password=str(values["pwd"]),
    )


def parse_date(value: str) -> pd.Timestamp:
    normalized = value.strip().replace("-", "").replace(".", "").replace("/", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"Date must be YYYYMMDD, got: {value}")
    return pd.Timestamp(dt.datetime.strptime(normalized, "%Y%m%d").date())


def to_db_date(value: pd.Timestamp | str) -> str:
    ts = parse_date(value) if isinstance(value, str) else pd.Timestamp(value)
    return ts.strftime("%Y.%m.%d")


def symbol_list(values: Iterable[str]) -> str:
    return "`" + "`".join(values)


def connect(config: DdbConfig) -> ddb.session:
    ddb.session.setTimeout(600)
    session = ddb.session()
    session.connect(config.ip, config.port, config.user, config.password, keepAliveTime=3600)
    return session


def get_latest_trade_date(session: ddb.session) -> pd.Timestamp:
    value = session.run(
        f"""
        exec max(date)
        from loadTable("{TRADE_DB_PATH}", "{STOCK_PRICE_TABLE}")
        where facname=`S_DQ_ADJCLOSE, isValid(facvalue), facvalue > 0
        """
    )
    if value is None or pd.isna(value):
        raise RuntimeError("Cannot find latest trade date from stock_price.")
    return pd.Timestamp(value)


def iter_date_chunks(
    begin_date: pd.Timestamp,
    end_date: pd.Timestamp,
    chunk_calendar_days: int,
) -> Iterable[tuple[pd.Timestamp, pd.Timestamp]]:
    chunk_begin = begin_date
    while chunk_begin <= end_date:
        chunk_end = min(chunk_begin + pd.Timedelta(chunk_calendar_days - 1, unit="D"), end_date)
        yield chunk_begin, chunk_end
        chunk_begin = chunk_end + pd.Timedelta(1, unit="D")


def empty_summary() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "n_stock",
            "industry_ret",
            "top_mean_excess",
            "bottom_mean_excess",
            "k_spread",
            "k_score",
            "dispersion_std",
            "iqr_excess",
            "positive_ratio",
            "negative_ratio",
            "date",
            "industry",
            "window",
            "k_zscore",
            "k_pct",
        ]
    )


def empty_constituents() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "date",
            "industry",
            "window",
            "secid",
            "ret",
            "industry_ret",
            "excess_ret",
            "industry_rank_pct",
            "group",
            "FREE_MV",
            "S_DQ_AMOUNT",
        ]
    )


def ddb_script_for_chunk(
    query_begin: pd.Timestamp,
    chunk_begin: pd.Timestamp,
    chunk_end: pd.Timestamp,
    window: int,
    params: ServerParams,
) -> str:
    facnames = symbol_list(PRICE_FACNAMES)
    exclude_limit_clause = (
        "and (!isValid(limit_status) or limit_status = 0)" if params.exclude_limit_status else ""
    )
    constituent_filter_clause = (
        "where date between chunkBegin : chunkEnd, k_group in `top`bottom"
        if params.save_all_constituents
        else "where date = latestSummaryDate, k_group in `top`bottom"
    )

    return f"""
    queryBegin = {to_db_date(query_begin)}
    chunkBegin = {to_db_date(chunk_begin)}
    chunkEnd = {to_db_date(chunk_end)}
    retWindow = {int(window)}
    topPct = {float(params.top_pct)}
    minStocks = {int(params.min_stocks)}
    histLookback = {int(params.hist_lookback)}
    minHistory = {int(params.min_history)}
    minListedDays = {int(params.min_listed_days)}
    minAmount = {float(params.min_amount)}

    priceLong = select date, secid, facname, double(facvalue) as facvalue
                from loadTable("{TRADE_DB_PATH}", "{STOCK_PRICE_TABLE}")
                where date between queryBegin : chunkEnd,
                      facname in {facnames},
                      isValid(secid),
                      isValid(facvalue)

    price = select
                max(iif(facname == `S_DQ_ADJCLOSE, facvalue, double(NULL))) as adjclose,
                max(iif(facname == `S_DQ_CLOSE, facvalue, double(NULL))) as close,
                max(iif(facname == `FREE_MV, facvalue, double(NULL))) as free_mv,
                max(iif(facname == `S_DQ_AMOUNT, facvalue, double(NULL))) as amount,
                max(iif(facname == `UP_DOWN_LIMIT_STATUS, facvalue, double(NULL))) as limit_status,
                max(iif(facname == `st, facvalue, double(NULL))) as st_status,
                max(iif(facname == `listed_days, facvalue, double(NULL))) as listed_days
            from priceLong
            group by date, secid

    industry = select date, secid, string(facvalue) as industry
               from loadTable("{TRADE_DB_PATH}", "{STOCK_IND_TABLE}")
               where date between queryBegin : chunkEnd,
                     facname=`{params.industry_facname},
                     isValid(secid),
                     isValid(facvalue)

    panel = lj(price, industry, `date`secid)
    panel = select date, secid, industry,
                   iif(isValid(adjclose) and adjclose > 0, adjclose, close) as price_for_ret,
                   free_mv as FREE_MV,
                   amount as S_DQ_AMOUNT,
                   iif(isValid(free_mv) and free_mv > 0, free_mv, double(NULL)) as weight,
                   limit_status,
                   st_status,
                   listed_days
            from panel
            where isValid(industry),
                  isValid(iif(isValid(adjclose) and adjclose > 0, adjclose, close)),
                  iif(isValid(adjclose) and adjclose > 0, adjclose, close) > 0,
                  (!isValid(listed_days) or listed_days >= minListedDays),
                  (!isValid(st_status) or st_status = 0),
                  (!isValid(amount) or amount >= minAmount)
                  {exclude_limit_clause}
            order by secid, date

    retPanel = select date, secid, industry, FREE_MV, S_DQ_AMOUNT, weight,
                      log(price_for_ret) - move(log(price_for_ret), retWindow) as ret
               from panel
               context by secid csort date

    retPanel = select *
               from retPanel
               where isValid(ret)

    industryRet = select
                      iif(
                          sum(iif(isValid(weight), weight, 0.0)) > 0,
                          sum(iif(isValid(weight), ret * weight, 0.0)) \\ sum(iif(isValid(weight), weight, 0.0)),
                          avg(ret)
                      ) as industry_ret
                  from retPanel
                  group by date, industry

    ranked = lj(retPanel, industryRet, `date`industry)
    ranked = select date, industry, retWindow as window, secid, ret, industry_ret,
                    ret - industry_ret as excess_ret,
                    rank(ret - industry_ret, percent=true) as industry_rank_pct,
                    FREE_MV,
                    S_DQ_AMOUNT
             from ranked
             context by date, industry

    ranked = select date, industry, window, secid, ret, industry_ret, excess_ret,
                    industry_rank_pct,
                    iif(industry_rank_pct >= 1.0 - topPct, `top,
                        iif(industry_rank_pct <= topPct, `bottom, `middle)) as k_group,
                    FREE_MV,
                    S_DQ_AMOUNT
             from ranked

    summaryBase = select count(*) as n_stock,
                         first(industry_ret) as industry_ret,
                         avg(iif(k_group == `top, excess_ret, double(NULL))) as top_mean_excess,
                         avg(iif(k_group == `bottom, excess_ret, double(NULL))) as bottom_mean_excess,
                         avg(iif(excess_ret > 0, 1.0, 0.0)) as positive_ratio,
                         avg(iif(excess_ret < 0, 1.0, 0.0)) as negative_ratio,
                         std(excess_ret) as dispersion_std,
                         percentile(excess_ret, 75) - percentile(excess_ret, 25) as iqr_excess
                  from ranked
                  group by date, industry, window

    summaryBase = select n_stock, industry_ret, top_mean_excess, bottom_mean_excess,
                         top_mean_excess - bottom_mean_excess as k_spread,
                         iif(top_mean_excess > 0 and bottom_mean_excess < 0,
                             top_mean_excess - bottom_mean_excess,
                             0.0) as k_score,
                         dispersion_std,
                         iqr_excess,
                         positive_ratio,
                         negative_ratio,
                         date,
                         industry,
                         window
                  from summaryBase
                  where n_stock >= minStocks
                  order by industry, date

    summaryHist = select *,
                         mavg(move(k_score, 1), histLookback, minHistory) as k_mean,
                         mstd(move(k_score, 1), histLookback, minHistory) as k_std,
                         mrank(k_score, true, histLookback + 1, true, `min, true, minHistory + 1) as k_pct
                  from summaryBase
                  context by industry csort date

    summaryHist = select n_stock, industry_ret, top_mean_excess, bottom_mean_excess,
                         k_spread, k_score, dispersion_std, iqr_excess,
                         positive_ratio, negative_ratio, date, industry, window,
                         iif(k_std > 0, (k_score - k_mean) \\ k_std, double(NULL)) as k_zscore,
                         k_pct
                  from summaryHist

    summaryOut = select *
                 from summaryHist
                 where date between chunkBegin : chunkEnd
    latestSummaryDate = exec max(date) from summaryOut

    if(size(summaryOut) == 0){{
        constituentsOut = table(
            array(DATE, 0) as date,
            array(STRING, 0) as industry,
            array(INT, 0) as window,
            array(SYMBOL, 0) as secid,
            array(DOUBLE, 0) as ret,
            array(DOUBLE, 0) as industry_ret,
            array(DOUBLE, 0) as excess_ret,
            array(DOUBLE, 0) as industry_rank_pct,
            array(SYMBOL, 0) as k_group,
            array(DOUBLE, 0) as FREE_MV,
            array(DOUBLE, 0) as S_DQ_AMOUNT
        )
    }} else {{
        constituentsOut = select date, industry, window, secid, ret, industry_ret,
                                excess_ret, industry_rank_pct, k_group, FREE_MV, S_DQ_AMOUNT
                          from ranked
                          {constituent_filter_clause}
    }}

    [summaryOut, constituentsOut]
    """


def run_server_chunk(
    session: ddb.session,
    chunk_begin: pd.Timestamp,
    chunk_end: pd.Timestamp,
    window: int,
    params: ServerParams,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    query_begin = chunk_begin - pd.Timedelta(int(params.buffer_calendar_days), unit="D")
    script = ddb_script_for_chunk(
        query_begin=query_begin,
        chunk_begin=chunk_begin,
        chunk_end=chunk_end,
        window=window,
        params=params,
    )
    summary, constituents = session.run(script)
    if "k_group" in constituents.columns:
        constituents = constituents.rename(columns={"k_group": "group"})
    return summary, constituents


def write_outputs(
    summary: pd.DataFrame,
    constituents: pd.DataFrame,
    output_dir: Path,
    save_all_constituents: bool,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = summary.copy()
    if not summary.empty:
        summary["date"] = pd.to_datetime(summary["date"])
        summary = summary.sort_values(
            ["date", "window", "k_pct", "k_score"],
            ascending=[True, True, False, False],
        )
    summary.to_csv(output_dir / "industry_k_shape_summary.csv", index=False, encoding="utf-8-sig")

    if summary.empty:
        empty_summary().to_csv(output_dir / "industry_k_shape_latest_summary.csv", index=False, encoding="utf-8-sig")
        empty_constituents().to_csv(
            output_dir / "industry_k_shape_latest_constituents.csv",
            index=False,
            encoding="utf-8-sig",
        )
        return

    latest_date_by_window = summary.groupby("window")["date"].max().rename("latest_date")
    latest = summary.merge(latest_date_by_window, on="window")
    latest = latest.loc[latest["date"].eq(latest["latest_date"])].drop(columns="latest_date")
    latest = latest.sort_values(["window", "k_pct", "k_score"], ascending=[True, False, False])
    latest.to_csv(output_dir / "industry_k_shape_latest_summary.csv", index=False, encoding="utf-8-sig")

    if constituents.empty:
        empty_constituents().to_csv(
            output_dir / "industry_k_shape_latest_constituents.csv",
            index=False,
            encoding="utf-8-sig",
        )
        return

    constituents = constituents.copy()
    constituents["date"] = pd.to_datetime(constituents["date"])
    latest_keys = latest[["date", "industry", "window"]].drop_duplicates()
    latest_constituents = constituents.merge(latest_keys, on=["date", "industry", "window"], how="inner")
    latest_constituents = latest_constituents.sort_values(
        ["window", "industry", "group", "industry_rank_pct"],
        ascending=[True, True, True, False],
    )
    latest_constituents.to_csv(
        output_dir / "industry_k_shape_latest_constituents.csv",
        index=False,
        encoding="utf-8-sig",
    )

    if save_all_constituents:
        constituents.to_csv(
            output_dir / "industry_k_shape_constituents.csv",
            index=False,
            encoding="utf-8-sig",
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate local tables for same-industry K-shaped divergence.")
    parser.add_argument("--begin-date", help="Output begin date, e.g. 20260101. Defaults to end-date minus 120 days.")
    parser.add_argument("--end-date", help="Output end date, e.g. 20260708. Defaults to latest available trade date.")
    parser.add_argument("--env-file", default=".env", help="Path to .env containing ip/port/usr/pwd.")
    parser.add_argument("--output-dir", default="research/同行业K形分化/output", help="Directory for CSV outputs.")
    parser.add_argument("--industry-facname", default="swind2", help="Industry classification facname, e.g. swind2/ind2.")
    parser.add_argument("--windows", nargs="+", type=int, default=[5, 20, 60], help="Return windows in trading days.")
    parser.add_argument("--top-pct", type=float, default=0.20, help="Top/bottom share inside each industry.")
    parser.add_argument("--min-stocks", type=int, default=10, help="Minimum stocks required for an industry-date.")
    parser.add_argument("--hist-lookback", type=int, default=252, help="History length for k_zscore/k_pct.")
    parser.add_argument("--min-history", type=int, default=60, help="Minimum history for k_zscore/k_pct.")
    parser.add_argument("--min-listed-days", type=int, default=60, help="Exclude stocks listed for fewer days.")
    parser.add_argument("--min-amount", type=float, default=0.0, help="Minimum S_DQ_AMOUNT in thousand yuan.")
    parser.add_argument("--exclude-limit-status", action="store_true", help="Exclude rows with nonzero limit status.")
    parser.add_argument(
        "--buffer-calendar-days",
        type=int,
        default=540,
        help="Extra calendar days before each chunk for returns and history stats.",
    )
    parser.add_argument(
        "--chunk-calendar-days",
        type=int,
        default=31,
        help="Output date span per DolphinDB request; smaller chunks reduce server memory pressure.",
    )
    parser.add_argument(
        "--save-all-constituents",
        action="store_true",
        help="Also write all top/bottom constituent rows in the output period.",
    )
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if not args.windows or any(window <= 0 for window in args.windows):
        raise ValueError("--windows must contain positive integers.")
    if not 0 < args.top_pct < 0.5:
        raise ValueError("--top-pct must be in (0, 0.5).")
    if args.min_stocks <= 0:
        raise ValueError("--min-stocks must be positive.")
    if args.hist_lookback <= 0 or args.min_history <= 0:
        raise ValueError("--hist-lookback and --min-history must be positive.")
    if args.min_history > args.hist_lookback:
        raise ValueError("--min-history cannot exceed --hist-lookback.")
    if args.min_listed_days < 0 or args.min_amount < 0:
        raise ValueError("--min-listed-days and --min-amount cannot be negative.")
    if args.buffer_calendar_days <= 0:
        raise ValueError("--buffer-calendar-days must be positive.")
    if args.chunk_calendar_days <= 0:
        raise ValueError("--chunk-calendar-days must be positive.")


def main() -> None:
    args = build_arg_parser().parse_args()
    validate_args(args)

    config = parse_env(Path(args.env_file))
    params = ServerParams(
        industry_facname=args.industry_facname,
        top_pct=args.top_pct,
        min_stocks=args.min_stocks,
        hist_lookback=args.hist_lookback,
        min_history=args.min_history,
        min_listed_days=args.min_listed_days,
        min_amount=args.min_amount,
        exclude_limit_status=args.exclude_limit_status,
        buffer_calendar_days=args.buffer_calendar_days,
        save_all_constituents=args.save_all_constituents,
    )

    summary_frames: list[pd.DataFrame] = []
    constituent_frames: list[pd.DataFrame] = []

    session = connect(config)
    try:
        end_date = parse_date(args.end_date) if args.end_date else get_latest_trade_date(session)
        begin_date = parse_date(args.begin_date) if args.begin_date else end_date - pd.Timedelta(120, unit="D")
        if begin_date > end_date:
            raise ValueError("--begin-date cannot be later than --end-date.")

        for chunk_begin, chunk_end in iter_date_chunks(begin_date, end_date, args.chunk_calendar_days):
            for window in sorted(set(args.windows)):
                query_begin = chunk_begin - pd.Timedelta(int(args.buffer_calendar_days), unit="D")
                print(
                    "[ddb] "
                    f"window={window} "
                    f"query={query_begin:%Y%m%d}-{chunk_end:%Y%m%d} "
                    f"output={chunk_begin:%Y%m%d}-{chunk_end:%Y%m%d}"
                )
                summary, constituents = run_server_chunk(
                    session=session,
                    chunk_begin=chunk_begin,
                    chunk_end=chunk_end,
                    window=window,
                    params=params,
                )
                summary_frames.append(summary)
                constituent_frames.append(constituents)
                print(f"[recv] summary={len(summary):,}, constituents={len(constituents):,}")
    finally:
        session.close()

    summary_out = pd.concat(summary_frames, ignore_index=True) if summary_frames else empty_summary()
    constituents_out = (
        pd.concat(constituent_frames, ignore_index=True) if constituent_frames else empty_constituents()
    )

    output_dir = Path(args.output_dir)
    write_outputs(
        summary=summary_out,
        constituents=constituents_out,
        output_dir=output_dir,
        save_all_constituents=args.save_all_constituents,
    )
    print(f"[done] wrote CSV tables to {output_dir.resolve()}")


if __name__ == "__main__":
    main()
