from __future__ import annotations

from pathlib import Path
from typing import Protocol

from RPA.Desktop import Desktop
from RPA.JavaAccessBridge import JavaAccessBridge

from .errors import EasControlError
from .models import ExportJob, QueryResult


class EasPort(Protocol):
    """EAS 控件操作抽象接口，便于测试时注入 fake。"""

    def open_voucher_query(self) -> None: ...
    def query(self, job: ExportJob) -> QueryResult: ...
    def export(self, job: ExportJob) -> None: ...
    def reopen_conditions(self) -> None: ...
    def screenshot(self, path: Path) -> None: ...


class EasClient:
    """通过 Java Access Bridge 操作已登录的金蝶 EAS 客户端。"""

    def __init__(
        self,
        jab: JavaAccessBridge,
        locators: dict[str, str],
        desktop: Desktop | None = None,
    ) -> None:
        self.jab = jab
        self.locators = locators
        self.desktop = desktop or Desktop()

    def _locator(self, key: str) -> str:
        try:
            return self.locators[key]
        except KeyError as exc:
            raise EasControlError(f"缺少控件定位器：{key}") from exc

    def click(self, key: str, *, right: bool = False) -> None:
        self.jab.click_element(
            self._locator(key),
            action=not right,
            click_type="right click" if right else "click",
        )

    def type(self, key: str, value: str) -> None:
        self.jab.type_text(self._locator(key), value, clear=True, typing=False)

    def refresh(self) -> None:
        self.jab.application_refresh()

    def open_voucher_query(self) -> None:
        self.click("voucher_query")

    def query(self, job: ExportJob) -> QueryResult:
        self.type("company", job.company.code)
        self.jab.press_keys("TAB")
        self.click("period_mode")
        self.type("start_year", str(job.year))
        self.type("start_month", str(job.month))
        self.type("end_year", str(job.year))
        self.type("end_month", str(job.month))
        # “最大返回结果数”下拉框：打开后选择第一项“全部”。
        self.jab.toggle_drop_down(self._locator("max_results"), index=0)
        for key in ("audit_all", "posted_all", "review_all", "voucher_mode"):
            self.click(key)
        company_display = self.jab.get_element_text(self._locator("company"))
        self.click("confirm")
        self.refresh()
        empty = not self.jab.get_elements(self._locator("result_rows"), strict=False)
        return QueryResult(company_display=company_display, empty=empty)

    def export(self, job: ExportJob) -> None:
        self.click("result_table", right=True)
        self.click("export_excel")
        self.refresh()
        self.type("export_path", str(job.path))
        self.click("export_confirm")

    def reopen_conditions(self) -> None:
        self.click("condition_query")

    def screenshot(self, path: Path) -> None:
        self.desktop.take_screenshot(path=str(path))
