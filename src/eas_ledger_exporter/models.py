from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata


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


_WINDOWS_INVALID_CHARS = frozenset('<>:"/\\|?*')
_WINDOWS_RESERVED_NAME = re.compile(
    r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExportJob:
    company: Company
    year: int
    month: int
    output_dir: Path

    def __post_init__(self) -> None:
        if type(self.year) is not int or not 2000 <= self.year <= 2100:
            raise ValueError("year 必须是 2000-2100 的整数")
        if type(self.month) is not int or not 1 <= self.month <= 12:
            raise ValueError("month 必须是 1-12 的整数")
        if not isinstance(self.output_dir, Path):
            raise TypeError("output_dir 必须是 Path")
        if self.output_dir == Path():
            raise ValueError("output_dir 不能为空")

        code = self.company.code
        if (
            not isinstance(code, str)
            or len(code) != 3
            or not code.isascii()
            or not code.isdigit()
        ):
            raise ValueError("公司编号必须恰好为 3 位 ASCII 数字")

        name = self.company.name
        if not isinstance(name, str) or not name.strip():
            raise ValueError("公司名称不能为空")
        if (
            any(
                char in _WINDOWS_INVALID_CHARS
                or unicodedata.category(char) == "Cc"
                for char in name
            )
            or name.endswith((".", " "))
            or _WINDOWS_RESERVED_NAME.match(name)
        ):
            raise ValueError("公司名称包含 Windows 文件名不允许的内容")

    @property
    def period(self) -> str:
        return f"{self.year:04d}{self.month:02d}"

    @property
    def path(self) -> Path:
        filename = (
            f"{self.company.code}.{self.company.name}_"
            f"{self.period}_凭证序时簿.xlsx"
        )
        return self.output_dir / filename
