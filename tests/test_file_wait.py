from __future__ import annotations

from dataclasses import FrozenInstanceError
import errno
import os
from pathlib import Path
import struct
from zipfile import BadZipFile, ZipFile

import pytest

from eas_ledger_exporter.errors import ExportFileError, ExportTimeoutError
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


class SequenceClock:
    def __init__(self, *readings):
        self._readings = iter(readings)
        self._last = readings[-1]

    def __call__(self):
        self._last = next(self._readings, self._last)
        return self._last


def wait(path, fake_time, **kwargs):
    return wait_until_stable(
        path,
        timeout=kwargs.pop("timeout", 10),
        interval=kwargs.pop("interval", 1),
        clock=fake_time.clock,
        sleeper=fake_time.sleep,
        **kwargs,
    )


def write_xlsx(path, *, workbook=True, content_types=True):
    with ZipFile(path, "w") as archive:
        if content_types:
            archive.writestr("[Content_Types].xml", "<Types/>")
        if workbook:
            archive.writestr("xl/workbook.xml", "<workbook/>")


def corrupt_zip_member(path, member):
    with ZipFile(path) as archive:
        info = archive.getinfo(member)
    data = bytearray(path.read_bytes())
    filename_length, extra_length = struct.unpack_from(
        "<HH", data, info.header_offset + 26
    )
    data_offset = info.header_offset + 30 + filename_length + extra_length
    data[data_offset] ^= 0xFF
    path.write_bytes(data)


def windows_error(error_type, winerror):
    error = error_type("locked")
    error.winerror = winerror
    return error


def test_export_job_builds_six_digit_period_and_path(tmp_path):
    job = ExportJob(Company("001", "广州总部"), 2026, 6, tmp_path)

    assert job.period == "202606"
    assert job.path == tmp_path / "001.广州总部_202606_凭证序时簿.xlsx"
    with pytest.raises(FrozenInstanceError):
        job.month = 7


@pytest.mark.parametrize("year", (True, 2026.0, "2026"))
def test_export_job_rejects_non_integer_year(tmp_path, year):
    with pytest.raises(TypeError, match="year"):
        ExportJob(Company("001", "广州总部"), year, 6, tmp_path)


@pytest.mark.parametrize("year", (1999, 2101))
def test_export_job_rejects_out_of_range_year(tmp_path, year):
    with pytest.raises(ValueError, match="year"):
        ExportJob(Company("001", "广州总部"), year, 6, tmp_path)


@pytest.mark.parametrize("month", (True, 6.0, "6"))
def test_export_job_rejects_non_integer_month(tmp_path, month):
    with pytest.raises(TypeError, match="month"):
        ExportJob(Company("001", "广州总部"), 2026, month, tmp_path)


@pytest.mark.parametrize("month", (0, 13))
def test_export_job_rejects_out_of_range_month(tmp_path, month):
    with pytest.raises(ValueError, match="month"):
        ExportJob(Company("001", "广州总部"), 2026, month, tmp_path)


@pytest.mark.parametrize("output_dir", ("output", None))
def test_export_job_rejects_non_path_output_dir(output_dir):
    with pytest.raises(TypeError, match="output_dir"):
        ExportJob(Company("001", "广州总部"), 2026, 6, output_dir)


def test_export_job_rejects_empty_output_dir():
    with pytest.raises(ValueError, match="output_dir"):
        ExportJob(Company("001", "广州总部"), 2026, 6, Path())


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


def test_export_job_rejects_filename_over_255_utf16_code_units(tmp_path):
    with pytest.raises(ValueError, match="文件名.*255"):
        ExportJob(Company("001", "😀" * 120), 2026, 6, tmp_path)


def test_wait_requires_baseline_plus_two_equal_observations(tmp_path):
    path = tmp_path / "ledger.xlsx"
    write_xlsx(path)
    fake_time = FakeTime()

    assert wait(path, fake_time, stable_checks=2) == path
    assert fake_time.sleeps == 2


def test_size_change_resets_stability_count(tmp_path):
    path = tmp_path / "ledger.xlsx"
    write_xlsx(path)

    def mutate(sleeps):
        if sleeps == 1:
            with ZipFile(path, "a") as archive:
                archive.writestr("changed.xml", "changed")

    fake_time = FakeTime(mutate)

    assert wait(path, fake_time, stable_checks=2) == path
    assert fake_time.sleeps == 3


def test_disappearance_resets_baseline_and_stability_count(tmp_path):
    path = tmp_path / "ledger.xlsx"
    write_xlsx(path)

    def mutate(sleeps):
        if sleeps == 1:
            path.unlink()
        elif sleeps == 2:
            write_xlsx(path)

    fake_time = FakeTime(mutate)

    assert wait(path, fake_time, stable_checks=2) == path
    assert fake_time.sleeps == 4


@pytest.mark.parametrize(
    "open_error",
    (
        lambda: windows_error(PermissionError, 32),
        lambda: windows_error(OSError, 33),
        lambda: BlockingIOError("busy"),
    ),
)
def test_locked_file_recovers_after_temporary_error(tmp_path, open_error):
    path = tmp_path / "ledger.xlsx"
    write_xlsx(path)
    attempts = 0

    def validator(candidate):
        nonlocal attempts
        assert candidate == path
        attempts += 1
        if attempts == 1:
            raise open_error()

    fake_time = FakeTime()

    assert wait(path, fake_time, stable_checks=2, validator=validator) == path
    assert attempts == 4


def test_default_validator_closes_archive_before_return(tmp_path):
    path = tmp_path / "ledger.xlsx"
    renamed = tmp_path / "renamed.xlsx"
    write_xlsx(path)

    assert wait(path, FakeTime(), stable_checks=1) == path

    path.rename(renamed)
    renamed.unlink()


def test_read_failure_requires_a_new_baseline_before_stability(tmp_path):
    path = tmp_path / "ledger.xlsx"
    write_xlsx(path)
    attempts = 0

    def fail_second_validation(candidate):
        nonlocal attempts
        assert candidate == path
        attempts += 1
        if attempts == 2:
            raise windows_error(PermissionError, 32)

    fake_time = FakeTime()

    assert wait(
        path, fake_time, stable_checks=2, validator=fail_second_validation
    ) == path
    assert attempts == 5
    assert fake_time.sleeps == 4


def test_disappearance_during_validation_resets_baseline(tmp_path):
    path = tmp_path / "ledger.xlsx"
    write_xlsx(path)
    attempts = 0

    def disappear_once(candidate):
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            candidate.unlink()
            raise FileNotFoundError(candidate)

    def recreate(sleeps):
        if sleeps == 2:
            write_xlsx(path)

    fake_time = FakeTime(recreate)

    assert wait(
        path, fake_time, stable_checks=1, validator=disappear_once
    ) == path
    assert fake_time.sleeps == 3


@pytest.mark.parametrize("validation_error", (BadZipFile, EOFError))
def test_incomplete_validation_errors_are_retryable(tmp_path, validation_error):
    path = tmp_path / "ledger.xlsx"
    write_xlsx(path)

    with pytest.raises(ExportTimeoutError, match="仍在写入/ZIP未完成"):
        wait(
            path,
            FakeTime(),
            timeout=1,
            validator=lambda _path: (_ for _ in ()).throw(validation_error()),
        )


def test_valid_xlsx_zip_succeeds(tmp_path):
    path = tmp_path / "ledger.xlsx"
    write_xlsx(path)

    assert wait(path, FakeTime(), stable_checks=1) == path


@pytest.mark.parametrize(
    "writer",
    (
        lambda path: path.write_bytes(b"PK\x03\x04unfinished"),
        lambda path: write_xlsx(path, workbook=False),
        lambda path: write_xlsx(path, content_types=False),
    ),
)
def test_incomplete_xlsx_zip_keeps_waiting_until_timeout(tmp_path, writer):
    path = tmp_path / "ledger.xlsx"
    writer(path)

    with pytest.raises(ExportTimeoutError, match="仍在写入/ZIP未完成"):
        wait(path, FakeTime(), timeout=2)


@pytest.mark.parametrize(
    "member", ("[Content_Types].xml", "xl/workbook.xml")
)
def test_critical_member_crc_failure_keeps_waiting_until_timeout(
    tmp_path, member
):
    path = tmp_path / "ledger.xlsx"
    write_xlsx(path)
    corrupt_zip_member(path, member)

    with pytest.raises(ExportTimeoutError, match="仍在写入/ZIP未完成"):
        wait(path, FakeTime(), timeout=2)


def test_same_size_mtime_change_resets_stability(tmp_path):
    path = tmp_path / "ledger.xlsx"
    write_xlsx(path)
    initial = path.stat().st_mtime_ns

    def touch_once(sleeps):
        if sleeps == 1:
            os.utime(path, ns=(initial + 1_000_000, initial + 1_000_000))

    fake_time = FakeTime(touch_once)

    assert wait(path, fake_time, stable_checks=1) == path
    assert fake_time.sleeps == 2


def test_deadline_crossed_before_return_times_out(tmp_path):
    path = tmp_path / "ledger.xlsx"
    write_xlsx(path)
    clock = SequenceClock(0.0, 0.0, 1.0)

    with pytest.raises(ExportTimeoutError, match="等待 1 秒后超时"):
        wait_until_stable(
            path,
            timeout=1,
            interval=0.1,
            stable_checks=1,
            clock=clock,
            sleeper=lambda _interval: None,
        )


def test_non_retryable_oserror_raises_export_file_error(tmp_path, monkeypatch):
    path = tmp_path / "ledger.xlsx"
    original_stat = Path.stat
    cause = OSError(errno.ENAMETOOLONG, "name too long")

    def broken_stat(self, *args, **kwargs):
        if self == path:
            raise cause
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", broken_stat)

    with pytest.raises(ExportFileError, match="导出文件") as caught:
        wait(path, FakeTime())

    assert caught.value.__cause__ is cause


@pytest.mark.parametrize(
    "cause",
    (
        PermissionError("access denied"),
        windows_error(PermissionError, 5),
    ),
)
def test_non_retryable_permission_error_raises_export_file_error(
    tmp_path, cause
):
    path = tmp_path / "ledger.xlsx"
    write_xlsx(path)

    with pytest.raises(ExportFileError, match="导出文件") as caught:
        wait(
            path,
            FakeTime(),
            validator=lambda _path: (_ for _ in ()).throw(cause),
        )

    assert caught.value.__cause__ is cause


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
        write_xlsx(path)

    fake_time = FakeTime()

    with pytest.raises(ExportTimeoutError) as caught:
        validator = (
            (
                lambda _path: (_ for _ in ()).throw(
                    windows_error(PermissionError, 32)
                )
            )
            if state == "locked"
            else None
        )
        wait(path, fake_time, timeout=2, validator=validator)

    text = str(caught.value)
    assert str(path) in text
    assert "等待 2 秒后超时" in text
    assert message in text


def test_continuously_changing_file_times_out_as_still_writing(tmp_path):
    path = tmp_path / "ledger.xlsx"
    write_xlsx(path)

    def mutate(_sleeps):
        with ZipFile(path, "a") as archive:
            archive.writestr(f"change-{_sleeps}.xml", "x")

    fake_time = FakeTime(mutate)

    with pytest.raises(ExportTimeoutError, match="仍在写入"):
        wait(path, fake_time, timeout=2)


@pytest.mark.parametrize(
    ("kwargs", "field"),
    (
        ({"timeout": 0}, "timeout"),
        ({"timeout": True}, "timeout"),
        ({"timeout": float("inf")}, "timeout"),
        ({"timeout": "1"}, "timeout"),
        ({"interval": -1}, "interval"),
        ({"interval": 0}, "interval"),
        ({"interval": False}, "interval"),
        ({"interval": float("nan")}, "interval"),
        ({"stable_checks": 0}, "stable_checks"),
        ({"stable_checks": True}, "stable_checks"),
        ({"stable_checks": 1.5}, "stable_checks"),
    ),
)
def test_wait_rejects_invalid_parameters(tmp_path, kwargs, field):
    kwargs.setdefault("timeout", 1)
    expected = TypeError if any(
        isinstance(value, (bool, str)) or field == "stable_checks" and value == 1.5
        for value in kwargs.values()
    ) else ValueError
    with pytest.raises(expected, match=field):
        wait_until_stable(tmp_path / "ledger.xlsx", **kwargs)
