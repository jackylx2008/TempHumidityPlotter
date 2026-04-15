from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from datetime import time as dt_time
from pathlib import Path
from typing import TYPE_CHECKING, cast

import matplotlib.dates as mdates

from .models import NormalizedRecord

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure


def extract_legend_label(path: Path) -> str:
    stem = path.stem
    if "室外温湿度趋势数据" in stem:
        return "室外温湿度趋势数据"
    if "outdoor" in stem.lower():
        return "outdoor"
    match = re.search(r"^[^_]*_([^_]+)_", stem)
    if match:
        return match.group(1)
    return stem


def safe_name_fragment(text: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text.strip())
    return cleaned.strip("-") or "series"


def build_output_file(
    output_dir: Path,
    labels: list[str],
    plot_format: str,
    metric_name: str,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    if len(labels) < 2:
        only = safe_name_fragment(labels[0]) if labels else "series"
        return output_dir / f"{metric_name}_compare_{only}.{plot_format}"
    left = safe_name_fragment(labels[0])
    right = safe_name_fragment(labels[1])
    if len(labels) > 2:
        return (
            output_dir
            / f"{metric_name}_compare_{left}_vs_{right}_plus_{len(labels) - 2}.{plot_format}"
        )
    return output_dir / f"{metric_name}_compare_{left}_vs_{right}.{plot_format}"


def build_paged_output_file(output_path: Path, page_index: int, page_count: int) -> Path:
    if page_count <= 1:
        return output_path
    return output_path.with_name(f"{output_path.stem}_p{page_index + 1:02d}{output_path.suffix}")


def split_series_into_pages(
    series_list: list[list[NormalizedRecord]],
    max_span_days: int | None,
) -> list[list[list[NormalizedRecord]]]:
    if not max_span_days:
        return [series_list]

    all_times = [item.timestamp for series in series_list for item in series]
    if not all_times:
        return [series_list]

    min_date = min(all_times).date()
    max_date = max(all_times).date()
    total_days = (max_date - min_date).days + 1
    if total_days <= max_span_days:
        return [series_list]

    pages: list[list[list[NormalizedRecord]]] = []
    page_start_date = min_date
    while page_start_date <= max_date:
        page_end_date = page_start_date + timedelta(days=max_span_days)
        page_start = datetime.combine(page_start_date, datetime.min.time())
        page_end = datetime.combine(page_end_date, datetime.min.time())
        page_series_list = [
            [item for item in series if page_start <= item.timestamp < page_end]
            for series in series_list
        ]
        if any(page_series for page_series in page_series_list):
            pages.append(page_series_list)
        page_start_date = page_end_date
    return pages or [series_list]


def plot_metric_comparison(
    series_list: list[list[NormalizedRecord]],
    labels: list[str],
    output_path: Path,
    plot_format: str,
    highlight_time_range: tuple[dt_time | None, dt_time | None],
    metric_getter,
    y_label: str,
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
    colors = ["#D55E00", "#0072B2", "#009E73", "#CC79A7"]

    all_times = [item.timestamp for series in series_list for item in series]
    if all_times:
        _draw_highlight_spans(axis, min(all_times), max(all_times), highlight_time_range)

    for index, series in enumerate(series_list):
        x_values = [float(mdates.date2num(item.timestamp)) for item in series]
        y_values = [metric_getter(item) for item in series]
        axis.plot(
            x_values,
            y_values,
            linewidth=2.0,
            color=colors[index % len(colors)],
            label=labels[index],
            zorder=3,
        )

    _configure_axis(axis, y_label)
    if all_times:
        _draw_midnight_lines(axis, min(all_times), max(all_times))
        _draw_date_weekday_labels(axis, min(all_times), max(all_times))
    axis.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, 1.02),
        ncol=min(max(len(labels), 1), 3),
        frameon=False,
        fontsize=11,
    )
    figure.tight_layout(rect=(0.0, 0.06, 1.0, 0.96))
    figure.savefig(output_path, format=plot_format, dpi=180)
    plt.close(figure)


def _draw_highlight_spans(
    axis: "Axes",
    start_time: datetime,
    end_time: datetime,
    highlight_time_range: tuple[dt_time | None, dt_time | None],
) -> None:
    highlight_start, highlight_end = highlight_time_range
    if not highlight_start or not highlight_end:
        return
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


def _configure_axis(axis: "Axes", y_label: str) -> None:
    axis.set_xlabel("时间", fontsize=12)
    axis.set_ylabel(y_label, fontsize=12)
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


def _draw_midnight_lines(axis: "Axes", start_time: datetime, end_time: datetime) -> None:
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


def _draw_date_weekday_labels(axis: "Axes", start_time: datetime, end_time: datetime) -> None:
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    label_positions: list[float] = []
    label_texts: list[str] = []

    current_date = start_time.date()
    end_date = end_time.date()
    while current_date <= end_date:
        day_start = datetime.combine(current_date, datetime.min.time())
        day_end = day_start + timedelta(days=1)
        visible_start = max(day_start, start_time)
        visible_end = min(day_end, end_time)
        if visible_start < visible_end:
            midpoint = visible_start + (visible_end - visible_start) / 2
            label_positions.append(float(mdates.date2num(midpoint)))
            label_texts.append(
                f"{current_date:%m-%d} {weekday_names[current_date.weekday()]}"
            )
        current_date += timedelta(days=1)

    if not label_positions:
        return

    secondary_axis = axis.secondary_xaxis(location=-0.18)
    secondary_axis.set_xticks(label_positions, label_texts)
    secondary_axis.tick_params(axis="x", length=0, pad=2, labelsize=10)
    secondary_axis.spines["bottom"].set_visible(False)
