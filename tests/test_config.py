from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from zipfile import ZipFile

import pytest

import eas_ledger_exporter.config as config_module
from eas_ledger_exporter.config import load_config
from eas_ledger_exporter.errors import ConfigError
from eas_ledger_exporter.models import Company, ExportConfig


def test_models_are_frozen(tmp_path):
    company = Company("001", "广州本部")
    config = ExportConfig(2026, 6, tmp_path, (company,))

    with pytest.raises(FrozenInstanceError):
        company.code = "002"
    with pytest.raises(FrozenInstanceError):
        config.month = 7


def test_load_config_preserves_company_code_and_filters_disabled(make_config_book):
    config = load_config(make_config_book())

    assert config.year == 2026
    assert config.month == 6
    assert config.output_dir.name == "序时账"
    assert config.companies == (Company("001", "广州本部"),)


def test_load_config_accepts_numeric_text_period(make_config_book):
    config = load_config(make_config_book(year="2025", month="09"))

    assert (config.year, config.month) == (2025, 9)


@pytest.mark.parametrize(
    ("raw_code", "expected"),
    [("001", "001"), (1, "001"), (1.0, "001")],
)
def test_load_config_normalizes_numeric_company_codes(
    make_config_book, raw_code, expected
):
    config = load_config(
        make_config_book(companies=((raw_code, "广州本部", "是"),))
    )

    assert config.companies[0].code == expected


@pytest.mark.parametrize(
    ("raw_code", "expected"),
    [("1", "001"), ("01", "001"), ("001", "001")],
)
def test_load_config_preserves_valid_ascii_string_company_codes(
    make_config_book, raw_code, expected
):
    config = load_config(
        make_config_book(companies=((raw_code, "广州本部", "是"),))
    )

    assert config.companies[0].code == expected


@pytest.mark.parametrize("raw_code", ("0001", "１", "１２３"))
def test_load_config_rejects_invalid_string_company_code_format(
    make_config_book, raw_code
):
    path = make_config_book(companies=((raw_code, "广州本部", "是"),))

    with pytest.raises(ConfigError, match="第2行公司编号"):
        load_config(path)


@pytest.mark.parametrize("month", (0, 13, "六月", True))
def test_load_config_rejects_invalid_month(make_config_book, month):
    with pytest.raises(ConfigError, match="月份"):
        load_config(make_config_book(month=month))


def test_load_config_rejects_no_enabled_company(make_config_book):
    path = make_config_book(companies=(("001", "广州本部", "否"),))

    with pytest.raises(ConfigError, match="没有启用的公司"):
        load_config(path)


@pytest.mark.parametrize("enabled", (True, 1, 0, "是的", "Y", "", None))
def test_load_config_rejects_invalid_execution_flag_on_business_row(
    make_config_book, enabled
):
    path = make_config_book(companies=(("001", "广州本部", enabled),))

    with pytest.raises(ConfigError, match="第2行.*是否执行.*是.*否"):
        load_config(path)


def test_load_config_skips_completely_blank_company_rows(make_config_book):
    config = load_config(
        make_config_book(
            companies=((None, None, None), ("001", "广州本部", "是"))
        )
    )

    assert config.companies == (Company("001", "广州本部"),)


@pytest.mark.parametrize("missing_sheet", ("执行期间", "执行操作的公司"))
def test_load_config_rejects_missing_sheet(make_config_book, missing_sheet):
    path = make_config_book(
        period_sheet=missing_sheet != "执行期间",
        companies_sheet=missing_sheet != "执行操作的公司",
    )

    with pytest.raises(ConfigError, match=missing_sheet):
        load_config(path)


def test_load_config_rejects_missing_output_path(make_config_book):
    path = make_config_book(output_dir="")

    with pytest.raises(ConfigError, match="输出路径不能为空"):
        load_config(path)


def test_load_config_rejects_duplicate_company_code(make_config_book):
    path = make_config_book(
        companies=(
            ("001", "广州本部", "是"),
            (1, "重复公司", "是"),
        )
    )

    with pytest.raises(ConfigError, match="公司编号重复.*001"):
        load_config(path)


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (True, "公司编号"),
        (1.5, "公司编号"),
        (None, "公司编号"),
    ],
)
def test_load_config_rejects_invalid_enabled_company_code(
    make_config_book, code, message
):
    path = make_config_book(companies=((code, "广州本部", "是"),))

    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_load_config_rejects_blank_enabled_company_name(make_config_book):
    path = make_config_book(companies=(("001", "  ", "是"),))

    with pytest.raises(ConfigError, match="公司名称不能为空"):
        load_config(path)


def test_load_config_wraps_missing_and_corrupt_files(tmp_path):
    missing = tmp_path / "missing.xlsx"
    corrupt = tmp_path / "corrupt.xlsx"
    corrupt.write_bytes(b"not an xlsx file")

    with pytest.raises(ConfigError, match="配置文件不存在"):
        load_config(missing)
    with pytest.raises(ConfigError, match="配置文件损坏或格式无效"):
        load_config(corrupt)


def test_load_config_wraps_xlsx_missing_required_zip_parts(tmp_path):
    malformed = tmp_path / "missing-workbook.xlsx"
    with ZipFile(malformed, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.sheet.main+xml"/>'
            "</Types>",
        )

    with pytest.raises(ConfigError, match="配置文件损坏或格式无效"):
        load_config(malformed)


def test_load_config_wraps_malformed_workbook_xml_and_releases_file(
    make_config_book, tmp_path
):
    source = make_config_book(filename="source.xlsx")
    malformed = tmp_path / "malformed-workbook.xlsx"

    with ZipFile(source) as source_archive, ZipFile(malformed, "w") as target:
        for item in source_archive.infolist():
            content = source_archive.read(item.filename)
            if item.filename == "xl/workbook.xml":
                content = b"<workbook><broken>"
            target.writestr(item, content)

    with pytest.raises(ConfigError, match="配置文件损坏或格式无效"):
        load_config(malformed)
    malformed.unlink()

    assert not malformed.exists()


def test_load_config_does_not_wrap_business_logic_key_error(tmp_path, monkeypatch):
    path = tmp_path / "info.xlsx"
    path.touch()

    class Workbook:
        closed = False

        def close(self):
            self.closed = True

    workbook = Workbook()
    monkeypatch.setattr(config_module, "load_workbook", lambda *args, **kwargs: workbook)
    monkeypatch.setattr(
        config_module,
        "_parse_workbook",
        lambda opened: (_ for _ in ()).throw(KeyError("programming error")),
    )

    with pytest.raises(KeyError, match="programming error"):
        load_config(path)

    assert workbook.closed is True


def test_load_config_preserves_primary_error_when_workbook_close_fails(
    tmp_path, monkeypatch
):
    path = tmp_path / "info.xlsx"
    path.touch()

    class Workbook:
        def close(self):
            raise OSError("close failed")

    monkeypatch.setattr(
        config_module, "load_workbook", lambda *args, **kwargs: Workbook()
    )
    monkeypatch.setattr(
        config_module,
        "_parse_workbook",
        lambda opened: (_ for _ in ()).throw(KeyError("primary error")),
    )

    with pytest.raises(KeyError, match="primary error"):
        load_config(path)


def test_load_config_wraps_workbook_close_failure_after_success(
    tmp_path, monkeypatch
):
    path = tmp_path / "info.xlsx"
    path.touch()
    expected = ExportConfig(2026, 6, tmp_path, (Company("001", "广州本部"),))

    class Workbook:
        def close(self):
            raise OSError("close failed")

    monkeypatch.setattr(
        config_module, "load_workbook", lambda *args, **kwargs: Workbook()
    )
    monkeypatch.setattr(config_module, "_parse_workbook", lambda opened: expected)

    with pytest.raises(ConfigError, match="关闭配置文件失败"):
        load_config(path)


def test_load_config_closes_workbook_after_success(make_config_book):
    path = make_config_book(filename="success.xlsx")

    load_config(path)
    path.unlink()

    assert not path.exists()


def test_load_config_closes_workbook_after_validation_error(make_config_book):
    path = make_config_book(month=13, filename="invalid.xlsx")

    with pytest.raises(ConfigError):
        load_config(path)
    path.unlink()

    assert not path.exists()
