from __future__ import annotations

import csv
import datetime
from pathlib import Path

from .models import ExportJob
from .validation import ValidationResult


FIELDS = ("公司编号", "公司名称", "期间", "状态", "数据行数", "文件", "错误")


class RunReporter:
    """记录每次运行的 CSV 汇总、截图路径和文本日志。"""

    def __init__(self, log_dir: Path) -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.summary_path = self.log_dir / "summary.csv"

    def screenshot_path(self, job: ExportJob) -> Path:
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        return self.log_dir / f"{job.company.code}_{job.period}_{timestamp}.png"

    def _append(
        self,
        job: ExportJob,
        status: str,
        row_count: int,
        error: str,
        file_text: str,
    ) -> None:
        row = {
            "公司编号": job.company.code,
            "公司名称": job.company.name,
            "期间": job.period,
            "状态": status,
            "数据行数": row_count,
            "文件": file_text,
            "错误": error,
        }
        exists = self.summary_path.exists()
        with self.summary_path.open("a", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            if not exists:
                writer.writeheader()
            writer.writerow(row)

    def success(self, job: ExportJob, result: ValidationResult) -> None:
        status = "空数据成功" if result.empty else "成功"
        self._append(job, status, result.row_count, "", str(job.path))

    def failure(self, job: ExportJob, exc: Exception, screenshot: Path) -> None:
        error = f"{type(exc).__name__}: {exc}; 截图：{screenshot}"
        self._append(job, "失败", 0, error, str(job.path))
