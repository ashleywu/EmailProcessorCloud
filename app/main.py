from __future__ import annotations

import argparse

from app.config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Daily Knowledge Digest CLI (Milestone 1 placeholder).",
    )
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Print resolved settings (paths and lock parameters).",
    )
    args = parser.parse_args()
    settings = load_settings()
    if args.show_config:
        print(f"db_path={settings.db_path}")
        print(f"lock_name={settings.lock_name}")
        print(f"lock_ttl_minutes={settings.lock_ttl_minutes}")
        print(f"max_email_retries={settings.max_email_retries}")


if __name__ == "__main__":
    main()
