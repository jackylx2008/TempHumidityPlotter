from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable


DiagnosticEntry = dict[str, str | int]


@dataclass(frozen=True)
class NormalizedRecord:
    timestamp: datetime
    temperature_C: float
    humidity_RH: float


@dataclass(frozen=True)
class ParsedSeries:
    source_path: Path
    format_name: str
    records: list[NormalizedRecord]


ParserFunc = Callable[[Path, str, list[DiagnosticEntry]], list[NormalizedRecord]]
