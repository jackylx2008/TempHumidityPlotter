from __future__ import annotations

from pathlib import Path

from .models import DiagnosticEntry


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
