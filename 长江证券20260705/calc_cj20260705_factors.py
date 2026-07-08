"""
Calculate factors from "长江证券20260705" and store them in DolphinDB.

The script only submits DolphinDB scripts. Connection parameters are read from
.env keys: ip, port, usr, pwd.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

try:
    import dolphindb as ddb
except ImportError as exc:  # pragma: no cover - only raised when executed without dependency.
    raise SystemExit("Please install dolphindb before running this script.") from exc


DATA_DB_PATH = "dfs://data_m"
DATA_TABLE = "stock_m"
FACTOR_DB_PATH = "dfs://factor_raw_intern"


FACTOR_ALIASES = {
    "ret_overall": "cj20260705_ret_overall_20d",
    "ret_period": "cj20260705_ret_period_20d_top20",
    "ret_point": "cj20260705_ret_point_20d",
    "price_high_amp": "cj20260705_price_high_amp",
    "volume_low_low_ret": "cj20260705_volume_low_low_ret",
    "volume_peak_count": "cj20260705_volume_peak_count",
}


def parse_env(path: Path) -> dict[str, str | int]:
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
    return values


def to_db_date(date: str | pd.Timestamp) -> str:
    ts = pd.Timestamp(date)
    return ts.strftime("%Y.%m.%d")


def to_yyyymmdd(date: str | pd.Timestamp) -> str:
    return pd.Timestamp(date).strftime("%Y%m%d")


@dataclass(frozen=True)
class FactorParams:
    begin_date: str
    end_date: str
    ret_lookback: int = 20
    ret_buffer_days: int = 90
    chunk_months: int = 3
    top_pct: float = 0.20
    smooth_window: int = 5
    left_window: int = 5
    right_window: int = 5
    force_update: bool = False


class Changjiang20260705FactorCalculator:
    def __init__(
        self,
        ip: str,
        port: int,
        user: str,
        password: str,
        data_db_path: str = DATA_DB_PATH,
        data_table: str = DATA_TABLE,
        factor_db_path: str = FACTOR_DB_PATH,
    ) -> None:
        ddb.session.setTimeout(600)
        self.session = ddb.session()
        self.session.connect(ip, port, user, password, keepAliveTime=3600)
        self.data_db_path = data_db_path
        self.data_table = data_table
        self.factor_db_path = factor_db_path

    def close(self) -> None:
        self.session.close()

    def create_factor_table(self, table_name: str) -> None:
        script = f"""
        if(!existsDatabase("{self.factor_db_path}")){{
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
            dbSecid = database("", HASH, [SYMBOL, 2])
            database("{self.factor_db_path}", COMPO, [dbDate, dbSecid])
        }}
        if(!existsTable("{self.factor_db_path}", "{table_name}")){{
            schemaTable = table(
                array(DATE, 0) as date,
                array(SYMBOL, 0) as secid,
                array(DOUBLE, 0) as factor
            )
            db = database("{self.factor_db_path}")
            createPartitionedTable(
                dbHandle=db,
                table=schemaTable,
                tableName="{table_name}",
                partitionColumns=`date`secid
            )
        }}
        """
        self.session.run(script)

    def prepare_table(self, table_name: str, begin_date: str, end_date: str, force_update: bool) -> None:
        self.create_factor_table(table_name)
        if force_update:
            self.session.run(
                f"""
                delete from loadTable("{self.factor_db_path}", "{table_name}")
                where date between {to_db_date(begin_date)} : {to_db_date(end_date)}
                """
            )

    @staticmethod
    def iter_date_chunks(begin_date: str, end_date: str, chunk_months: int) -> Iterable[tuple[str, str]]:
        chunk_begin = pd.Timestamp(begin_date)
        final_end = pd.Timestamp(end_date)
        while chunk_begin <= final_end:
            chunk_end = min(chunk_begin + pd.DateOffset(months=chunk_months) - pd.offsets.Day(1), final_end)
            yield to_yyyymmdd(chunk_begin), to_yyyymmdd(chunk_end)
            chunk_begin = chunk_end + pd.offsets.Day(1)

    @staticmethod
    def ret_buffer_begin(begin_date: str, buffer_days: int) -> str:
        return to_yyyymmdd(pd.Timestamp(begin_date) - pd.offsets.Day(int(buffer_days)))

    def run_all(self, params: FactorParams, factors: Iterable[str]) -> None:
        selected = list(dict.fromkeys(factors))
        if "all" in selected:
            selected = list(FACTOR_ALIASES)

        for factor in selected:
            if factor == "ret_overall":
                self.calc_ret_overall(params)
            elif factor == "ret_period":
                self.calc_ret_period(params)
            elif factor == "ret_point":
                self.calc_ret_point(params)
            elif factor == "price_high_amp":
                self.calc_price_high_amp(params)
            elif factor == "volume_low_low_ret":
                self.calc_volume_low_low_ret(params)
            elif factor == "volume_peak_count":
                self.calc_volume_peak_count(params)
            else:
                raise ValueError(f"Unknown factor: {factor}")

    def calc_ret_overall(self, params: FactorParams) -> None:
        table_name = FACTOR_ALIASES["ret_overall"]
        self.prepare_table(table_name, params.begin_date, params.end_date, params.force_update)
        for chunk_begin, chunk_end in self.iter_date_chunks(params.begin_date, params.end_date, params.chunk_months):
            buffer_begin = self.ret_buffer_begin(chunk_begin, params.ret_buffer_days)
            script = self._ret_base_script(buffer_begin, chunk_end)
            script += f"""
            daily = select sum(log_ret) as raw_factor
                    from bars
                    group by trade_date, secid

            daily = select trade_date as date, secid,
                           msum(raw_factor, {params.ret_lookback}) as raw_factor
                    from daily
                    context by secid csort trade_date

            factor = select date, secid,
                            iif(std(raw_factor) > 0,
                                (raw_factor - avg(raw_factor)) \\ std(raw_factor),
                                double(NULL)) as factor
                     from daily
                     context by date

            factor = select date, secid, factor
                     from factor
                     where date between {to_db_date(chunk_begin)} : {to_db_date(chunk_end)},
                           isValid(factor)
            loadTable("{self.factor_db_path}", "{table_name}").append!(factor)
            """
            self.session.run(script)

    def calc_ret_period(self, params: FactorParams) -> None:
        table_name = FACTOR_ALIASES["ret_period"]
        self.prepare_table(table_name, params.begin_date, params.end_date, params.force_update)
        rank_cutoff = 1.0 - params.top_pct
        for chunk_begin, chunk_end in self.iter_date_chunks(params.begin_date, params.end_date, params.chunk_months):
            buffer_begin = self.ret_buffer_begin(chunk_begin, params.ret_buffer_days)
            script = self._ret_base_script(buffer_begin, chunk_end)
            script += f"""
            bars = select *, rank(vol_per_trade, percent=true) as vol_per_trade_rank
                   from bars
                   context by trade_date, secid

            daily = select sum(log_ret) as raw_factor
                    from bars
                    where vol_per_trade_rank >= {rank_cutoff}, isValid(log_ret)
                    group by trade_date, secid

            daily = select trade_date as date, secid,
                           msum(raw_factor, {params.ret_lookback}) as raw_factor
                    from daily
                    context by secid csort trade_date

            factor = select date, secid,
                            iif(std(raw_factor) > 0,
                                (raw_factor - avg(raw_factor)) \\ std(raw_factor),
                                double(NULL)) as factor
                     from daily
                     context by date

            factor = select date, secid, factor
                     from factor
                     where date between {to_db_date(chunk_begin)} : {to_db_date(chunk_end)},
                           isValid(factor)
            loadTable("{self.factor_db_path}", "{table_name}").append!(factor)
            """
            self.session.run(script)

    def calc_ret_point(self, params: FactorParams) -> None:
        table_name = FACTOR_ALIASES["ret_point"]
        self.prepare_table(table_name, params.begin_date, params.end_date, params.force_update)
        for chunk_begin, chunk_end in self.iter_date_chunks(params.begin_date, params.end_date, params.chunk_months):
            buffer_begin = self.ret_buffer_begin(chunk_begin, params.ret_buffer_days)
            script = self._ret_base_script(buffer_begin, chunk_end)
            script += f"""
            max_point = select max(vol_per_trade) as max_vol_per_trade
                        from bars
                        where isValid(vol_per_trade)
                        group by trade_date, secid

            point = ej(bars, max_point, `trade_date`secid)
            point = select *
                    from point
                    where vol_per_trade = max_vol_per_trade
                    order by secid, trade_date, dt

            daily = select first(log_ret) as raw_factor
                    from point
                    group by trade_date, secid

            daily = select trade_date as date, secid,
                           msum(raw_factor, {params.ret_lookback}) as raw_factor
                    from daily
                    context by secid csort trade_date

            factor = select date, secid,
                            iif(std(raw_factor) > 0,
                                (raw_factor - avg(raw_factor)) \\ std(raw_factor),
                                double(NULL)) as factor
                     from daily
                     context by date

            factor = select date, secid, factor
                     from factor
                     where date between {to_db_date(chunk_begin)} : {to_db_date(chunk_end)},
                           isValid(factor)
            loadTable("{self.factor_db_path}", "{table_name}").append!(factor)
            """
            self.session.run(script)

    def calc_price_high_amp(self, params: FactorParams) -> None:
        table_name = (
            f"{FACTOR_ALIASES['price_high_amp']}"
            f"_w{params.smooth_window}_l{params.left_window}_r{params.right_window}"
        )
        self.prepare_table(table_name, params.begin_date, params.end_date, params.force_update)
        for chunk_begin, chunk_end in self.iter_date_chunks(params.begin_date, params.end_date, params.chunk_months):
            script = self._minute_base_script(chunk_begin, chunk_end)
            script += f"""
            data = select dt, trade_date, secid, close, high, low,
                          mavg(close, {params.smooth_window}) as close_ma,
                          rowNo(close) as rn
                   from raw
                   context by trade_date, secid csort dt

            peak_value = select max(close_ma) as max_close_ma
                         from data
                         where isValid(close_ma)
                         group by trade_date, secid

            peak = ej(data, peak_value, `trade_date`secid)
            peak = select min(rn) as peak_rn
                   from peak
                   where close_ma = max_close_ma
                   group by trade_date, secid

            data = ej(data, peak, `trade_date`secid)
            factor_raw = select avg((high - low) \\ close) as raw_factor
                         from data
                         where close > 0,
                               rn >= peak_rn - {params.left_window},
                               rn <= peak_rn + {params.right_window}
                         group by trade_date, secid

            factor = select trade_date as date, secid,
                            iif(std(raw_factor) > 0,
                                (raw_factor - avg(raw_factor)) \\ std(raw_factor),
                                double(NULL)) as factor
                     from factor_raw
                     context by trade_date

            factor = select date, secid, factor from factor where isValid(factor)
            loadTable("{self.factor_db_path}", "{table_name}").append!(factor)
            """
            self.session.run(script)

    def calc_volume_low_low_ret(self, params: FactorParams) -> None:
        table_name = f"{FACTOR_ALIASES['volume_low_low_ret']}_w{params.smooth_window}"
        self.prepare_table(table_name, params.begin_date, params.end_date, params.force_update)
        for chunk_begin, chunk_end in self.iter_date_chunks(params.begin_date, params.end_date, params.chunk_months):
            script = self._minute_base_script(chunk_begin, chunk_end)
            script += f"""
            data = select dt, trade_date, secid, open, close, volume,
                          iif(open > 0 and close > 0, log(close \\ open), double(NULL)) as log_ret,
                          mavg(volume, {params.smooth_window}) as volume_ma,
                          rowNo(volume) as rn
                   from raw
                   context by trade_date, secid csort dt

            peak_value = select max(volume_ma) as max_volume_ma
                         from data
                         where isValid(volume_ma)
                         group by trade_date, secid

            peak = ej(data, peak_value, `trade_date`secid)
            peak = select min(rn) as peak_rn
                   from peak
                   where volume_ma = max_volume_ma
                   group by trade_date, secid

            data = ej(data, peak, `trade_date`secid)

            left_pool = select trade_date, secid, rn, volume_ma
                        from data
                        where rn < peak_rn, isValid(volume_ma)
            left_min = select min(volume_ma) as left_min_volume
                       from left_pool
                       group by trade_date, secid
            left_pool = ej(left_pool, left_min, `trade_date`secid)
            left_low = select max(rn) as left_rn
                       from left_pool
                       where volume_ma = left_min_volume
                       group by trade_date, secid

            right_pool = select trade_date, secid, rn, volume_ma
                         from data
                         where rn > peak_rn, isValid(volume_ma)
            right_min = select min(volume_ma) as right_min_volume
                        from right_pool
                        group by trade_date, secid
            right_pool = ej(right_pool, right_min, `trade_date`secid)
            right_low = select min(rn) as right_rn
                        from right_pool
                        where volume_ma = right_min_volume
                        group by trade_date, secid

            interval_point = ej(left_low, right_low, `trade_date`secid)
            data = ej(data, interval_point, `trade_date`secid)

            factor_raw = select avg(log_ret) as raw_factor
                         from data
                         where rn >= left_rn,
                               rn <= right_rn,
                               isValid(log_ret)
                         group by trade_date, secid

            factor = select trade_date as date, secid,
                            iif(std(raw_factor) > 0,
                                (raw_factor - avg(raw_factor)) \\ std(raw_factor),
                                double(NULL)) as factor
                     from factor_raw
                     context by trade_date

            factor = select date, secid, factor from factor where isValid(factor)
            loadTable("{self.factor_db_path}", "{table_name}").append!(factor)
            """
            self.session.run(script)

    def calc_volume_peak_count(self, params: FactorParams) -> None:
        table_name = f"{FACTOR_ALIASES['volume_peak_count']}_w{params.smooth_window}"
        self.prepare_table(table_name, params.begin_date, params.end_date, params.force_update)
        for chunk_begin, chunk_end in self.iter_date_chunks(params.begin_date, params.end_date, params.chunk_months):
            script = self._minute_base_script(chunk_begin, chunk_end)
            script += f"""
            data = select dt, trade_date, secid, volume,
                          mavg(volume, {params.smooth_window}) as volume_ma
                   from raw
                   context by trade_date, secid csort dt

            data = select *,
                          avg(volume_ma) as volume_ma_avg,
                          std(volume_ma) as volume_ma_std,
                          prev(volume_ma) as prev_volume_ma,
                          next(volume_ma) as next_volume_ma
                   from data
                   context by trade_date, secid csort dt

            factor_raw = select sum(
                                iif(
                                    isValid(prev_volume_ma) and isValid(next_volume_ma)
                                    and volume_ma > prev_volume_ma
                                    and volume_ma > next_volume_ma
                                    and volume_ma >= volume_ma_avg + volume_ma_std,
                                    1,
                                    0
                                )
                             ) as raw_factor
                         from data
                         group by trade_date, secid

            factor = select trade_date as date, secid,
                            iif(std(raw_factor) > 0,
                                (raw_factor - avg(raw_factor)) \\ std(raw_factor),
                                double(NULL)) as factor
                     from factor_raw
                     context by trade_date

            factor = select date, secid, factor from factor where isValid(factor)
            loadTable("{self.factor_db_path}", "{table_name}").append!(factor)
            """
            self.session.run(script)

    def _minute_base_script(self, begin_date: str, end_date: str) -> str:
        return f"""
        raw = select date as dt,
                     date(date) as trade_date,
                     secid,
                     double(close) as close,
                     double(high) as high,
                     double(low) as low,
                     double(open) as open,
                     double(volume) as volume,
                     double(num_trades) as num_trades
              from loadTable("{self.data_db_path}", "{self.data_table}")
              where date(date) between {to_db_date(begin_date)} : {to_db_date(end_date)},
                    (
                        time(date) between 09:30:00.000 : 11:30:00.000
                        or time(date) between 13:00:00.000 : 15:00:00.000
                    ),
                    isValid(secid),
                    isValid(close),
                    isValid(high),
                    isValid(low),
                    isValid(open),
                    isValid(volume)
              order by secid, trade_date, dt
        """

    def _ret_base_script(self, buffer_begin: str, end_date: str) -> str:
        return f"""
        raw = select date as dt,
                     date(date) as trade_date,
                     secid,
                     double(close) as close,
                     double(high) as high,
                     double(low) as low,
                     double(open) as open,
                     double(volume) as volume,
                     double(num_trades) as num_trades
              from loadTable("{self.data_db_path}", "{self.data_table}")
              where date(date) between {to_db_date(buffer_begin)} : {to_db_date(end_date)},
                    (
                        time(date) between 09:30:00.000 : 11:30:00.000
                        or time(date) between 13:00:00.000 : 15:00:00.000
                    ),
                    isValid(secid),
                    isValid(close),
                    isValid(open),
                    isValid(volume)
              order by secid, trade_date, dt

        bars = select trade_date, secid, dt, open, high, low, close, volume, num_trades,
                      iif(open > 0 and close > 0, log(close \\ open), double(NULL)) as log_ret,
                      iif(num_trades > 0, volume \\ num_trades, double(NULL)) as vol_per_trade
               from raw
               order by secid, trade_date, dt
        """


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Calculate Changjiang 20260705 raw factors.")
    parser.add_argument("--begin-date", required=True, help="Start date, e.g. 20240101.")
    parser.add_argument("--end-date", required=True, help="End date, e.g. 20241231.")
    parser.add_argument(
        "--factors",
        nargs="+",
        default=["all"],
        choices=["all", *FACTOR_ALIASES.keys()],
        help="Factor keys to calculate.",
    )
    parser.add_argument("--env-file", default=".env", help="Path to .env containing ip/port/usr/pwd.")
    parser.add_argument("--ret-lookback", type=int, default=20, help="Trading-day lookback for return factors.")
    parser.add_argument(
        "--ret-buffer-days",
        type=int,
        default=90,
        help="Calendar-day buffer before each return-factor chunk for rolling lookback.",
    )
    parser.add_argument(
        "--chunk-months",
        type=int,
        default=3,
        help="Number of calendar months per DolphinDB query for return factors.",
    )
    parser.add_argument("--top-pct", type=float, default=0.20, help="Top volume-per-trade share for ret_period.")
    parser.add_argument("--smooth-window", type=int, default=5, help="Rolling mean window for time-point factors.")
    parser.add_argument("--left-window", type=int, default=5, help="Left K-line window for price_high_amp.")
    parser.add_argument("--right-window", type=int, default=5, help="Right K-line window for price_high_amp.")
    parser.add_argument("--force-update", action="store_true", help="Delete existing rows in the date range first.")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    if args.ret_lookback <= 0:
        raise ValueError("--ret-lookback must be positive.")
    if args.ret_buffer_days <= 0:
        raise ValueError("--ret-buffer-days must be positive.")
    if args.chunk_months <= 0:
        raise ValueError("--chunk-months must be positive.")
    if not 0 < args.top_pct <= 1:
        raise ValueError("--top-pct must be in (0, 1].")
    if args.smooth_window <= 0:
        raise ValueError("--smooth-window must be positive.")
    if args.left_window < 0 or args.right_window < 0:
        raise ValueError("--left-window and --right-window must be non-negative.")

    env = parse_env(Path(args.env_file))
    params = FactorParams(
        begin_date=to_yyyymmdd(args.begin_date),
        end_date=to_yyyymmdd(args.end_date),
        ret_lookback=args.ret_lookback,
        ret_buffer_days=args.ret_buffer_days,
        chunk_months=args.chunk_months,
        top_pct=args.top_pct,
        smooth_window=args.smooth_window,
        left_window=args.left_window,
        right_window=args.right_window,
        force_update=args.force_update,
    )

    calculator = Changjiang20260705FactorCalculator(
        ip=str(env["ip"]),
        port=int(env["port"]),
        user=str(env["usr"]),
        password=str(env["pwd"]),
    )
    try:
        calculator.run_all(params, args.factors)
    finally:
        calculator.close()


if __name__ == "__main__":
    main()
