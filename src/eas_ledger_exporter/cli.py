from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from RPA.Desktop import Desktop
from RPA.JavaAccessBridge import JavaAccessBridge

from .config import load_config
from .eas_client import EasClient
from .errors import ConfigError, ExportError
from .models import ExportJob
from .runner import ExportRunner


DEFAULT_LOCATORS_PATH = Path("config/eas-locators.json")
DEFAULT_DLL = Path(
    r"D:\Kingdee\eas\oracle_jdk1.8\jre\bin\WindowsAccessBridge-64.dll"
)
LOG_DIR = Path("logs")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="通过 Java Access Bridge 批量导出金蝶 EAS 凭证序时簿。"
    )
    parser.add_argument(
        "--config", type=Path, required=True, help="配置 Excel 路径"
    )
    parser.add_argument("--limit", type=int, help="限制处理公司数")
    parser.add_argument(
        "--dry-run", action="store_true", help="仅填写查询条件，不执行导出"
    )
    return parser


def _configure_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "run.log"
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    )
    root = logging.getLogger()
    for existing in root.handlers:
        if (
            isinstance(existing, logging.FileHandler)
            and getattr(existing, "baseFilename", None) == str(log_path)
        ):
            return
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def create_eas_client(
    locators_path: Path = DEFAULT_LOCATORS_PATH,
    access_bridge_path: Path = DEFAULT_DLL,
) -> EasClient:
    with locators_path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)

    locators = {
        key: value["locator"]
        for key, value in data.get("verified_controls", {}).items()
    }

    jab = JavaAccessBridge(
        ignore_callbacks=True,
        access_bridge_path=str(access_bridge_path),
    )
    windows = jab.list_java_windows()
    matches = [window for window in windows if "金蝶EAS" in window.title]
    if len(matches) != 1:
        available = ", ".join(repr(window.title) for window in windows) or "<none>"
        raise RuntimeError(
            f"预期找到 1 个金蝶 EAS 窗口，实际为 {len(matches)} 个：{available}"
        )
    jab.select_window_by_pid(matches[0].pid, bring_foreground=False)

    return EasClient(jab, locators, desktop=Desktop())


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 1

    companies = (
        config.companies[: args.limit] if args.limit else config.companies
    )
    jobs = [
        ExportJob(company, config.year, config.month, config.output_dir)
        for company in companies
    ]

    if args.dry_run:
        print(f"干运行模式：将处理 {len(jobs)} 家公司")
        for job in jobs:
            print(f"  {job.company.code} {job.company.name}")
        return 0

    log_dir = LOG_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
    _configure_logging(log_dir)

    try:
        eas = create_eas_client()
    except Exception as exc:
        print(f"无法连接 EAS：{exc}", file=sys.stderr)
        return 1

    runner = ExportRunner(eas, log_dir)
    try:
        runner.run(jobs)
    except ExportError as exc:
        print(f"导出失败：{exc}", file=sys.stderr)
        return 1

    return 0
