"""
Submit a low-frequency single-factor TEST command.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from low_freq_factor_common import (
    DEFAULT_BUY_P,
    DEFAULT_FACTOR_RAW_DB_PATH,
    DEFAULT_POOLS,
    DEFAULT_RESULTS_DB_PATH,
    DEFAULT_SELL_P,
    ddb_credentials,
    low_freq_service,
    maybe_send,
    parse_env,
    to_yyyymmdd,
    validate_factor_name,
)


@dataclass(frozen=True)
class TestConfig:
    factor: str
    factor_db_path: str
    results_db_path: str
    pools: list[str]
    num_g: int
    ret_w: int
    buy_p: str
    sell_p: str
    begin_date: str | None
    end_date: str | None
    dry_run: bool


def build_test_msg(config: TestConfig, credentials: dict[str, Any]) -> dict[str, Any]:
    validate_factor_name(config.factor)
    if config.num_g <= 1:
        raise ValueError("--num-g must be greater than 1")
    if config.ret_w <= 0:
        raise ValueError("--ret-w must be positive")
    if not config.pools:
        raise ValueError("--pools must include at least one pool")

    msg: dict[str, Any] = {
        **credentials,
        "command": "TEST",
        "factor": config.factor,
        "factor_dbPath": config.factor_db_path,
        "results_dbPath": config.results_db_path,
        "pools": config.pools,
        "num_g": config.num_g,
        "ret_w": config.ret_w,
        "buy_p": config.buy_p,
        "sell_p": config.sell_p,
    }
    if config.begin_date:
        msg["beginDate"] = config.begin_date
    if config.end_date:
        msg["endDate"] = config.end_date
    return msg


def submit_test(config: TestConfig, credentials: dict[str, Any], service_ip: str, service_port: int) -> None:
    msg = build_test_msg(config, credentials)
    maybe_send(msg, service_ip, service_port, config.dry_run)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Submit a low-frequency single-factor TEST command.")
    parser.add_argument("--factor", required=True, help="Target factor table name, e.g. cj20260705_ret_overall_20d.")
    parser.add_argument("--begin-date", help="Optional test begin date, e.g. 20150105.")
    parser.add_argument("--end-date", help="Optional test end date, e.g. 20250722.")
    parser.add_argument("--env-file", default=".env", help="Path to .env.")
    parser.add_argument("--factor-db-path", default=DEFAULT_FACTOR_RAW_DB_PATH, help="Source factor database path.")
    parser.add_argument("--results-db-path", default=DEFAULT_RESULTS_DB_PATH, help="Result database path.")
    parser.add_argument("--pools", nargs="+", default=DEFAULT_POOLS, help="Stock pools for TEST.")
    parser.add_argument("--num-g", type=int, default=10, help="Number of groups for TEST.")
    parser.add_argument("--ret-w", type=int, default=20, help="Holding/rebalance period for TEST.")
    parser.add_argument("--buy-p", default=DEFAULT_BUY_P, help="Buy price/time for TEST.")
    parser.add_argument("--sell-p", default=DEFAULT_SELL_P, help="Sell price/time for TEST.")
    parser.add_argument("--dry-run", action="store_true", help="Print JSON command without sending it.")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    env = parse_env(Path(args.env_file))
    config = TestConfig(
        factor=validate_factor_name(args.factor),
        factor_db_path=args.factor_db_path,
        results_db_path=args.results_db_path,
        pools=args.pools,
        num_g=args.num_g,
        ret_w=args.ret_w,
        buy_p=args.buy_p,
        sell_p=args.sell_p,
        begin_date=to_yyyymmdd(args.begin_date),
        end_date=to_yyyymmdd(args.end_date),
        dry_run=args.dry_run,
    )
    service_ip, service_port = low_freq_service(env)
    submit_test(config, ddb_credentials(env), service_ip, service_port)


if __name__ == "__main__":
    main()
