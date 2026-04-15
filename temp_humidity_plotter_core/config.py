from __future__ import annotations

import logging
import math
import os
import re
from datetime import datetime
from datetime import time as dt_time
from pathlib import Path
from typing import Any

import yaml

ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y.%m.%d %H:%M:%S",
    "%Y.%m.%d %H:%M",
)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ[key] = value.strip()


def resolve_placeholders(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: resolve_placeholders(v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_placeholders(item) for item in value]
    if isinstance(value, str):
        return ENV_PATTERN.sub(_replace_env_placeholder, value)
    return value


def _replace_env_placeholder(match: re.Match[str]) -> str:
    key = match.group(1)
    default = match.group(2) or ""
    return os.getenv(key, default)


def load_app_config(config_path: Path) -> dict[str, Any]:
    load_env_file(Path("common.env"))
    raw_config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    app = resolve_placeholders(raw_config).get("app", {})
    return {
        "log_level": str(app.get("log_level", "INFO")),
        "input_path": str(app.get("input_path", "./input")),
        "output_dir": str(app.get("output_dir", "./output")),
        "input_file_type": str(app.get("input_file_type", "auto")).lstrip(".").lower(),
        "input_mode": str(app.get("input_mode", "batch")).strip().lower(),
        "input_file": app.get("input_file", ""),
        "outdoor_temp_humidity_file": str(app.get("outdoor_temp_humidity_file", "")).strip(),
        "plot_format": str(app.get("plot_format", "png")).lstrip(".").lower(),
        "range_start": str(app.get("range_start", "")).strip(),
        "range_end": str(app.get("range_end", "")).strip(),
        "max_span_days": str(app.get("max_span_days", "")).strip(),
        "highlight_start_time": str(app.get("highlight_start_time", "")).strip(),
        "highlight_end_time": str(app.get("highlight_end_time", "")).strip(),
    }


def parse_log_level(log_level: str) -> int:
    return int(getattr(logging, log_level.strip().upper(), logging.INFO))


def parse_datetime_value(value: str) -> datetime:
    text = re.sub(r"\s+", " ", value.strip())
    if not text:
        raise ValueError("datetime value is empty")

    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass

    for dt_format in DATETIME_FORMATS:
        try:
            return datetime.strptime(text, dt_format)
        except ValueError:
            continue

    try:
        from dateutil import parser as date_parser
    except Exception as exc:  # pragma: no cover
        raise ValueError(f"Unsupported datetime format: {text}") from exc

    return date_parser.parse(text)


def resolve_time_range(config: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    range_start = parse_datetime_value(config["range_start"]) if config["range_start"] else None
    range_end = parse_datetime_value(config["range_end"]) if config["range_end"] else None
    if range_start and range_end and range_start > range_end:
        raise ValueError(
            f"range_start must be earlier than or equal to range_end: {range_start} > {range_end}"
        )
    return range_start, range_end


def resolve_max_span_days(config: dict[str, Any]) -> int | None:
    raw_value = config["max_span_days"]
    if not raw_value:
        return None
    try:
        max_span_days = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"max_span_days must be a number: {raw_value}") from exc
    if max_span_days <= 0:
        raise ValueError(f"max_span_days must be greater than 0: {raw_value}")
    return math.ceil(max_span_days)


def parse_time_of_day(value: str) -> dt_time:
    text = value.strip()
    for time_format in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, time_format).time()
        except ValueError:
            continue
    raise ValueError(f"Unsupported time-of-day format: {value}")


def resolve_highlight_time_range(
    config: dict[str, Any],
) -> tuple[dt_time | None, dt_time | None]:
    start_raw = config["highlight_start_time"]
    end_raw = config["highlight_end_time"]
    if not start_raw and not end_raw:
        return None, None
    if not start_raw or not end_raw:
        raise ValueError("highlight_start_time and highlight_end_time must be set together")
    return parse_time_of_day(start_raw), parse_time_of_day(end_raw)
