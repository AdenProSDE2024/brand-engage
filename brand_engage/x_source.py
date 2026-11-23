"""Read-only X recent search.

The only network call in this module is GET https://api.x.com/2/tweets/search/recent.
There is no pagination. One page per query, then stop.
"""

from __future__ import annotations

from datetime import datetime

from brand_engage.http_get import AuthError, HttpGet, RateLimitError
from brand_engage.models import Account, Post, Settings, TopicQuery, parse_time
from brand_engage.rank import start_time_param
from brand_engage.safety import SEARCH_PATH, X_HOST

SEARCH_URL = f"https://{X_HOST}{SEARCH_PATH}"
QUERY_LIMIT = 512


class XReadClient:
    def __init__(self, bearer_token: str, http: HttpGet | None = None) -> None:
        if not bearer_token.strip():
            raise AuthError("Missing X bearer token.")
        self._token = bearer_token.strip()
        self._http = http or HttpGet()

    def search_recent(self, query: str, *, max_results: int, start_time: str) -> dict:
        if len(query) > QUERY_LIMIT:
            raise ValueError(f"X query is {len(query)} characters. The limit is {QUERY_LIMIT}.")
        return self._http.get_json(
            SEARCH_URL,
            params={
                "query": query,
                "max_results": str(max_results),
                "start_time": start_time,
                "tweet.fields": "created_at,public_metrics,lang,author_id,conversation_id,in_reply_to_user_id,referenced_tweets",
                "expansions": "author_id",
                "user.fields": "username,name,description,public_metrics",
            },
            headers={"Authorization": f"Bearer {self._token}"},
        )


def plan_queries(
    accounts: list[Account],
    topics: list[TopicQuery],
    settings: Settings,
) -> list[tuple[str, str]]:
    """Return (query, source) pairs, account batches first, then topics, under the cap."""
    handles = [account.handle for account in accounts if account.enabled]
    account_queries = _chunk_handles(handles, settings)
    topic_queries = []
    for topic in topics:
        if not topic.enabled or not topic.query:
            continue
        query = ensure_filters(topic.query, settings)
        if len(query) > QUERY_LIMIT:
            raise ValueError(
                f"A topic query is {len(query)} characters after the standard filters. "
                f"X allows {QUERY_LIMIT}. Shorten it in config/targets.yaml."
            )
        topic_queries.append((query, "topic"))
    budget = settings.max_search_requests
    if budget <= 0:
        return []
    # Leave one slot for a topic when there is at least one, so the list is not the whole search.
    topic_slots = 1 if topic_queries and budget > 1 else 0
    account_slots = min(len(account_queries), budget - topic_slots)
    if account_slots < 1 and account_queries:
        account_slots = min(len(account_queries), budget)
        topic_slots = max(0, budget - account_slots)
    chosen = account_queries[:account_slots]
    remaining = budget - len(chosen)
    chosen.extend(topic_queries[:remaining])
    return chosen


def ensure_filters(query: str, settings: Settings) -> str:
    text = " ".join(query.split())
    if "-is:retweet" not in text:
        text += " -is:retweet"
    if "-is:reply" not in text:
        text += " -is:reply"
    if settings.lang and f"lang:{settings.lang}" not in text:
        text += f" lang:{settings.lang}"
    lowered = text.lower()
    for handle in (settings.your_handle, settings.company_handle):
        if handle and f"-from:{handle.lower()}" not in lowered:
            text += f" -from:{handle}"
            lowered = text.lower()
    return text


def fetch_posts(
    client: XReadClient,
    queries: list[tuple[str, str]],
    *,
    now: datetime,
    settings: Settings,
) -> tuple[list[Post], list[str]]:
    notes: list[str] = []
    posts: list[Post] = []
    seen: set[str] = set()
    start = start_time_param(now, settings.max_age_hours)
    for index, (query, source) in enumerate(queries, start=1):
        try:
            payload = client.search_recent(
                query,
                max_results=settings.max_results_per_request,
                start_time=start,
            )
        except RateLimitError:
            notes.append(
                f"Stopped after {index - 1} X searches because the app hit a rate limit."
            )
            break
        except AuthError:
            raise
        for post in parse_search_payload(payload, source=source):
            if post.id in seen:
                continue
            seen.add(post.id)
            posts.append(post)
    if not queries:
        notes.append("No X queries were planned. Check config/targets.yaml.")
    return posts, notes


def parse_search_payload(payload: dict, *, source: str) -> list[Post]:
    users = {}
    for user in (payload.get("includes") or {}).get("users") or []:
        users[str(user.get("id", ""))] = user
    posts: list[Post] = []
    for item in payload.get("data") or []:
        author_id = str(item.get("author_id", ""))
        user = users.get(author_id) or {}
        metrics = item.get("public_metrics") or {}
        user_metrics = user.get("public_metrics") or {}
        handle = str(user.get("username") or "")
        tweet_id = str(item.get("id", ""))
        if not tweet_id:
            continue
        refs = item.get("referenced_tweets") or []
        is_reply = bool(item.get("in_reply_to_user_id")) or any(
            ref.get("type") == "replied_to" for ref in refs
        )
        is_repost = any(ref.get("type") == "retweeted" for ref in refs)
        created_raw = item.get("created_at")
        if not created_raw:
            continue
        url_handle = handle or "i"
        posts.append(
            Post(
                platform="x",
                id=tweet_id,
                url=f"https://x.com/{url_handle}/status/{tweet_id}",
                author_handle=handle,
                author_name=str(user.get("name") or handle),
                text=str(item.get("text") or ""),
                created_at=parse_time(str(created_raw)),
                author_followers=int(user_metrics.get("followers_count") or 0),
                author_bio=str(user.get("description") or ""),
                like_count=int(metrics.get("like_count") or 0),
                reply_count=int(metrics.get("reply_count") or 0),
                repost_count=int(metrics.get("retweet_count") or 0),
                quote_count=int(metrics.get("quote_count") or 0),
                is_reply=is_reply,
                is_repost=is_repost,
                lang=str(item.get("lang") or ""),
                source=source,
            )
        )
    return posts


def _chunk_handles(handles: list[str], settings: Settings) -> list[tuple[str, str]]:
    chunks: list[list[str]] = []
    current: list[str] = []
    for handle in handles:
        trial = current + [handle]
        query = _from_query(trial, settings)
        if len(query) > QUERY_LIMIT - 12 and current:
            chunks.append(current)
            current = [handle]
        else:
            current = trial
    if current:
        chunks.append(current)
    planned: list[tuple[str, str]] = []
    for chunk in chunks:
        query = _from_query(chunk, settings)
        if len(query) <= QUERY_LIMIT:
            planned.append((query, "accounts"))
    return planned


def _from_query(handles: list[str], settings: Settings) -> str:
    inner = " OR ".join(f"from:{handle}" for handle in handles)
    return ensure_filters(f"({inner})", settings)
