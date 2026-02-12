from shutil import copy2
from pathlib import Path
from datetime import datetime
import json

from utils.bo_c_client import fetch_latest_and_prev_from_group, GROUP_BONDS, GROUP_TBILLS
from utils.curve_plotter import plot_yield_curve
from utils.excel_writer import open_template, ensure_sheet, write_text, write_table, freeze_panes, autosize_columns_basic, TableSpec
from utils.fred_client import fetch_latest_and_prev as fred_latest_prev


TEMPLATE_PATH = Path("templates/Morning_Brief_Template.xlsx")
REPORTS_DIR = Path("reports")
STATE_PATH = Path("state/last_run.json")


# US curve series (FRED)
US_SERIES = [
    ("1M",  1/12, "DGS1MO"),
    ("3M",  3/12, "DGS3MO"),
    ("6M",  6/12, "DGS6MO"),
    ("1Y",  1.0,  "DGS1"),
    ("2Y",  2.0,  "DGS2"),
    ("3Y",  3.0,  "DGS3"),
    ("5Y",  5.0,  "DGS5"),
    ("7Y",  7.0,  "DGS7"),
    ("10Y", 10.0, "DGS10"),
    ("20Y", 20.0, "DGS20"),
    ("30Y", 30.0, "DGS30"),
]



# Canada curve series (Bank of Canada Valet)
# These are common BoC yield curve series for Government of Canada bond yields.
# If one fails, we’ll adjust series names to match BoC exactly.
CA_TBILL_SERIES = [
    ("3M",  3/12, "V80691303"),
    ("6M",  6/12, "V80691304"),
    ("1Y",  1.0,  "V80691305"),
]

CA_BOND_SERIES = [
    ("2Y",  2.0,  "BD.CDN.2YR.DQ.YLD"),
    ("3Y",  3.0,  "BD.CDN.3YR.DQ.YLD"),
    ("5Y",  5.0,  "BD.CDN.5YR.DQ.YLD"),
    ("7Y",  7.0,  "BD.CDN.7YR.DQ.YLD"),
    ("10Y", 10.0, "BD.CDN.10YR.DQ.YLD"),
]

def bp_diff(yields: dict, long_tenor: str, short_tenor: str):
    """
    Return (bp, missing_reason). If missing, bp is None and missing_reason is a string.
    """
    if short_tenor not in yields:
        return None, f"missing {short_tenor}"
    if long_tenor not in yields:
        return None, f"missing {long_tenor}"
    return (yields[long_tenor] - yields[short_tenor]) * 100.0, None

def slope_bp(yields: dict, long_tenor: str, short_tenor: str):
    v, err = bp_diff(yields, long_tenor, short_tenor)
    return v, err

def slope_change_bp(y0: dict, y1: dict, long_tenor: str, short_tenor: str):
    s0, err0 = slope_bp(y0, long_tenor, short_tenor)
    s1, err1 = slope_bp(y1, long_tenor, short_tenor)
    if err0 is not None:
        return None, err0
    if err1 is not None:
        return None, err1
    return s0 - s1, None  # positive = steepening, negative = flattening

def bucket_slope(level_bp: float):
    if level_bp < 0:
        return "inverted"
    if level_bp < 25:
        return "flat"
    if level_bp < 100:
        return "normal"
    return "steep"

def bucket_momentum(chg_bp: float):
    if chg_bp > 5:
        return "steepening"
    if chg_bp < -5:
        return "flattening"
    return "stable"

def safe_bucket_slope(yields: dict):
    v, err = bp_diff(yields, "10Y", "2Y")
    if err is not None or v is None:
        return "UNKNOWN"
    return bucket_slope(v).upper()

def safe_bucket_momentum(y0: dict, y1: dict):
    v, err = slope_change_bp(y0, y1, "10Y", "2Y")
    if err is not None or v is None:
        return "UNKNOWN"
    return bucket_momentum(v).upper()

def curve_driver(yields: dict):
    """
    Heuristic:
    - If 2s5s big but 5s10s small => BELLY
    - If 2s5s small but 5s10s big => LONG_END
    - Else => MIXED
    """
    s_2s5s, e1 = bp_diff(yields, "5Y", "2Y")
    s_5s10s, e2 = bp_diff(yields, "10Y", "5Y")
    if e1 is not None or e2 is not None or s_2s5s is None or s_5s10s is None:
        return "UNKNOWN"

    if s_2s5s > 25 and s_5s10s < 15:
        return "BELLY"
    if s_2s5s < 15 and s_5s10s > 25:
        return "LONG_END"
    return "MIXED"

def delta_bp(y0: dict, y1: dict, tenor: str):
    """
    Return (change in yield in bp, missing_reason).
    Positive = yields up (sell-off). Negative = yields down (rally).
    """
    if tenor not in y0:
        return None, f"missing {tenor}"
    if tenor not in y1:
        return None, f"missing prev {tenor}"
    return (y0[tenor] - y1[tenor]) * 100.0, None

def steepening_type(y0: dict, y1: dict):
    """
    Classify curve move using 2Y and 10Y daily changes:
    - Bear steepening: long end up more than front end
    - Bull steepening: front end down more than long end
    - Bear flattening: front end up more than long end
    - Bull flattening: long end down more than front end
    """
    d2, e2 = delta_bp(y0, y1, "2Y")
    d10, e10 = delta_bp(y0, y1, "10Y")
    if e2 is not None or e10 is not None or d2 is None or d10 is None:
        return "UNKNOWN"

    slope_chg, e = slope_change_bp(y0, y1, "10Y", "2Y")
    if e is not None or slope_chg is None:
        return "UNKNOWN"

    # slope_chg > 0 => steepening, < 0 => flattening
    if slope_chg > 0:
        # steepening
        if d10 > d2:
            return "BEAR_STEEPENING"
        else:
            return "BULL_STEEPENING"
    elif slope_chg < 0:
        # flattening
        if d2 > d10:
            return "BEAR_FLATTENING"
        else:
            return "BULL_FLATTENING"
    else:
        return "STABLE"

def rates_interpretation_block(us_y0: dict, us_y1: dict, ca_y0: dict, ca_y1: dict):
    lines = []

    # US summary 
    us_2s10s, _ = bp_diff(us_y0, "10Y", "2Y")
    us_2s10s_chg, _ = slope_change_bp(us_y0, us_y1, "10Y", "2Y")
    us_move = steepening_type(us_y0, us_y1)
    us_drv = curve_driver(us_y0)

    if us_2s10s is not None:
        lines.append(f"US curve: {bucket_slope(us_2s10s)} (2s10s {us_2s10s:.0f} bp).")
    if us_2s10s_chg is not None:
        mom = bucket_momentum(us_2s10s_chg)
        lines.append(f"US curve momentum: {mom} ({us_2s10s_chg:+.0f} bp vs prior).")
    if us_move != "UNKNOWN":
        lines.append(f"US daily move type: {us_move.replace('_', ' ').title()}.")
    if us_drv != "UNKNOWN":
        lines.append(f"US driver: {us_drv.replace('_', ' ').title()}-led.")

    # Canada summary
    ca_2s10s, _ = bp_diff(ca_y0, "10Y", "2Y")
    ca_2s10s_chg, _ = slope_change_bp(ca_y0, ca_y1, "10Y", "2Y")
    ca_move = steepening_type(ca_y0, ca_y1)
    ca_drv = curve_driver(ca_y0)

    if ca_2s10s is not None:
        lines.append(f"Canada curve: {bucket_slope(ca_2s10s)} (2s10s {ca_2s10s:.0f} bp).")
    if ca_2s10s_chg is not None:
        mom = bucket_momentum(ca_2s10s_chg)
        lines.append(f"Canada curve momentum: {mom} ({ca_2s10s_chg:+.0f} bp vs prior).")
    if ca_move != "UNKNOWN":
        lines.append(f"Canada daily move type: {ca_move.replace('_', ' ').title()}.")
    if ca_drv != "UNKNOWN":
        lines.append(f"Canada driver: {ca_drv.replace('_', ' ').title()}-led.")

    # Cross-market note (simple + useful)
    if us_2s10s is not None and ca_2s10s is not None:
        diff = ca_2s10s - us_2s10s
        if diff > 10:
            lines.append(f"Canada curve steeper than US by {diff:.0f} bp (CA easing premium).")
        elif diff < -10:
            lines.append(f"US curve steeper than Canada by {abs(diff):.0f} bp (US premium).")
        else:
            lines.append("US vs Canada: 2s10s slopes broadly similar.")

    return lines


def interpret_slopes(us_y0: dict, us_y1: dict, ca_y0: dict, ca_y1: dict):
    lines = []

    # Core slopes (levels)
    us_2s10s, e = slope_bp(us_y0, "10Y", "2Y")
    ca_2s10s, e2 = slope_bp(ca_y0, "10Y", "2Y")

    us_3m10y, _ = slope_bp(us_y0, "10Y", "3M")
    ca_3m10y, _ = slope_bp(ca_y0, "10Y", "3M")

    # Momentum (change vs prev observation)
    us_2s10s_chg, _ = slope_change_bp(us_y0, us_y1, "10Y", "2Y")
    ca_2s10s_chg, _ = slope_change_bp(ca_y0, ca_y1, "10Y", "2Y")

    # Levels text
    if us_2s10s is not None:
        lines.append(f"US curve {bucket_slope(us_2s10s)} (2s10s = {us_2s10s:.0f} bp).")
    if us_3m10y is not None:
        state = "inverted" if us_3m10y < 0 else "positive"
        lines.append(f"US 3M–10Y is {state} ({us_3m10y:.0f} bp).")

    if ca_2s10s is not None:
        lines.append(f"Canada curve {bucket_slope(ca_2s10s)} (2s10s = {ca_2s10s:.0f} bp).")
    if ca_3m10y is not None:
        state = "inverted" if ca_3m10y < 0 else "positive"
        lines.append(f"Canada 3M–10Y is {state} ({ca_3m10y:.0f} bp).")

    # Momentum text
    if us_2s10s_chg is not None:
        lines.append(f"US 2s10s {bucket_momentum(us_2s10s_chg)} vs prior ({us_2s10s_chg:+.0f} bp).")
    if ca_2s10s_chg is not None:
        lines.append(f"Canada 2s10s {bucket_momentum(ca_2s10s_chg)} vs prior ({ca_2s10s_chg:+.0f} bp).")

    # Driver hints (front-end vs long-end)
    # If 2s5s steep but 5s10s flat -> belly-led; if 2s5s flat but 5s10s steep -> long-end led
    us_2s5s, _ = slope_bp(us_y0, "5Y", "2Y")
    us_5s10s, _ = slope_bp(us_y0, "10Y", "5Y")
    if us_2s5s is not None and us_5s10s is not None:
        if us_2s5s > 25 and us_5s10s < 15:
            lines.append("US steepness looks belly-led (policy-path repricing).")
        elif us_2s5s < 15 and us_5s10s > 25:
            lines.append("US steepness looks long-end-led (term premium / long-end pressure).")

    ca_2s5s, _ = slope_bp(ca_y0, "5Y", "2Y")
    ca_5s10s, _ = slope_bp(ca_y0, "10Y", "5Y")
    if ca_2s5s is not None and ca_5s10s is not None:
        if ca_2s5s > 25 and ca_5s10s < 15:
            lines.append("Canada steepness looks belly-led (BoC path repricing).")
        elif ca_2s5s < 15 and ca_5s10s > 25:
            lines.append("Canada steepness looks long-end-led (term premium / long-end pressure).")

    # Cross-market comparison
    if us_2s10s is not None and ca_2s10s is not None:
        diff = ca_2s10s - us_2s10s
        if diff > 10:
            lines.append(f"Canada curve steeper than US by {diff:.0f} bp (earlier easing priced in CA).")
        elif diff < -10:
            lines.append(f"US curve steeper than Canada by {abs(diff):.0f} bp (US growth/term premium advantage).")
        else:
            lines.append("US and Canada 2s10s slopes are broadly similar.")

    return lines

def run_phase2_curves(wb, now_str: str, file_stamp: str):
    """
    Phase 2 runner used by run_morning_agent.py.
    IMPORTANT:
    - DO NOT open the workbook here
    - DO NOT save the workbook here
    - Only write into sheets inside the provided wb
    """
    # Everything that used to be inside main() after "wb = open_template(...)" goes here.
    # You will keep all your existing logic (Curve_US, Curve_CA, spreads, slope metrics, interpretation).
    # Just remove open/save and use the wb passed in.

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    file_stamp = now.strftime("%Y%m%d_%H%M%S")

    # Build US curve table (FRED) 
    us_rows = []
    us_curve_points = []
    us_yields = {}
    us_prev_yields = {}

    for tenor, x_years, series_id in US_SERIES:
        (d0, y0), (d1, y1) = fred_latest_prev(series_id)
        y0 = float(y0); y1 = float(y1)
        chg_bp = (y0 - y1) * 100.0

        us_rows.append([tenor, y0, chg_bp, d0])
        us_curve_points.append((x_years, y0))
        us_yields[tenor] = y0
        us_prev_yields[tenor] = y1

    ws_us = ensure_sheet(wb, "Curve_US")
    us_cols = ["Tenor", "Yield (%)", "Chg (bp)", "As of"]
    us_formats = [None, "0.00", "0.0", None]

    write_table(
        ws_us,
        spec=TableSpec(start_row=1, start_col=1, header=True),
        columns=us_cols,
        rows=us_rows,
        number_formats=us_formats,
    )

    freeze_panes(ws_us, "A2")
    autosize_columns_basic(ws_us, start_col=1, end_col=4)

    # Plot US
    us_curve_points.sort(key=lambda x: x[0])
    x = [p[0] for p in us_curve_points]
    y = [p[1] for p in us_curve_points]

    plot_path = REPORTS_DIR / "plots" / f"US_Curve_{file_stamp}.png"
    plot_path.parent.mkdir(parents=True, exist_ok=True)
    plot_yield_curve(x, y, "US Treasury Yield Curve", plot_path)
    print(f"Saved plot: {plot_path.resolve()}")


    # Timestamp on Desk_Commentary
    ws_commentary = ensure_sheet(wb, "Desk_Commentary")
    write_text(ws_commentary, "B1", now_str)

    # Build Canada curve table
    ca_rows = []
    curve_points = []  # (x_years, y_yield)
    ca_yields = {}
    ca_prev_yields = {}


    #Treasury bills
    for tenor, x_years, series_id in CA_TBILL_SERIES:
        (d0, y0), (d1, y1) = fetch_latest_and_prev_from_group(GROUP_TBILLS, series_id)
        y0 = float(y0)
        y1 = float(y1)
        chg_bp = (y0 - y1) * 100.0

        ca_rows.append([tenor, y0, chg_bp, d0])
        curve_points.append((x_years, y0))
        ca_yields[tenor] = y0
        ca_prev_yields[tenor] = y1

    #Benchmark bonds
    for tenor, x_years, series_id in CA_BOND_SERIES:
        (d0, y0), (d1, y1) = fetch_latest_and_prev_from_group(GROUP_BONDS, series_id)
        y0 = float(y0)
        y1 = float(y1)
        chg_bp = (y0 - y1) * 100.0

        ca_rows.append([tenor, y0, chg_bp, d0])
        curve_points.append((x_years, y0))
        ca_yields[tenor] = y0
        ca_prev_yields[tenor] = y1


    ws_ca = ensure_sheet(wb, "Curve_CA")
    ca_cols = ["Tenor", "Yield (%)", "Chg (bp)", "As of"]
    ca_formats = [None, "0.00", "0.0", None]

    write_table(
        ws_ca,
        spec=TableSpec(start_row=1, start_col=1, header=True),
        columns=ca_cols,
        rows=ca_rows,
        number_formats=ca_formats,
    )
    freeze_panes(ws_ca, "A2")
    autosize_columns_basic(ws_ca, start_col=1, end_col=4)

    curve_points.sort(key=lambda x: x[0])
    x = [p[0] for p in curve_points]
    y = [p[1] for p in curve_points]

    plot_path = REPORTS_DIR / "plots" / f"CA_Curve_{file_stamp}.png"
    plot_yield_curve(x, y, "Canada Yield Curve (Bills + Benchmarks)", plot_path)
    print(f"Saved plot: {plot_path.resolve()}")
    

    #Build US–CA spreads table (bp) and write it below the Canada curve
    us_yields = {}
    for tenor, x_years, series_id in US_SERIES:
        (d0, y0), _ = fred_latest_prev(series_id)
        us_yields[tenor] = y0

    spread_rows = []
    for tenor in ["2Y", "5Y", "10Y"]:
        if tenor in us_yields and tenor in ca_yields:
            spread_bp = (us_yields[tenor] - ca_yields[tenor]) * 100.0
            spread_rows.append([f"US–CA {tenor}", spread_bp])

    # Write spreads starting at row 8 (safe spacing)
    spread_start_row = 1 + 1 + len(ca_rows) + 2

    write_table(
    ws_ca,
    spec=TableSpec(start_row=spread_start_row, start_col=1, header=True),
    columns=["Spread", "bp"],
    rows=spread_rows,
    number_formats=[None, "0.0"],
)
    
    

    autosize_columns_basic(ws_ca, start_col=1, end_col=2)

    # Slope metrics (bps)
    metrics = []

    # US slopes
    v, err = bp_diff(us_yields, "10Y", "2Y")
    metrics.append(["US 2s10s (bp)", v if err is None else err])

    v, err = bp_diff(us_yields, "10Y", "3M")
    metrics.append(["US 3M10Y (bp)", v if err is None else err])

    v, err = bp_diff(us_yields, "5Y", "2Y")
    metrics.append(["US 2s5s (bp)", v if err is None else err])

    # CA slopes
    v, err = bp_diff(ca_yields, "10Y", "2Y")
    metrics.append(["CA 2s10s (bp)", v if err is None else err])

    v, err = bp_diff(ca_yields, "5Y", "2Y")
    metrics.append(["CA 2s5s (bp)", v if err is None else err])

    
    # Write into Desk_Commentary
    ws_commentary = ensure_sheet(wb, "Desk_Commentary")

    # Slope Metrics table
    write_text(ws_commentary, "A6", "Slope Metrics", bold=True)

    write_table(
        ws_commentary,
        spec=TableSpec(start_row=7, start_col=1, header=True),
        columns=["Metric", "Value"],
        rows=metrics,
        number_formats=[None, "0.0"],
    )

    autosize_columns_basic(ws_commentary, start_col=1, end_col=2)

    #Slope interpretation text
    interpretation = interpret_slopes(us_yields, us_prev_yields, ca_yields, ca_prev_yields)

    start_row = 7 + len(metrics) + 2  # below slope table with spacing

    write_text(ws_commentary, f"A{start_row}", "Slope Interpretation", bold=True)

    for i, line in enumerate(interpretation, start=1):
        write_text(ws_commentary, f"A{start_row + i}", f"- {line}")

    # Regime tags (deterministic) 
    us_level = safe_bucket_slope(us_yields)
    us_momo = safe_bucket_momentum(us_yields, us_prev_yields)
    us_driver = curve_driver(us_yields)
    US_RATES_REGIME = f"US_{us_level}_{us_momo}_{us_driver}"

    ca_level = safe_bucket_slope(ca_yields)
    ca_momo = safe_bucket_momentum(ca_yields, ca_prev_yields)
    ca_driver = curve_driver(ca_yields)
    CA_RATES_REGIME = f"CA_{ca_level}_{ca_momo}_{ca_driver}"

    # Write regime tags into Desk_Commentary (short + visible)
    # Put these below the interpretation block
    tag_row = start_row + len(interpretation) + 2
    write_text(ws_commentary, f"A{tag_row}", "Rates Regime Tags", bold=True)
    write_text(ws_commentary, f"A{tag_row+1}", f"US_RATES_REGIME: {US_RATES_REGIME}")
    write_text(ws_commentary, f"A{tag_row+2}", f"CA_RATES_REGIME: {CA_RATES_REGIME}")

    # Rates Interpretation (Phase 3)
    rates_lines = rates_interpretation_block(us_yields, us_prev_yields, ca_yields, ca_prev_yields)

    # Put it below regime tags
    rates_row = tag_row + 4
    write_text(ws_commentary, f"A{rates_row}", "Rates Interpretation", bold=True)

    for i, line in enumerate(rates_lines, start=1):
        write_text(ws_commentary, f"A{rates_row + i}", f"- {line}")
    
    rates_end_row = rates_row + len(rates_lines)  # header row + N lines
    return rates_end_row


    # Save report
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # Always overwrite "latest"
    latest_path = REPORTS_DIR / "Morning_Brief_latest.xlsx"
    print(f"Saved latest report: {latest_path.resolve()}")

    # Also archive a timestamped copy each run
    archive_dir = REPORTS_DIR / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    archive_path = archive_dir / f"Morning_Brief_{now.strftime('%Y%m%d_%H%M%S')}.xlsx"
    copy2(latest_path, archive_path)
    print(f"Archived report: {archive_path.resolve()}")


    # Update state
    state_payload = {
        "last_run": now_str,
        "last_report": str(latest_path),
        "us_rates_regime": US_RATES_REGIME,
        "ca_rates_regime": CA_RATES_REGIME,
    }
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state_payload, indent=2), encoding="utf-8")
    print(f"Updated state: {STATE_PATH.resolve()}")


    print(f"Saved report: {latest_path.resolve()}")
    print("Wrote Curve_CA + US–CA spreads.")
    


