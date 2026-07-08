"""
Run low-frequency factor commands in one entry point.

Supported modes:
- test
- neu
- neu+test
"""

from __future__ import annotations

import argparse
from pathlib import Path

from low_freq_factor_common import (
    DEFAULT_BUY_P,
    DEFAULT_FACTOR_DB_PATH,
    DEFAULT_FACTOR_RAW_DB_PATH,
    DEFAULT_POOLS,
    DEFAULT_RESULTS_DB_PATH,
    DEFAULT_SELL_P,
    ddb_credentials,
    low_freq_service,
    parse_env,
    to_yyyymmdd,
    validate_factor_name,
)
from low_freq_factor_neu import NeuConfig, submit_neu
from low_freq_factor_test import TestConfig, submit_test

TEST_FACTOR_SOURCE_CHOICES = ["raw", "neutralized"]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run low-frequency NEU/TEST commands.")
    parser.add_argument(
        "--mode",
        choices=["test", "neu", "neu+test"],
        default="test",
        help="Command workflow to run.",
    )
    parser.add_argument("--factor", required=True, help="Target factor table name.")
    parser.add_argument("--begin-date", help="Begin date, e.g. 20150105. Required for NEU.")
    parser.add_argument("--end-date", help="End date, e.g. 20250722. Required for NEU.")
    parser.add_argument("--env-file", default=".env", help="Path to .env.")
    parser.add_argument("--factor-raw-db-path", default=DEFAULT_FACTOR_RAW_DB_PATH)
    parser.add_argument("--factor-db-path", default=DEFAULT_FACTOR_DB_PATH)
    parser.add_argument(
        "--test-factor-source",
        choices=TEST_FACTOR_SOURCE_CHOICES,
        help="Factor source for TEST. In test mode defaults to raw; in neu+test defaults to neutralized.",
    )
    parser.add_argument("--test-factor-db-path", help="Override factor_dbPath used by TEST.")
    parser.add_argument("--results-db-path", default=DEFAULT_RESULTS_DB_PATH)
    parser.add_argument("--pools", nargs="+", default=DEFAULT_POOLS, help="Stock pools for TEST.")
    parser.add_argument("--num-g", type=int, default=10, help="Number of groups for TEST.")
    parser.add_argument("--ret-w", type=int, default=20, help="Holding/rebalance period for TEST.")
    parser.add_argument("--buy-p", default=DEFAULT_BUY_P, help="Buy price/time for TEST.")
    parser.add_argument("--sell-p", default=DEFAULT_SELL_P, help="Sell price/time for TEST.")
    parser.add_argument("--dry-run", action="store_true", help="Print JSON command(s) without sending.")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    env = parse_env(Path(args.env_file))
    credentials = ddb_credentials(env)
    service_ip, service_port = low_freq_service(env)
    factor = validate_factor_name(args.factor)
    begin_date = to_yyyymmdd(args.begin_date)
    end_date = to_yyyymmdd(args.end_date)

    if "neu" in args.mode and (not begin_date or not end_date):
        raise ValueError("--begin-date and --end-date are required for mode neu or neu+test.")

    if args.mode in {"neu", "neu+test"}:
        neu_config = NeuConfig(
            factor=factor,
            begin_date=begin_date or "",
            end_date=end_date or "",
            factor_raw_db_path=args.factor_raw_db_path,
            factor_db_path=args.factor_db_path,
            dry_run=args.dry_run,
        )
        submit_neu(neu_config, credentials, service_ip, service_port)

    if args.mode in {"test", "neu+test"}:
        if args.test_factor_db_path:
            test_factor_db_path = args.test_factor_db_path
        elif args.test_factor_source == "raw":
            test_factor_db_path = args.factor_raw_db_path
        elif args.test_factor_source == "neutralized" or args.mode == "neu+test":
            test_factor_db_path = args.factor_db_path
        else:
            test_factor_db_path = args.factor_raw_db_path

        test_config = TestConfig(
            factor=factor,
            factor_db_path=test_factor_db_path,
            results_db_path=args.results_db_path,
            pools=args.pools,
            num_g=args.num_g,
            ret_w=args.ret_w,
            buy_p=args.buy_p,
            sell_p=args.sell_p,
            begin_date=begin_date,
            end_date=end_date,
            dry_run=args.dry_run,
        )
        submit_test(test_config, credentials, service_ip, service_port)


if __name__ == "__main__":
    main()
