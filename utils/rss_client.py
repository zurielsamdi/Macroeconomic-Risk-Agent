from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

import feedparser


@dataclass
class HeadlineItem:
    source: str
    category: str
    title: str
    link: str
    published: Optional[datetime]


def _parse_dt(entry: Dict[str, Any]) -> Optional[datetime]:
    # feedparser may provide published_parsed / updated_parsed as time.struct_time
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if not t:
        return None
    try:
        # convert to UTC-aware datetime
        return datetime(*t[:6], tzinfo=timezone.utc)
    except Exception:
        return None


def fetch_rss(url: str, timeout: int = 10) -> List[Dict[str, Any]]:
    d = feedparser.parse(url, request_headers={"User-Agent": "MorningAgent/1.0"})
    # feedparser doesn't expose timeout cleanly across environments; keep it simple.
    if getattr(d, "bozo", False):
        # bozo_exception exists sometimes; we just return what we got
        pass
    return list(getattr(d, "entries", []) or [])


def pull_headlines(
    feeds: List[Dict[str, str]],
    max_per_feed: int = 8,
) -> List[HeadlineItem]:
    """
    feeds: list of dicts with keys: source, url, category
    """
    out: List[HeadlineItem] = []

    for f in feeds:
        source = f.get("source", "").strip() or "Unknown"
        url = f.get("url", "").strip()
        category = f.get("category", "").strip() or "General"
        if not url:
            continue

        entries = fetch_rss(url)
        count = 0
        for e in entries:
            if count >= max_per_feed:
                break
            title = (e.get("title") or "").strip()
            link = (e.get("link") or "").strip()
            if not title or not link:
                continue

            out.append(
                HeadlineItem(
                    source=source,
                    category=category,
                    title=title,
                    link=link,
                    published=_parse_dt(e),
                )
            )
            count += 1

    return out
