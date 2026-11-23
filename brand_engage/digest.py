"""Phone-readable digest. One plain-text layout for the file and for Slack."""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from brand_engage.models import (
    Digest,
    DigestItem,
    DraftText,
    LinkedInProfile,
    Post,
    ProfileReminder,
    ScoredPost,
    Settings,
)

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def local_now(moment: datetime, timezone_name: str) -> datetime:
    try:
        zone = ZoneInfo(timezone_name)
    except Exception as exc:  # zoneinfo raises ZoneInfoNotFoundError, a subclass of KeyError
        raise RuntimeError(f"Unknown timezone {timezone_name}.") from exc
    return moment.astimezone(zone)


def file_stamp(moment: datetime, timezone_name: str) -> str:
    return local_now(moment, timezone_name).strftime("%Y-%m-%d")


def title_stamp(moment: datetime, timezone_name: str) -> str:
    local = local_now(moment, timezone_name)
    return f"{_WEEKDAYS[local.weekday()]} {_MONTHS[local.month - 1]} {local.day}"


def compact_followers(count: int) -> str:
    if count >= 1_000_000:
        value = count / 1_000_000
        text = f"{value:.1f}".rstrip("0").rstrip(".")
        return f"{text}M followers"
    if count >= 10_000:
        return f"{count / 1000:.0f}k followers"
    if count >= 1000:
        return f"{count / 1000:.1f}k followers"
    return f"{count} followers"


def why_they_matter(post: Post) -> str:
    if post.platform == "linkedin":
        why = post.author_why.strip() or "You pasted this post."
        if not why.endswith("."):
            why += "."
        return why
    if post.author_why:
        why = post.author_why.strip()
        if not why.endswith("."):
            why += "."
        return why
    bio = re.sub(r"\s+", " ", post.author_bio).strip()
    if len(bio) > 140:
        bio = bio[:137].rstrip() + "..."
    base = "Not on your saved list. Came in through a topic search."
    if bio:
        return f"{base} Bio: {bio}"
    return base


def build_digest(
    *,
    x_posts: list[ScoredPost],
    x_drafts: list[DraftText],
    linkedin_posts: list[Post],
    linkedin_drafts: list[DraftText],
    originals: list[DraftText],
    profiles: list[LinkedInProfile],
    skipped_line: str,
    notes: list[str],
    settings: Settings,
    now: datetime,
    dry_run: bool,
    short_day: bool,
) -> Digest:
    notes = list(notes)
    items: list[DigestItem] = []
    for scored, drafted in zip(x_posts, x_drafts):
        if not drafted.text:
            notes.append(f"Dropped @{scored.post.author_handle} because the draft was empty.")
            continue
        post = scored.post
        items.append(
            DigestItem(
                kind_label="Reply on X",
                platform="x",
                kind="reply",
                author_line=_author_line(post),
                author=f"@{post.author_handle}",
                link=post.url,
                why_they_matter=why_they_matter(post),
                why_now=scored.why_now,
                their_post=post.text,
                draft=drafted.text,
                warnings=list(drafted.warnings),
                score=scored.score,
            )
        )
    for post, drafted in zip(linkedin_posts, linkedin_drafts):
        if not drafted.text:
            notes.append(f"Dropped {post.author_name} because the draft was empty.")
            continue
        items.append(
            DigestItem(
                kind_label="Comment on LinkedIn",
                platform="linkedin",
                kind="comment",
                author_line=post.author_name,
                author=post.author_name,
                link=post.url,
                why_they_matter=why_they_matter(post),
                why_now="You pasted this today. Comment while it is still near the top of the feed.",
                their_post=post.text,
                draft=drafted.text,
                warnings=list(drafted.warnings),
                score=0,
            )
        )
    for drafted in originals:
        if not drafted.text:
            notes.append("Dropped an original post because the draft was empty.")
            continue
        items.append(
            DigestItem(
                kind_label="New post on X",
                platform="x",
                kind="original",
                author_line=f"@{settings.your_handle}",
                author=f"@{settings.your_handle}",
                link="",
                why_they_matter="Your account. This builds your point of view, not someone else's reach.",
                why_now="From your notes. Post it after the replies, or later today.",
                their_post=None,
                draft=drafted.text,
                warnings=list(drafted.warnings),
                score=0,
            )
        )
    count = len(items)
    when = title_stamp(now, settings.timezone)
    title = f"{when} · {count} item" if count == 1 else f"{when} · {count} items"
    preamble = []
    if dry_run:
        preamble.append("Dry run. Made-up posts. Do not post these.")
    else:
        preamble.append("Live list. You post these yourself. Nothing was sent.")
    preamble.append(f"For @{settings.your_handle}. Do not cross-post them to @{settings.company_handle}.")
    preamble.append("Do them in this order. Replies first, while the window is open. Your own posts are at the end.")
    if short_day:
        preamble.append(
            f"Short day. {count} cleared the bar. Do not force the list up to {settings.min_items}."
        )
    preamble.extend(notes)
    reminders = [
        ProfileReminder(name=profile.name, url=profile.url, why=profile.why)
        for profile in profiles
        if profile.enabled and profile.url
    ]
    footer = [
        "Mark used and result in log.csv after you post. That is the whole feedback loop for now."
    ]
    return Digest(
        title=title,
        dry_run=dry_run,
        preamble=preamble,
        items=items,
        profiles=reminders,
        skipped_line=skipped_line,
        footer=footer,
    )


def render(digest: Digest) -> str:
    lines = [f"# {digest.title}", ""]
    lines.extend(digest.preamble)
    lines.append("")
    if not digest.items:
        lines.append("Nothing cleared the bar today.")
        lines.append("")
    for number, item in enumerate(digest.items, start=1):
        lines.append(f"{number}. {item.kind_label}")
        lines.append(item.author_line)
        if item.link:
            lines.append(item.link)
        else:
            lines.append("New post. No link.")
        lines.append("")
        lines.append("Why they matter:")
        lines.append(item.why_they_matter)
        lines.append("")
        lines.append("Why now:")
        lines.append(item.why_now)
        lines.append("")
        if item.their_post:
            lines.append("Their post:")
            lines.append(_quote(item.their_post))
            lines.append("")
        lines.append("Draft:")
        lines.append(item.draft or "(no draft)")
        if item.warnings:
            lines.append("")
            lines.append("Edit before posting:")
            for warning in item.warnings:
                lines.append(f"- {warning}")
        lines.append("")
        lines.append("---")
        lines.append("")
    lines.append("Check these LinkedIn profiles")
    if digest.profiles:
        lines.append("No post was pasted for these. If one of them published, paste it into linkedin_inbox.md.")
        lines.append("")
        for profile in digest.profiles:
            lines.append(f"- {profile.name}. {profile.why}")
            lines.append(f"  {profile.url}")
    else:
        lines.append("None enabled. Add profiles in config/targets.yaml.")
    lines.append("")
    if digest.skipped_line:
        lines.append(digest.skipped_line)
        lines.append("")
    lines.extend(digest.footer)
    lines.append("")
    return "\n".join(lines)


def _author_line(post: Post) -> str:
    name = post.author_name
    if name and name.lower() != post.author_handle.lower():
        return f"@{post.author_handle} · {name} · {compact_followers(post.author_followers)}"
    return f"@{post.author_handle} · {compact_followers(post.author_followers)}"


def _quote(text: str, limit: int = 320) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    if len(flat) > limit:
        flat = flat[: limit - 3].rstrip() + "..."
    return "> " + flat
