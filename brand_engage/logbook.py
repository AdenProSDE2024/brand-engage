"""A CSV Aden marks by hand. No scoring, no auto-tuning."""

from __future__ import annotations

import csv
from pathlib import Path

from brand_engage.models import Digest

FIELDS = ["date", "platform", "kind", "url", "author", "draft", "used", "result", "notes"]


def rows_from_digest(digest: Digest, day: str) -> list[dict[str, str]]:
    rows = []
    for item in digest.items:
        rows.append(
            {
                "date": day,
                "platform": item.platform,
                "kind": item.kind,
                "url": item.link,
                "author": item.author,
                "draft": item.draft,
                "used": "",
                "result": "",
                "notes": "",
            }
        )
    return rows


def upsert(path: Path, new_rows: list[dict[str, str]]) -> None:
    existing = _read(path)
    index = {(row["date"], row["platform"], row["kind"], row["url"]): row for row in existing}
    for row in new_rows:
        key = (row["date"], row["platform"], row["kind"], row["url"])
        prior = index.get(key)
        if prior and (prior.get("used") or prior.get("result") or prior.get("notes")):
            continue
        index[key] = {field: row.get(field, "") for field in FIELDS}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in index.values():
            writer.writerow(row)


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for row in reader:
            rows.append({field: (row.get(field) or "") for field in FIELDS})
        return rows
