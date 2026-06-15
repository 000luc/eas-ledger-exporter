from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl.utils import column_index_from_string, get_column_letter

from .errors import WorkbookRepairError


_CELL_REF = re.compile(rb'<c\b[^>]*?r="([A-Z]+)(\d+)"')
_DIMENSION = re.compile(rb'<dimension ref="[^"]*"\s*/>')
_SHEET_NAME = "xl/worksheets/sheet1.xml"


def _scan_last_cell(path: Path) -> tuple[str, int]:
    max_col_index = -1
    max_row = 0

    with path.open("rb") as stream:
        chunk_size = 1024 * 1024
        overlap = 1024
        buffer = b""
        while True:
            data = stream.read(chunk_size)
            if not data:
                break
            buffer += data
            for match in _CELL_REF.finditer(buffer):
                col_index = column_index_from_string(match.group(1).decode("ascii")) - 1
                row = int(match.group(2))
                if row > max_row:
                    max_row = row
                if col_index > max_col_index:
                    max_col_index = col_index
            if len(data) < chunk_size:
                break
            buffer = buffer[-overlap:]

    if max_col_index < 0 or max_row == 0:
        raise WorkbookRepairError(f"{_SHEET_NAME} 中没有找到单元格")

    return get_column_letter(max_col_index + 1), max_row


def _write_repaired_sheet(source: Path, target: Path, dimension: str) -> None:
    dimension_bytes = f'<dimension ref="{dimension}"/>'.encode("utf-8")
    with source.open("rb") as in_stream, target.open("wb") as out_stream:
        buffer = b""
        while True:
            data = in_stream.read(64 * 1024)
            if not data:
                break
            buffer += data
            match = _DIMENSION.search(buffer)
            if match:
                out_stream.write(buffer[: match.start()])
                out_stream.write(dimension_bytes)
                out_stream.write(buffer[match.end() :])
                while True:
                    chunk = in_stream.read(1024 * 1024)
                    if not chunk:
                        break
                    out_stream.write(chunk)
                return
        out_stream.write(buffer)


def repair_dimension(path: Path) -> str:
    target = Path(path)
    temp_dir = Path(tempfile.mkdtemp(prefix="eas-repair-"))
    try:
        original_sheet = temp_dir / "sheet1.xml"
        with ZipFile(target) as source:
            try:
                with source.open(_SHEET_NAME) as member, original_sheet.open("wb") as out:
                    shutil.copyfileobj(member, out)
            except KeyError as exc:
                raise WorkbookRepairError(f"缺少 {_SHEET_NAME}") from exc

        last_col, last_row = _scan_last_cell(original_sheet)
        dimension = f"A1:{last_col}{last_row}"

        repaired_sheet = temp_dir / "sheet1.repaired.xml"
        _write_repaired_sheet(original_sheet, repaired_sheet, dimension)

        repaired_xlsx = temp_dir / "repaired.xlsx"
        with ZipFile(target) as source, ZipFile(
            repaired_xlsx, "w", compression=ZIP_DEFLATED
        ) as sink:
            for info in source.infolist():
                if info.filename == _SHEET_NAME:
                    sink.write(repaired_sheet, _SHEET_NAME)
                else:
                    sink.writestr(info, source.read(info.filename))

        repaired_xlsx.replace(target)
        return dimension
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
