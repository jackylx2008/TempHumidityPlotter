"""Generate a two-series temperature comparison plot from CSV input files."""

from __future__ import annotations

import csv
import logging
import math
import os
import re
from datetime import datetime, timedelta
from datetime import time as dt_time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import matplotlib.dates as mdates
import yaml

from logging_config import get_logger, setup_logger

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure

ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
REQUIRED_COLUMNS = {"datetime", "temperature_C", "humidity_RH"}
ENCODING_CANDIDATES = ("utf-8-sig", "utf-8", "gb18030", "gbk")
DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y.%m.%d %H:%M:%S",
    "%Y.%m.%d %H:%M",
)
SUPPORTED_INPUT_FILE_TYPES = {"csv", "txt"}


DiagnosticEntry = dict[str, str | int]


def load_env_file(path: Path) -> None:
    """Load KEY=VALUE pairs into environment without overriding existing values."""
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
        os.environ.setdefault(key, value.strip())


def resolve_placeholders(value: Any) -> Any:
    """Resolve ${ENV:-default} placeholders recursively."""
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
        "plot_format": str(app.get("plot_format", "png")).lstrip(".").lower(),
        "range_start": str(app.get("range_start", "")).strip(),
        "range_end": str(app.get("range_end", "")).strip(),
        "max_span_days": str(app.get("max_span_days", "")).strip(),
        "highlight_start_time": str(app.get("highlight_start_time", "")).strip(),
        "highlight_end_time": str(app.get("highlight_end_time", "")).strip(),
    }


def parse_log_level(log_level: str) -> int:
    return int(getattr(logging, log_level.strip().upper(), logging.INFO))


def parse_input_targets(input_file: Any) -> list[str]:
    if not input_file:
        return []
    if isinstance(input_file, list):
        return [str(item).strip() for item in input_file if str(item).strip()]
    if isinstance(input_file, str):
        return [part.strip() for part in re.split(r"[;,]", input_file) if part.strip()]
    return [str(input_file).strip()]


def resolve_input_files(config: dict[str, Any]) -> list[Path]:
    input_dir = Path(config["input_path"])
    file_type = config["input_file_type"]
    input_mode = config["input_mode"]

    if input_mode == "single":
        targets = parse_input_targets(config["input_file"])
        if len(targets) != 2:
            raise ValueError("single mode requires exactly 2 files in app.input_file.")
        files = []
        for item in targets:
            path = Path(item)
            if not path.is_absolute():
                path = input_dir / path
            files.append(path)
    elif input_mode == "batch":
        if not input_dir.exists():
            raise FileNotFoundError(
                "Input directory does not exist: "
                f"{input_dir} (configured from app.input_path / INPUT_FILE)"
            )
        if not input_dir.is_dir():
            raise NotADirectoryError(
                "Input path is not a directory in batch mode: "
                f"{input_dir} (configured from app.input_path / INPUT_FILE)"
            )
        if file_type == "auto":
            files = sorted(
                path
                for path in input_dir.iterdir()
                if path.is_file() and path.suffix.lower().lstrip(".") in SUPPORTED_INPUT_FILE_TYPES
            )
        else:
            files = sorted(
                path
                for path in input_dir.iterdir()
                if path.is_file() and path.suffix.lower().lstrip(".") == file_type
            )
    else:
        raise ValueError(f"Unsupported input_mode: {input_mode}")

    if len(files) != 2:
        available_files = sorted(path.name for path in input_dir.iterdir() if path.is_file())
        raise ValueError(
            f"Exactly 2 input files are required, found {len(files)} files: "
            f"{[str(path) for path in files]}. "
            f"input_path={input_dir}, input_file_type={file_type}, "
            f"available_files={available_files}"
        )

    missing_files = [str(path) for path in files if not path.exists()]
    if missing_files:
        raise FileNotFoundError(f"Input files not found: {missing_files}")

    return files


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


def add_diagnostic(
    diagnostics: list[DiagnosticEntry],
    level: str,
    source: str,
    line_no: int | None,
    content: str,
    detail: str,
) -> None:
    diagnostics.append(
        {
            "level": level.upper(),
            "source": source,
            "line_no": "" if line_no is None else str(line_no),
            "content": content,
            "detail": detail,
        }
    )


def escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>").strip() or "-"


def write_diagnostics_report(
    diagnostics: list[DiagnosticEntry],
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "temp_humidity_diagnostics.md"

    sections = ["WARNING", "ERROR"]
    lines = ["# Temp Humidity Diagnostics", ""]
    for level in sections:
        level_entries = [item for item in diagnostics if item["level"] == level]
        lines.append(f"## {level.title()}s")
        lines.append("")
        lines.append("| Level | Source | Line | Content | Detail |")
        lines.append("|:---:|:---:|:---:|:---:|:---:|")
        if level_entries:
            for item in level_entries:
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            escape_markdown_cell(str(item["level"])),
                            escape_markdown_cell(str(item["source"])),
                            escape_markdown_cell(str(item["line_no"])),
                            escape_markdown_cell(str(item["content"])),
                            escape_markdown_cell(str(item["detail"])),
                        ]
                    )
                    + " |"
                )
        else:
            lines.append("| - | - | - | - | No entries |")
        lines.append("")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def filter_series_by_time_range(
    series: list[tuple[datetime, float]],
    start_time: datetime | None,
    end_time: datetime | None,
    source_name: str,
) -> list[tuple[datetime, float]]:
    filtered = [
        item
        for item in series
        if (start_time is None or item[0] >= start_time)
        and (end_time is None or item[0] <= end_time)
    ]
    if not filtered:
        raise ValueError(
            f"No data points remain in {source_name} after time filter: "
            f"start={start_time}, end={end_time}"
        )
    return filtered


def read_temperature_series(
    csv_path: Path,
    diagnostics: list[DiagnosticEntry],
) -> list[tuple[datetime, float]]:
    decode_error: UnicodeDecodeError | None = None
    for encoding in ENCODING_CANDIDATES:
        try:
            if csv_path.suffix.lower() == ".txt":
                return _read_temperature_report_with_encoding(csv_path, encoding, diagnostics)
            return _read_temperature_series_with_encoding(csv_path, encoding, diagnostics)
        except UnicodeDecodeError as exc:
            decode_error = exc
            continue

    if decode_error:
        raise decode_error
    raise ValueError(f"Failed to read input file: {csv_path}")


def _read_temperature_series_with_encoding(
    csv_path: Path,
    encoding: str,
    diagnostics: list[DiagnosticEntry],
) -> list[tuple[datetime, float]]:
    rows: list[tuple[datetime, float]] = []
    with csv_path.open("r", encoding=encoding, newline="") as file_handle:
        reader = csv.DictReader(file_handle)
        fieldnames = set(reader.fieldnames or [])
        missing_columns = REQUIRED_COLUMNS.difference(fieldnames)
        if missing_columns:
            add_diagnostic(
                diagnostics,
                "ERROR",
                csv_path.name,
                1,
                ",".join(reader.fieldnames or []),
                f"CSV columns missing: {sorted(missing_columns)}",
            )
            raise ValueError(
                f"CSV columns missing in {csv_path.name}: {sorted(missing_columns)}"
            )

        for line_no, row in enumerate(reader, start=2):
            if not any((value or "").strip() for value in row.values()):
                continue
            try:
                dt_value = parse_datetime_value((row.get("datetime") or "").strip())
                temp_value = float((row.get("temperature_C") or "").strip())
            except Exception as exc:
                add_diagnostic(
                    diagnostics,
                    "ERROR",
                    csv_path.name,
                    line_no,
                    repr(row),
                    "Invalid CSV row",
                )
                raise ValueError(
                    f"Invalid row in {csv_path.name} at line {line_no}: {row}"
                ) from exc
            rows.append((dt_value, temp_value))

    if not rows:
        raise ValueError(f"No data rows found in {csv_path.name}")

    rows.sort(key=lambda item: item[0])
    return rows


def _read_temperature_report_with_encoding(
    txt_path: Path,
    encoding: str,
    diagnostics: list[DiagnosticEntry],
) -> list[tuple[datetime, float]]:
    rows: list[tuple[datetime, float]] = []
    header_found = False
    expected_year: int | None = None
    corrected_year_rows: list[tuple[int, str]] = []
    ff_rows: list[tuple[int, str]] = []
    skipped_rows: list[tuple[int, str]] = []

    with txt_path.open("r", encoding=encoding, newline="") as file_handle:
        for line_no, raw_line in enumerate(file_handle, start=1):
            line = raw_line.replace("\x00", "").strip()
            if not line:
                continue

            if not header_found:
                if expected_year is None and "开始记录时间" in line:
                    match = re.search(
                        r"开始记录时间[:：]\s*([0-9]{4}[/-][0-9]{2}[/-][0-9]{2}\s+[0-9]{2}:[0-9]{2}:[0-9]{2})",
                        line,
                    )
                    if match:
                        expected_year = parse_datetime_value(match.group(1)).year
                if "温度(℃)" in line and "湿度(%RH)" in line:
                    header_found = True
                continue

            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 3:
                continue

            if parts[1].upper() == "FF":
                ff_rows.append((line_no, line))
                continue

            try:
                dt_value = parse_datetime_value(parts[0])
                if expected_year is not None and dt_value.year != expected_year:
                    dt_value = dt_value.replace(year=expected_year)
                    corrected_year_rows.append((line_no, line))
                temp_value = float(parts[1])
                float(parts[2])
            except Exception:
                skipped_rows.append((line_no, line))
                continue
            rows.append((dt_value, temp_value))

    if not header_found:
        add_diagnostic(
            diagnostics,
            "ERROR",
            txt_path.name,
            None,
            "",
            "TXT header row not found",
        )
        raise ValueError(f"TXT header row not found in {txt_path.name}")
    if not rows:
        add_diagnostic(
            diagnostics,
            "ERROR",
            txt_path.name,
            None,
            "",
            "No data rows found in TXT file",
        )
        raise ValueError(f"No data rows found in {txt_path.name}")
    if ff_rows:
        logging.getLogger(__name__).warning(
            'Removed %s TXT rows with temperature "FF" in %s (lines: %s)',
            len(ff_rows),
            txt_path.name,
            [item[0] for item in ff_rows[:10]],
        )
        for line_no, line in ff_rows:
            add_diagnostic(
                diagnostics,
                "WARNING",
                txt_path.name,
                line_no,
                line,
                'Temperature "FF" row removed from plot',
            )
    if skipped_rows:
        logging.getLogger(__name__).warning(
            "Skipped %s invalid TXT rows in %s (lines: %s)",
            len(skipped_rows),
            txt_path.name,
            [item[0] for item in skipped_rows[:10]],
        )
        for line_no, line in skipped_rows:
            add_diagnostic(
                diagnostics,
                "WARNING",
                txt_path.name,
                line_no,
                line,
                "Invalid TXT row skipped",
            )
    if corrected_year_rows:
        logging.getLogger(__name__).warning(
            "Corrected year for %s TXT rows in %s using header year %s (lines: %s)",
            len(corrected_year_rows),
            txt_path.name,
            expected_year,
            [item[0] for item in corrected_year_rows[:10]],
        )
        for line_no, line in corrected_year_rows:
            add_diagnostic(
                diagnostics,
                "WARNING",
                txt_path.name,
                line_no,
                line,
                f"Year corrected to {expected_year}",
            )

    rows.sort(key=lambda item: item[0])
    return rows


def extract_legend_label(csv_path: Path) -> str:
    stem = csv_path.stem
    match = re.search(r"^[^_]*_([^_]+)_", stem)
    if match:
        return match.group(1)
    return stem


def safe_name_fragment(text: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text.strip())
    return cleaned.strip("-") or "series"


def build_output_file(output_dir: Path, labels: list[str], plot_format: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    left = safe_name_fragment(labels[0])
    right = safe_name_fragment(labels[1])
    filename = f"temperature_compare_{left}_vs_{right}.{plot_format}"
    return output_dir / filename


def build_paged_output_file(output_path: Path, page_index: int, page_count: int) -> Path:
    if page_count <= 1:
        return output_path
    return output_path.with_name(
        f"{output_path.stem}_p{page_index + 1:02d}{output_path.suffix}"
    )


def split_series_into_pages(
    series_list: list[list[tuple[datetime, float]]],
    max_span_days: int | None,
) -> list[list[list[tuple[datetime, float]]]]:
    if not max_span_days:
        return [series_list]

    all_times = [item[0] for series in series_list for item in series]
    if not all_times:
        return [series_list]

    min_time = min(all_times)
    max_time = max(all_times)
    min_date = min_time.date()
    max_date = max_time.date()
    total_days = (max_date - min_date).days + 1
    if total_days <= max_span_days:
        return [series_list]

    pages: list[list[list[tuple[datetime, float]]]] = []
    page_start_date = min_date
    while page_start_date <= max_date:
        page_end_date = page_start_date + timedelta(days=max_span_days)
        page_start = datetime.combine(page_start_date, datetime.min.time())
        page_end = datetime.combine(page_end_date, datetime.min.time())
        page_series_list = [
            [item for item in series if page_start <= item[0] < page_end]
            for series in series_list
        ]
        if any(page_series for page_series in page_series_list):
            pages.append(page_series_list)
        page_start_date = page_end_date
    return pages or [series_list]


def plot_temperature_comparison(
    series_list: list[list[tuple[datetime, float]]],
    labels: list[str],
    output_path: Path,
    plot_format: str,
    highlight_time_range: tuple[dt_time | None, dt_time | None],
) -> None:
    os.environ.setdefault("MPLBACKEND", "Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False

    figure, axis = plt.subplots(figsize=(14, 7))
    figure = cast("Figure", figure)
    axis = cast("Axes", axis)
    colors = ["#D55E00", "#0072B2"]

    all_times = [item[0] for series in series_list for item in series]
    if all_times:
        start_time = min(all_times)
        end_time = max(all_times)
        highlight_start, highlight_end = highlight_time_range
        if highlight_start and highlight_end:
            current_date = start_time.date()
            end_date = end_time.date()
            while current_date <= end_date:
                span_start = datetime.combine(current_date, highlight_start)
                span_end = datetime.combine(current_date, highlight_end)
                if span_end <= span_start:
                    span_end += timedelta(days=1)
                visible_start = max(span_start, start_time)
                visible_end = min(span_end, end_time)
                if visible_start < visible_end:
                    axis.axvspan(
                        float(mdates.date2num(visible_start)),
                        float(mdates.date2num(visible_end)),
                        color="#B9DFFF",
                        alpha=0.5,
                        zorder=-2,
                    )
                current_date += timedelta(days=1)

    for index, series in enumerate(series_list):
        x_values = [float(mdates.date2num(item[0])) for item in series]
        y_values = [item[1] for item in series]
        axis.plot(
            x_values,
            y_values,
            linewidth=2.0,
            color=colors[index % len(colors)],
            label=labels[index],
            zorder=3,
        )

    axis.set_xlabel("\u65f6\u95f4", fontsize=12)
    axis.set_ylabel("\u6e29\u5ea6 (\u00b0C)", fontsize=12)
    axis.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 4)))
    axis.xaxis.set_minor_locator(mdates.HourLocator(interval=1))
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    axis.tick_params(axis="x", rotation=30)
    axis.grid(
        True,
        axis="x",
        which="major",
        linestyle="--",
        color="#A0A0A0",
        alpha=0.55,
        linewidth=0.9,
        zorder=0,
    )
    axis.grid(
        True,
        axis="x",
        which="minor",
        linestyle="--",
        color="#B5B5B5",
        alpha=0.45,
        linewidth=0.8,
        zorder=0,
    )

    if all_times:
        start_time = min(all_times)
        end_time = max(all_times)
        midnight = datetime.combine(start_time.date(), datetime.min.time())
        if midnight < start_time:
            midnight += timedelta(days=1)
        while midnight <= end_time:
            axis.axvline(
                float(mdates.date2num(midnight)),
                color="#5C5C5C",
                linestyle="--",
                linewidth=1.3,
                alpha=0.9,
                zorder=1,
            )
            midnight += timedelta(days=1)
    axis.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, 1.02),
        ncol=2,
        frameon=False,
        fontsize=11,
    )

    figure.tight_layout(rect=(0.0, 0.0, 1.0, 0.96))
    figure.savefig(output_path, format=plot_format, dpi=180)
    plt.close(figure)


def main() -> int:
    config = load_app_config(Path("config.yaml"))
    setup_logger(log_level=parse_log_level(config["log_level"]))
    logger = get_logger(__name__)
    diagnostics: list[DiagnosticEntry] = []
    range_start, range_end = resolve_time_range(config)
    max_span_days = resolve_max_span_days(config)
    highlight_time_range = resolve_highlight_time_range(config)
    output_dir = Path(config["output_dir"])
    try:
        input_files = resolve_input_files(config)
        logger.info("Selected input files: %s", [str(path) for path in input_files])
        if range_start or range_end:
            logger.info("Applying time range filter: start=%s, end=%s", range_start, range_end)
        if max_span_days:
            logger.info("Applying max page span: %s days", max_span_days)
        if highlight_time_range[0] and highlight_time_range[1]:
            logger.info(
                "Applying daily highlight range: %s to %s",
                highlight_time_range[0],
                highlight_time_range[1],
            )

        series_list = [
            filter_series_by_time_range(
                read_temperature_series(path, diagnostics),
                range_start,
                range_end,
                path.name,
            )
            for path in input_files
        ]
        labels = [extract_legend_label(path) for path in input_files]
        output_path = build_output_file(output_dir, labels, config["plot_format"])
        paged_series_list = split_series_into_pages(series_list, max_span_days)
        output_paths: list[Path] = []
        for page_index, page_series_list in enumerate(paged_series_list):
            page_output_path = build_paged_output_file(
                output_path,
                page_index,
                len(paged_series_list),
            )
            plot_temperature_comparison(
                page_series_list,
                labels,
                page_output_path,
                config["plot_format"],
                highlight_time_range,
            )
            output_paths.append(page_output_path)

        report_path = write_diagnostics_report(diagnostics, output_dir)
        logger.info("Diagnostics report generated: %s", report_path.resolve())
        for page_output_path in output_paths:
            logger.info("Plot generated: %s", page_output_path.resolve())
            print(str(page_output_path.resolve()))
        return 0
    except Exception as exc:
        add_diagnostic(diagnostics, "ERROR", "__main__", None, "", str(exc))
        report_path = write_diagnostics_report(diagnostics, output_dir)
        logger.info("Diagnostics report generated: %s", report_path.resolve())
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        logging.basicConfig(
            level=logging.ERROR,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )
        logging.getLogger(__name__).error("%s", exc)
        raise SystemExit(1) from None
    except Exception:
        logging.basicConfig(
            level=logging.ERROR,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )
        logging.getLogger(__name__).exception("Script failed.")
        raise
