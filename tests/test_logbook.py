from brand_engage.logbook import upsert


def test_upsert_keeps_marks_aden_already_made(tmp_path):
    path = tmp_path / "log.csv"
    first = [
        {
            "date": "2026-11-23",
            "platform": "x",
            "kind": "reply",
            "url": "https://x.com/swyx/status/1",
            "author": "@swyx",
            "draft": "first draft",
            "used": "",
            "result": "",
            "notes": "",
        }
    ]
    upsert(path, first)
    marked = dict(first[0], used="yes", result="2 replies", notes="posted on the train")
    upsert(path, [marked])
    # A later run must not wipe the marks, even if the draft text changed.
    rerun = dict(first[0], draft="rewritten draft")
    upsert(path, [rerun])
    text = path.read_text(encoding="utf-8")
    assert "yes" in text
    assert "2 replies" in text
    assert "posted on the train" in text
    assert "first draft" in text
    assert "rewritten draft" not in text


def test_upsert_refreshes_a_row_he_has_not_marked(tmp_path):
    path = tmp_path / "log.csv"
    row = {
        "date": "2026-11-23",
        "platform": "x",
        "kind": "reply",
        "url": "https://x.com/swyx/status/1",
        "author": "@swyx",
        "draft": "first draft",
        "used": "",
        "result": "",
        "notes": "",
    }
    upsert(path, [row])
    upsert(path, [dict(row, draft="better draft")])
    assert "better draft" in path.read_text(encoding="utf-8")
    assert "first draft" not in path.read_text(encoding="utf-8")
