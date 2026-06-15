from __future__ import annotations

from pathlib import Path

import pytest

from eas_ledger_exporter.eas_client import EasClient
from eas_ledger_exporter.errors import EasControlError, ExportError, ValidationError
from eas_ledger_exporter.models import Company, ExportJob, QueryResult
from eas_ledger_exporter.runner import ExportRunner
from eas_ledger_exporter.validation import REQUIRED_HEADERS


REQUIRED_HEADERS = (
    "公司",
    "记账日期",
    "期间",
    "凭证类型",
    "凭证号",
    "状态",
    "制单",
    "审核",
    "出纳",
    "过账",
    "摘要",
    "科目编码",
    "科目名称",
    "币别",
    "核算项目",
    "原币金额",
    "借方",
    "贷方",
    "业务日期",
    "来源系统",
    "审核退回",
    "来源类型",
    "参考信息",
    "附件",
    "计量单位",
    "数量",
    "制单人",
    "结算号",
)


def _write_export(path: Path, headers: tuple[str, ...], rows: list[tuple]) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.remove(workbook.active)
    sheet = workbook.create_sheet("凭证序时簿")
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    workbook.close()


def _full_row(company: str = "广电计量检测集团股份有限公司", period: str = "2026.6") -> tuple:
    return (
        company,
        "2026-06-01",
        period,
        "记",
        "001",
        "已过账",
        "制单人",
        "审核人",
        "出纳人",
        "已过账",
        "摘要",
        "1001",
        "库存现金",
        "人民币",
        None,
        None,
        100.0,
        None,
        "2026-06-01",
        "EAS",
        None,
        None,
        None,
        None,
        None,
        None,
        "制单人",
        None,
    )


class FakeJab:
    def __init__(
        self,
        *,
        result_rows: list[object] | None = None,
        company_display: str = "广电计量检测集团股份有限公司",
    ):
        self.clicked: list[tuple[str, bool]] = []
        self.typed: list[tuple[str, str]] = []
        self.pressed_keys: list[str] = []
        self.toggled: list[tuple[str, int]] = []
        self._result_rows = result_rows if result_rows is not None else []
        self._company_display = company_display
        self.refreshed = 0

    def click_element(
        self, locator: str, *, action: bool = True, click_type: str = "click"
    ):
        self.clicked.append((locator, click_type == "right click"))

    def type_text(
        self, locator: str, value: str, *, clear: bool = True, typing: bool = False
    ):
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

    def take_screenshot(
        self, *, path: str | None = None, locator=None, embed: bool = True
    ):
        self.screenshots.append(path)


class FakeEas:
    def __init__(self, *, fail_on: str | None = None, empty: bool = False):
        self.fail_on = fail_on
        self.empty = empty
        self.queried: list[str] = []
        self.exported: list[str] = []
        self.screenshots: list[Path] = []
        self.opened = False
        self.reopened: list[str] = []

    def open_voucher_query(self) -> None:
        self.opened = True

    def query(self, job: ExportJob) -> QueryResult:
        if self.fail_on == job.company.code:
            raise RuntimeError(f"模拟查询失败：{job.company.code}")
        self.queried.append(job.company.code)
        return QueryResult(
            company_display="广电计量检测集团股份有限公司", empty=self.empty
        )

    def export(self, job: ExportJob) -> None:
        if self.fail_on == f"export_{job.company.code}":
            raise RuntimeError(f"模拟导出失败：{job.company.code}")
        self.exported.append(job.company.code)
        _write_export(
            job.path,
            REQUIRED_HEADERS,
            [] if self.empty else [_full_row()],
        )

    def reopen_conditions(self) -> None:
        self.reopened.append("reopened")

    def screenshot(self, path: Path) -> None:
        self.screenshots.append(path)
        path.write_bytes(b"fake screenshot")


@pytest.fixture
def jobs(tmp_path):
    return [
        ExportJob(Company("001", "广州本部"), 2026, 6, tmp_path / "out"),
        ExportJob(Company("002", "深圳公司"), 2026, 6, tmp_path / "out"),
    ]


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


def test_runner_runs_all_jobs(jobs):
    eas = FakeEas()
    runner = ExportRunner(eas, jobs[0].output_dir / "logs")
    runner.run(jobs)
    assert eas.queried == ["001", "002"]
    assert eas.exported == ["001", "002"]
    assert eas.reopened == ["reopened"]


def test_runner_stops_on_first_failure(jobs):
    eas = FakeEas(fail_on="002")
    runner = ExportRunner(eas, jobs[0].output_dir / "logs")
    with pytest.raises(ExportError, match="002"):
        runner.run(jobs)
    assert eas.queried == ["001"]
    assert eas.exported == ["001"]
    assert len(eas.screenshots) == 1
    assert "002" in eas.screenshots[0].name


def test_runner_reports_success_in_summary(jobs):
    eas = FakeEas()
    log_dir = jobs[0].output_dir / "logs"
    runner = ExportRunner(eas, log_dir)
    runner.run(jobs)

    summary = log_dir / "summary.csv"
    assert summary.exists()
    text = summary.read_text(encoding="utf-8-sig")
    assert "成功" in text
    assert "001" in text
    assert "002" in text


def test_runner_reports_failure_in_summary(jobs):
    eas = FakeEas(fail_on="002")
    log_dir = jobs[0].output_dir / "logs"
    runner = ExportRunner(eas, log_dir)
    with pytest.raises(ExportError):
        runner.run(jobs)

    summary = log_dir / "summary.csv"
    text = summary.read_text(encoding="utf-8-sig")
    assert "失败" in text
    assert "002" in text


def test_runner_detects_empty_state_mismatch(jobs):
    eas = FakeEas(empty=False)

    def empty_export(job: ExportJob) -> None:
        eas.exported.append(job.company.code)
        _write_export(job.path, REQUIRED_HEADERS, [])

    eas.export = empty_export
    runner = ExportRunner(eas, jobs[0].output_dir / "logs")
    with pytest.raises(ExportError, match="001"):
        runner.run(jobs)

    summary = (jobs[0].output_dir / "logs" / "summary.csv").read_text(
        encoding="utf-8-sig"
    )
    assert "001" in summary
    assert "失败" in summary

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
