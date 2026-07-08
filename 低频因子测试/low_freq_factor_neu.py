"""
Submit a low-frequency NEU command for industry/market-value neutralization.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from low_freq_factor_common import (
    DEFAULT_FACTOR_DB_PATH,
    DEFAULT_FACTOR_RAW_DB_PATH,
    ddb_credentials,
    low_freq_service,
    maybe_send,
    parse_env,
    to_yyyymmdd,
    validate_factor_name,
)


@dataclass(frozen=True)
class NeuConfig:
    factor: str
    begin_date: str
    end_date: str
    factor_raw_db_path: str
    factor_db_path: str
    dry_run: bool


def build_neu_msg(config: NeuConfig, credentials: dict[str, Any]) -> dict[str, Any]:
    validate_factor_name(config.factor)
    if not config.begin_date or not config.end_date:
        raise ValueError("--begin-date and --end-date are required for NEU")

    return {
        **credentials,
        "command": "NEU",
        "factor": config.factor,
        "beginDate": config.begin_date,
        "endDate": config.end_date,
        "factor_raw_dbPath": config.factor_raw_db_path,
        "factor_dbPath": config.factor_db_path,
    }


def submit_neu(config: NeuConfig, credentials: dict[str, Any], service_ip: str, service_port: int) -> None:
    msg = build_neu_msg(config, credentials)
    maybe_send(msg, service_ip, service_port, config.dry_run)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Submit a low-frequency NEU command.")
    parser.add_argument("--factor", required=True, help="Target factor table name.")
    parser.add_argument("--begin-date", required=True, help="Neutralization begin date, e.g. 20150105.")
    parser.add_argument("--end-date", required=True, help="Neutralization end date, e.g. 20250722.")
    parser.add_argument("--env-file", default=".env", help="Path to .env.")
    parser.add_argument("--factor-raw-db-path", default=DEFAULT_FACTOR_RAW_DB_PATH)
    parser.add_argument("--factor-db-path", default=DEFAULT_FACTOR_DB_PATH)
    parser.add_argument("--dry-run", action="store_true", help="Print JSON command without sending it.")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    env = parse_env(Path(args.env_file))
    config = NeuConfig(
        factor=validate_factor_name(args.factor),
        begin_date=to_yyyymmdd(args.begin_date) or "",
        end_date=to_yyyymmdd(args.end_date) or "",
        factor_raw_db_path=args.factor_raw_db_path,
        factor_db_path=args.factor_db_path,
        dry_run=args.dry_run,
    )
    service_ip, service_port = low_freq_service(env)
    submit_neu(config, ddb_credentials(env), service_ip, service_port)


if __name__ == "__main__":
    main()
