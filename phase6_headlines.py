from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Tuple

from utils.excel_writer import ensure_sheet, write_text, write_table, freeze_panes, autosize_columns_basic, TableSpec
from utils.rss_feeds_loader import load_rss_feeds_from_wb
from utils.rss_client import pull_headlines, HeadlineItem

def _to_bool(v) -> bool:
    # Handles: True, "TRUE", "true", 1, "1", "yes", "y", "on",
    # and Excel formulas like "=TRUE"
    if isinstance(v, bool):
        return v
    if v is None:
        return False

    s = str(v).strip().lower()

    # Excel formulas often come through like "=TRUE"
    if s.startswith("="):
        s = s.lstrip("=").strip()

    return s in {"true", "1", "yes", "y", "on"}



def load_rss_feeds_from_wb(wb, sheet_name: str = "RSS_Feeds"):
    if sheet_name not in wb.sheetnames:
        return []

    ws = wb[sheet_name]

    # Read headers from row 1 (strip spaces)
    headers = [ws.cell(1, c).value for c in range(1, 10)]
    idx = {str(h).strip(): i for i, h in enumerate(headers) if h is not None}

    # Accept both exact-case and weird spacing
    # We’ll look up by name, but safely.
    def col(name: str, default=None):
        return idx.get(name, default)

    url_i = col("URL")
    active_i = col("Active")

    if url_i is None or active_i is None:
        return []

    feeds = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        url = row[url_i] if url_i < len(row) else None
        active_raw = row[active_i] if active_i < len(row) else None

        if url is None or str(url).strip() == "":
            continue

        if not _to_bool(active_raw):
            continue

        source = row[col("Source", 0)] if col("Source", 0) < len(row) else ""
        category = row[col("Category", 2)] if col("Category", 2) < len(row) else ""

        feeds.append(
            {
                "source": (str(source).strip() if source is not None else ""),
                "url": str(url).strip(),
                "category": (str(category).strip() if category is not None else ""),
            }
        )

    return feeds


def _fmt_dt(dt):
    if not dt:
        return ""
    # show local-ish readable UTC time
    try:
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return ""


def _dedupe(items: List[HeadlineItem]) -> List[HeadlineItem]:
    seen = set()
    out = []
    for it in items:
        key = (it.title.lower().strip(), it.link.strip())
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def run_phase6_headlines(wb, now_str: str, start_row: int, max_per_feed: int = 8) -> int:
    """
    Writes:
      1) Headlines table into sheet "Headlines"
      2) A compact "Headlines" synthesis input block into Desk_Commentary starting at start_row
    Returns: last row written on Desk_Commentary
    """

    ws_head = ensure_sheet(wb, "Headlines")
    ws_comm = ensure_sheet(wb, "Desk_Commentary")

    # Load feeds from Excel
    feeds = load_rss_feeds_from_wb(wb, sheet_name="RSS_Feeds")

    # If none, still write something clean
    if not feeds:
        write_text(ws_head, "A1", "Headlines", bold=True)
        write_text(ws_head, "A2", f"Last Updated: {now_str}")
        write_text(ws_head, "A4", "No active RSS feeds found in RSS_Feeds sheet.")
        return start_row

    # Pull headlines
    items = pull_headlines(feeds, max_per_feed=max_per_feed)
    items = _dedupe(items)

    # Sort newest first (None timestamps last)
    items.sort(key=lambda x: (x.published is None, x.published), reverse=False)
    items = list(reversed(items))

    # Write Headlines sheet
    write_text(ws_head, "A1", "Headlines", bold=True)
    write_text(ws_head, "A2", f"Last Updated: {now_str}")

    rows: List[Tuple[str, str, str, str, str]] = []
    for it in items:
        rows.append((it.category, it.source, _fmt_dt(it.published), it.title, it.link))

    write_table(
        ws_head,
        spec=TableSpec(start_row=4, start_col=1, header=True),
        columns=["Category", "Source", "Published", "Title", "Link"],
        rows=rows,
        number_formats=[None, None, None, None, None],
    )
    freeze_panes(ws_head, "A5")
    autosize_columns_basic(ws_head, start_col=1, end_col=5)

    # Write Desk_Commentary synthesis input
    write_text(ws_comm, f"A{start_row}", "Headlines", bold=True)
    r = start_row + 1

    # Keep this “LLM-friendly”: compact bullets, no giant table
    top_n = min(10, len(items))
    for i in range(top_n):
        it = items[i]
        # short line; link stored in Headlines sheet anyway
        line = f"- [{it.category}] {it.title} ({it.source})"
        write_text(ws_comm, f"A{r}", line)
        r += 1

    return r - 1
