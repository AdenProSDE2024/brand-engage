from datetime import datetime, timedelta, timezone

from brand_engage.models import Post, Settings
from brand_engage.rank import (
    allocate,
    annotate_topics,
    explain_why_now,
    follower_floor,
    pick_diverse,
    rank_posts,
    topic_hits,
)

NOW = datetime(2026, 11, 23, 15, 0, tzinfo=timezone.utc)
TERMS = [
    "AI agents",
    "AI",
    "workflow",
    "operations",
    "exceptions",
    "automation",
    "GTM",
    "back office",
]


def make_post(**overrides) -> Post:
    base = dict(
        platform="x",
        id="1",
        url="https://x.com/swyx/status/1",
        author_handle="swyx",
        author_name="Shawn",
        text="AI agents break when the workflow hits exceptions in operations.",
        created_at=NOW - timedelta(minutes=30),
        author_followers=100_000,
        like_count=20,
        reply_count=4,
        repost_count=2,
        quote_count=0,
        lang="en",
    )
    base.update(overrides)
    return Post(**base)


def test_topic_hits_do_not_match_inside_other_words():
    hits = topic_hits("Again, the team said the AI agents failed. Then AI did not.", TERMS)
    lowered = {hit.lower() for hit in hits}
    assert "ai agents" in lowered
    assert "ai" in lowered
    assert all("again" not in hit.lower() for hit in hits)


def test_topic_hits_do_not_count_a_word_inside_a_longer_term():
    hits = [hit.lower() for hit in topic_hits("AI agents need a workflow.", TERMS)]
    assert "ai agents" in hits
    assert "ai" not in hits
    assert "workflow" in hits


def test_fresh_rising_post_beats_an_older_one_and_a_crowded_one():
    fresh = make_post(id="fresh", created_at=NOW - timedelta(minutes=35), like_count=40, reply_count=8)
    older = make_post(
        id="older",
        author_handle="emollick",
        url="https://x.com/emollick/status/2",
        created_at=NOW - timedelta(hours=3),
        like_count=30,
        reply_count=6,
    )
    crowded = make_post(
        id="crowded",
        author_handle="pmarca",
        url="https://x.com/pmarca/status/3",
        created_at=NOW - timedelta(minutes=20),
        author_followers=2_000_000,
        like_count=8000,
        reply_count=500,
        repost_count=1200,
        quote_count=200,
    )
    posts = [older, crowded, fresh]
    annotate_topics(posts, TERMS)
    ranked = rank_posts(posts, NOW, Settings()).ranked
    assert [item.post.id for item in ranked] == ["fresh", "older", "crowded"]
    assert ranked[0].score > ranked[1].score > ranked[2].score


def test_filters_drop_posts_that_are_not_a_reply_window():
    settings = Settings()
    posts = [
        make_post(id="ok"),
        make_post(id="old", created_at=NOW - timedelta(hours=8)),
        make_post(id="small", author_followers=800, author_handle="small"),
        make_post(id="reply", is_reply=True),
        make_post(id="repost", is_repost=True),
        make_post(id="mine", author_handle="AdenYCantU"),
        make_post(id="company", author_handle="Subliminal_Labs"),
        make_post(id="spanish", lang="es"),
        make_post(id="pancakes", text="I made pancakes this morning."),
        make_post(id="future", created_at=NOW + timedelta(hours=2)),
        make_post(id="anon", author_handle=""),
    ]
    annotate_topics(posts, TERMS)
    result = rank_posts(posts, NOW, settings)
    assert [item.post.id for item in result.ranked] == ["ok"]
    assert result.skipped["too_old"] == 1
    assert result.skipped["too_small"] == 1
    assert result.skipped["reply"] == 1
    assert result.skipped["repost"] == 1
    assert result.skipped["own_account"] == 2
    assert result.skipped["not_english"] == 1
    assert result.skipped["off_topic"] == 1
    assert result.skipped["clock"] == 1
    assert result.skipped["missing_author"] == 1


def test_follower_floor_uses_the_stricter_of_ratio_and_minimum():
    settings = Settings(your_follower_count=1000, min_follower_ratio=10, min_author_followers=5000)
    assert follower_floor(settings) == 10_000
    below = make_post(id="below", author_followers=9_000)
    above = make_post(id="above", author_followers=10_000, author_handle="other")
    annotate_topics([below, above], TERMS)
    result = rank_posts([below, above], NOW, settings)
    assert [item.post.id for item in result.ranked] == ["above"]
    assert result.skipped["too_small"] == 1


def test_pick_diverse_prefers_a_new_author_then_backfills():
    posts = [
        make_post(id="a1", author_handle="swyx"),
        make_post(id="a2", author_handle="swyx", url="https://x.com/swyx/status/2"),
        make_post(id="b1", author_handle="emollick", url="https://x.com/emollick/status/3"),
    ]
    annotate_topics(posts, TERMS)
    ranked = rank_posts(posts, NOW, Settings()).ranked
    # Force a known order: both swyx posts first, then the other author.
    ranked = sorted(ranked, key=lambda item: (item.post.author_handle != "swyx", item.post.id))
    picked = pick_diverse(ranked, limit=2, per_author=1)
    assert [item.post.id for item in picked] == ["a1", "b1"]
    backfill = pick_diverse(ranked, limit=3, per_author=1)
    assert [item.post.id for item in backfill] == ["a1", "b1", "a2"]


def test_allocate_fills_to_eight_and_adds_a_second_original_on_a_short_day():
    settings = Settings()
    assert allocate(10, 2, 2, settings) == (5, 2, 1)
    assert allocate(2, 2, 2, settings) == (2, 2, 2)
    assert allocate(0, 0, 2, settings) == (0, 0, 2)
    assert allocate(0, 0, 0, settings) == (0, 0, 0)


def test_why_now_is_plain_and_has_no_em_dash():
    post = make_post()
    annotate_topics([post], TERMS)
    text = explain_why_now(post, 0.5, Settings())
    assert "minutes old" in text
    assert "likes" in text
    assert "—" not in text
    assert "–" not in text
