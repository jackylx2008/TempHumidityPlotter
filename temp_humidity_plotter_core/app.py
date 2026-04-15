from __future__ import annotations

from datetime import datetime
import math
from pathlib import Path

from logging_config import get_logger, setup_logger

from .config import (
    load_app_config,
    parse_log_level,
    resolve_atmospheric_pressure_kpa,
    resolve_highlight_time_range,
    resolve_max_span_days,
    resolve_time_range,
)
from .diagnostics import add_diagnostic, write_diagnostics_report
from .models import DiagnosticEntry, NormalizedRecord
from .parsers import (
    filter_series_by_time_range,
    read_parsed_series,
    resolve_input_files,
)
from .plotting import (
    build_output_file,
    build_paged_output_file,
    extract_legend_label,
    plot_metric_comparison,
    split_series_into_pages,
)


def main() -> int:
    config = load_app_config(Path("config.yaml"))
    setup_logger(log_level=parse_log_level(config["log_level"]))
    logger = get_logger(__name__)
    diagnostics: list[DiagnosticEntry] = []
    range_start, range_end = resolve_time_range(config)
    atmospheric_pressure_kpa = resolve_atmospheric_pressure_kpa(config)
    max_span_days = resolve_max_span_days(config)
    highlight_time_range = resolve_highlight_time_range(config)
    output_dir = Path(config["output_dir"])

    try:
        input_files = resolve_input_files(config)
        outdoor_path_raw = config.get("outdoor_temp_humidity_file", "")
        outdoor_path: Path | None = None
        if outdoor_path_raw:
            outdoor_path = Path(outdoor_path_raw)
            if not outdoor_path.exists():
                raise FileNotFoundError(
                    f"Outdoor temp humidity file not found: {outdoor_path}"
                )
            input_files.append(outdoor_path)
        logger.info("Selected input files: %s", [str(path) for path in input_files])
        if range_start or range_end:
            logger.info(
                "Applying time range filter: start=%s, end=%s", range_start, range_end
            )
        if max_span_days:
            logger.info("Applying max page span: %s days", max_span_days)
        if highlight_time_range[0] and highlight_time_range[1]:
            logger.info(
                "Applying daily highlight range: %s to %s",
                highlight_time_range[0],
                highlight_time_range[1],
            )

        parsed_series_list = [
            read_parsed_series(path, diagnostics) for path in input_files
        ]
        logger.info(
            "Detected input formats: %s",
            {
                parsed.source_path.name: parsed.format_name
                for parsed in parsed_series_list
            },
        )
        filtered_items: list[tuple] = []
        for parsed in parsed_series_list:
            try:
                filtered_records = filter_series_by_time_range(
                    parsed.records,
                    range_start,
                    range_end,
                    parsed.source_path.name,
                )
                filtered_items.append((parsed, filtered_records))
            except ValueError:
                if outdoor_path and parsed.source_path == outdoor_path:
                    aligned_records = _project_series_onto_filter_range(
                        parsed.records,
                        range_start,
                        range_end,
                    )
                    if aligned_records:
                        message = (
                            "Outdoor temp humidity series aligned to the active filter range "
                            "by matching month/day/time across years"
                        )
                        add_diagnostic(
                            diagnostics,
                            "WARNING",
                            parsed.source_path.name,
                            None,
                            "",
                            message,
                        )
                        logger.warning("%s", message)
                        filtered_items.append((parsed, aligned_records))
                        continue
                    message = (
                        "Outdoor temp humidity series skipped because no data points remain "
                        f"after time filter: start={range_start}, end={range_end}"
                    )
                    add_diagnostic(
                        diagnostics,
                        "WARNING",
                        parsed.source_path.name,
                        None,
                        "",
                        message,
                    )
                    logger.warning("%s", message)
                    continue
                raise

        series_list = [records for _, records in filtered_items]
        labels = [
            extract_legend_label(parsed.source_path) for parsed, _ in filtered_items
        ]
        if len(series_list) < 2:
            raise ValueError("At least 2 data series are required after filtering.")
        paged_series_list = split_series_into_pages(series_list, max_span_days)
        output_paths: list[Path] = []

        for metric_name, metric_getter, y_label in [
            ("temperature", lambda item: item.temperature_C, "温度 (°C)"),
            ("humidity", lambda item: item.humidity_RH, "湿度 (%RH)"),
            (
                "enthalpy",
                lambda item: calculate_enthalpy_kj_per_kg_dry_air(item, atmospheric_pressure_kpa),
                "焓值 (kJ/kg干空气)",
            ),
        ]:
            output_path = build_output_file(
                output_dir,
                labels,
                config["plot_format"],
                metric_name,
            )
            metric_output_paths: list[Path] = []
            for page_index, page_series_list in enumerate(paged_series_list):
                page_output_path = build_paged_output_file(
                    output_path, page_index, len(paged_series_list)
                )
                plot_metric_comparison(
                    page_series_list,
                    labels,
                    page_output_path,
                    config["plot_format"],
                    highlight_time_range,
                    metric_getter,
                    y_label,
                )
                metric_output_paths.append(page_output_path)
                output_paths.append(page_output_path)

            merged_output_path = _merge_metric_pdf_outputs(
                metric_output_paths,
                output_path,
                config["plot_format"],
            )
            if merged_output_path is not None:
                output_paths.append(merged_output_path)

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


def _project_series_onto_filter_range(
    series: list[NormalizedRecord],
    start_time: datetime | None,
    end_time: datetime | None,
) -> list[NormalizedRecord]:
    if start_time is None or end_time is None:
        return []

    candidate_years = list(range(start_time.year, end_time.year + 1))
    projected: list[NormalizedRecord] = []
    seen_timestamps: set[datetime] = set()

    for item in series:
        for year in candidate_years:
            try:
                projected_timestamp = item.timestamp.replace(year=year)
            except ValueError:
                continue
            if projected_timestamp < start_time or projected_timestamp > end_time:
                continue
            if projected_timestamp in seen_timestamps:
                continue
            seen_timestamps.add(projected_timestamp)
            projected.append(
                NormalizedRecord(
                    timestamp=projected_timestamp,
                    temperature_C=item.temperature_C,
                    humidity_RH=item.humidity_RH,
                )
            )
            break

    projected.sort(key=lambda item: item.timestamp)
    return projected


def calculate_enthalpy_kj_per_kg_dry_air(
    record: NormalizedRecord,
    atmospheric_pressure_kpa: float,
) -> float:
    saturation_pressure_kpa = 0.61078 * math.exp(
        17.2694 * record.temperature_C / (record.temperature_C + 237.3)
    )
    relative_humidity = record.humidity_RH / 100.0
    vapor_pressure_kpa = relative_humidity * saturation_pressure_kpa
    humidity_ratio = 0.62198 * vapor_pressure_kpa / (atmospheric_pressure_kpa - vapor_pressure_kpa)
    return 1.006 * record.temperature_C + humidity_ratio * (2501 + 1.86 * record.temperature_C)


def _merge_metric_pdf_outputs(
    metric_output_paths: list[Path],
    merged_output_path: Path,
    plot_format: str,
) -> Path | None:
    if plot_format.lower() != "pdf" or len(metric_output_paths) <= 1:
        return None

    from pypdf import PdfWriter

    writer = PdfWriter()
    for path in metric_output_paths:
        writer.append(str(path))

    with merged_output_path.open("wb") as file_handle:
        writer.write(file_handle)
    writer.close()

    for path in metric_output_paths:
        if path != merged_output_path and path.exists():
            path.unlink()

    return merged_output_path
