from pathlib import Path
from datetime import datetime

from utils.excel_writer import (
    open_template,
    ensure_sheet,
    write_text,
    write_table,
    freeze_panes,
    autosize_columns_basic,
    TableSpec,
)
from utils.fx_client import fetch_fx_latest_and_prev, pct_change

TEMPLATE_PATH = Path("templates/Morning_Brief_Template.xlsx")
REPORTS_DIR = Path("reports")
STATE_PATH = Path("state/last_run.json")

# G10 FX vs USD (Yahoo tickers)
# Commonly used spot proxies
G10_TICKERS = [
    ("EURUSD", "EURUSD=X"),
    ("GBPUSD", "GBPUSD=X"),
    ("AUDUSD", "AUDUSD=X"),
    ("NZDUSD", "NZDUSD=X"),
    ("USDCAD", "CAD=X"),     # Note: Yahoo uses CAD=X as USD/CAD
    ("USDJPY", "JPY=X"),     # USD/JPY
    ("USDCHF", "CHF=X"),     # USD/CHF
    ("USDNOK", "NOK=X"),
    ("USDSEK", "SEK=X"),
]

def fx_interpretation_block(rows):
    """
    Deterministic, short interpretation based on top movers.
    rows: list of [pair, last, pct, asof]
    """
    # Sort by absolute move
    movers = sorted(rows, key=lambda r: abs(r[2]), reverse=True)
    top = movers[:3]

    lines = []
    lines.append("FX: Top movers (abs daily %): " + ", ".join([f"{r[0]} {r[2]:+.2f}%" for r in top]) + ".")

    # Simple USD tone heuristic:
    # If most USD-quoted pairs (EURUSD/GBPUSD/AUDUSD/NZDUSD) are up -> USD softer.
    # If most USDxxx pairs (USDJPY/USDCHF/USDNOK/USDSEK/USDCAD) are up -> USD firmer.
    usd_soft_count = 0
    usd_firm_count = 0

    for pair, _, pct, _ in rows:
        if pair in {"EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"}:
            if pct > 0:
                usd_soft_count += 1
            elif pct < 0:
                usd_firm_count += 1
        elif pair.startswith("USD"):
            if pct > 0:
                usd_firm_count += 1
            elif pct < 0:
                usd_soft_count += 1

    if usd_firm_count > usd_soft_count + 1:
        lines.append("FX: Broad USD tone is firmer (more USD-up pairs).")
    elif usd_soft_count > usd_firm_count + 1:
        lines.append("FX: Broad USD tone is softer (more USD-down pairs).")
    else:
        lines.append("FX: Broad USD tone is mixed/flat (no clear majority).")

    return lines

def run_phase4_fx(wb, now_str: str, rates_end_row: int):
    """
    Phase 4 runner used by run_morning_agent.py.
    IMPORTANT:
    - DO NOT open the workbook here
    - DO NOT save the workbook here
    - Only write into sheets inside the provided wb
    """
    # Everything that used to be inside main() after workbook creation goes here.
    latest_path = REPORTS_DIR / "Morning_Brief_latest.xlsx"

    # Load existing latest report if it exists, otherwise start from template
    

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    # Build FX table
    rows = []
    for pair, ticker in G10_TICKERS:
        (d0, px0), (d1, px1) = fetch_fx_latest_and_prev(ticker)
        chg = pct_change(px0, px1)
        rows.append([pair, px0, chg, d0])

    # Write FX_G10
    ws_fx = ensure_sheet(wb, "FX_G10")
    cols = ["Pair", "Last", "Chg (%)", "As of"]
    fmts = [None, "0.0000", "0.00", None]

    write_table(
        ws_fx,
        spec=TableSpec(start_row=1, start_col=1, header=True),
        columns=cols,
        rows=rows,
        number_formats=fmts,
    )
    freeze_panes(ws_fx, "A2")
    autosize_columns_basic(ws_fx, start_col=1, end_col=4)

    # Write commentary
    ws_commentary = ensure_sheet(wb, "Desk_Commentary")

    # Always update timestamp at top
    write_text(ws_commentary, "B1", now_str)

    # Put FX block right after Rates block + padding
    # rates_row is the row where you wrote "Rates Interpretation"
    # and len(rates_lines) is how many bullet lines you wrote under it

    fx_start_row = rates_end_row + 3  # 3 blank rows after rates block
    write_text(ws_commentary, f"A{fx_start_row}", "FX Interpretation", bold=True)

    fx_lines = fx_interpretation_block(rows)
    for i, line in enumerate(fx_lines, start=1):
        write_text(ws_commentary, f"A{fx_start_row + i}", f"- {line}")

    # Save report (overwrite latest, archive optional later)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    latest_path = REPORTS_DIR / "Morning_Brief_latest.xlsx"
    wb.save(latest_path)
    print(f"Saved report: {latest_path.resolve()}")

    return fx_start_row + len(fx_lines)



