import textwrap
from datetime import datetime, timezone
from pathlib import Path

from brand_engage.config import load_settings, load_targets, repo_root
from brand_engage.linkedin_source import load_inbox, parse_inbox
from brand_engage.x_source import (
    ensure_filters,
    fetch_posts,
    parse_search_payload,
    plan_queries,
)
from brand_engage.http_get import RateLimitError

ROOT = repo_root()
NOW = datetime(2026, 11, 23, 15, 0, tzinfo=timezone.utc)


def test_seed_list_is_unconfirmed_and_queries_stay_inside_the_cap():
    settings = load_settings(ROOT / "config" / "settings.yaml")
    targets = load_targets(ROOT / "config" / "targets.yaml")
    enabled = [account for account in targets.accounts if account.enabled]
    assert settings.commit_digest is False
    assert len(enabled) >= 20
    assert all(account.confirmed is False for account in targets.accounts)
    assert any(account.handle.startswith("TODO") for account in targets.accounts)
    assert all(not account.enabled for account in targets.accounts if account.handle.startswith("TODO"))

    queries = plan_queries(targets.accounts, targets.topics, settings)
    assert 1 <= len(queries) <= settings.max_search_requests
    assert any(source == "accounts" for _, source in queries)
    assert any(source == "topic" for _, source in queries)
    for query, _source in queries:
        assert len(query) <= 512
        assert "-is:retweet" in query
        assert "-is:reply" in query
        assert "-from:AdenYCantU" in query
        assert "-from:Subliminal_Labs" in query
        assert "TODO" not in query


def test_parse_search_payload_reads_metrics_and_reply_flags():
    payload = {
        "data": [
            {
                "id": "50",
                "author_id": "7",
                "created_at": "2026-11-23T14:00:00.000Z",
                "lang": "en",
                "text": "hello",
                "in_reply_to_user_id": "9",
                "public_metrics": {"like_count": 3, "reply_count": 1, "retweet_count": 4, "quote_count": 2},
            }
        ],
        "includes": {
            "users": [
                {
                    "id": "7",
                    "username": "swyx",
                    "name": "Shawn",
                    "description": "AI engineering",
                    "public_metrics": {"followers_count": 10},
                }
            ]
        },
    }
    posts = parse_search_payload(payload, source="accounts")
    assert len(posts) == 1
    post = posts[0]
    assert post.is_reply is True
    assert post.author_handle == "swyx"
    assert post.author_followers == 10
    assert post.repost_count == 4
    assert post.url == "https://x.com/swyx/status/50"


def test_fetch_stops_on_rate_limit_without_a_retry_loop():
    class FakeClient:
        def __init__(self):
            self.calls = 0

        def search_recent(self, query, *, max_results, start_time):
            self.calls += 1
            if self.calls == 2:
                raise RateLimitError("slow down")
            return {"data": [], "includes": {"users": []}}

    client = FakeClient()
    settings = load_settings()
    posts, notes = fetch_posts(
        client,
        [("from:swyx", "accounts"), ("from:karpathy", "accounts")],
        now=NOW,
        settings=settings,
    )
    assert posts == []
    assert client.calls == 2
    assert "rate limit" in notes[0].lower()
    assert "start_time" not in notes[0]


def test_start_time_is_the_freshness_window():
    from brand_engage.rank import start_time_param

    stamp = start_time_param(NOW, 6)
    assert stamp == "2026-11-23T09:00:00Z"


def test_topic_query_gets_the_same_exclusions_as_account_search():
    settings = load_settings()
    query = ensure_filters("AI agents", settings)
    assert query.startswith("AI agents")
    assert "-is:retweet" in query
    assert "-from:AdenYCantU" in query


def test_real_inbox_template_is_empty_and_a_paste_parses():
    posts, notes = load_inbox(ROOT / "linkedin_inbox.md", now=NOW)
    assert posts == []
    assert notes == []
    pasted, extra = parse_inbox(
            textwrap.dedent(
                """
                ## post
                url: https://www.linkedin.com/feed/update/urn:li:activity:42
                author: Example Operator
                why: Large audience
                text: |
                  The team still does it in a spreadsheet.
                ## post
                url: https://x.com/someone/status/1
                author: Nope
                why: Wrong site
                text: hello
                ## post
                url: https://www.linkedin.com/feed/update/EXAMPLE
                author: Skip
                why: sample
                text: ignore me
                """
            ),
            now=NOW,
        )
    assert len(pasted) == 1
    assert pasted[0].author_name == "Example Operator"
    assert "spreadsheet" in pasted[0].text
    assert extra == ["Skipped a pasted block because the URL is not a LinkedIn link."]


def test_fixture_search_dedupes_a_post_that_appears_twice():
    import json

    raw = json.loads((ROOT / "fixtures" / "x_search.json").read_text())
    ids = []
    for entry in raw["responses"]:
        for post in parse_search_payload(entry["payload"], source=entry["source"]):
            ids.append(post.id)
    assert ids.count("1001") == 2
