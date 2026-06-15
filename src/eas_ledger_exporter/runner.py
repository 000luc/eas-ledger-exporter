from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

from .eas_client import EasPort
from .errors import ExportError, ValidationError
from .file_wait import wait_until_stable
from .models import ExportJob
from .reporting import RunReporter
from .validation import validate_export
from .xlsx_repair import repair_dimension


logger = logging.getLogger(__name__)


class ExportRunner:
    """串联 EAS 查询、导出、等待、修复和校验；首个错误处停止。"""

    def __init__(self, eas: EasPort, log_dir: Path) -> None:
        self.eas = eas
        self.reporter = RunReporter(log_dir)

    def run(self, jobs: Sequence[ExportJob], *, wait_timeout: float = 1800) -> None:
        self.eas.open_voucher_query()
        for index, job in enumerate(jobs):
            try:
                job.output_dir.mkdir(parents=True, exist_ok=True)
                job.path.unlink(missing_ok=True)

                query = self.eas.query(job)
                self.eas.export(job)
                wait_until_stable(job.path, timeout=wait_timeout)
                repair_dimension(job.path)
                result = validate_export(
                    job.path, query.company_display, job.year, job.month
                )
                if result.empty != query.empty:
                    raise ValidationError(
                        "EAS查询结果与导出文件空数据状态不一致"
                    )

                self.reporter.success(job, result)
                logger.info(
                    "%s %s 导出成功，数据行数：%s",
                    job.company.code,
                    job.company.name,
                    result.row_count,
                )

                if index < len(jobs) - 1:
                    self.eas.reopen_conditions()
            except Exception as exc:
                screenshot = self.reporter.screenshot_path(job)
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                self.eas.screenshot(screenshot)
                self.reporter.failure(job, exc, screenshot)
                logger.exception(
                    "%s %s 导出失败",
                    job.company.code,
                    job.company.name,
                )
                raise ExportError(
                    f"{job.company.code} {job.company.name} 导出失败"
                ) from exc
