"""Command line. Dry-run never reads API keys and never calls the network."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from brand_engage.config import ConfigError, load_settings, load_targets, repo_root
from brand_engage.digest import file_stamp, render
from brand_engage.draft import FixtureDrafter, LlmDrafter
from brand_engage.http_get import AuthError
from brand_engage.linkedin_source import load_inbox
from brand_engage.logbook import rows_from_digest, upsert
from brand_engage.models import parse_time
from brand_engage.pipeline import assemble, load_notes
from brand_engage.safety import SafetyError, public_error
from brand_engage.slack_delivery import send_digest
from brand_engage.x_source import XReadClient, fetch_posts, parse_search_payload, plan_queries


def main() -> None:
    sys.exit(run(sys.argv[1:]))


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="brand-engage",
        description="Draft a daily X and LinkedIn engagement list. Never posts.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Use fixtures. No keys, no network.")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--targets", type=Path, default=None)
    parser.add_argument("--inbox", type=Path, default=None)
    parser.add_argument("--notes", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--log", type=Path, default=None)
    parser.add_argument("--now", default=None, help="ISO timestamp. Tests and fixtures use this.")
    args = parser.parse_args(argv)

    try:
        settings = load_settings(args.config)
        targets = load_targets(args.targets)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    root = repo_root()
    try:
        if args.dry_run:
            now, posts, fetch_notes = _load_fixture(root / "fixtures" / "x_search.json")
            if args.now:
                now = parse_time(args.now)
            inbox_path = args.inbox or root / "fixtures" / "linkedin_inbox.md"
            notes_path = args.notes or root / "fixtures" / "notes"
            drafter = FixtureDrafter.load(root / "fixtures" / "drafts.json")
            linkedin, inbox_notes = load_inbox(inbox_path, now=now)
            notes = load_notes(notes_path)
            digest = assemble(
                posts=posts,
                linkedin_posts=linkedin,
                notes=notes,
                targets=targets,
                settings=settings,
                drafter=drafter,
                now=now,
                dry_run=True,
                extra_notes=fetch_notes + inbox_notes,
            )
        else:
            now = parse_time(args.now) if args.now else datetime.now(timezone.utc)
            token = os.environ.get("X_BEARER_TOKEN", "").strip()
            api_key = os.environ.get("LLM_API_KEY", "").strip()
            if not token:
                print("Missing X_BEARER_TOKEN.", file=sys.stderr)
                return 1
            if not api_key:
                print("Missing LLM_API_KEY.", file=sys.stderr)
                return 1
            inbox_path = args.inbox or root / "linkedin_inbox.md"
            notes_path = args.notes or root / "notes"
            client = XReadClient(token)
            queries = plan_queries(targets.accounts, targets.topics, settings)
            posts, fetch_notes = fetch_posts(client, queries, now=now, settings=settings)
            linkedin, inbox_notes = load_inbox(inbox_path, now=now)
            notes = load_notes(notes_path)
            drafter = LlmDrafter(settings, api_key)
            digest = assemble(
                posts=posts,
                linkedin_posts=linkedin,
                notes=notes,
                targets=targets,
                settings=settings,
                drafter=drafter,
                now=now,
                dry_run=False,
                extra_notes=fetch_notes + inbox_notes,
            )
    except (AuthError, SafetyError, RuntimeError, ValueError) as exc:
        print(public_error(exc), file=sys.stderr)
        return 1

    text = render(digest)
    day = file_stamp(now, settings.timezone)
    out = args.out or root / "digests" / f"{day}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")

    log_path = args.log
    if log_path is None and not args.dry_run:
        log_path = root / "log.csv"
    if log_path is not None:
        upsert(log_path, rows_from_digest(digest, day))

    _emit(text, settings=settings, dry_run=args.dry_run, out=out)
    return _maybe_slack(text, settings=settings, dry_run=args.dry_run)


def _load_fixture(path: Path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    now = parse_time(raw["now"])
    posts = []
    seen: set[str] = set()
    for entry in raw.get("responses") or []:
        source = str(entry.get("source") or "fixture")
        for post in parse_search_payload(entry.get("payload") or {}, source=source):
            if post.id in seen:
                continue
            seen.add(post.id)
            posts.append(post)
    return now, posts, []


def _emit(text: str, *, settings, dry_run: bool, out: Path) -> None:
    print(f"Wrote {out}", file=sys.stderr)
    if _show_body(settings, dry_run):
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
        return
    print(
        "Drafts were not printed. A public Actions log would publish them.",
        file=sys.stderr,
    )


def _show_body(settings, dry_run: bool) -> bool:
    if dry_run or settings.commit_digest:
        return True
    return os.environ.get("GITHUB_ACTIONS") != "true"


def _maybe_slack(text: str, *, settings, dry_run: bool) -> int:
    if dry_run:
        return 0
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook:
        if os.environ.get("GITHUB_ACTIONS") == "true" and not settings.commit_digest:
            print(
                "No SLACK_WEBHOOK_URL. Refusing to leave the digest only in a public Actions log.",
                file=sys.stderr,
            )
            return 1
        print("SLACK_WEBHOOK_URL is not set. Digest was written locally.", file=sys.stderr)
        return 0
    try:
        send_digest(webhook, text)
    except (SafetyError, RuntimeError) as exc:
        print(public_error(exc), file=sys.stderr)
        return 1
    print("Slack: sent.", file=sys.stderr)
    return 0
