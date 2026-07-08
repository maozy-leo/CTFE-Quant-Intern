"""
Append latest Changjiang 20260705 factors to existing DolphinDB factor tables.

This script reads the current max(date) of each selected factor table, then
computes and appends rows from the next calendar day through --end-date.

Example:
    python append_cj20260705_latest_factors.py --end-date 20260708
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Iterable

import pandas as pd

from calc_cj20260705_factors import (
    FACTOR_ALIASES,
    FACTOR_DB_PATH,
    Changjiang20260705FactorCalculator,
    FactorParams,
    parse_env,
    to_yyyymmdd,
)


DEFAULT_APPEND_BEGIN_DATE = "20250723"


def expand_factors(factors: Iterable[str]) -> list[str]:
    selected = list(dict.fromkeys(factors))
    if "all" in selected:
        return list(FACTOR_ALIASES)
    return selected


def factor_table_name(factor: str, params: FactorParams) -> str:
    if factor in {"ret_overall", "ret_period", "ret_point"}:
        return FACTOR_ALIASES[factor]
    if factor == "price_high_amp":
        return (
            f"{FACTOR_ALIASES[factor]}"
            f"_w{params.smooth_window}_l{params.left_window}_r{params.right_window}"
        )
    if factor in {"volume_low_low_ret", "volume_peak_count"}:
        return f"{FACTOR_ALIASES[factor]}_w{params.smooth_window}"
    raise ValueError(f"Unknown factor: {factor}")


def db_date_to_yyyymmdd(value: object) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return None
    return ts.strftime("%Y%m%d")


def next_calendar_day(date: str) -> str:
    return to_yyyymmdd(pd.Timestamp(date) + pd.offsets.Day(1))


def shift_calendar_days(date: str, days: int) -> str:
    return to_yyyymmdd(pd.Timestamp(date) + pd.offsets.Day(days))


def table_exists(calculator: Changjiang20260705FactorCalculator, table_name: str) -> bool:
    return bool(
        calculator.session.run(
            f'existsTable("{calculator.factor_db_path}", "{table_name}")'
        )
    )


def max_factor_date(
    calculator: Changjiang20260705FactorCalculator,
    table_name: str,
) -> str | None:
    value = calculator.session.run(
        f'exec max(date) from loadTable("{calculator.factor_db_path}", "{table_name}")'
    )
    return db_date_to_yyyymmdd(value)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Append latest Changjiang 20260705 raw factors to existing tables."
    )
    parser.add_argument("--end-date", required=True, help="Target end date, e.g. 20260708.")
    parser.add_argument(
        "--factors",
        nargs="+",
        default=["all"],
        choices=["all", *FACTOR_ALIASES.keys()],
        help="Factor keys to append.",
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
        help="Number of calendar months per DolphinDB query.",
    )
    parser.add_argument("--top-pct", type=float, default=0.20, help="Top volume-per-trade share for ret_period.")
    parser.add_argument("--smooth-window", type=int, default=5, help="Rolling mean window for time-point factors.")
    parser.add_argument("--left-window", type=int, default=5, help="Left K-line window for price_high_amp.")
    parser.add_argument("--right-window", type=int, default=5, help="Right K-line window for price_high_amp.")
    parser.add_argument(
        "--recalc-overlap-days",
        type=int,
        default=0,
        help=(
            "Recalculate the last N calendar days already in each factor table. "
            "Rows in the recalculated range are deleted before appending."
        ),
    )
    parser.add_argument(
        "--create-missing",
        action="store_true",
        help="Create missing or empty factor tables and start from --fallback-begin-date.",
    )
    parser.add_argument(
        "--fallback-begin-date",
        default=DEFAULT_APPEND_BEGIN_DATE,
        help="Begin date used only when --create-missing is set and a table is missing or empty.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned date ranges without writing factor rows.",
    )
    return parser


def validate_args(args: argparse.Namespace) -> None:
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
    if args.recalc_overlap_days < 0:
        raise ValueError("--recalc-overlap-days must be non-negative.")


def append_latest_factors(
    calculator: Changjiang20260705FactorCalculator,
    base_params: FactorParams,
    factors: Iterable[str],
    fallback_begin_date: str,
    create_missing: bool,
    recalc_overlap_days: int,
    dry_run: bool,
) -> None:
    end_date = to_yyyymmdd(base_params.end_date)
    fallback_begin_date = to_yyyymmdd(fallback_begin_date)

    for factor in expand_factors(factors):
        table_name = factor_table_name(factor, base_params)
        exists = table_exists(calculator, table_name)
        if not exists:
            if not create_missing:
                raise RuntimeError(
                    f'Factor table "{table_name}" does not exist. '
                    "Use --create-missing only if you really want to create it."
                )
            calculator.create_factor_table(table_name)

        current_max_date = max_factor_date(calculator, table_name)
        if current_max_date is None:
            if not create_missing:
                raise RuntimeError(
                    f'Factor table "{table_name}" is empty. '
                    "Use --create-missing to start from --fallback-begin-date."
                )
            begin_date = fallback_begin_date
        elif recalc_overlap_days > 0:
            begin_date = shift_calendar_days(current_max_date, -(recalc_overlap_days - 1))
        else:
            begin_date = next_calendar_day(current_max_date)

        if pd.Timestamp(begin_date) > pd.Timestamp(end_date):
            print(
                f"[skip] {factor}: {table_name}, current max date {current_max_date} "
                f"is already >= target end date {end_date}."
            )
            continue

        force_update = recalc_overlap_days > 0
        params = replace(
            base_params,
            begin_date=begin_date,
            end_date=end_date,
            force_update=force_update,
        )
        action = "plan" if dry_run else "append"
        print(
            f"[{action}] {factor}: {table_name}, "
            f"current_max={current_max_date or 'EMPTY'}, "
            f"range={begin_date}-{end_date}, "
            f"force_update={force_update}"
        )
        if not dry_run:
            calculator.run_all(params, [factor])


def main() -> None:
    args = build_arg_parser().parse_args()
    validate_args(args)

    env = parse_env(Path(args.env_file))
    params = FactorParams(
        begin_date=DEFAULT_APPEND_BEGIN_DATE,
        end_date=to_yyyymmdd(args.end_date),
        ret_lookback=args.ret_lookback,
        ret_buffer_days=args.ret_buffer_days,
        chunk_months=args.chunk_months,
        top_pct=args.top_pct,
        smooth_window=args.smooth_window,
        left_window=args.left_window,
        right_window=args.right_window,
        force_update=False,
    )

    calculator = Changjiang20260705FactorCalculator(
        ip=str(env["ip"]),
        port=int(env["port"]),
        user=str(env["usr"]),
        password=str(env["pwd"]),
        factor_db_path=FACTOR_DB_PATH,
    )
    try:
        append_latest_factors(
            calculator=calculator,
            base_params=params,
            factors=args.factors,
            fallback_begin_date=args.fallback_begin_date,
            create_missing=args.create_missing,
            recalc_overlap_days=args.recalc_overlap_days,
            dry_run=args.dry_run,
        )
    finally:
        calculator.close()


if __name__ == "__main__":
    main()
