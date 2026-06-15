from __future__ import annotations

from pathlib import Path

import pytest

from eas_ledger_exporter.eas_client import EasClient
from eas_ledger_exporter.errors import EasControlError
from eas_ledger_exporter.models import Company, ExportJob, QueryResult


class FakeJab:
    def __init__(self, *, result_rows=None, company_display="广电计量检测集团股份有限公司"):
        self.clicked: list[tuple[str, bool]] = []
        self.typed: list[tuple[str, str]] = []
        self.pressed_keys: list[str] = []
        self.toggled: list[tuple[str, int]] = []
        self._result_rows = result_rows if result_rows is not None else []
        self._company_display = company_display
        self.refreshed = 0

    def click_element(self, locator: str, *, action: bool = True, click_type: str = "click"):
        self.clicked.append((locator, click_type == "right click"))

    def type_text(self, locator: str, value: str, *, clear: bool = True, typing: bool = False):
        self.typed.append((locator, value))

    def press_keys(self, keys: str):
        self.pressed_keys.append(keys)

    def toggle_drop_down(self, locator: str, index: int = 0):
        self.toggled.append((locator, index))

    def application_refresh(self):
        self.refreshed += 1

    def get_element_text(self, locator: str) -> str:
        return self._company_display

    def get_elements(self, locator: str, *, strict: bool = True):
        return self._result_rows


class FakeDesktop:
    def __init__(self):
        self.screenshots: list[str] = []

    def take_screenshot(self, *, path: str | None = None, locator=None, embed: bool = True):
        self.screenshots.append(path)


@pytest.fixture
def locators():
    return {
        "voucher_query": "role:label and name:凭证查询",
        "company": "role:text and name:公司",
        "period_mode": "name:按期间查询",
        "start_year": "role:text and ancestry:会计期间 and indexInParent:0",
        "start_month": "role:text and ancestry:会计期间 and indexInParent:1",
        "end_year": "role:text and ancestry:至 and indexInParent:0",
        "end_month": "role:text and ancestry:至 and indexInParent:1",
        "max_results": "name:最大返回结果数",
        "audit_all": "name:全部 and ancestry:审核状态",
        "posted_all": "name:全部 and ancestry:过账状态",
        "review_all": "name:全部 and ancestry:复核状态",
        "voucher_mode": "name:按凭证查询",
        "confirm": "role:push button and name:确定",
        "result_table": "role:table",
        "result_rows": "role:table cell and ancestry:凭证序时簿",
        "export_excel": "name:导出到Excel",
        "export_path": "role:text and ancestry:导出序时簿向导",
        "export_confirm": "role:push button and name:完成 and ancestry:导出序时簿向导",
        "condition_query": "name:条件查询",
    }


@pytest.fixture
def job(tmp_path):
    return ExportJob(Company("001", "广州本部"), 2026, 6, tmp_path)


def test_client_opens_voucher_query(locators):
    jab = FakeJab()
    client = EasClient(jab, locators)
    client.open_voucher_query()
    assert jab.clicked == [(locators["voucher_query"], False)]


def test_client_query_sets_company_and_period(locators, job):
    jab = FakeJab()
    client = EasClient(jab, locators)
    result = client.query(job)

    assert isinstance(result, QueryResult)
    assert result.company_display == "广电计量检测集团股份有限公司"
    assert result.empty is True
    assert jab.typed == [
        (locators["company"], "001"),
        (locators["start_year"], "2026"),
        (locators["start_month"], "6"),
        (locators["end_year"], "2026"),
        (locators["end_month"], "6"),
    ]
    assert jab.pressed_keys == ["TAB"]
    assert jab.toggled == [(locators["max_results"], 0)]


def test_client_query_detects_non_empty_results(locators, job):
    jab = FakeJab(result_rows=[object()])
    client = EasClient(jab, locators)
    result = client.query(job)
    assert result.empty is False


def test_client_query_clicks_all_status_options(locators, job):
    jab = FakeJab()
    client = EasClient(jab, locators)
    client.query(job)

    status_clicks = [locator for locator, right in jab.clicked if not right]
    assert locators["period_mode"] in status_clicks
    assert locators["audit_all"] in status_clicks
    assert locators["posted_all"] in status_clicks
    assert locators["review_all"] in status_clicks
    assert locators["voucher_mode"] in status_clicks
    assert locators["confirm"] in status_clicks


def test_client_export_fills_path_and_confirms(locators, job):
    jab = FakeJab()
    client = EasClient(jab, locators)
    client.export(job)

    assert (locators["result_table"], True) in jab.clicked
    assert (locators["export_excel"], False) in jab.clicked
    assert (locators["export_confirm"], False) in jab.clicked
    assert (locators["export_path"], str(job.path)) in jab.typed


def test_client_reopens_conditions(locators):
    jab = FakeJab()
    client = EasClient(jab, locators)
    client.reopen_conditions()
    assert (locators["condition_query"], False) in jab.clicked


def test_client_screenshot_uses_desktop(locators, tmp_path):
    jab = FakeJab()
    desktop = FakeDesktop()
    client = EasClient(jab, locators, desktop=desktop)
    path = tmp_path / "failure.png"
    client.screenshot(path)
    assert desktop.screenshots == [str(path)]


def test_client_raises_when_locator_missing(locators):
    jab = FakeJab()
    client = EasClient(jab, {**locators, "confirm": ""})
    del client.locators["confirm"]
    with pytest.raises(EasControlError, match="缺少控件定位器：confirm"):
        client.click("confirm")
