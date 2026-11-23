"""Turn posts, pasted LinkedIn, and notes into one digest."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

from brand_engage.digest import build_digest
from brand_engage.models import Account, Digest, DraftText, Post, Settings, Targets
from brand_engage.rank import allocate, annotate_topics, pick_diverse, rank_posts, skipped_line


class Drafter(Protocol):
    def reply(self, post: Post, notes: str) -> DraftText: ...

    def comment(self, post: Post, notes: str) -> DraftText: ...

    def original(self, notes: str, index: int, already: list[str]) -> DraftText: ...


def load_notes(folder: Path) -> str:
    if not folder.exists():
        return ""
    parts: list[str] = []
    for path in sorted(folder.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        text = path.read_text(encoding="utf-8").strip()
        if text:
            parts.append(f"# {path.name}\n{text}")
    return "\n\n".join(parts)


def attach_accounts(posts: list[Post], accounts: list[Account]) -> None:
    by_handle = {account.handle.lower(): account for account in accounts if account.enabled}
    for post in posts:
        account = by_handle.get(post.author_handle.lower())
        if account:
            post.on_list = True
            post.author_why = account.why


def assemble(
    *,
    posts: list[Post],
    linkedin_posts: list[Post],
    notes: str,
    targets: Targets,
    settings: Settings,
    drafter: Drafter,
    now: datetime,
    dry_run: bool,
    extra_notes: list[str] | None = None,
) -> Digest:
    attach_accounts(posts, targets.accounts)
    annotate_topics(posts, targets.topic_terms)
    ranked = rank_posts(posts, now, settings)
    originals_available = 2 if notes.strip() else 0
    x_count, li_count, original_count = allocate(
        len(ranked.ranked),
        len(linkedin_posts),
        originals_available,
        settings,
    )
    chosen_x = pick_diverse(ranked.ranked, x_count, settings.max_posts_per_author)
    chosen_li = linkedin_posts[:li_count]
    x_drafts = [drafter.reply(item.post, notes) for item in chosen_x]
    li_drafts = [drafter.comment(post, notes) for post in chosen_li]
    originals: list[DraftText] = []
    used: list[str] = []
    for index in range(1, original_count + 1):
        drafted = drafter.original(notes, index, used)
        originals.append(drafted)
        if drafted.text:
            used.append(drafted.text)
    digest_notes = list(extra_notes or [])
    if originals_available == 0:
        digest_notes.append("No notes in notes/. Add a few lines to get an original post.")
    item_count = len(chosen_x) + len(chosen_li) + len(originals)
    profiles = [profile for profile in targets.linkedin_profiles if profile.enabled]
    line = skipped_line(ranked.skipped)
    held_back = len(ranked.ranked) - len(chosen_x)
    if held_back:
        extra = f"{held_back} other X posts cleared the bar and did not fit today."
        line = f"{line} {extra}" if line else extra
    return build_digest(
        x_posts=chosen_x,
        x_drafts=x_drafts,
        linkedin_posts=chosen_li,
        linkedin_drafts=li_drafts,
        originals=originals,
        profiles=profiles,
        skipped_line=line,
        notes=digest_notes,
        settings=settings,
        now=now,
        dry_run=dry_run,
        short_day=item_count < settings.min_items,
    )
