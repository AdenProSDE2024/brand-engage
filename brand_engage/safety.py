"""Guards that keep network calls inside the reads this tool is allowed to make.

X and LinkedIn writes are refused here, before any socket opens. The LLM and the
Slack webhook are the only POST callers, and each one refuses social hosts.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

SEARCH_PATH = "/2/tweets/search/recent"
X_HOST = "api.x.com"

SOCIAL_HOSTS = {
    "api.x.com",
    "x.com",
    "www.x.com",
    "mobile.x.com",
    "api.twitter.com",
    "twitter.com",
    "www.twitter.com",
    "mobile.twitter.com",
    "api.linkedin.com",
    "linkedin.com",
    "www.linkedin.com",
    "hooks.slack.com",
}

SLACK_WEBHOOK = re.compile(
    r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+"
)


class SafetyError(RuntimeError):
    """A call tried to leave the read-only, drafts-only boundary."""


def assert_x_read_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        raise SafetyError("X reads must use https.")
    if host != X_HOST:
        raise SafetyError("X client refuses any host other than api.x.com.")
    if parsed.path != SEARCH_PATH:
        raise SafetyError("X client only calls recent search.")
    if parsed.username or parsed.password:
        raise SafetyError("Refusing credentials embedded in an X URL.")
    if parsed.fragment:
        raise SafetyError("Refusing an X URL with a fragment.")


def assert_llm_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        raise SafetyError("LLM calls must use https.")
    if _is_social_host(host):
        raise SafetyError("LLM client refuses X, Twitter, LinkedIn, and Slack hosts.")
    if any(token in url.lower() for token in ("api_key=", "apikey=", "key=", "token=")):
        raise SafetyError("Refusing an API key placed in an LLM URL.")
    allowed = parsed.path.endswith("/chat/completions") or parsed.path.endswith("/messages")
    if not allowed:
        raise SafetyError("LLM client only calls chat completions or messages.")


def assert_slack_webhook(url: str) -> None:
    if not SLACK_WEBHOOK.fullmatch(url or ""):
        raise SafetyError(
            "Slack delivery only posts to an https://hooks.slack.com/services/... incoming webhook."
        )


def _is_social_host(host: str) -> bool:
    if host in SOCIAL_HOSTS:
        return True
    return (
        host.endswith(".x.com")
        or host.endswith(".twitter.com")
        or "linkedin" in host
        or host.endswith(".slack.com")
    )


def public_error(exc: BaseException) -> str:
    """Strip secrets from an exception before it reaches a log."""
    text = str(exc)
    text = re.sub(r"https://hooks\.slack\.com/\S+", "https://hooks.slack.com/[redacted]", text)
    text = re.sub(r"Bearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [redacted]", text)
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-[redacted]", text)
    text = re.sub(r"(?i)(api[_-]?key|token|authorization)['\"=: ]+\S+", r"\1 [redacted]", text)
    return text[:400]
