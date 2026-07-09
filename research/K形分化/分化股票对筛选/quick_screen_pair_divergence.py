"""
Quickly screen stock pairs with stable long-term traction and short-term divergence.

The heavy work is submitted to DolphinDB. Python only builds monthly chunks,
retrieves a compact ranked table, and writes a local CSV under this directory.
Connection parameters are read from .env keys: ip, port, usr, pwd.
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
except ImportError as exc:  # pragma: no cover - only raised when executed without dependency.
    raise SystemExit("Please install dolphindb before running this script.") from exc


TRACTION_DB_PATH = "dfs://zxn_traction"
TRACTION_TABLE = "TracCorr_DailyRet"
TRADE_DB_PATH = "dfs://trade_data_wy"
STOCK_PRICE_TABLE = "stock_price"
STOCK_IND_TABLE = "stock_ind"
INDUSTRY_FACNAME = "swind2"


@dataclass(frozen=True)
class DdbConfig:
    ip: str
    port: int
    user: str
    password: str


@dataclass(frozen=True)
class ScreenParams:
    end_date: pd.Timestamp
    long_months: int
    traction_chunk_days: int
    price_lookback_days: int
    short_window: int
    min_month_traction: float
    min_month_obs: int
    min_long_avg_traction: float
    min_hit_ratio: float
    min_abs_spread_z: float
    min_abs_ret_diff: float
    candidate_limit: int
    output_limit: int
    same_industry_only: bool


@dataclass(frozen=True)
class SourceConfig:
    traction_db_path: str
    traction_table: str
    trade_db_path: str
    stock_price_table: str
    stock_ind_table: str
    industry_facname: str


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


def connect(config: DdbConfig) -> ddb.session:
    ddb.session.setTimeout(900)
    session = ddb.session()
    session.connect(config.ip, config.port, config.user, config.password, keepAliveTime=3600)
    return session


def get_latest_common_date(session: ddb.session, source: SourceConfig) -> pd.Timestamp:
    latest_traction = session.run(
        f"""
        exec max(date)
        from loadTable("{source.traction_db_path}", "{source.traction_table}")
        """
    )
    latest_price = session.run(
        f"""
        exec max(date)
        from loadTable("{source.trade_db_path}", "{source.stock_price_table}")
        where facname=`S_DQ_ADJCLOSE, isValid(facvalue), facvalue > 0
        """
    )
    if (
        latest_traction is None
        or latest_price is None
        or pd.isna(latest_traction)
        or pd.isna(latest_price)
    ):
        raise RuntimeError("Cannot find latest common date from source tables.")
    return min(pd.Timestamp(latest_traction), pd.Timestamp(latest_price))


def iter_month_periods(begin_date: pd.Timestamp, end_date: pd.Timestamp) -> Iterable[tuple[pd.Timestamp, pd.Timestamp]]:
    current = pd.Timestamp(year=begin_date.year, month=begin_date.month, day=1)
    while current <= end_date:
        period_begin = max(current, begin_date)
        month_end = current + pd.offsets.MonthEnd(0)
        period_end = min(month_end, end_date)
        if period_begin <= period_end:
            yield period_begin, period_end
        current = current + pd.offsets.MonthBegin(1)


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


def month_window(end_date: pd.Timestamp, long_months: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    month_start = pd.Timestamp(year=end_date.year, month=end_date.month, day=1)
    begin_date = month_start - pd.DateOffset(months=long_months - 1)
    return pd.Timestamp(begin_date), end_date


def ddb_bool(value: bool) -> str:
    return "true" if value else "false"


def build_screen_script(source: SourceConfig, params: ScreenParams) -> str:
    long_begin, long_end = month_window(params.end_date, params.long_months)
    price_begin = params.end_date - pd.Timedelta(
        int(params.price_lookback_days + params.short_window + 30),
        unit="D",
    )
    monthly_blocks: list[str] = []
    for month_begin, month_end in iter_month_periods(long_begin, long_end):
        chunk_blocks: list[str] = []
        for chunk_begin, chunk_end in iter_date_chunks(
            month_begin,
            month_end,
            params.traction_chunk_days,
        ):
            chunk_blocks.append(
                f"""
    chunkAgg = select sum(double(traction)) as traction_sum,
                      long(count(traction)) as n_obs
               from loadTable("{source.traction_db_path}", "{source.traction_table}")
               where date between {to_db_date(chunk_begin)} : {to_db_date(chunk_end)},
                     isValid(secid),
                     isValid(secid2),
                     secid != secid2,
                     string(secid) < string(secid2),
                     isValid(traction)
               group by secid, secid2

    chunkAgg = select secid, secid2, traction_sum, n_obs
               from chunkAgg

    monthState.append!(chunkAgg)
    monthState = select sum(traction_sum) as traction_sum,
                        long(sum(n_obs)) as n_obs
                 from monthState
                 group by secid, secid2
    monthState = select secid, secid2, traction_sum, n_obs
                 from monthState

    undef(`chunkAgg, VAR)
                """
            )
        monthly_blocks.append(
            f"""
    monthBegin = {to_db_date(month_begin)}
    monthEnd = {to_db_date(month_end)}
    monthYear = {int(month_end.year)}
    monthValue = {int(month_end.month)}

    monthState = table(
        array(SYMBOL, 0) as secid,
        array(SYMBOL, 0) as secid2,
        array(DOUBLE, 0) as traction_sum,
        array(LONG, 0) as n_obs
    )

    {"".join(chunk_blocks)}

    monthAgg = select secid,
                      secid2,
                      traction_sum \\ n_obs as traction_avg,
                      n_obs
               from monthState
               where n_obs >= minMonthObs

    monthAgg = select *
               from monthAgg
               where traction_avg >= minMonthTraction

    industryRaw = select date, secid, facvalue
                  from loadTable("{source.trade_db_path}", "{source.stock_ind_table}")
                  where date between monthBegin : monthEnd,
                        facname = industryFacname,
                        isValid(secid),
                        isValid(facvalue)
                  order by secid, date

    industryLatest = select last(facvalue) as secid_facvalue
                     from industryRaw
                     group by secid

    industryLatest2 = select secid as secid2,
                             secid_facvalue as secid2_facvalue
                      from industryLatest

    monthAgg = lj(monthAgg, industryLatest, `secid)
    monthAgg = lj(monthAgg, industryLatest2, `secid2)
    monthAgg = select secid, secid2, monthYear as year, monthValue as month,
                      traction_avg, n_obs, secid_facvalue, secid2_facvalue
               from monthAgg
               where (!sameIndustryOnly or (
                         isValid(secid_facvalue)
                         and isValid(secid2_facvalue)
                         and secid_facvalue = secid2_facvalue
                     ))

    candidateMonthly.append!(monthAgg)
    undef(`monthState`monthAgg`industryRaw`industryLatest`industryLatest2, VAR)
            """
        )

    return f"""
    endDate = {to_db_date(params.end_date)}
    priceBegin = {to_db_date(price_begin)}
    shortWindow = {int(params.short_window)}
    minMonthTraction = {float(params.min_month_traction)}
    minMonthObs = {int(params.min_month_obs)}
    minLongAvgTraction = {float(params.min_long_avg_traction)}
    minHitRatio = {float(params.min_hit_ratio)}
    minAbsSpreadZ = {float(params.min_abs_spread_z)}
    minAbsRetDiff = {float(params.min_abs_ret_diff)}
    totalMonths = {int(params.long_months)}
    sameIndustryOnly = {ddb_bool(params.same_industry_only)}
    industryFacname = `{source.industry_facname}

    candidateMonthly = table(
        array(SYMBOL, 0) as secid,
        array(SYMBOL, 0) as secid2,
        array(INT, 0) as year,
        array(INT, 0) as month,
        array(DOUBLE, 0) as traction_avg,
        array(LONG, 0) as n_obs,
        array(SYMBOL, 0) as secid_facvalue,
        array(SYMBOL, 0) as secid2_facvalue
    )

    {"".join(monthly_blocks)}

    longAgg = select
                  sum(traction_avg * n_obs) \\ sum(n_obs) as long_avg_traction,
                  std(traction_avg) as long_std_traction,
                  double(count(*)) \\ totalMonths as traction_hit_ratio,
                  long(sum(n_obs)) as n_obs_long,
                  last(secid_facvalue) as secid_facvalue,
                  last(secid2_facvalue) as secid2_facvalue
              from candidateMonthly
              group by secid, secid2

    longAgg = select secid, secid2,
                     long_avg_traction,
                     iif(isValid(long_std_traction), long_std_traction, 0.0) as long_std_traction,
                     traction_hit_ratio,
                     n_obs_long,
                     secid_facvalue,
                     secid2_facvalue,
                     long_avg_traction * traction_hit_ratio \\ (1.0 + iif(isValid(long_std_traction), long_std_traction, 0.0)) as long_score
              from longAgg
              where long_avg_traction >= minLongAvgTraction,
                    traction_hit_ratio >= minHitRatio

    candidates = select top {int(params.candidate_limit)} *
                 from longAgg
                 order by long_score desc

    candidateStocks = table(array(SYMBOL, 0) as secid)
    candidateStocks.append!(select secid from candidates)
    candidateStocks.append!(select secid2 as secid from candidates)
    candidateStocks = select distinct secid from candidateStocks
    stockIds = exec secid from candidateStocks

    priceLong = select date, secid, double(facvalue) as adjclose
                from loadTable("{source.trade_db_path}", "{source.stock_price_table}")
                where date between priceBegin : endDate,
                      facname=`S_DQ_ADJCLOSE,
                      secid in stockIds,
                      isValid(facvalue),
                      facvalue > 0
                order by secid, date

    pricePanel = select date, secid,
                        log(adjclose) as log_price,
                        log(adjclose) - move(log(adjclose), shortWindow) as ret_short
                 from priceLong
                 context by secid csort date

    pricePanel = select *
                 from pricePanel
                 where date <= endDate

    p1 = lj(candidates, pricePanel, `secid)
    p2 = select date,
                secid as secid2,
                log_price as log_price2,
                ret_short as ret_short2
         from pricePanel

    pairPanel = lj(p1, p2, `secid2`date)
    pairPanel = select secid, secid2, date,
                       log_price - log_price2 as spread,
                       ret_short,
                       ret_short2
                from pairPanel
                where isValid(log_price),
                      isValid(log_price2)
                order by secid, secid2, date

    spreadStats = select last(date) as price_date,
                         last(spread) as spread,
                         avg(spread) as spread_mean,
                         std(spread) as spread_std,
                         last(ret_short) as ret_short_1,
                         last(ret_short2) as ret_short_2,
                         long(count(spread)) as n_price_obs
                  from pairPanel
                  group by secid, secid2

    result = lj(candidates, spreadStats, `secid`secid2)
    result = select secid,
                    secid2,
                    secid_facvalue,
                    secid2_facvalue,
                    long_avg_traction,
                    long_std_traction,
                    traction_hit_ratio,
                    n_obs_long,
                    price_date,
                    n_price_obs,
                    ret_short_1,
                    ret_short_2,
                    ret_short_1 - ret_short_2 as ret_diff_short,
                    spread,
                    spread_mean,
                    spread_std,
                    iif(spread_std > 0, (spread - spread_mean) \\ spread_std, double(NULL)) as spread_z,
                    long_score,
                    long_score
                        * abs(iif(spread_std > 0, (spread - spread_mean) \\ spread_std, double(NULL)))
                        * abs(ret_short_1 - ret_short_2) as final_score
             from result
             where isValid(ret_short_1),
                   isValid(ret_short_2),
                   isValid(spread_std),
                   spread_std > 0,
                   n_price_obs >= shortWindow + 20

    result = select *
             from result
             where abs(spread_z) >= minAbsSpreadZ,
                   abs(ret_diff_short) >= minAbsRetDiff

    result = select top {int(params.output_limit)} *
             from result
             order by final_score desc

    undef(
        `candidateMonthly`longAgg`candidates`candidateStocks`stockIds`priceLong`pricePanel`p1`p2`pairPanel`spreadStats,
        VAR
    )

    result
    """


def run_screen(session: ddb.session, source: SourceConfig, params: ScreenParams) -> pd.DataFrame:
    script = build_screen_script(source, params)
    result = session.run(script)
    if result is None:
        return pd.DataFrame()
    return result


def default_output_path(output_dir: Path, end_date: pd.Timestamp) -> Path:
    return output_dir / f"quick_pair_divergence_{end_date:%Y%m%d}.csv"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Quickly screen long-term similar but short-term divergent stock pairs."
    )
    parser.add_argument("--end-date", help="End date, e.g. 20260630. Defaults to latest common source date.")
    parser.add_argument("--env-file", default=".env", help="Path to .env containing ip/port/usr/pwd.")
    parser.add_argument("--output-dir", default="research/K形分化/分化股票对筛选/output")
    parser.add_argument("--output-file", help="Explicit CSV output path. Overrides --output-dir.")
    parser.add_argument("--traction-db-path", default=TRACTION_DB_PATH)
    parser.add_argument("--traction-table", default=TRACTION_TABLE)
    parser.add_argument("--trade-db-path", default=TRADE_DB_PATH)
    parser.add_argument("--stock-price-table", default=STOCK_PRICE_TABLE)
    parser.add_argument("--stock-ind-table", default=STOCK_IND_TABLE)
    parser.add_argument("--industry-facname", default=INDUSTRY_FACNAME)
    parser.add_argument("--long-months", type=int, default=12, help="Long-term traction lookback in calendar months.")
    parser.add_argument(
        "--traction-chunk-days",
        type=int,
        default=5,
        help="Calendar days per traction aggregation chunk. Smaller values reduce DolphinDB memory pressure.",
    )
    parser.add_argument("--price-lookback-days", type=int, default=370, help="Calendar days for spread z-score history.")
    parser.add_argument("--short-window", type=int, default=20, help="Trading-day return window for short divergence.")
    parser.add_argument(
        "--min-month-traction",
        type=float,
        default=0.60,
        help="Keep only pair-months whose monthly average traction is at least this value.",
    )
    parser.add_argument("--min-month-obs", type=int, default=10, help="Minimum valid observations in a pair-month.")
    parser.add_argument("--min-long-avg-traction", type=float, default=0.70)
    parser.add_argument("--min-hit-ratio", type=float, default=0.60)
    parser.add_argument("--min-abs-spread-z", type=float, default=2.0)
    parser.add_argument("--min-abs-ret-diff", type=float, default=0.05)
    parser.add_argument("--candidate-limit", type=int, default=5000)
    parser.add_argument("--output-limit", type=int, default=100)
    parser.add_argument(
        "--allow-cross-industry",
        action="store_true",
        help="Allow pairs whose latest monthly industry labels differ.",
    )
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if args.long_months <= 0:
        raise ValueError("--long-months must be positive.")
    if args.traction_chunk_days <= 0:
        raise ValueError("--traction-chunk-days must be positive.")
    if args.price_lookback_days <= 0:
        raise ValueError("--price-lookback-days must be positive.")
    if args.short_window <= 0:
        raise ValueError("--short-window must be positive.")
    if args.min_month_obs <= 0:
        raise ValueError("--min-month-obs must be positive.")
    if not 0 <= args.min_month_traction <= 1:
        raise ValueError("--min-month-traction must be in [0, 1].")
    if not 0 <= args.min_long_avg_traction <= 1:
        raise ValueError("--min-long-avg-traction must be in [0, 1].")
    if not 0 <= args.min_hit_ratio <= 1:
        raise ValueError("--min-hit-ratio must be in [0, 1].")
    if args.min_abs_spread_z < 0:
        raise ValueError("--min-abs-spread-z cannot be negative.")
    if args.min_abs_ret_diff < 0:
        raise ValueError("--min-abs-ret-diff cannot be negative.")
    if args.candidate_limit <= 0 or args.output_limit <= 0:
        raise ValueError("--candidate-limit and --output-limit must be positive.")


def main() -> None:
    args = build_arg_parser().parse_args()
    validate_args(args)

    config = parse_env(Path(args.env_file))
    source = SourceConfig(
        traction_db_path=args.traction_db_path,
        traction_table=args.traction_table,
        trade_db_path=args.trade_db_path,
        stock_price_table=args.stock_price_table,
        stock_ind_table=args.stock_ind_table,
        industry_facname=args.industry_facname,
    )

    session = connect(config)
    try:
        end_date = parse_date(args.end_date) if args.end_date else get_latest_common_date(session, source)
        params = ScreenParams(
            end_date=end_date,
            long_months=args.long_months,
            traction_chunk_days=args.traction_chunk_days,
            price_lookback_days=args.price_lookback_days,
            short_window=args.short_window,
            min_month_traction=args.min_month_traction,
            min_month_obs=args.min_month_obs,
            min_long_avg_traction=args.min_long_avg_traction,
            min_hit_ratio=args.min_hit_ratio,
            min_abs_spread_z=args.min_abs_spread_z,
            min_abs_ret_diff=args.min_abs_ret_diff,
            candidate_limit=args.candidate_limit,
            output_limit=args.output_limit,
            same_industry_only=not args.allow_cross_industry,
        )
        result = run_screen(session, source, params)
    finally:
        session.close()

    output_path = Path(args.output_file) if args.output_file else default_output_path(Path(args.output_dir), end_date)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"[done] wrote {len(result):,} rows to {output_path.resolve()}")


if __name__ == "__main__":
    main()
