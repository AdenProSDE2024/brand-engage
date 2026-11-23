"""Draft replies and original posts. Live drafts call an LLM. Dry-run uses fixtures."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Callable

from brand_engage.models import DraftText, Post, Settings
from brand_engage.safety import SafetyError, assert_llm_url, public_error

SYSTEM_PROMPT = """You write drafts for Aden Yu. He posts every one of them himself. You do not post, reply, like, or send anything.

Who he is:
Aden Yu does go-to-market at Subliminal Labs. His X account is @AdenYCantU. The company account is @Subliminal_Labs. He is not a native English speaker. Use simple words and short sentences he can read once on his phone and post.

What Subliminal is:
Subliminal installs a recorder that watches how a back-office team actually works. It finds the workflows an AI could take over. It builds and tests those automations in a shadow environment, beside the live process, before any rollout. It is paid from a share of the savings. The buyer decides whether to roll it out. Beachhead buyers are PE firms, their operating partners, and portfolio companies, plus desk-heavy operators such as BPOs, insurance, lending, accounting, and staffing.

Claims rule:
Never say Subliminal builds, deploys, or runs automations "for you" or "for your team". Never sound like a consultancy, an agency, or a done-for-you service. Do not offer to implement, deploy, or set anything up for the reader. You may describe the recorder, the shadow environment, and being paid from savings.

How a draft should sound:
Most replies should not mention Subliminal at all. Add a useful point. Mention the product only when the post is directly about discovering real work, shadow testing, or paying for automation from savings, and then only in one plain clause.
Add one specific point of view, one concrete detail, or one sharp question.
No "great post", "love this", "so true", or any empty praise.
No hype, no emoji, no hashtags.
Do not use em dashes or en dashes.
Do not invent numbers, customers, or results. If the notes do not contain a figure, do not make one up.
Do not start with an @mention.
One to three short sentences. A reply stays under 400 characters.
Sound like a person who has watched the work.

Output the draft only. No label. No quotation marks around it.
"""

BANNED_PHRASES = (
    "great post",
    "great thread",
    "love this",
    "so true",
    "couldn't agree more",
    "could not agree more",
    "game changer",
    "game-changer",
    "happy to help",
    "for you",
    "we'll build",
    "we will build",
    "we can build",
    "we'll deploy",
    "we will deploy",
    "done for you",
    "done-for-you",
    "our consultants",
    "our consultancy",
    "dm me",
    "link in bio",
    "as a service",
    "well said",
    "nailed it",
    "awesome",
    "incredible",
    "super interesting",
)

_EMOJI = re.compile(r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF]")
_HASHTAG = re.compile(r"(?<!\w)#\w+")


def clean_draft(text: str) -> str:
    stripped = text.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {'"', "'"}:
        stripped = stripped[1:-1].strip()
    return re.sub(r"\s+", " ", stripped).strip()


def draft_problems(text: str, *, kind: str) -> list[str]:
    if not text.strip():
        return ["Draft is empty."]
    problems: list[str] = []
    lowered = text.lower().replace("’", "'").replace("`", "'")
    for phrase in BANNED_PHRASES:
        if phrase in lowered:
            problems.append(f"Contains {phrase!r}.")
    if "—" in text or "–" in text:
        problems.append("Contains a dash that is not a hyphen.")
    if _HASHTAG.search(text):
        problems.append("Contains a hashtag.")
    if text.count("!") > 1:
        problems.append("Too many exclamation marks.")
    if _EMOJI.search(text):
        problems.append("Contains emoji.")
    if text.lstrip().startswith("@"):
        problems.append("Starts with an @mention.")
    limit = 700 if kind == "original" else 450
    if len(text) > limit:
        problems.append(f"Too long ({len(text)} characters).")
    return problems


class FixtureDrafter:
    def __init__(self, drafts: dict[str, str]) -> None:
        self._drafts = drafts

    @classmethod
    def load(cls, path) -> "FixtureDrafter":
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls({str(key): str(value) for key, value in raw.items()})

    def reply(self, post: Post, notes: str) -> DraftText:
        return self._take(post.id, "reply")

    def comment(self, post: Post, notes: str) -> DraftText:
        return self._take(post.id, "comment")

    def original(self, notes: str, index: int, already: list[str]) -> DraftText:
        return self._take(f"original:{index}", "original")

    def _take(self, key: str, kind: str) -> DraftText:
        text = clean_draft(self._drafts.get(key) or _FALLBACK)
        return DraftText(text=text, warnings=draft_problems(text, kind=kind))


_FALLBACK = (
    "UNSCRIPTED FALLBACK. The messy files are the job, and a pilot that only "
    "runs the clean ones will not change the roster."
)


class LlmDrafter:
    def __init__(self, settings: Settings, api_key: str, transport: Callable[..., dict] | None = None) -> None:
        if not api_key.strip():
            raise RuntimeError("Missing LLM API key.")
        self._settings = settings
        self._api_key = api_key.strip()
        self._transport = transport or post_json

    def reply(self, post: Post, notes: str) -> DraftText:
        user = (
            "Write a reply Aden can post under this X post.\n\n"
            f"Author: @{post.author_handle} ({post.author_name}), {post.author_followers} followers.\n"
            f"Why they matter: {post.author_why or post.author_bio}\n"
            f"Post:\n{post.text}\n\n"
            f"Notes:\n{_notes(notes)}"
        )
        return self._complete(user, "reply")

    def comment(self, post: Post, notes: str) -> DraftText:
        user = (
            "Write a LinkedIn comment Aden can post himself.\n\n"
            f"Author: {post.author_name}\n"
            f"Why they matter: {post.author_why}\n"
            f"Post:\n{post.text}\n\n"
            f"Notes:\n{_notes(notes)}"
        )
        return self._complete(user, "comment")

    def original(self, notes: str, index: int, already: list[str]) -> DraftText:
        used = "\n".join(f"- {item}" for item in already) or "(none)"
        user = (
            f"Write original post {index} for @AdenYCantU. It must stand alone. "
            "Base it on the notes. Do not mention a specific customer. "
            "If another draft is listed, take a different angle.\n\n"
            f"Already used:\n{used}\n\nNotes:\n{_notes(notes)}"
        )
        return self._complete(user, "original")

    def _complete(self, user: str, kind: str) -> DraftText:
        text = clean_draft(self._call(user))
        problems = draft_problems(text, kind=kind)
        if problems:
            retry = self._call(
                user
                + "\n\nRewrite. The last draft failed these checks: "
                + " ".join(problems)
                + " Return only the new draft."
            )
            text = clean_draft(retry)
            problems = draft_problems(text, kind=kind)
        return DraftText(text=text, warnings=problems)

    def _call(self, user: str) -> str:
        provider = self._settings.llm_provider
        if provider == "anthropic":
            url = _anthropic_url(self._settings.llm_base_url)
            headers = {
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            body = {
                "model": self._settings.llm_model,
                "max_tokens": 300,
                "temperature": 0.4,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user}],
            }
            extract = _anthropic_text
        else:
            url = self._settings.llm_base_url.rstrip("/") + "/chat/completions"
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "content-type": "application/json",
            }
            body = {
                "model": self._settings.llm_model,
                "temperature": 0.4,
                "max_tokens": 300,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
            }
            extract = _openai_text
        # Checked here, not only inside the default transport, so a substitute
        # transport cannot aim this client at X or LinkedIn.
        assert_llm_url(url)
        return extract(self._transport(url, body, headers))


def post_json(url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    assert_llm_url(url)
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM returned HTTP {exc.code}. {public_error(RuntimeError(detail))}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM request failed. {public_error(exc)}") from None
    except SafetyError:
        raise
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("LLM returned a response that was not JSON.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("LLM returned a JSON value that was not an object.")
    if payload.get("error"):
        raise RuntimeError(f"LLM error. {public_error(RuntimeError(json.dumps(payload['error'])))}")
    return payload


def _anthropic_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/messages"):
        return base
    if "anthropic.com" in base or base.endswith("/v1"):
        if base.endswith("/v1"):
            return base + "/messages"
        return "https://api.anthropic.com/v1/messages"
    return base + "/messages"


def _openai_text(payload: dict[str, Any]) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("LLM response did not include a draft.") from exc
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return str(content or "")


def _anthropic_text(payload: dict[str, Any]) -> str:
    parts = payload.get("content") or []
    text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
    if not text:
        raise RuntimeError("LLM response did not include a draft.")
    return text


def _notes(notes: str) -> str:
    text = notes.strip() or "(no notes this week)"
    return text[:8000]
