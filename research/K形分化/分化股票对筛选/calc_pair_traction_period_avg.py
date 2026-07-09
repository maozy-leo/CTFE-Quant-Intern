"""
Aggregate stock-pair traction by year and month on DolphinDB.

The script only submits DolphinDB scripts. Heavy calculation, industry matching,
and final table writes all happen on the server. Connection parameters are read
from .env keys: ip, port, usr, pwd.
"""

from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

import pandas as pd

try:
    import dolphindb as ddb
except ImportError as exc:  # pragma: no cover - only raised when executed without dependency.
    raise SystemExit("Please install dolphindb before running this script.") from exc


TRACTION_DB_PATH = "dfs://zxn_traction"
TRACTION_TABLE = "TracCorr_DailyRet"

# Project convention is dfs://trade_data_wy / stock_ind. Both are configurable
# because some notes refer to this source as dfs://trade_data_wy-stock_ind.
INDUSTRY_DB_PATH = "dfs://trade_data_wy"
INDUSTRY_TABLE = "stock_ind"
INDUSTRY_FACNAME = "swind2"

OUTPUT_DB_PATH = "dfs://factor_intern"
YEARLY_TABLE = "kshape_pair_traction_yearly_avg"
MONTHLY_TABLE = "kshape_pair_traction_monthly_avg"

PeriodKind = Literal["year", "month"]


@dataclass(frozen=True)
class DdbConfig:
    ip: str
    port: int
    user: str
    password: str


@dataclass(frozen=True)
class SourceConfig:
    traction_db_path: str
    traction_table: str
    industry_db_path: str
    industry_table: str
    industry_facname: str
    output_db_path: str
    yearly_table: str
    monthly_table: str
    replace_periods: bool
    skip_existing: bool


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
    ddb.session.setTimeout(600)
    session = ddb.session()
    session.connect(config.ip, config.port, config.user, config.password, keepAliveTime=3600)
    return session


def get_source_date_range(session: ddb.session, source: SourceConfig) -> tuple[pd.Timestamp, pd.Timestamp]:
    date_range = session.run(
        f"""
        select min(date) as begin_date, max(date) as end_date
        from loadTable("{source.traction_db_path}", "{source.traction_table}")
        """
    )
    begin_date = date_range["begin_date"].iloc[0]
    end_date = date_range["end_date"].iloc[0]
    if begin_date is None or end_date is None or pd.isna(begin_date) or pd.isna(end_date):
        raise RuntimeError("Cannot find source date range from traction table.")
    return pd.Timestamp(begin_date), pd.Timestamp(end_date)


def iter_year_periods(begin_date: pd.Timestamp, end_date: pd.Timestamp) -> Iterable[tuple[pd.Timestamp, pd.Timestamp]]:
    current = pd.Timestamp(year=begin_date.year, month=1, day=1)
    while current <= end_date:
        period_begin = max(current, begin_date)
        year_end = pd.Timestamp(year=current.year, month=12, day=31)
        period_end = min(year_end, end_date)
        if period_begin <= period_end:
            yield period_begin, period_end
        current = pd.Timestamp(year=current.year + 1, month=1, day=1)


def iter_month_periods(begin_date: pd.Timestamp, end_date: pd.Timestamp) -> Iterable[tuple[pd.Timestamp, pd.Timestamp]]:
    current = pd.Timestamp(year=begin_date.year, month=begin_date.month, day=1)
    while current <= end_date:
        period_begin = max(current, begin_date)
        month_end = current + pd.offsets.MonthEnd(0)
        period_end = min(month_end, end_date)
        if period_begin <= period_end:
            yield period_begin, period_end
        current = current + pd.offsets.MonthBegin(1)


def ensure_output_database(session: ddb.session, output_db_path: str) -> None:
    session.run(
        f"""
        if(!existsDatabase("{output_db_path}")){{
            dbDate = database(
                "",
                RANGE,
                [
                    2004.01.01, 2005.01.01, 2006.01.01, 2007.01.01, 2008.01.01,
                    2009.01.01, 2010.01.01, 2011.01.01, 2012.01.01, 2013.01.01,
                    2014.01.01, 2015.01.01, 2016.01.01, 2017.01.01, 2018.01.01,
                    2019.01.01, 2020.01.01, 2021.01.01, 2022.01.01, 2023.01.01,
                    2024.01.01, 2025.01.01, 2026.01.01, 2027.01.01, 2028.01.01,
                    2029.01.01, 2030.01.01, 2031.01.01, 2032.01.01, 2033.01.01,
                    2034.01.01, 2035.01.01, 2036.01.01, 2037.01.01, 2038.01.01,
                    2039.01.01, 2040.01.01, 2041.01.01, 2042.01.01, 2043.01.01,
                    2044.01.01, 2045.01.01, 2046.01.01, 2047.01.01, 2048.01.01,
                    2049.01.01, 2050.01.01
                ]
            )
            dbSecid = database("", HASH, [SYMBOL, 20])
            database("{output_db_path}", COMPO, [dbDate, dbSecid])
        }}
        """
    )


def ensure_output_table(
    session: ddb.session,
    output_db_path: str,
    table_name: str,
    period_kind: PeriodKind,
) -> None:
    period_columns = (
        "array(INT, 0) as year,"
        if period_kind == "year"
        else "array(INT, 0) as year,\n                array(INT, 0) as month,"
    )
    session.run(
        f"""
        if(!existsTable("{output_db_path}", "{table_name}")){{
            schemaTable = table(
                array(DATE, 0) as date,
                {period_columns}
                array(SYMBOL, 0) as secid,
                array(SYMBOL, 0) as secid2,
                array(DOUBLE, 0) as traction_avg,
                array(LONG, 0) as n_obs,
                array(SYMBOL, 0) as secid_facname,
                array(SYMBOL, 0) as secid_facvalue,
                array(SYMBOL, 0) as secid2_facname,
                array(SYMBOL, 0) as secid2_facvalue
            )
            db = database("{output_db_path}")
            createPartitionedTable(
                dbHandle=db,
                table=schemaTable,
                tableName="{table_name}",
                partitionColumns=`date`secid
            )
        }}
        """
    )


def period_exists(
    session: ddb.session,
    output_db_path: str,
    table_name: str,
    period_end: pd.Timestamp,
) -> bool:
    probe = session.run(
        f"""
        select top 1 date
        from loadTable("{output_db_path}", "{table_name}")
        where date = {to_db_date(period_end)}
        """
    )
    return not probe.empty


def build_period_script(
    source: SourceConfig,
    period_kind: PeriodKind,
    table_name: str,
    period_begin: pd.Timestamp,
    period_end: pd.Timestamp,
) -> str:
    year_value = int(period_end.year)
    month_value = int(period_end.month)
    delete_clause = (
        f"""
        delete from loadTable("{source.output_db_path}", "{table_name}")
        where date = periodEnd
        """
        if source.replace_periods
        else ""
    )
    period_select_columns = (
        "periodEnd as date, periodYear as year,"
        if period_kind == "year"
        else "periodEnd as date, periodYear as year, periodMonth as month,"
    )

    return f"""
    periodBegin = {to_db_date(period_begin)}
    periodEnd = {to_db_date(period_end)}
    periodYear = {year_value}
    periodMonth = {month_value}
    industryFacname = `{source.industry_facname}

    {delete_clause}

    tractionAgg = select avg(double(traction)) as traction_avg,
                         long(count(traction)) as n_obs
                  from loadTable("{source.traction_db_path}", "{source.traction_table}")
                  where date between periodBegin : periodEnd,
                        isValid(secid),
                        isValid(secid2),
                        isValid(traction)
                  group by secid, secid2

    tractionAgg = select secid, secid2, traction_avg, n_obs
                  from tractionAgg

    industryRaw = select date, secid, facvalue
                  from loadTable("{source.industry_db_path}", "{source.industry_table}")
                  where date between periodBegin : periodEnd,
                        facname = industryFacname,
                        isValid(secid),
                        isValid(facvalue)
                  order by secid, date

    industryLatest = select industryFacname as secid_facname,
                            last(facvalue) as secid_facvalue
                     from industryRaw
                     group by secid

    industryLatest2 = select secid as secid2,
                             secid_facname as secid2_facname,
                             secid_facvalue as secid2_facvalue
                      from industryLatest

    result = lj(tractionAgg, industryLatest, `secid)
    result = lj(result, industryLatest2, `secid2)
    result = select {period_select_columns}
                    secid,
                    secid2,
                    traction_avg,
                    n_obs,
                    secid_facname,
                    secid_facvalue,
                    secid2_facname,
                    secid2_facvalue
             from result

    loadTable("{source.output_db_path}", "{table_name}").append!(result)

    undef(`tractionAgg`industryRaw`industryLatest`industryLatest2`result, VAR)
    """


def build_yearly_period_script(
    source: SourceConfig,
    table_name: str,
    period_begin: pd.Timestamp,
    period_end: pd.Timestamp,
) -> str:
    year_value = int(period_end.year)
    delete_clause = (
        f"""
        delete from loadTable("{source.output_db_path}", "{table_name}")
        where date = periodEnd
        """
        if source.replace_periods
        else ""
    )
    monthly_blocks: list[str] = []
    for month_begin, month_end in iter_month_periods(period_begin, period_end):
        monthly_blocks.append(
            f"""
    monthAgg = select sum(double(traction)) as traction_sum,
                      long(count(traction)) as n_obs
               from loadTable("{source.traction_db_path}", "{source.traction_table}")
               where date between {to_db_date(month_begin)} : {to_db_date(month_end)},
                     isValid(secid),
                     isValid(secid2),
                     isValid(traction)
               group by secid, secid2

    monthAgg = select secid, secid2, traction_sum, n_obs
               from monthAgg

    tractionAgg.append!(monthAgg)
    tractionAgg = select sum(traction_sum) as traction_sum,
                         long(sum(n_obs)) as n_obs
                  from tractionAgg
                  group by secid, secid2
    tractionAgg = select secid, secid2, traction_sum, n_obs
                  from tractionAgg

    undef(`monthAgg, VAR)
            """
        )

    return f"""
    periodBegin = {to_db_date(period_begin)}
    periodEnd = {to_db_date(period_end)}
    periodYear = {year_value}
    industryFacname = `{source.industry_facname}

    {delete_clause}

    tractionAgg = table(
        array(SYMBOL, 0) as secid,
        array(SYMBOL, 0) as secid2,
        array(DOUBLE, 0) as traction_sum,
        array(LONG, 0) as n_obs
    )

    {"".join(monthly_blocks)}

    tractionAgg = select sum(traction_sum) \\ sum(n_obs) as traction_avg,
                         long(sum(n_obs)) as n_obs
                  from tractionAgg
                  where n_obs > 0
                  group by secid, secid2
    tractionAgg = select secid, secid2, traction_avg, n_obs
                  from tractionAgg

    industryRaw = select date, secid, facvalue
                  from loadTable("{source.industry_db_path}", "{source.industry_table}")
                  where date between periodBegin : periodEnd,
                        facname = industryFacname,
                        isValid(secid),
                        isValid(facvalue)
                  order by secid, date

    industryLatest = select industryFacname as secid_facname,
                            last(facvalue) as secid_facvalue
                     from industryRaw
                     group by secid

    industryLatest2 = select secid as secid2,
                             secid_facname as secid2_facname,
                             secid_facvalue as secid2_facvalue
                      from industryLatest

    result = lj(tractionAgg, industryLatest, `secid)
    result = lj(result, industryLatest2, `secid2)
    result = select periodEnd as date,
                    periodYear as year,
                    secid,
                    secid2,
                    traction_avg,
                    n_obs,
                    secid_facname,
                    secid_facvalue,
                    secid2_facname,
                    secid2_facvalue
             from result

    loadTable("{source.output_db_path}", "{table_name}").append!(result)

    undef(`tractionAgg`industryRaw`industryLatest`industryLatest2`result, VAR)
    """


def run_periods(
    session: ddb.session,
    source: SourceConfig,
    period_kind: PeriodKind,
    periods: Iterable[tuple[pd.Timestamp, pd.Timestamp]],
) -> None:
    table_name = source.yearly_table if period_kind == "year" else source.monthly_table
    ensure_output_table(session, source.output_db_path, table_name, period_kind)

    for period_begin, period_end in periods:
        if source.skip_existing and period_exists(session, source.output_db_path, table_name, period_end):
            print(f"[skip] {period_kind} {period_begin:%Y%m%d}-{period_end:%Y%m%d} already exists")
            continue
        print(f"[ddb] {period_kind} {period_begin:%Y%m%d}-{period_end:%Y%m%d} -> {table_name}")
        if period_kind == "year":
            script = build_yearly_period_script(
                source=source,
                table_name=table_name,
                period_begin=period_begin,
                period_end=period_end,
            )
        else:
            script = build_period_script(
                source=source,
                period_kind=period_kind,
                table_name=table_name,
                period_begin=period_begin,
                period_end=period_end,
            )
        session.run(script)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aggregate TracCorr_DailyRet traction by year/month and write DolphinDB tables."
    )
    parser.add_argument("--begin-date", help="Begin date, e.g. 20150101. Defaults to source min(date).")
    parser.add_argument("--end-date", help="End date, e.g. 20260630. Defaults to source max(date).")
    parser.add_argument("--env-file", default=".env", help="Path to .env containing ip/port/usr/pwd.")
    parser.add_argument("--traction-db-path", default=TRACTION_DB_PATH)
    parser.add_argument("--traction-table", default=TRACTION_TABLE)
    parser.add_argument("--industry-db-path", default=INDUSTRY_DB_PATH)
    parser.add_argument("--industry-table", default=INDUSTRY_TABLE)
    parser.add_argument("--industry-facname", default=INDUSTRY_FACNAME)
    parser.add_argument("--output-db-path", default=OUTPUT_DB_PATH)
    parser.add_argument("--yearly-table", default=YEARLY_TABLE)
    parser.add_argument("--monthly-table", default=MONTHLY_TABLE)
    parser.add_argument(
        "--only",
        choices=["all", "year", "month"],
        default="all",
        help="Limit output to one aggregation frequency.",
    )
    parser.add_argument(
        "--append-only",
        action="store_true",
        help="Append rows without checking or deleting existing rows; this can create duplicate periods.",
    )
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Delete and recompute periods that already exist in the output tables.",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    if args.append_only and args.replace_existing:
        raise ValueError("--append-only and --replace-existing cannot be used together.")
    config = parse_env(Path(args.env_file))
    source = SourceConfig(
        traction_db_path=args.traction_db_path,
        traction_table=args.traction_table,
        industry_db_path=args.industry_db_path,
        industry_table=args.industry_table,
        industry_facname=args.industry_facname,
        output_db_path=args.output_db_path,
        yearly_table=args.yearly_table,
        monthly_table=args.monthly_table,
        replace_periods=args.replace_existing,
        skip_existing=not args.append_only and not args.replace_existing,
    )

    session = connect(config)
    try:
        source_begin, source_end = get_source_date_range(session, source)
        begin_date = parse_date(args.begin_date) if args.begin_date else source_begin
        end_date = parse_date(args.end_date) if args.end_date else source_end
        begin_date = max(begin_date, source_begin)
        end_date = min(end_date, source_end)
        if begin_date > end_date:
            raise ValueError("Requested date range has no overlap with source traction table.")

        ensure_output_database(session, source.output_db_path)

        if args.only in {"all", "year"}:
            run_periods(
                session=session,
                source=source,
                period_kind="year",
                periods=iter_year_periods(begin_date, end_date),
            )
        if args.only in {"all", "month"}:
            run_periods(
                session=session,
                source=source,
                period_kind="month",
                periods=iter_month_periods(begin_date, end_date),
            )
    finally:
        session.close()

    print(
        "[done] wrote "
        f"{source.yearly_table if args.only in {'all', 'year'} else ''} "
        f"{source.monthly_table if args.only in {'all', 'month'} else ''} "
        f"to {source.output_db_path}"
    )


if __name__ == "__main__":
    main()
