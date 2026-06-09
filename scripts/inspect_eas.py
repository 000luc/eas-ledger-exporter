from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
import logging
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from typing import Callable

from JABWrapper.parsers.keybind_parser import AccessibleKeyBindingsParser
from RPA.JavaAccessBridge import JavaAccessBridge


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DLL = Path(
    r"D:\Kingdee\eas\oracle_jdk1.8\jre\bin\WindowsAccessBridge-64.dll"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts" / "eas-controls.txt"
NATIVE_EVIDENCE_LOCATOR = "role:label and name:凭证查询"
LOGGER = logging.getLogger(__name__)
_KEY_BINDINGS_PATCH_LOCK = threading.RLock()


def _skip_key_bindings(self, jab_wrapper, context) -> None:
    """Java 6 returns corrupt key-binding data; locators do not need it."""


@contextmanager
def skip_broken_key_bindings():
    """Patch key-binding parsing only while this standalone probe owns the lock."""
    with _KEY_BINDINGS_PATCH_LOCK:
        original_parse = AccessibleKeyBindingsParser.parse
        AccessibleKeyBindingsParser.parse = _skip_key_bindings
        try:
            yield
        finally:
            AccessibleKeyBindingsParser.parse = original_parse


class QuietJavaAccessBridge(JavaAccessBridge):
    def get_version_info(self):
        """Read version info without logging malformed Java 6 proxy strings."""
        return self.jab_wrapper.get_version_info()


def safe_text(value: object) -> str:
    return (
        str(value)
        .encode("utf-8", errors="replace")
        .decode("utf-8")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )


def render_control_tree(jab: JavaAccessBridge) -> str:
    lines = []
    for node in jab.context_info_tree:
        info = node.context_info
        text = node.text.items.sentence if info.accessibleText else ""
        lines.append(
            f"{'| ' * node.ancestry}"
            f"role:{safe_text(info.role)}; "
            f"name:{safe_text(info.name)}; "
            f"virtual_accessible_name:{safe_text(node.virtual_accessible_name)}; "
            f"description:{safe_text(info.description)}; "
            f"text:{safe_text(text)}; "
            f"states:{safe_text(info.states)}; "
            f"indexInParent:{info.indexInParent}; "
            f"childrenCount:{info.childrenCount}; "
            f"x:{info.x}; y:{info.y}; width:{info.width}; height:{info.height}"
        )
    return "\n".join(lines)


def publish_artifact(tree: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(tree)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, output)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def focused_nodes(jab: JavaAccessBridge):
    return [
        node
        for node in jab.context_info_tree
        if "已集中" in node.context_info.states
    ]


def node_identity(node) -> tuple[str, str, str, int]:
    info = node.context_info
    return info.role, info.name, info.description, info.indexInParent


def restore_focus(jab: JavaAccessBridge, original_focus) -> None:
    jab.application_refresh()
    current_focus = focused_nodes(jab)
    if [node_identity(node) for node in current_focus] != [
        node_identity(node) for node in original_focus
    ]:
        if len(original_focus) != 1:
            raise RuntimeError("Cannot restore ambiguous EAS focus state.")
        original_focus[0].request_focus()
        jab.application_refresh()
        if [node_identity(node) for node in focused_nodes(jab)] != [
            node_identity(node) for node in original_focus
        ]:
            raise RuntimeError("Failed to restore the original EAS focus.")


def restore_foreground_with(foreground_api, original_foreground: int) -> None:
    deadline = time.monotonic() + 0.5
    while foreground_api.GetForegroundWindow() != original_foreground:
        if time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    if foreground_api.GetForegroundWindow() == original_foreground:
        return

    foreground_api.SetForegroundWindow(original_foreground)
    deadline = time.monotonic() + 1
    while foreground_api.GetForegroundWindow() != original_foreground:
        if time.monotonic() >= deadline:
            raise RuntimeError("Failed to restore the original foreground window.")
        time.sleep(0.05)


def validate_native_evidence(jab: JavaAccessBridge, window_title: str) -> None:
    evidence = jab.get_elements(NATIVE_EVIDENCE_LOCATOR, strict=True)
    if len(evidence) != 1 or not all(
        state in evidence[0].context_info.states
        for state in ("可见", "正在显示")
    ):
        raise RuntimeError(
            f"EAS window {window_title!r} was selected, but the control tree "
            "does not contain exactly one visible native 凭证查询 control."
        )


def inspect_eas(
    title_contains: str = "金蝶EAS",
    output: Path = DEFAULT_OUTPUT,
    access_bridge_path: Path = DEFAULT_DLL,
    bridge_factory: Callable[..., JavaAccessBridge] = QuietJavaAccessBridge,
    foreground_api=None,
) -> str:
    foreground_api = foreground_api or ctypes.windll.user32
    original_foreground = foreground_api.GetForegroundWindow()
    patch_context = skip_broken_key_bindings()
    patch_active = False
    jab = None
    original_focus = []
    window_selected = False
    tree = None
    primary_error = None
    primary_traceback = None
    cleanup_errors: list[tuple[str, BaseException]] = []

    try:
        patch_context.__enter__()
        patch_active = True
        jab = bridge_factory(
            ignore_callbacks=True,
            access_bridge_path=str(access_bridge_path),
        )
        windows = jab.list_java_windows()
        matches = [window for window in windows if title_contains in window.title]
        if len(matches) != 1:
            available = ", ".join(repr(window.title) for window in windows) or "<none>"
            raise RuntimeError(
                f"Expected exactly one Java window containing {title_contains!r}; "
                f"found {len(matches)}. Available Java windows: {available}"
            )

        window = matches[0]
        jab.select_window_by_pid(window.pid, bring_foreground=False)
        window_selected = True
        original_focus = focused_nodes(jab)
        tree = render_control_tree(jab)
        validate_native_evidence(jab, window.title)
    except BaseException as exc:
        primary_error = exc
        primary_traceback = sys.exc_info()[2]
    finally:
        if jab is not None and window_selected:
            try:
                restore_focus(jab, original_focus)
            except BaseException as exc:
                cleanup_errors.append(("restore EAS focus", exc))
        try:
            restore_foreground_with(foreground_api, original_foreground)
        except BaseException as exc:
            cleanup_errors.append(("restore foreground window", exc))
        if jab is not None:
            try:
                jab.shutdown_jab()
            except BaseException as exc:
                cleanup_errors.append(("shutdown JAB", exc))
        if patch_active:
            try:
                patch_context.__exit__(None, None, None)
            except BaseException as exc:
                cleanup_errors.append(("restore key-binding parser", exc))

    if primary_error is not None:
        for action, error in cleanup_errors:
            LOGGER.error("Cleanup failed while trying to %s: %s", action, error)
        raise primary_error.with_traceback(primary_traceback)
    if cleanup_errors:
        action, error = cleanup_errors[0]
        for extra_action, extra_error in cleanup_errors[1:]:
            LOGGER.error(
                "Additional cleanup failure while trying to %s: %s",
                extra_action,
                extra_error,
            )
        raise RuntimeError(f"Cleanup failed while trying to {action}: {error}") from error

    assert tree is not None
    publish_artifact(tree, output)
    return tree


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect the Kingdee EAS JAB tree.")
    parser.add_argument("--title-contains", default="金蝶EAS")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--access-bridge-path", type=Path, default=DEFAULT_DLL)
    args = parser.parse_args()
    inspect_eas(args.title_contains, args.output, args.access_bridge_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
