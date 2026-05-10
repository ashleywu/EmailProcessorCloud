from __future__ import annotations

import argparse
import sys

from app.config import format_gmail_config_summary, load_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Daily Knowledge Digest CLI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    cfg = sub.add_parser(
        "show-config",
        help="Print a safe Gmail-oriented configuration summary (no secrets).",
    )
    cfg.set_defaults(handler=_cmd_show_config)

    args = parser.parse_args(argv)

    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    return handler(args)


def _cmd_show_config(_args: argparse.Namespace) -> int:
    print(format_gmail_config_summary(load_settings()), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
