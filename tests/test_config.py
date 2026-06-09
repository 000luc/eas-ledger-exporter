from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

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


@pytest.mark.parametrize("month", (0, 13, "六月", True))
def test_load_config_rejects_invalid_month(make_config_book, month):
    with pytest.raises(ConfigError, match="月份"):
        load_config(make_config_book(month=month))


def test_load_config_rejects_no_enabled_company(make_config_book):
    path = make_config_book(companies=(("001", "广州本部", "否"),))

    with pytest.raises(ConfigError, match="没有启用的公司"):
        load_config(path)


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
