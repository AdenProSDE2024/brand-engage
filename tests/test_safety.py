import ast
import json
from pathlib import Path

import pytest

from brand_engage.http_get import HttpGet, interpret_http_error
from brand_engage.safety import SafetyError, assert_llm_url, assert_slack_webhook, assert_x_read_url
from brand_engage.slack_delivery import send_digest

PACKAGE = Path(__file__).resolve().parents[1] / "brand_engage"

BANNED_SNIPPETS = (
    "/likes",
    "/following",
    "/retweets",
    "dm_conversations",
    "direct_messages",
    "api.linkedin.com",
    "search/all",
    "next_token",
    "statuses/update",
    "friendships/create",
    "/2/users/",
)


def test_x_client_allows_only_recent_search_over_https():
    assert_x_read_url("https://api.x.com/2/tweets/search/recent")
    for url in (
        "http://api.x.com/2/tweets/search/recent",
        "https://api.twitter.com/2/tweets/search/recent",
        "https://api.x.com/2/tweets",
        "https://api.x.com/2/users/123/likes",
        "https://api.x.com/2/tweets/search/all",
        "https://user:pass@api.x.com/2/tweets/search/recent",
    ):
        with pytest.raises(SafetyError):
            assert_x_read_url(url)


def test_llm_url_refuses_social_hosts_and_odd_paths():
    assert_llm_url("https://api.openai.com/v1/chat/completions")
    assert_llm_url("https://api.anthropic.com/v1/messages")
    for url in (
        "https://api.x.com/2/tweets/search/recent",
        "https://api.twitter.com/2/tweets",
        "https://api.linkedin.com/v2/ugcPosts",
        "https://hooks.slack.com/services/T00/B00/abc",
        "https://evil.example/v1/admin",
        "http://api.openai.com/v1/chat/completions",
        "https://api.openai.com/v1/chat/completions?api_key=sk-secret",
    ):
        with pytest.raises(SafetyError):
            assert_llm_url(url)


def test_slack_webhook_shape_is_strict():
    assert_slack_webhook("https://hooks.slack.com/services/T000/B000/abcdefghijklmnopqrstuvwxyz")
    for url in (
        "https://hooks.slack.com/services/not-a-webhook",
        "https://evil.example/services/T000/B000/abc",
        "http://hooks.slack.com/services/T000/B000/abc",
        "https://api.x.com/2/tweets",
    ):
        with pytest.raises(SafetyError):
            assert_slack_webhook(url)


def test_http_get_sends_get_and_refuses_other_paths():
    seen = {}

    class Response:
        def read(self):
            return b'{"data":[]}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def opener(request, timeout):
        seen["method"] = request.get_method()
        seen["url"] = request.full_url
        seen["auth"] = request.get_header("Authorization")
        return Response()

    client = HttpGet(opener=opener)
    payload = client.get_json(
        "https://api.x.com/2/tweets/search/recent",
        {"query": "from:swyx"},
        {"Authorization": "Bearer secret-token"},
    )
    assert payload == {"data": []}
    assert seen["method"] == "GET"
    assert seen["url"].startswith("https://api.x.com/2/tweets/search/recent?")
    assert "from%3Aswyx" in seen["url"] or "from:swyx" in seen["url"]
    assert seen["auth"] == "Bearer secret-token"
    assert not hasattr(HttpGet, "post")

    def fail_opener(request, timeout):
        raise AssertionError("network")

    with pytest.raises(SafetyError):
        HttpGet(opener=fail_opener).get_json(
            "https://api.x.com/2/tweets",
            {},
            {},
        )


def test_status_codes_do_not_look_like_write_retries():
    assert type(interpret_http_error(429, "")).__name__ == "RateLimitError"
    assert type(interpret_http_error(401, "")).__name__ == "AuthError"
    assert type(interpret_http_error(402, "")).__name__ == "AuthError"
    message = str(interpret_http_error(400, "bad query Bearer abc sk-live"))
    assert "abc" not in message
    assert "sk-live" not in message


def test_slack_send_is_a_text_post_to_the_webhook_only():
    seen = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def transport(request, timeout):
        seen["method"] = request.get_method()
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data.decode())
        return Response()

    send_digest(
        "https://hooks.slack.com/services/T000/B000/abc",
        "hello",
        transport=transport,
    )
    assert seen["method"] == "POST"
    assert seen["body"] == {"text": "hello"}
    with pytest.raises(SafetyError):
        send_digest("https://api.x.com/2/tweets", "nope", transport=transport)


def test_source_has_no_write_endpoints_and_only_two_post_callers():
    post_files = set()
    for path in PACKAGE.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for snippet in BANNED_SNIPPETS:
            # safety.py names the hosts it refuses. That list is the blocklist.
            if path.name == "safety.py" and snippet == "api.linkedin.com":
                continue
            assert snippet not in source, f"{path.name} contains {snippet}"
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "method" and isinstance(keyword.value, ast.Constant):
                    if keyword.value.value == "POST":
                        post_files.add(path.name)
                    else:
                        assert keyword.value.value == "GET"
    assert post_files == {"draft.py", "slack_delivery.py"}
