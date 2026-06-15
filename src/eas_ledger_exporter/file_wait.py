from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Callable
from zipfile import BadZipFile, ZipFile

from .errors import ExportFileError, ExportTimeoutError


Validator = Callable[[Path], None]
_REQUIRED_XLSX_PARTS = frozenset(("[Content_Types].xml", "xl/workbook.xml"))


class _IncompleteXlsxError(Exception):
    pass


def _validate_positive_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} 必须是有限数值")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} 必须是大于 0 的有限数值")
    return number


def _validate_xlsx(path: Path) -> None:
    try:
        with ZipFile(path) as archive:
            for member in _REQUIRED_XLSX_PARTS:
                archive.read(member)
    except (BadZipFile, EOFError, KeyError) as exc:
        raise _IncompleteXlsxError from exc


def _is_temporary_file_error(exc: OSError) -> bool:
    return isinstance(exc, BlockingIOError) or getattr(exc, "winerror", None) in (
        32,
        33,
    )


def _raise_file_error(target: Path, exc: OSError) -> None:
    raise ExportFileError(f"无法检查导出文件：{target}") from exc


def wait_until_stable(
    path: Path,
    timeout: float,
    interval: float = 1.0,
    stable_checks: int = 2,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    validator: Validator | None = None,
) -> Path:
    timeout_value = _validate_positive_number("timeout", timeout)
    interval_value = _validate_positive_number("interval", interval)
    if isinstance(stable_checks, bool) or not isinstance(stable_checks, int):
        raise TypeError("stable_checks 必须是大于等于 1 的整数")
    if stable_checks < 1:
        raise ValueError("stable_checks 必须是大于等于 1 的整数")

    target = Path(path)
    deadline = clock() + timeout_value
    validate = validator or _validate_xlsx
    previous_fingerprint: tuple[int, int] | None = None
    stable_count = 0
    last_state = "不存在"

    while True:
        try:
            stat = target.stat()
        except FileNotFoundError:
            previous_fingerprint = None
            stable_count = 0
            last_state = "不存在"
        except OSError as exc:
            if not _is_temporary_file_error(exc):
                _raise_file_error(target, exc)
            previous_fingerprint = None
            stable_count = 0
            last_state = "文件被占用或无法读取"
        else:
            if stat.st_size == 0:
                previous_fingerprint = None
                stable_count = 0
                last_state = "空文件"
            else:
                try:
                    validate(target)
                except FileNotFoundError:
                    previous_fingerprint = None
                    stable_count = 0
                    last_state = "不存在"
                except (_IncompleteXlsxError, BadZipFile, EOFError):
                    previous_fingerprint = None
                    stable_count = 0
                    last_state = "仍在写入/ZIP未完成"
                except OSError as exc:
                    if not _is_temporary_file_error(exc):
                        _raise_file_error(target, exc)
                    previous_fingerprint = None
                    stable_count = 0
                    last_state = "文件被占用或无法读取"
                else:
                    try:
                        post_stat = target.stat()
                    except FileNotFoundError:
                        previous_fingerprint = None
                        stable_count = 0
                        last_state = "不存在"
                    except OSError as exc:
                        if not _is_temporary_file_error(exc):
                            _raise_file_error(target, exc)
                        previous_fingerprint = None
                        stable_count = 0
                        last_state = "文件被占用或无法读取"
                    else:
                        fingerprint = (post_stat.st_size, post_stat.st_mtime_ns)
                        if previous_fingerprint == fingerprint:
                            stable_count += 1
                        else:
                            previous_fingerprint = fingerprint
                            stable_count = 0
                        last_state = "仍在写入"
                        if stable_count >= stable_checks:
                            if clock() >= deadline:
                                raise ExportTimeoutError(
                                    f"等待 {timeout_value:g} 秒后超时：{target}；"
                                    f"最后状态：{last_state}"
                                )
                            return target

        now = clock()
        if now >= deadline:
            raise ExportTimeoutError(
                f"等待 {timeout_value:g} 秒后超时：{target}；最后状态：{last_state}"
            )
        sleeper(min(interval_value, max(0.0, deadline - now)))
