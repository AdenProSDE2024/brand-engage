import json

from brand_engage.draft import (
    SYSTEM_PROMPT,
    FixtureDrafter,
    LlmDrafter,
    clean_draft,
    draft_problems,
    post_json,
)
from brand_engage.models import Post, Settings
from brand_engage.safety import SafetyError
from datetime import datetime, timezone

import pytest


def test_system_prompt_carries_the_claims_rule():
    assert "for you" in SYSTEM_PROMPT
    assert "shadow" in SYSTEM_PROMPT
    assert "consultancy" in SYSTEM_PROMPT
    assert "do not invent numbers" in SYSTEM_PROMPT.lower()


def test_linter_catches_praise_claims_and_dashes():
    problems = draft_problems("Great post. We will build this for you — happy to help!", kind="reply")
    blob = " ".join(problems).lower()
    assert "great post" in blob
    assert "for you" in blob
    assert "dash" in blob
    assert draft_problems("The messy files are the job.", kind="reply") == []


def test_clean_draft_strips_wrapping_quotes_and_newlines():
    assert clean_draft('"Hello\nthere"') == "Hello there"


def test_llm_rewrites_once_when_the_draft_breaks_a_rule():
    calls = []

    def transport(url, body, headers):
        calls.append((url, body))
        if len(calls) == 1:
            return {"choices": [{"message": {"content": "Great post. We will build this for you."}}]}
        return {
            "choices": [
                {
                    "message": {
                        "content": "The exception is the job. A pilot on clean files will not change the roster."
                    }
                }
            ]
        }

    settings = Settings()
    drafter = LlmDrafter(settings, "sk-test", transport=transport)
    post = Post(
        platform="x",
        id="1",
        url="https://x.com/swyx/status/1",
        author_handle="swyx",
        author_name="Shawn",
        text="AI agents fail in operations.",
        created_at=datetime(2026, 11, 23, tzinfo=timezone.utc),
    )
    drafted = drafter.reply(post, "notes")
    assert len(calls) == 2
    assert calls[0][0] == "https://api.openai.com/v1/chat/completions"
    assert "failed these checks" in calls[1][1]["messages"][1]["content"]
    assert drafted.warnings == []
    assert "exception" in drafted.text.lower()
    assert calls[0][1]["messages"][0]["role"] == "system"


def test_llm_client_refuses_a_social_host_before_the_transport_runs():
    def transport(url, body, headers):
        raise AssertionError("network")

    settings = Settings(llm_base_url="https://api.x.com/v1")
    drafter = LlmDrafter(settings, "sk-test", transport=transport)
    with pytest.raises(SafetyError):
        drafter.reply(
            Post(
                platform="x",
                id="1",
                url="https://x.com/a/status/1",
                author_handle="a",
                author_name="A",
                text="text",
                created_at=datetime(2026, 11, 23, tzinfo=timezone.utc),
            ),
            "",
        )


def test_post_json_refuses_linkedin(monkeypatch):
    import urllib.request

    def explode(*args, **kwargs):
        raise AssertionError("network")

    monkeypatch.setattr(urllib.request, "urlopen", explode)
    with pytest.raises(SafetyError):
        post_json("https://api.linkedin.com/v2/ugcPosts", {}, {})


def test_anthropic_shape():
    calls = []

    def transport(url, body, headers):
        calls.append((url, body, headers))
        return {"content": [{"type": "text", "text": "The messy files are the job."}]}

    settings = Settings(llm_provider="anthropic", llm_model="claude-test", llm_base_url="https://api.anthropic.com")
    drafter = LlmDrafter(settings, "sk-ant-test", transport=transport)
    drafted = drafter.original("Record the week.", 1, [])
    assert calls[0][0] == "https://api.anthropic.com/v1/messages"
    assert calls[0][1]["system"] == SYSTEM_PROMPT
    assert calls[0][2]["x-api-key"] == "sk-ant-test"
    assert drafted.text == "The messy files are the job."
    assert json.dumps(calls[0][1]).find("sk-ant-test") == -1


def test_fixture_drafts_pass_the_linter():
    drafter = FixtureDrafter.load(
        __import__("brand_engage.config", fromlist=["repo_root"]).repo_root() / "fixtures" / "drafts.json"
    )
    for key, text in drafter._drafts.items():
        kind = "original" if key.startswith("original:") else "reply"
        assert draft_problems(text, kind=kind) == [], key
