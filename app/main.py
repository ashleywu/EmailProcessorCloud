from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from pydantic import ValidationError

from app.agents.daily_digest_agent import DailyDigestAgent
from app.agents.leadership_agent import LeadershipProcessorAgent
from app.agents.noise_agent import NoiseProcessorAgent
from app.agents.radar_agent import RadarProcessorAgent
from app.agents.router_agent import RouterAgent
from app.agents.technology_agent import TechnologyProcessorAgent
from app.config import (
    build_gmail_client,
    build_run_lock,
    format_gmail_config_summary,
    load_settings,
)
from app.digest.composer import DigestComposer
from app.digest.quality_gate import DigestQualityGateAgent
from app.gmail.fetcher import GmailFetcher
from app.gmail.labeler import GmailLabeler
from app.gmail.sender import GmailSender
from app.llm.providers.openai_provider import OpenAIProvider
from app.storage.repository import StateRepository


def _cli_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Daily Knowledge Digest CLI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    cfg = sub.add_parser(
        "show-config",
        help="Print a safe configuration summary (secrets redacted; credential files not read).",
    )
    cfg.set_defaults(handler=_cmd_show_config)

    rd = sub.add_parser(
        "run-daily",
        help="Fetch newsletter mail from Gmail, upsert into SQLite, run digest pipeline.",
    )
    rd.set_defaults(handler=_cmd_run_daily)

    pv = sub.add_parser(
        "preview-digest",
        help="Print the latest digest HTML for a UTC calendar day (read-only; does not send mail).",
        epilog=(
            "Exits with code 1 if there is no digest for that UTC day, or if the latest row has "
            "no preview HTML; stderr explains why. Does not require OPENAI_API_KEY."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pv.add_argument(
        "--date",
        required=True,
        type=_cli_date,
        metavar="YYYY-MM-DD",
        help="UTC calendar day (YYYY-MM-DD).",
    )
    pv.add_argument(
        "-o",
        "--output",
        metavar="PATH",
        help="Write HTML to this file instead of stdout (file is only written on success).",
    )
    pv.set_defaults(handler=_cmd_preview_digest)

    args = parser.parse_args(argv)

    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    return handler(args)


def _cmd_show_config(_args: argparse.Namespace) -> int:
    try:
        settings = load_settings()
    except ValidationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1
    print(format_gmail_config_summary(settings), end="")
    return 0


def _cmd_run_daily(_args: argparse.Namespace) -> int:
    try:
        settings = load_settings()
    except ValidationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    if not settings.digest_recipient_email or not settings.digest_recipient_email.strip():
        print("DIGEST_RECIPIENT_EMAIL is required for run-daily.", file=sys.stderr)
        return 1
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        print("OPENAI_API_KEY is required for run-daily.", file=sys.stderr)
        return 1

    repo = StateRepository(settings.db_path, max_email_retries=settings.max_email_retries)
    try:
        client = build_gmail_client(settings)
        fetcher = GmailFetcher(
            client,
            senders=list(settings.newsletter_senders),
            lookback_days=settings.gmail_lookback_days,
        )
        for msg in fetcher.fetch_recent():
            repo.upsert_email(msg.to_email_input())

        llm = OpenAIProvider(
            api_key=settings.openai_api_key,
            router_model=settings.router_model,
            processor_model=settings.processor_model,
        )
        agent = DailyDigestAgent(
            repo=repo,
            run_lock=build_run_lock(settings),
            fetcher=fetcher,
            router_agent=RouterAgent(llm, model=llm.router_model),
            technology_agent=TechnologyProcessorAgent(llm, model=llm.processor_model),
            radar_agent=RadarProcessorAgent(llm, model=llm.processor_model),
            leadership_agent=LeadershipProcessorAgent(llm, model=llm.processor_model),
            noise_agent=NoiseProcessorAgent(llm, model=llm.processor_model),
            composer=DigestComposer(),
            quality_gate=DigestQualityGateAgent(),
            labeler=GmailLabeler(client),
            sender=GmailSender(client, sender="me"),
            digest_to=settings.digest_recipient_email.strip(),
            max_quality_gate_attempts=settings.max_quality_gate_attempts,
        )
        completed = agent.run_daily()
        if not completed:
            print("Another run holds the lock; skipping.", file=sys.stderr)
            return 1
        return 0
    finally:
        repo.close()


def _cmd_preview_digest(args: argparse.Namespace) -> int:
    try:
        settings = load_settings()
    except ValidationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    repo = StateRepository(settings.db_path, max_email_retries=settings.max_email_retries)
    try:
        row = repo.fetch_latest_digest_for_utc_calendar_day(args.date)
        if row is None:
            print(f"No digest found for UTC date {args.date.isoformat()}.", file=sys.stderr)
            return 1
        body = row.body_html
        if body is None or not str(body).strip():
            print(
                f"Digest id={row.digest_id} status={row.status!r} has no preview HTML.",
                file=sys.stderr,
            )
            return 1

        html_out = str(body)
        out_path: Path | None = args.output
        if out_path is not None:
            out_path.write_text(html_out, encoding="utf-8")
        else:
            sys.stdout.write(html_out)
        return 0
    finally:
        repo.close()


if __name__ == "__main__":
    sys.exit(main())
