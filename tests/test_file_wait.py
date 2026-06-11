from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from eas_ledger_exporter.errors import ExportTimeoutError
from eas_ledger_exporter.file_wait import wait_until_stable
from eas_ledger_exporter.models import Company, ExportJob


class FakeTime:
    def __init__(self, on_sleep=None):
        self.now = 0.0
        self.sleeps = 0
        self.on_sleep = on_sleep

    def clock(self):
        return self.now

    def sleep(self, interval):
        self.sleeps += 1
        self.now += max(interval, 0.1)
        if self.on_sleep is not None:
            self.on_sleep(self.sleeps)


def wait(path, fake_time, **kwargs):
    return wait_until_stable(
        path,
        timeout=kwargs.pop("timeout", 10),
        interval=kwargs.pop("interval", 1),
        clock=fake_time.clock,
        sleeper=fake_time.sleep,
        **kwargs,
    )


def test_export_job_builds_six_digit_period_and_path(tmp_path):
    job = ExportJob(Company("001", "广州总部"), 2026, 6, tmp_path)

    assert job.period == "202606"
    assert job.path == tmp_path / "001.广州总部_202606_凭证序时簿.xlsx"
    with pytest.raises(FrozenInstanceError):
        job.month = 7


@pytest.mark.parametrize("year", (1999, 2101, True, 2026.0))
def test_export_job_rejects_invalid_year(tmp_path, year):
    with pytest.raises((TypeError, ValueError), match="year"):
        ExportJob(Company("001", "广州总部"), year, 6, tmp_path)


@pytest.mark.parametrize("month", (0, 13, True, 6.0))
def test_export_job_rejects_invalid_month(tmp_path, month):
    with pytest.raises((TypeError, ValueError), match="month"):
        ExportJob(Company("001", "广州总部"), 2026, month, tmp_path)


@pytest.mark.parametrize("output_dir", ("output", None, Path()))
def test_export_job_rejects_invalid_output_dir(output_dir):
    with pytest.raises((TypeError, ValueError), match="output_dir"):
        ExportJob(Company("001", "广州总部"), 2026, 6, output_dir)


@pytest.mark.parametrize("code", ("01", "0001", "１２３", "12a", ""))
def test_export_job_rejects_unsafe_company_code(tmp_path, code):
    with pytest.raises(ValueError, match="公司编号"):
        ExportJob(Company(code, "广州总部"), 2026, 6, tmp_path)


@pytest.mark.parametrize(
    "name",
    (
        "",
        "   ",
        "广州/总部",
        "广州:总部",
        "广州\x1f总部",
        "广州\x7f总部",
        "CON",
        "con.txt",
        "PRN.xlsx",
        "COM1",
        "lpt9.log",
        "广州总部.",
        "广州总部 ",
    ),
)
def test_export_job_rejects_unsafe_company_name(tmp_path, name):
    with pytest.raises(ValueError, match="公司名称"):
        ExportJob(Company("001", name), 2026, 6, tmp_path)


def test_wait_requires_baseline_plus_two_equal_observations(tmp_path):
    path = tmp_path / "ledger.xlsx"
    path.write_bytes(b"ready")
    fake_time = FakeTime()

    assert wait(path, fake_time, stable_checks=2) == path
    assert fake_time.sleeps == 2


def test_size_change_resets_stability_count(tmp_path):
    path = tmp_path / "ledger.xlsx"
    path.write_bytes(b"a")

    def mutate(sleeps):
        if sleeps == 1:
            path.write_bytes(b"changed")

    fake_time = FakeTime(mutate)

    assert wait(path, fake_time, stable_checks=2) == path
    assert fake_time.sleeps == 3


def test_disappearance_resets_baseline_and_stability_count(tmp_path):
    path = tmp_path / "ledger.xlsx"
    path.write_bytes(b"ready")

    def mutate(sleeps):
        if sleeps == 1:
            path.unlink()
        elif sleeps == 2:
            path.write_bytes(b"ready")

    fake_time = FakeTime(mutate)

    assert wait(path, fake_time, stable_checks=2) == path
    assert fake_time.sleeps == 4


@pytest.mark.parametrize("open_error", (PermissionError, OSError))
def test_locked_file_recovers_and_each_open_is_closed(
    tmp_path, monkeypatch, open_error
):
    path = tmp_path / "ledger.xlsx"
    path.write_bytes(b"ready")
    real_open = Path.open
    attempts = 0
    opened = []

    class TrackedFile:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.closed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.wrapped.close()
            self.closed = True

    def controlled_open(self, *args, **kwargs):
        nonlocal attempts
        if self != path:
            return real_open(self, *args, **kwargs)
        attempts += 1
        if attempts == 1:
            raise open_error("locked")
        tracked = TrackedFile(real_open(self, *args, **kwargs))
        opened.append(tracked)
        return tracked

    monkeypatch.setattr(Path, "open", controlled_open)
    fake_time = FakeTime()

    assert wait(path, fake_time, stable_checks=2) == path
    assert attempts == 4
    assert opened and all(item.closed for item in opened)
    path.unlink()


def test_read_failure_requires_a_new_baseline_before_stability(tmp_path, monkeypatch):
    path = tmp_path / "ledger.xlsx"
    path.write_bytes(b"0123456789")
    real_open = Path.open
    attempts = 0

    def fail_second_open(self, *args, **kwargs):
        nonlocal attempts
        if self != path:
            return real_open(self, *args, **kwargs)
        attempts += 1
        if attempts == 2:
            raise PermissionError("locked")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_second_open)
    fake_time = FakeTime()

    assert wait(path, fake_time, stable_checks=2) == path
    assert attempts == 5
    assert fake_time.sleeps == 4


@pytest.mark.parametrize(
    ("state", "message"),
    (
        ("missing", "不存在"),
        ("empty", "空文件"),
        ("locked", "文件被占用或无法读取"),
    ),
)
def test_wait_timeout_reports_last_state(tmp_path, monkeypatch, state, message):
    path = tmp_path / "ledger.xlsx"
    if state == "empty":
        path.touch()
    elif state == "locked":
        path.write_bytes(b"ready")

        def locked_open(self, *args, **kwargs):
            if self == path:
                raise PermissionError("locked")
            return original_open(self, *args, **kwargs)

        original_open = Path.open
        monkeypatch.setattr(Path, "open", locked_open)

    fake_time = FakeTime()

    with pytest.raises(ExportTimeoutError) as caught:
        wait(path, fake_time, timeout=2)

    text = str(caught.value)
    assert str(path) in text
    assert "等待 2 秒后超时" in text
    assert message in text


def test_continuously_changing_file_times_out_as_still_writing(tmp_path):
    path = tmp_path / "ledger.xlsx"
    path.write_bytes(b"a")

    def mutate(_sleeps):
        path.write_bytes(path.read_bytes() + b"x")

    fake_time = FakeTime(mutate)

    with pytest.raises(ExportTimeoutError, match="仍在写入"):
        wait(path, fake_time, timeout=2)


@pytest.mark.parametrize(
    ("kwargs", "field"),
    (
        ({"timeout": 0}, "timeout"),
        ({"timeout": True}, "timeout"),
        ({"timeout": float("inf")}, "timeout"),
        ({"interval": -1}, "interval"),
        ({"interval": False}, "interval"),
        ({"interval": float("nan")}, "interval"),
        ({"stable_checks": 0}, "stable_checks"),
        ({"stable_checks": True}, "stable_checks"),
        ({"stable_checks": 1.5}, "stable_checks"),
    ),
)
def test_wait_rejects_invalid_parameters(tmp_path, kwargs, field):
    kwargs.setdefault("timeout", 1)
    with pytest.raises((TypeError, ValueError), match=field):
        wait_until_stable(tmp_path / "ledger.xlsx", **kwargs)
