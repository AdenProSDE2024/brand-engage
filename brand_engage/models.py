"""Shared records. Nothing in here talks to the network."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def parse_time(value: str) -> datetime:
    text = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass
class Post:
    platform: str
    id: str
    url: str
    author_handle: str
    author_name: str
    text: str
    created_at: datetime
    author_followers: int = 0
    author_why: str = ""
    author_bio: str = ""
    like_count: int = 0
    reply_count: int = 0
    repost_count: int = 0
    quote_count: int = 0
    is_reply: bool = False
    is_repost: bool = False
    lang: str = ""
    on_list: bool = False
    topic_hits: tuple[str, ...] = ()
    source: str = ""

    @property
    def engagement(self) -> int:
        return (
            self.like_count
            + 3 * self.reply_count
            + 2 * self.repost_count
            + 2 * self.quote_count
        )


@dataclass
class Account:
    handle: str
    why: str
    confirmed: bool = False
    enabled: bool = True


@dataclass
class TopicQuery:
    query: str
    why: str
    enabled: bool = True


@dataclass
class LinkedInProfile:
    name: str
    url: str
    why: str
    enabled: bool = True


@dataclass
class Targets:
    accounts: list[Account]
    topics: list[TopicQuery]
    linkedin_profiles: list[LinkedInProfile]
    topic_terms: list[str]


@dataclass
class Settings:
    commit_digest: bool = False
    timezone: str = "America/Los_Angeles"
    max_age_hours: float = 6
    max_items: int = 8
    min_items: int = 6
    original_posts_per_day: int = 1
    max_linkedin_comments: int = 2
    max_posts_per_author: int = 1
    max_search_requests: int = 4
    max_results_per_request: int = 10
    your_handle: str = "AdenYCantU"
    company_handle: str = "Subliminal_Labs"
    your_follower_count: int = 1000
    min_follower_ratio: float = 10
    min_author_followers: int = 5000
    saturated_reply_count: int = 40
    buried_engagement: int = 1500
    lang: str = "en"
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str = "https://api.openai.com/v1"


@dataclass
class ScoredPost:
    post: Post
    score: float
    why_now: str
    age_hours: float


@dataclass
class RankResult:
    ranked: list[ScoredPost]
    skipped: dict[str, int] = field(default_factory=dict)


@dataclass
class DraftText:
    text: str
    warnings: list[str]


@dataclass
class DigestItem:
    kind_label: str
    platform: str
    kind: str
    author_line: str
    author: str
    link: str
    why_they_matter: str
    why_now: str
    their_post: str | None
    draft: str
    warnings: list[str]
    score: float


@dataclass
class ProfileReminder:
    name: str
    url: str
    why: str


@dataclass
class Digest:
    title: str
    dry_run: bool
    preamble: list[str]
    items: list[DigestItem]
    profiles: list[ProfileReminder]
    skipped_line: str
    footer: list[str]
