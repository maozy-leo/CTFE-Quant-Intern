from __future__ import annotations

import datetime as dt
import json
import socket
from pathlib import Path
from typing import Any


DEFAULT_FACTOR_RAW_DB_PATH = "dfs://factor_raw_intern"
DEFAULT_FACTOR_DB_PATH = "dfs://factor_intern"
DEFAULT_RESULTS_DB_PATH = "dfs://factor_results_intern"
DEFAULT_POOLS = ["market", "1000", "500", "300"]
DEFAULT_BUY_P = "t1_open"
DEFAULT_SELL_P = "t2_open"


def parse_env(path: Path) -> dict[str, str | int]:
    values: dict[str, str | int] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = [part.strip() for part in line.split("=", 1)]
        value = value.strip("\"'")
        values[key] = int(value) if key.lower().endswith("port") else value

    required = {"ip", "port", "usr", "pwd", "LOW_FREQ_SERVICE_IP", "LOW_FREQ_SERVICE_PORT"}
    missing = required - set(values)
    if missing:
        raise ValueError(f"Missing keys in {path}: {sorted(missing)}")
    return values


def parse_date(date: str) -> dt.date:
    normalized = str(date).strip().replace("-", "").replace(".", "").replace("/", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"Date must be YYYYMMDD, got: {date}")
    return dt.datetime.strptime(normalized, "%Y%m%d").date()


def to_yyyymmdd(date: str | None) -> str | None:
    return parse_date(date).strftime("%Y%m%d") if date else None


def validate_factor_name(name: str) -> str:
    if not name:
        raise ValueError("factor name cannot be empty")
    if not all(ch.isalnum() or ch == "_" for ch in name):
        raise ValueError("factor name may only contain letters, digits, and underscore")
    return name


def ddb_credentials(env: dict[str, str | int]) -> dict[str, Any]:
    return {
        "ip": str(env["ip"]),
        "port": int(env["port"]),
        "user": str(env["usr"]),
        "passwd": str(env["pwd"]),
    }


def low_freq_service(env: dict[str, str | int]) -> tuple[str, int]:
    return str(env["LOW_FREQ_SERVICE_IP"]), int(env["LOW_FREQ_SERVICE_PORT"])


def print_msg(msg: dict[str, Any]) -> None:
    printable_msg = dict(msg)
    if "passwd" in printable_msg:
        printable_msg["passwd"] = "***"
    print(json.dumps(printable_msg, ensure_ascii=False, indent=2))


def send_command(msg_dict: dict[str, Any], service_ip: str, service_port: int) -> None:
    msg = json.dumps(msg_dict, ensure_ascii=False).encode("utf-8")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((service_ip, service_port))
        print(f"Connected to {service_ip}:{service_port}")
        sock.sendall(msg)
        while True:
            response = sock.recv(4096)
            if not response:
                continue
            response_str = response.decode("utf-8")
            print(f"Received from server: {response_str}")
            if response_str == "Finished":
                break


def maybe_send(msg: dict[str, Any], service_ip: str, service_port: int, dry_run: bool) -> None:
    print_msg(msg)
    if not dry_run:
        send_command(msg, service_ip, service_port)
