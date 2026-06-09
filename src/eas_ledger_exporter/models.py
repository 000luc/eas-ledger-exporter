from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Company:
    code: str
    name: str


@dataclass(frozen=True)
class ExportConfig:
    year: int
    month: int
    output_dir: Path
    companies: tuple[Company, ...]
