from datetime import datetime
from utils.excel_writer import ensure_sheet, write_text
from utils.events_loader import load_macro_events_from_wb

def surprise_value(ev):
    if ev.actual is None or ev.expected is None:
        return None
    return ev.actual - ev.expected

def run_phase5_calendar(wb, start_row: int) -> int:
    """
    Writes Macro Calendar / Event Risk block to Desk_Commentary starting at start_row.
    Returns the last row written (end row).
    """
    ws = ensure_sheet(wb, "Desk_Commentary")
    ws_events = ensure_sheet(wb, "Macro_Events")
    ws_events.sheet_state = "visible"

    # Header
    write_text(ws, f"A{start_row}", "Macro Calendar / Event Risk", bold=True)
    row = start_row + 1

    today = datetime.now().date()

    # Load today's events from Macro_Events
    events = load_macro_events_from_wb(wb, today=today, sheet_name="Macro_Events")

    # Importance filtering (default: show 2+)
    min_imp_raw = ws_events["N1"].value
    try:
        MIN_IMPORTANCE = int(float(min_imp_raw))
    except Exception:
        MIN_IMPORTANCE = 2 

    events = [e for e in events if (e.importance or 0) >= MIN_IMPORTANCE]

    if not events:
        write_text(ws, f"A{row}", "- No active events (importance-filtered) for today.")
        return row

    # Write event lines
    for ev in events:
        s = surprise_value(ev)

        # Surprise string
        if s is None:
            s_txt = "Surprise: n/a"
        else:
            sign = "+" if s > 0 else ""
            unit = ev.unit or ""
            s_txt = f"Surprise: {sign}{s:.2f}{unit}"

        # Actual/Expected string
        if ev.actual is not None and ev.expected is not None:
            unit = ev.unit or ""
            a_txt = f"Act {ev.actual:.2f}{unit} vs Exp {ev.expected:.2f}{unit}"
        else:
            a_txt = "Act/Exp: n/a"

        imp = ev.importance if ev.importance is not None else "?"
        time = ev.time or ""
        risk = ev.risk or ""

        line = f"- ({imp}) {ev.region} {time} — {ev.event} | {risk} | {a_txt} | {s_txt}"
        write_text(ws, f"A{row}", line)
        row += 1

    return row - 1
