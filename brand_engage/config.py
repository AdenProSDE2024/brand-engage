"""Load the two files Aden edits: knobs, and who to watch."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from brand_engage.models import (
    Account,
    LinkedInProfile,
    Settings,
    Targets,
    TopicQuery,
)

HANDLE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
# A single recent-search page is 10 to 100 posts. More requests than this
# would quietly spend real money on a typo.
MAX_SEARCH_REQUESTS_CEILING = 8
MAX_ITEMS_CEILING = 8


class ConfigError(ValueError):
    pass


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_settings(path: Path | None = None) -> Settings:
    path = path or repo_root() / "config" / "settings.yaml"
    raw = _read_yaml(path)
    settings = Settings(
        commit_digest=bool(raw.get("commit_digest", False)),
        timezone=str(raw.get("timezone", "America/Los_Angeles")),
        max_age_hours=float(raw.get("max_age_hours", 6)),
        max_items=int(raw.get("max_items", 8)),
        min_items=int(raw.get("min_items", 6)),
        original_posts_per_day=int(raw.get("original_posts_per_day", 1)),
        max_linkedin_comments=int(raw.get("max_linkedin_comments", 2)),
        max_posts_per_author=int(raw.get("max_posts_per_author", 1)),
        max_search_requests=int(raw.get("max_search_requests", 4)),
        max_results_per_request=int(raw.get("max_results_per_request", 10)),
        your_handle=str(raw.get("your_handle", "AdenYCantU")).lstrip("@"),
        company_handle=str(raw.get("company_handle", "Subliminal_Labs")).lstrip("@"),
        your_follower_count=int(raw.get("your_follower_count", 1000)),
        min_follower_ratio=float(raw.get("min_follower_ratio", 10)),
        min_author_followers=int(raw.get("min_author_followers", 5000)),
        saturated_reply_count=int(raw.get("saturated_reply_count", 40)),
        buried_engagement=int(raw.get("buried_engagement", 1500)),
        lang=str(raw.get("lang", "en")),
        llm_provider=str(_llm(raw).get("provider", "openai")),
        llm_model=str(_llm(raw).get("model", "gpt-4o-mini")),
        llm_base_url=str(_llm(raw).get("base_url", "https://api.openai.com/v1")),
    )
    settings.llm_provider = _env("LLM_PROVIDER", settings.llm_provider).lower()
    settings.llm_model = _env("LLM_MODEL", settings.llm_model)
    settings.llm_base_url = _env("LLM_BASE_URL", settings.llm_base_url).rstrip("/")
    _clamp(settings)
    if settings.llm_provider not in {"openai", "anthropic"}:
        raise ConfigError("llm.provider must be openai or anthropic.")
    if not HANDLE.match(settings.your_handle):
        raise ConfigError("your_handle is not a valid X handle.")
    if not HANDLE.match(settings.company_handle):
        raise ConfigError("company_handle is not a valid X handle.")
    return settings


def load_targets(path: Path | None = None) -> Targets:
    path = path or repo_root() / "config" / "targets.yaml"
    raw = _read_yaml(path)
    accounts: list[Account] = []
    for entry in raw.get("accounts") or []:
        handle = str(entry.get("handle", "")).strip().lstrip("@")
        why = str(entry.get("why", "")).strip()
        enabled = bool(entry.get("enabled", True))
        if handle.lower().startswith("todo"):
            enabled = False
        if enabled and not HANDLE.match(handle):
            raise ConfigError(f"Invalid X handle: {handle}")
        if enabled and not why:
            raise ConfigError(f"Enabled account @{handle} needs a why.")
        accounts.append(
            Account(
                handle=handle,
                why=why,
                confirmed=bool(entry.get("confirmed", False)),
                enabled=enabled,
            )
        )
    topics: list[TopicQuery] = []
    for entry in raw.get("topics") or []:
        topics.append(
            TopicQuery(
                query=str(entry.get("query", "")).strip(),
                why=str(entry.get("why", "")).strip(),
                enabled=bool(entry.get("enabled", True)),
            )
        )
    profiles: list[LinkedInProfile] = []
    for entry in raw.get("linkedin_profiles") or []:
        profiles.append(
            LinkedInProfile(
                name=str(entry.get("name", "")).strip(),
                url=str(entry.get("url", "")).strip(),
                why=str(entry.get("why", "")).strip(),
                enabled=bool(entry.get("enabled", True)),
            )
        )
    terms = [str(term).strip() for term in (raw.get("topic_terms") or []) if str(term).strip()]
    if not terms:
        raise ConfigError("topic_terms is empty. Add the subjects Aden can speak to.")
    return Targets(
        accounts=accounts,
        topics=topics,
        linkedin_profiles=profiles,
        topic_terms=terms,
    )


def _llm(raw: dict) -> dict:
    value = raw.get("llm") or {}
    if not isinstance(value, dict):
        raise ConfigError("llm must be a mapping.")
    return value


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"Missing config file: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ConfigError(f"{path} must be a YAML mapping.")
    return loaded


def _env(name: str, current: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or current


def _clamp(settings: Settings) -> None:
    if settings.max_items > MAX_ITEMS_CEILING:
        settings.max_items = MAX_ITEMS_CEILING
    if settings.max_items < 1:
        settings.max_items = 1
    if settings.min_items > settings.max_items:
        settings.min_items = settings.max_items
    if settings.min_items < 1:
        settings.min_items = 1
    if settings.max_search_requests > MAX_SEARCH_REQUESTS_CEILING:
        settings.max_search_requests = MAX_SEARCH_REQUESTS_CEILING
    if settings.max_search_requests < 1:
        settings.max_search_requests = 1
    if settings.max_results_per_request < 10:
        settings.max_results_per_request = 10
    if settings.max_results_per_request > 100:
        settings.max_results_per_request = 100
    if settings.max_age_hours <= 0:
        settings.max_age_hours = 6
    if settings.original_posts_per_day < 0:
        settings.original_posts_per_day = 0
    if settings.original_posts_per_day > 2:
        settings.original_posts_per_day = 2
    if settings.max_linkedin_comments < 0:
        settings.max_linkedin_comments = 0
    if settings.max_posts_per_author < 1:
        settings.max_posts_per_author = 1
