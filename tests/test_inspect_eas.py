from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts import inspect_eas


class FakeForeground:
    def __init__(self, handle: int = 123) -> None:
        self.handle = handle

    def GetForegroundWindow(self) -> int:
        return self.handle

    def SetForegroundWindow(self, handle: int) -> int:
        self.handle = handle
        return 1


class FakeBridge:
    def __init__(
        self,
        *,
        main_error: Exception | None = None,
        cleanup_error: Exception | None = None,
        evidence_found: bool = True,
    ) -> None:
        self.main_error = main_error
        self.cleanup_error = cleanup_error
        self.evidence_found = evidence_found
        self.shutdown_calls = 0
        self.context_info_tree = []

    def list_java_windows(self):
        if self.main_error:
            raise self.main_error
        return [SimpleNamespace(title="金蝶EAS Cloud-test", pid=42)]

    def select_window_by_pid(self, pid: int, bring_foreground: bool) -> None:
        assert pid == 42
        assert bring_foreground is False

    def get_elements(self, locator: str, strict: bool):
        assert locator == inspect_eas.NATIVE_EVIDENCE_LOCATOR
        assert strict is True
        if not self.evidence_found:
            return []
        return [
            SimpleNamespace(
                context_info=SimpleNamespace(states="已启用,可见,正在显示")
            )
        ]

    def application_refresh(self) -> None:
        if self.cleanup_error:
            raise self.cleanup_error

    def shutdown_jab(self) -> None:
        self.shutdown_calls += 1
        if self.cleanup_error:
            raise self.cleanup_error


def test_cli_imports_and_help_runs(capsys):
    cli = importlib.import_module("eas_ledger_exporter.cli")

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--help"])

    assert exc_info.value.code == 0
    assert "Java Access Bridge" in capsys.readouterr().out


def test_atomic_publish_failure_preserves_existing_artifact(tmp_path, monkeypatch):
    output = tmp_path / "eas-controls.txt"
    output.write_text("trusted", encoding="utf-8")

    def fail_replace(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        inspect_eas.publish_artifact("new tree", output)

    assert output.read_text(encoding="utf-8") == "trusted"
    assert list(tmp_path.glob(f".{output.name}.*.tmp")) == []


def test_primary_error_is_not_masked_by_cleanup_error(tmp_path, caplog):
    bridge = FakeBridge(
        main_error=ValueError("primary failure"),
        cleanup_error=RuntimeError("cleanup failure"),
    )
    output = tmp_path / "eas-controls.txt"
    output.write_text("trusted", encoding="utf-8")

    with pytest.raises(ValueError, match="primary failure"):
        inspect_eas.inspect_eas(
            output=output,
            bridge_factory=lambda **kwargs: bridge,
            foreground_api=FakeForeground(),
        )

    assert "cleanup failure" in caplog.text
    assert output.read_text(encoding="utf-8") == "trusted"
    assert bridge.shutdown_calls == 1


def test_cleanup_failure_prevents_artifact_publish(tmp_path):
    bridge = FakeBridge(cleanup_error=RuntimeError("cleanup failure"))
    output = tmp_path / "eas-controls.txt"
    output.write_text("trusted", encoding="utf-8")

    with pytest.raises(RuntimeError, match="cleanup failure"):
        inspect_eas.inspect_eas(
            output=output,
            bridge_factory=lambda **kwargs: bridge,
            foreground_api=FakeForeground(),
        )

    assert output.read_text(encoding="utf-8") == "trusted"


def test_validation_failure_prevents_artifact_publish(tmp_path):
    bridge = FakeBridge(evidence_found=False)
    output = tmp_path / "eas-controls.txt"
    output.write_text("trusted", encoding="utf-8")

    with pytest.raises(RuntimeError, match="visible native 凭证查询"):
        inspect_eas.inspect_eas(
            output=output,
            bridge_factory=lambda **kwargs: bridge,
            foreground_api=FakeForeground(),
        )

    assert output.read_text(encoding="utf-8") == "trusted"


@pytest.mark.parametrize("raises", [False, True])
def test_key_binding_patch_restores_original_method(raises):
    original = inspect_eas.AccessibleKeyBindingsParser.parse

    with pytest.raises(RuntimeError) if raises else inspect_eas.skip_broken_key_bindings():
        if raises:
            with inspect_eas.skip_broken_key_bindings():
                assert (
                    inspect_eas.AccessibleKeyBindingsParser.parse
                    is inspect_eas._skip_key_bindings
                )
                raise RuntimeError("probe failed")
        else:
            assert (
                inspect_eas.AccessibleKeyBindingsParser.parse
                is inspect_eas._skip_key_bindings
            )

    assert inspect_eas.AccessibleKeyBindingsParser.parse is original


def test_verified_config_locators_exist_in_artifact():
    config = json.loads(
        (PROJECT_ROOT / "config" / "eas-locators.json").read_text(encoding="utf-8")
    )
    artifact = (PROJECT_ROOT / "artifacts" / "eas-controls.txt").read_text(
        encoding="utf-8"
    )

    assert "page_setup_button" not in config["verified_controls"]
    for control in config["verified_controls"].values():
        terms = dict(
            part.split(":", 1)
            for part in control["locator"].split(" and ")
        )
        assert any(
            all(f"{key}:{value}" in line for key, value in terms.items())
            for line in artifact.splitlines()
        )
