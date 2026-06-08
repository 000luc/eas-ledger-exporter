from __future__ import annotations

import argparse
from pathlib import Path

from RPA.JavaAccessBridge import JavaAccessBridge


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DLL = Path(
    r"D:\Kingdee\eas\oracle_jdk1.8\jre\bin\WindowsAccessBridge-64.dll"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts" / "eas-controls.txt"


def inspect_eas(
    title_contains: str = "金蝶EAS",
    output: Path = DEFAULT_OUTPUT,
    access_bridge_path: Path = DEFAULT_DLL,
) -> str:
    jab = JavaAccessBridge(
        ignore_callbacks=True,
        access_bridge_path=str(access_bridge_path),
    )
    try:
        windows = jab.list_java_windows()
        matches = [window for window in windows if title_contains in window.title]
        if len(matches) != 1:
            available = ", ".join(repr(window.title) for window in windows) or "<none>"
            raise RuntimeError(
                f"Expected exactly one Java window containing {title_contains!r}; "
                f"found {len(matches)}. Available Java windows: {available}"
            )

        window = matches[0]
        jab.select_window_by_pid(window.pid)
        output.parent.mkdir(parents=True, exist_ok=True)
        tree = jab.print_element_tree(str(output))
        if "财务会计" not in tree:
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
