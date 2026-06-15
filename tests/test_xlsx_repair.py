from __future__ import annotations

from zipfile import ZipFile

import pytest

from eas_ledger_exporter.errors import WorkbookRepairError
from eas_ledger_exporter.xlsx_repair import repair_dimension


def _write_broken_xlsx(path, rows, *, dimension='ref="A1"'):
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
        cells = []
        for row_index, row in enumerate(rows, start=1):
            for col_index, value in enumerate(row, start=1):
                if value is not None:
                    col_letter = _column_letter(col_index)
                    cells.append(f'<c r="{col_letter}{row_index}" t="str"><v>{value}</v></c>')
        sheet = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<dimension {dimension}/>'
            f'<sheetData>{"".join(cells)}</sheetData>'
            f'</worksheet>'
        )
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


def _column_letter(index: int) -> str:
    result = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def test_repair_dimension_uses_last_cell(tmp_path):
    path = tmp_path / "broken.xlsx"
    _write_broken_xlsx(path, [["a", "b", "c"], ["d", "e", "f"], ["g", "h", "i"]], dimension='ref="A1"')

    assert repair_dimension(path) == "A1:C3"

    with ZipFile(path) as archive:
        xml = archive.read("xl/worksheets/sheet1.xml")
    assert b'dimension ref="A1:C3"' in xml


def test_repair_dimension_handles_many_columns(tmp_path):
    path = tmp_path / "broken.xlsx"
    row = [f"v{i}" for i in range(28)]
    _write_broken_xlsx(path, [row], dimension='ref="A1"')

    assert repair_dimension(path) == "A1:AB1"

    with ZipFile(path) as archive:
        xml = archive.read("xl/worksheets/sheet1.xml")
    assert b'dimension ref="A1:AB1"' in xml


def test_repair_dimension_preserves_other_content(tmp_path):
    path = tmp_path / "broken.xlsx"
    _write_broken_xlsx(path, [["x"]], dimension='ref="A1"')
    original = path.read_bytes()

    repair_dimension(path)

    with ZipFile(path) as archive:
        assert "[Content_Types].xml" in archive.namelist()
        assert "xl/workbook.xml" in archive.namelist()
        sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        assert "<sheetData>" in sheet
        assert "<v>x</v>" in sheet


def test_repair_dimension_missing_sheet_raises(tmp_path):
    path = tmp_path / "broken.xlsx"
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")

    with pytest.raises(WorkbookRepairError, match="缺少"):
        repair_dimension(path)


def test_repair_dimension_empty_sheet_raises(tmp_path):
    path = tmp_path / "broken.xlsx"
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0" encoding="UTF-8"?><worksheet/>',
        )

    with pytest.raises(WorkbookRepairError, match="没有找到单元格"):
        repair_dimension(path)
