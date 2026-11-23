"""Filter and rank posts by reply-window value.

Reach is a light touch. The follower floor already requires an account much
bigger than Aden, so a famous account should not beat a better window.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone

from brand_engage.models import Post, RankResult, ScoredPost, Settings

SKIP_LABELS = {
    "too_old": ("too old", "too old"),
    "too_small": ("too small", "too small"),
    "reply": ("reply", "replies"),
    "repost": ("repost", "reposts"),
    "own_account": ("from your accounts", "from your accounts"),
    "off_topic": ("off topic", "off topic"),
    "not_english": ("not English", "not English"),
    "missing_author": ("missing author", "missing authors"),
    "clock": ("bad timestamp", "bad timestamps"),
}


def topic_hits(text: str, terms: list[str]) -> tuple[str, ...]:
    hay = text.lower()
    occupied = [False] * len(hay)
    found: list[str] = []
    ordered = sorted(
        {term.strip() for term in terms if term.strip()},
        key=lambda term: (-len(term), term.lower()),
    )
    for term in ordered:
        needle = term.lower()
        if needle[0].isalnum() and needle[-1].isalnum():
            pattern = re.compile(rf"\b{re.escape(needle)}\b")
        else:
            pattern = re.compile(re.escape(needle))
        for match in pattern.finditer(hay):
            start, end = match.span()
            if any(occupied[start:end]):
                continue
            for index in range(start, end):
                occupied[index] = True
            found.append(term)
            break
    return tuple(found)


def annotate_topics(posts: list[Post], terms: list[str]) -> None:
    for post in posts:
        post.topic_hits = topic_hits(post.text, terms)


def rank_posts(posts: list[Post], now: datetime, settings: Settings) -> RankResult:
    skipped: dict[str, int] = {}
    scored: list[ScoredPost] = []
    for post in posts:
        reason = _reject_reason(post, now, settings)
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        age = _age_hours(post, now)
        value = _score(post, age, settings)
        scored.append(
            ScoredPost(
                post=post,
                score=value,
                why_now=explain_why_now(post, age, settings),
                age_hours=age,
            )
        )
    scored.sort(key=lambda item: item.score, reverse=True)
    return RankResult(ranked=scored, skipped=skipped)


def explain_why_now(post: Post, age_hours: float, settings: Settings) -> str:
    minutes = max(1, int(round(age_hours * 60)))
    if minutes < 90:
        age = f"{minutes} minutes old"
    else:
        age = f"{age_hours:.1f} hours old"
    parts = [age, f"{post.like_count} likes, {post.reply_count} replies"]
    if post.reply_count >= settings.saturated_reply_count or post.engagement >= settings.buried_engagement:
        parts.append("The thread is already crowded, so this is a weak window")
    elif age_hours < 2 and (post.like_count + post.reply_count) >= 8:
        parts.append("Early, and it is starting to move")
    elif age_hours < 2:
        parts.append("Early, before the thread fills up")
    else:
        parts.append("Still inside the window, so do it before the fresher ones go cold")
    if post.topic_hits:
        shown = ", ".join(post.topic_hits[:3])
        parts.append(f"Topic: {shown}")
    return ". ".join(parts) + "."


def skipped_line(skipped: dict[str, int]) -> str:
    if not skipped:
        return ""
    bits = []
    for reason, count in sorted(skipped.items(), key=lambda item: (-item[1], item[0])):
        singular, plural = SKIP_LABELS.get(reason, (reason, reason))
        label = singular if count == 1 else plural
        bits.append(f"{count} {label}")
    total = sum(skipped.values())
    return f"Skipped {total}: " + ", ".join(bits) + "."


def allocate(n_x: int, n_linkedin: int, n_originals_available: int, settings: Settings) -> tuple[int, int, int]:
    """How many X replies, LinkedIn comments, and original posts to draft."""
    linkedin = min(n_linkedin, settings.max_linkedin_comments, settings.max_items)
    originals = min(settings.original_posts_per_day, n_originals_available, 2)
    x_count = min(n_x, max(0, settings.max_items - linkedin - originals))
    total = x_count + linkedin + originals
    if (
        total < settings.min_items
        and n_originals_available > originals
        and originals < 2
        and total + 1 <= settings.max_items
    ):
        originals += 1
    while x_count + linkedin + originals > settings.max_items:
        if x_count > 0:
            x_count -= 1
        elif originals > 0:
            originals -= 1
        elif linkedin > 0:
            linkedin -= 1
        else:
            break
    return x_count, linkedin, originals


def pick_diverse(ranked: list[ScoredPost], limit: int, per_author: int) -> list[ScoredPost]:
    """Prefer different authors, then backfill if the day would otherwise be short."""
    if limit <= 0:
        return []
    picked: list[ScoredPost] = []
    deferred: list[ScoredPost] = []
    counts: dict[str, int] = {}
    for item in ranked:
        handle = item.post.author_handle.lower()
        if counts.get(handle, 0) >= per_author:
            deferred.append(item)
            continue
        picked.append(item)
        counts[handle] = counts.get(handle, 0) + 1
        if len(picked) >= limit:
            return picked
    for item in deferred:
        if len(picked) >= limit:
            break
        picked.append(item)
    return picked


def follower_floor(settings: Settings) -> int:
    ratio_floor = int(settings.your_follower_count * settings.min_follower_ratio)
    return max(settings.min_author_followers, ratio_floor)


def _reject_reason(post: Post, now: datetime, settings: Settings) -> str | None:
    if post.platform != "x":
        return None
    if not post.author_handle:
        return "missing_author"
    excluded = {settings.your_handle.lower(), settings.company_handle.lower()}
    if post.author_handle.lower() in excluded:
        return "own_account"
    if post.is_repost:
        return "repost"
    if post.is_reply:
        return "reply"
    if post.lang and settings.lang and post.lang.lower() not in {settings.lang.lower(), "und", "qme"}:
        return "not_english"
    age = _age_hours(post, now)
    if age < -0.1:
        return "clock"
    if age > settings.max_age_hours:
        return "too_old"
    if post.author_followers < follower_floor(settings):
        return "too_small"
    if not post.topic_hits:
        return "off_topic"
    return None


def _age_hours(post: Post, now: datetime) -> float:
    created = post.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (now - created).total_seconds() / 3600


def _score(post: Post, age_hours: float, settings: Settings) -> float:
    age_hours = max(age_hours, 1 / 60)
    early = max(0.0, (settings.max_age_hours - age_hours) / settings.max_age_hours)
    velocity = post.engagement / age_hours
    if post.engagement == 0 and age_hours > 1:
        rising = 0.2
    elif post.engagement == 0:
        rising = 0.5
    else:
        rising = 1.0 + min(2.0, math.log1p(velocity) / 3.0)
    topics = float(min(3, len(post.topic_hits)))
    reach = math.log10(max(post.author_followers, 10))
    raw = early * 4.0 + rising * 3.0 + topics * 2.0 + reach * 0.5
    if post.reply_count >= settings.saturated_reply_count:
        window = 0.25
    elif post.reply_count >= settings.saturated_reply_count / 2:
        window = 0.6
    else:
        window = 1.0
    if post.engagement >= settings.buried_engagement:
        window *= 0.35
    return raw * window


def start_time_param(now: datetime, max_age_hours: float) -> str:
    stamp = now - timedelta(hours=max_age_hours)
    return stamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
