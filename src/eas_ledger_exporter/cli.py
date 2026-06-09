from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "总账导出业务尚未实现；当前请使用 scripts/inspect_eas.py "
            "验证 EAS Java 可访问性。"
        )
    )
    parser.parse_args(argv)
    return 0
