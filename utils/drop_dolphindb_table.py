from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = "dfs://factor_intern"
DEFAULT_ENV_FILE = ".env"

DB_PATH_PATTERN = re.compile(r"^dfs://[A-Za-z0-9_./:-]+$")
TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _import_dolphindb():
    try:
        import dolphindb as ddb
    except ImportError as exc:  # pragma: no cover - only raised without dependency.
        raise SystemExit("Please install dolphindb before running this script.") from exc
    return ddb


def parse_env(path: Path) -> dict[str, str | int]:
    values: dict[str, str | int] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = [part.strip() for part in line.split("=", 1)]
        value = value.strip("\"'")
        values[key] = int(value) if key.lower().endswith("port") else value
    return values


def validate_db_path(db_path: str) -> str:
    db_path = db_path.strip()
    if not DB_PATH_PATTERN.fullmatch(db_path):
        raise ValueError(
            "db_path must be a DolphinDB dfs path containing only letters, "
            "digits, underscore, slash, colon, dot, or hyphen."
        )
    return db_path


def validate_table_name(table_name: str) -> str:
    table_name = table_name.strip()
    if not TABLE_NAME_PATTERN.fullmatch(table_name):
        raise ValueError(
            "table_name must start with a letter or underscore and contain only "
            "letters, digits, or underscore."
        )
    return table_name


def ddb_string_literal(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass(frozen=True)
class ConnectionConfig:
    host: str
    port: int
    user: str
    password: str


@dataclass(frozen=True)
class DropResult:
    status: str
    db_path: str
    table_name: str
    message: str


def connection_config_from_args(args: argparse.Namespace) -> ConnectionConfig:
    env_path = Path(args.env_file)
    env: dict[str, Any] = parse_env(env_path) if env_path.exists() else {}

    host = args.host or env.get("ip") or env.get("host")
    port = args.port or env.get("port")
    user = args.user or env.get("usr") or env.get("user") or env.get("userid")
    password = args.password or env.get("pwd") or env.get("password")

    missing = [
        name
        for name, value in {
            "host/ip": host,
            "port": port,
            "user/usr": user,
            "password/pwd": password,
        }.items()
        if value in (None, "")
    ]
    if missing:
        raise ValueError(
            f"Missing DolphinDB connection value(s): {', '.join(missing)}. "
            f"Provide them in {env_path} or via command-line options."
        )

    return ConnectionConfig(
        host=str(host),
        port=int(port),
        user=str(user),
        password=str(password),
    )


class DolphinDBTableDropper:
    def __init__(self, config: ConnectionConfig, keep_alive_time: int = 3600) -> None:
        ddb = _import_dolphindb()
        self.session = ddb.session()
        self.session.connect(
            config.host,
            config.port,
            config.user,
            config.password,
            keepAliveTime=keep_alive_time,
        )

    def close(self) -> None:
        self.session.close()

    def database_exists(self, db_path: str) -> bool:
        return bool(self.session.run(f"existsDatabase({ddb_string_literal(db_path)})"))

    def table_exists(self, db_path: str, table_name: str) -> bool:
        return bool(
            self.session.run(
                f"existsTable({ddb_string_literal(db_path)}, {ddb_string_literal(table_name)})"
            )
        )

    def drop_table(
        self,
        db_path: str,
        table_name: str,
        *,
        dry_run: bool = False,
        ignore_missing: bool = False,
    ) -> DropResult:
        db_path = validate_db_path(db_path)
        table_name = validate_table_name(table_name)

        if not self.database_exists(db_path):
            message = f"Database does not exist: {db_path}"
            if ignore_missing:
                return DropResult("missing_database", db_path, table_name, message)
            raise RuntimeError(message)

        if not self.table_exists(db_path, table_name):
            message = f"Table does not exist: {db_path}/{table_name}"
            if ignore_missing:
                return DropResult("missing_table", db_path, table_name, message)
            raise RuntimeError(message)

        if dry_run:
            return DropResult(
                "would_drop",
                db_path,
                table_name,
                f"Would drop table: {db_path}/{table_name}",
            )

        script = f"""
        db = database({ddb_string_literal(db_path)})
        dropTable(db, {ddb_string_literal(table_name)})
        """
        self.session.run(script)
        return DropResult("dropped", db_path, table_name, f"Dropped table: {db_path}/{table_name}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Drop one table from a DolphinDB DFS database.",
    )
    parser.add_argument("table_name", help="DolphinDB table name to drop.")
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"DolphinDB database path. Default: {DEFAULT_DB_PATH}",
    )
    parser.add_argument(
        "--env-file",
        default=DEFAULT_ENV_FILE,
        help="Path to .env containing ip/port/usr/pwd. Default: .env",
    )
    parser.add_argument("--host", help="DolphinDB host. Overrides .env ip/host.")
    parser.add_argument("--port", type=int, help="DolphinDB port. Overrides .env port.")
    parser.add_argument("--user", help="DolphinDB user. Overrides .env usr/user.")
    parser.add_argument("--password", help="DolphinDB password. Overrides .env pwd/password.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check whether the table exists without deleting it.",
    )
    parser.add_argument(
        "--ignore-missing",
        action="store_true",
        help="Exit successfully if the database or table does not exist.",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Actually drop the table. Required unless --dry-run is used.",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    if not args.dry_run and not args.yes:
        raise SystemExit("Refusing to drop a table without --yes. Use --dry-run to check first.")

    config = connection_config_from_args(args)
    dropper = DolphinDBTableDropper(config)
    try:
        result = dropper.drop_table(
            db_path=args.db_path,
            table_name=args.table_name,
            dry_run=args.dry_run,
            ignore_missing=args.ignore_missing,
        )
    finally:
        dropper.close()

    print(f"[{result.status}] {result.message}")


if __name__ == "__main__":
    main()
