from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Any

from .config import parse_datetime_value
from .diagnostics import add_diagnostic
from .models import DiagnosticEntry, NormalizedRecord, ParsedSeries, ParserFunc

REQUIRED_COLUMNS = {"datetime", "temperature_C", "humidity_RH"}
ENCODING_CANDIDATES = ("utf-8-sig", "utf-8", "gb18030", "gbk")
SUPPORTED_INPUT_FILE_TYPES = {"csv", "txt"}


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


def filter_series_by_time_range(
    series: list[NormalizedRecord],
    start_time,
    end_time,
    source_name: str,
) -> list[NormalizedRecord]:
    filtered = [
        item
        for item in series
        if (start_time is None or item.timestamp >= start_time)
        and (end_time is None or item.timestamp <= end_time)
    ]
    if not filtered:
        raise ValueError(
            f"No data points remain in {source_name} after time filter: "
            f"start={start_time}, end={end_time}"
        )
    return filtered


def detect_input_format(path: Path, preview_text: str) -> str:
    lines = [line.strip() for line in preview_text.splitlines() if line.strip()]
    lowered_lines = [line.lower() for line in lines[:5]]
    if lines and "Point Name -" in lines[0] and "TimeStamp,DataValue" in preview_text:
        return "outdoor_trend_csv"
    if any("温度(℃)" in line and "湿度(%RH)" in line for line in lines[:30]):
        return "raw_txt_report"
    if lowered_lines:
        header_columns = {part.strip() for part in lowered_lines[0].split(",")}
        if REQUIRED_COLUMNS.issubset(header_columns):
            return "normalized_csv"
    if path.suffix.lower() == ".txt":
        return "raw_txt_report"
    if path.suffix.lower() == ".csv":
        return "normalized_csv"
    raise ValueError(f"Unsupported input format for {path.name}")


def get_parser_registry() -> dict[str, ParserFunc]:
    return {
        "normalized_csv": _read_normalized_csv_with_encoding,
        "raw_txt_report": _read_temperature_report_with_encoding,
        "outdoor_trend_csv": _read_outdoor_trend_csv_with_encoding,
    }


def read_parsed_series(
    input_path: Path,
    diagnostics: list[DiagnosticEntry],
) -> ParsedSeries:
    decode_error: UnicodeDecodeError | None = None
    parse_error: ValueError | None = None
    for encoding in ENCODING_CANDIDATES:
        try:
            preview_text = input_path.read_text(encoding=encoding)
            format_name = detect_input_format(input_path, preview_text)
            parser = get_parser_registry()[format_name]
            records = parser(input_path, encoding, diagnostics)
            return ParsedSeries(
                source_path=input_path,
                format_name=format_name,
                records=records,
            )
        except UnicodeDecodeError as exc:
            decode_error = exc
            continue
        except ValueError as exc:
            parse_error = exc
            continue

    if decode_error:
        raise decode_error
    if parse_error:
        raise parse_error
    raise ValueError(f"Failed to read input file: {input_path}")


def _read_normalized_csv_with_encoding(
    csv_path: Path,
    encoding: str,
    diagnostics: list[DiagnosticEntry],
) -> list[NormalizedRecord]:
    rows: list[NormalizedRecord] = []
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
                humidity_value = float((row.get("humidity_RH") or "").strip())
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
            rows.append(
                NormalizedRecord(
                    timestamp=dt_value,
                    temperature_C=temp_value,
                    humidity_RH=humidity_value,
                )
            )

    if not rows:
        raise ValueError(f"No data rows found in {csv_path.name}")
    rows.sort(key=lambda item: item.timestamp)
    return rows


def _read_temperature_report_with_encoding(
    txt_path: Path,
    encoding: str,
    diagnostics: list[DiagnosticEntry],
) -> list[NormalizedRecord]:
    rows: list[NormalizedRecord] = []
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
                humidity_value = float(parts[2])
            except Exception:
                skipped_rows.append((line_no, line))
                continue
            rows.append(
                NormalizedRecord(
                    timestamp=dt_value,
                    temperature_C=temp_value,
                    humidity_RH=humidity_value,
                )
            )

    if not header_found:
        add_diagnostic(diagnostics, "ERROR", txt_path.name, None, "", "TXT header row not found")
        raise ValueError(f"TXT header row not found in {txt_path.name}")
    if not rows:
        add_diagnostic(diagnostics, "ERROR", txt_path.name, None, "", "No data rows found in TXT file")
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
            add_diagnostic(diagnostics, "WARNING", txt_path.name, line_no, line, "Invalid TXT row skipped")
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

    rows.sort(key=lambda item: item.timestamp)
    return rows


def _read_outdoor_trend_csv_with_encoding(
    csv_path: Path,
    encoding: str,
    diagnostics: list[DiagnosticEntry],
) -> list[NormalizedRecord]:
    with csv_path.open("r", encoding=encoding, newline="") as file_handle:
        table = list(csv.reader(file_handle))

    if not table:
        add_diagnostic(diagnostics, "ERROR", csv_path.name, None, "", "Outdoor trend CSV is empty")
        raise ValueError(f"Outdoor trend CSV is empty: {csv_path.name}")

    point_name_row = next(
        (row for row in table if any("Point Name -" in (cell or "") for cell in row)),
        None,
    )
    header_index = next(
        (
            index
            for index, row in enumerate(table)
            if any((cell or "").strip() == "TimeStamp" for cell in row)
        ),
        None,
    )
    if point_name_row is None or header_index is None:
        add_diagnostic(
            diagnostics,
            "ERROR",
            csv_path.name,
            None,
            "",
            "Outdoor trend CSV header rows not found",
        )
        raise ValueError(f"Outdoor trend CSV header rows not found in {csv_path.name}")

    header_row = table[header_index]
    temperature_col: int | None = None
    humidity_col: int | None = None

    for index, cell in enumerate(header_row):
        if (cell or "").strip() != "TimeStamp":
            continue
        point_name = (point_name_row[index] if index < len(point_name_row) else "").strip()
        normalized_name = point_name.lower()
        if "室外温度" in point_name or "oa-t" in normalized_name:
            temperature_col = index
        elif "室外湿度" in point_name or "oa-h" in normalized_name:
            humidity_col = index

    if temperature_col is None or humidity_col is None:
        add_diagnostic(
            diagnostics,
            "ERROR",
            csv_path.name,
            None,
            "",
            "Outdoor temperature or humidity columns not found",
        )
        raise ValueError(f"Outdoor temperature or humidity columns not found in {csv_path.name}")

    temperature_by_time: dict = {}
    humidity_by_time: dict = {}
    invalid_rows: list[tuple[int, str, str]] = []

    for line_no, row in enumerate(table[header_index + 1 :], start=header_index + 2):
        _read_outdoor_point_row(
            row=row,
            source_col=temperature_col,
            target=temperature_by_time,
            line_no=line_no,
            invalid_rows=invalid_rows,
            point_label="temperature",
        )
        _read_outdoor_point_row(
            row=row,
            source_col=humidity_col,
            target=humidity_by_time,
            line_no=line_no,
            invalid_rows=invalid_rows,
            point_label="humidity",
        )

    common_timestamps = sorted(set(temperature_by_time).intersection(humidity_by_time))
    rows: list[NormalizedRecord] = [
        NormalizedRecord(
            timestamp=timestamp,
            temperature_C=temperature_by_time[timestamp],
            humidity_RH=humidity_by_time[timestamp],
        )
        for timestamp in common_timestamps
    ]

    if invalid_rows:
        logging.getLogger(__name__).warning(
            "Skipped %s invalid outdoor trend values in %s (lines: %s)",
            len(invalid_rows),
            csv_path.name,
            [item[0] for item in invalid_rows[:10]],
        )
        for line_no, content, detail in invalid_rows:
            add_diagnostic(diagnostics, "WARNING", csv_path.name, line_no, content, detail)

    if not rows:
        add_diagnostic(
            diagnostics,
            "ERROR",
            csv_path.name,
            None,
            "",
            "No matching outdoor temperature/humidity rows found",
        )
        raise ValueError(f"No matching outdoor temperature/humidity rows found in {csv_path.name}")

    return rows


def _read_outdoor_point_row(
    row: list[str],
    source_col: int,
    target: dict,
    line_no: int,
    invalid_rows: list[tuple[int, str, str]],
    point_label: str,
) -> None:
    if source_col + 1 >= len(row):
        return
    timestamp_text = (row[source_col] or "").strip()
    value_text = (row[source_col + 1] or "").strip()
    reliability_text = (row[source_col + 2] or "").strip() if source_col + 2 < len(row) else ""
    if not timestamp_text and not value_text:
        return
    try:
        timestamp = parse_datetime_value(timestamp_text.strip('"'))
        value = float(value_text.strip('"'))
    except Exception:
        invalid_rows.append(
            (
                line_no,
                repr(row),
                f"Invalid outdoor {point_label} row skipped",
            )
        )
        return
    if reliability_text:
        invalid_rows.append(
            (
                line_no,
                repr(row),
                f'Outdoor {point_label} row marked unreliable: {reliability_text.strip(chr(34))}',
            )
        )
        return
    target[timestamp] = value
