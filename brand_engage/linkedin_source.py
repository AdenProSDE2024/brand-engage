"""LinkedIn input Aden pastes by hand. This module never touches the network."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from brand_engage.models import Post

_BLOCK = re.compile(r"(?im)^##\s+post\s*$")
_KEY = re.compile(r"^([A-Za-z_]+)\s*:\s*(.*)$")


def load_inbox(path: Path, *, now: datetime | None = None) -> tuple[list[Post], list[str]]:
    if not path.exists():
        return [], [f"No LinkedIn inbox at {path.name}."]
    return parse_inbox(path.read_text(encoding="utf-8"), now=now)


def parse_inbox(text: str, *, now: datetime | None = None) -> tuple[list[Post], list[str]]:
    moment = now or datetime.now(timezone.utc)
    notes: list[str] = []
    posts: list[Post] = []
    parts = _BLOCK.split(text)
    for part in parts[1:]:
        meta = _parse_block(part)
        url = (meta.get("url") or "").strip()
        body = (meta.get("text") or "").strip()
        if not url and not body:
            continue
        if not url or not body:
            notes.append("Skipped a pasted LinkedIn block because it needs both a url and text.")
            continue
        if "EXAMPLE" in url.upper() or "TODO" in url.upper():
            continue
        if not _is_linkedin_url(url):
            notes.append("Skipped a pasted block because the URL is not a LinkedIn link.")
            continue
        author = (meta.get("author") or "LinkedIn").strip()
        why = (meta.get("why") or "You pasted this post.").strip()
        posts.append(
            Post(
                platform="linkedin",
                id=url,
                url=url,
                author_handle=author,
                author_name=author,
                text=body,
                created_at=moment,
                author_why=why,
                source="inbox",
            )
        )
    return posts, notes


def _parse_block(part: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    body: list[str] = []
    mode = "meta"
    for line in part.strip("\n").splitlines():
        if mode == "meta":
            if not line.strip():
                continue
            match = _KEY.match(line)
            if match and match.group(1).lower() == "text":
                inline = match.group(2).strip()
                if inline not in {"|", ">", ""}:
                    meta["text"] = inline
                mode = "text"
                continue
            if match:
                meta[match.group(1).lower()] = match.group(2).strip()
                continue
            mode = "text"
            body.append(line)
        else:
            body.append(line)
    if body:
        extra = _dedent(body).strip()
        if extra:
            meta["text"] = f"{meta['text']}\n{extra}".strip() if meta.get("text") else extra
    return meta


def _dedent(lines: list[str]) -> str:
    indents = []
    for line in lines:
        if line.strip():
            indents.append(len(line) - len(line.lstrip(" ")))
    trim = min(indents) if indents else 0
    return "\n".join(line[trim:] if line.startswith(" " * trim) else line for line in lines)


def _is_linkedin_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and host in {"linkedin.com", "www.linkedin.com"}
