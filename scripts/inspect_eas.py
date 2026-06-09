from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path
import time

import pyperclip
from JABWrapper.parsers.keybind_parser import AccessibleKeyBindingsParser
from RPA.JavaAccessBridge import JavaAccessBridge


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DLL = Path(
    r"D:\Kingdee\eas\oracle_jdk1.8\jre\bin\WindowsAccessBridge-64.dll"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts" / "eas-controls.txt"
MENU_SEARCH_LOCATOR = (
    "role:text and description:录入快捷码或菜单名称(支持拼音和首字母)"
)


def _skip_key_bindings(self, jab_wrapper, context) -> None:
    """Java 6 returns corrupt key-binding data; locators do not need it."""


@contextmanager
def skip_broken_key_bindings():
    """Temporarily avoid parsing corrupt key bindings from the EAS Java runtime."""
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


def write_control_tree(jab: JavaAccessBridge, output: Path) -> str:
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
    tree = "\n".join(lines)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(tree, encoding="utf-8")
    return tree


def control_text(node) -> str:
    if not node.context_info.accessibleText:
        return ""
    return node.text.items.sentence.rstrip("\r\n")


def replace_control_text(node, text: str) -> None:
    node.request_focus()
    node.do_action("select-all")
    if text:
        pyperclip.copy(text)
        node.do_action("paste-from-clipboard")
    else:
        node.do_action("delete-next")


def probe_menu_text(jab: JavaAccessBridge, output: Path, text: str) -> str:
    matches = jab.get_elements(MENU_SEARCH_LOCATOR, strict=True)
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one EAS menu search control; found {len(matches)}."
        )
    search_control = matches[0]
    original_text = control_text(search_control)
    original_clipboard = pyperclip.paste()
    try:
        replace_control_text(search_control, text)
        time.sleep(1)
        jab.application_refresh()
        return write_control_tree(jab, output)
    finally:
        try:
            replace_control_text(search_control, original_text)
            time.sleep(0.5)
            jab.application_refresh()
            restored = jab.get_elements(MENU_SEARCH_LOCATOR, strict=True)
            if len(restored) != 1:
                raise RuntimeError(
                    "Could not verify restoration of the EAS menu search control."
                )
            restored_text = control_text(restored[0])
            if restored_text != original_text:
                raise RuntimeError(
                    "EAS menu search text was not restored after accessibility probe."
                )
        finally:
            pyperclip.copy(original_clipboard)


def inspect_eas(
    title_contains: str = "金蝶EAS",
    output: Path = DEFAULT_OUTPUT,
    access_bridge_path: Path = DEFAULT_DLL,
) -> str:
    with skip_broken_key_bindings():
        jab = QuietJavaAccessBridge(
            ignore_callbacks=True,
            access_bridge_path=str(access_bridge_path),
        )
        try:
            windows = jab.list_java_windows()
            matches = [window for window in windows if title_contains in window.title]
            if len(matches) != 1:
                available = (
                    ", ".join(repr(window.title) for window in windows) or "<none>"
                )
                raise RuntimeError(
                    f"Expected exactly one Java window containing {title_contains!r}; "
                    f"found {len(matches)}. Available Java windows: {available}"
                )

            window = matches[0]
            jab.select_window_by_pid(window.pid, bring_foreground=False)
            tree = write_control_tree(jab, output)
            if "text:财务会计" not in tree:
                tree = probe_menu_text(jab, output, "财务会计")
            if "text:财务会计" not in tree:
                raise RuntimeError(
                    f"EAS window {window.title!r} was selected, but the control tree "
                    "does not contain '财务会计'."
                )
            return tree
        finally:
            jab.shutdown_jab()


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
