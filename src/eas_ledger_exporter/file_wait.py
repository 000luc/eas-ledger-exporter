from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Callable

from .errors import ExportTimeoutError


def _validate_number(name: str, value: object, *, allow_zero: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} 必须是有限数值")
    number = float(value)
    if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        comparison = "大于等于 0" if allow_zero else "大于 0"
        raise ValueError(f"{name} 必须是{comparison}的有限数值")
    return number


def wait_until_stable(
    path: Path,
    timeout: float,
    interval: float = 1.0,
    stable_checks: int = 2,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> Path:
    timeout_value = _validate_number("timeout", timeout, allow_zero=False)
    interval_value = _validate_number("interval", interval, allow_zero=True)
    if (
        isinstance(stable_checks, bool)
        or not isinstance(stable_checks, int)
        or stable_checks < 1
    ):
        raise ValueError("stable_checks 必须是大于等于 1 的整数")

    target = Path(path)
    deadline = clock() + timeout_value
    previous_size: int | None = None
    stable_count = 0
    last_state = "不存在"

    while True:
        try:
            size = target.stat().st_size
        except FileNotFoundError:
            previous_size = None
            stable_count = 0
            last_state = "不存在"
        except OSError:
            stable_count = 0
            last_state = "文件被占用或无法读取"
        else:
            if size == 0:
                previous_size = None
                stable_count = 0
                last_state = "空文件"
            else:
                try:
                    with target.open("rb"):
                        pass
                except OSError:
                    previous_size = size
                    stable_count = 0
                    last_state = "文件被占用或无法读取"
                else:
                    if previous_size == size:
                        stable_count += 1
                    else:
                        previous_size = size
                        stable_count = 0
                    last_state = "仍在写入"
                    if stable_count >= stable_checks:
                        return target

        now = clock()
        if now >= deadline:
            raise ExportTimeoutError(
                f"等待导出文件超时：{target}；timeout={timeout}；最后状态：{last_state}"
            )
        sleeper(min(interval_value, max(0.0, deadline - now)))
