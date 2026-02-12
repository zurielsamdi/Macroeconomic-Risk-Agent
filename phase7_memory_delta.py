from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from utils.excel_writer import ensure_sheet, write_text
from utils.state_store import load_last_state, save_state, safe_float, delta, fmt_delta


def _extract_today_state_from_workbook(wb) -> Dict[str, Any]:
    """
    Minimal, robust snapshot using what you ALREADY write into the workbook.
    We avoid fragile parsing of narrative text.
    """

    st: Dict[str, Any] = {}
    today = datetime.now().date().strftime("%Y-%m-%d")
    st["date"] = today

    # Rates regimes (these are already printed in Desk_Commentary in your screenshots)
    # We'll read them directly from Desk_Commentary cells if they exist.
    ws_comm = wb["Desk_Commentary"] if "Desk_Commentary" in wb.sheetnames else None
    if ws_comm:
        # US tag line looked like: "US_RATES_REGIME: US_NORMAL_STABLE_MIXED"
        # CA tag line looked like: "CA_RATES_REGIME: CA_NORMAL_STABLE_MIXED"
        us_tag = ws_comm["A24"].value  # adjust if template moves; see note below
        ca_tag = ws_comm["A25"].value
        st["rates_regime_us"] = str(us_tag).strip() if us_tag else None
        st["rates_regime_ca"] = str(ca_tag).strip() if ca_tag else None

    # Macro events count (from Macro_Events sheet: count Active==TRUE rows)
    if "Macro_Events" in wb.sheetnames:
        ws_ev = wb["Macro_Events"]
        # headers row 1
        headers = [ws_ev.cell(1, c).value for c in range(1, 30)]
        idx = {str(h).strip(): i for i, h in enumerate(headers) if h is not None}
        active_i = idx.get("Active")
        if active_i is not None:
            cnt = 0
            for row in ws_ev.iter_rows(min_row=2, values_only=True):
                v = row[active_i] if active_i < len(row) else None
                if str(v).strip().lower() in {"true", "1", "yes", "y", "on", "=true"}:
                    cnt += 1
            st["events_active_count"] = cnt

    # FX: store top movers line if present (simple)
    # You already write FX block into Desk_Commentary; we keep one line.
    if ws_comm:
        # In your screenshot FX Interpretation started around row ~39-41.
        fx_line = ws_comm["A40"].value
        st["fx_top_movers_line"] = str(fx_line).strip() if fx_line else None

    st["series"] = _extract_slope_series(wb)

    return st


def _curve_yields_from_sheet(ws) -> Dict[str, float]:
    out: Dict[str, float] = {}
    # Expected columns from phase2: A=Tenor, B=Yield (%)
    for r in range(2, ws.max_row + 1):
        tenor = ws.cell(r, 1).value
        yld = ws.cell(r, 2).value
        if tenor is None or yld is None:
            continue
        t = str(tenor).strip().upper()
        if t == "":
            continue
        try:
            out[t] = float(yld)
        except Exception:
            continue
    return out


def _extract_slope_series(wb) -> Dict[str, Optional[float]]:
    """
    Prefer Desk_Commentary Slope Metrics values, fallback to Curve_US/Curve_CA yields.
    """
    series: Dict[str, Optional[float]] = {
        "us_2s10s_bp": None,
        "ca_2s10s_bp": None,
        "us_3m10y_bp": None,
        "ca_3m10y_bp": None,
    }

    # 1) Preferred source: Desk_Commentary "Slope Metrics" table
    ws_comm = wb["Desk_Commentary"] if "Desk_Commentary" in wb.sheetnames else None
    if ws_comm:
        metric_map = {
            "US 2s10s (bp)": "us_2s10s_bp",
            "CA 2s10s (bp)": "ca_2s10s_bp",
            "US 3M10Y (bp)": "us_3m10y_bp",
            "CA 3M10Y (bp)": "ca_3m10y_bp",
        }
        for r in range(1, ws_comm.max_row + 1):
            m = ws_comm.cell(r, 1).value
            if m is None:
                continue
            mtxt = str(m).strip()
            if mtxt in metric_map:
                v = safe_float(ws_comm.cell(r, 2).value)
                series[metric_map[mtxt]] = v

    # 2) Fallback: compute from Curve_US/Curve_CA yields
    need_us_2s10s = series["us_2s10s_bp"] is None
    need_ca_2s10s = series["ca_2s10s_bp"] is None
    need_us_3m10y = series["us_3m10y_bp"] is None
    need_ca_3m10y = series["ca_3m10y_bp"] is None

    if (need_us_2s10s or need_us_3m10y) and "Curve_US" in wb.sheetnames:
        y = _curve_yields_from_sheet(wb["Curve_US"])
        if need_us_2s10s and ("10Y" in y and "2Y" in y):
            series["us_2s10s_bp"] = (y["10Y"] - y["2Y"]) * 100.0
        if need_us_3m10y and ("10Y" in y and "3M" in y):
            series["us_3m10y_bp"] = (y["10Y"] - y["3M"]) * 100.0

    if (need_ca_2s10s or need_ca_3m10y) and "Curve_CA" in wb.sheetnames:
        y = _curve_yields_from_sheet(wb["Curve_CA"])
        if need_ca_2s10s and ("10Y" in y and "2Y" in y):
            series["ca_2s10s_bp"] = (y["10Y"] - y["2Y"]) * 100.0
        if need_ca_3m10y and ("10Y" in y and "3M" in y):
            series["ca_3m10y_bp"] = (y["10Y"] - y["3M"]) * 100.0

    return series


def _regime_streak(today_regime: Optional[str], y_state: Optional[Dict[str, Any]], key: str) -> int:
    """
    If unchanged, increment yesterday's streak; otherwise reset to 1.
    """
    if not today_regime:
        return 0
    if not y_state:
        return 1
    y_regime = y_state.get(key)
    y_streak_key = f"{key}_streak"
    y_streak = int(y_state.get(y_streak_key, 0) or 0)
    if y_regime and str(y_regime).strip() == str(today_regime).strip():
        return y_streak + 1 if y_streak > 0 else 2
    return 1


def run_phase7_memory_delta(wb, start_row: int) -> int:
    """
    Writes:
      - "What changed vs yesterday" block into Desk_Commentary
      - Updates state/last_state.json
    Returns last row written.
    """
    ws = ensure_sheet(wb, "Desk_Commentary")

    # Load yesterday
    y_state = load_last_state()

    # Build today snapshot from workbook
    t_state = _extract_today_state_from_workbook(wb)

    # Add streaks
    t_state["rates_regime_us_streak"] = _regime_streak(t_state.get("rates_regime_us"), y_state, "rates_regime_us")
    t_state["rates_regime_ca_streak"] = _regime_streak(t_state.get("rates_regime_ca"), y_state, "rates_regime_ca")

    # Write delta block
    r = start_row
    write_text(ws, f"A{r}", "What changed vs yesterday", bold=True); r += 1

    if not y_state:
        write_text(ws, f"A{r}", "- No prior state found (first run)."); r += 1
    else:
        # Events
        ev_today = t_state.get("events_active_count")
        ev_yday = y_state.get("events_active_count")
        if ev_today is not None or ev_yday is not None:
            d = None
            if ev_today is not None and ev_yday is not None:
                d = ev_today - ev_yday
            sign = "+" if (d is not None and d > 0) else ""
            write_text(ws, f"A{r}", f"- Macro events (active): {ev_today} (yday {ev_yday}, Δ {sign}{d if d is not None else 'n/a'})")
            r += 1

        # Regime continuity
        us_reg = t_state.get("rates_regime_us")
        ca_reg = t_state.get("rates_regime_ca")
        if us_reg:
            write_text(ws, f"A{r}", f"- US rates regime: {us_reg} (streak {t_state['rates_regime_us_streak']}d)")
            r += 1
        if ca_reg:
            write_text(ws, f"A{r}", f"- CA rates regime: {ca_reg} (streak {t_state['rates_regime_ca_streak']}d)")
            r += 1

        # FX movers (string compare)
        fx_t = t_state.get("fx_top_movers_line")
        fx_y = y_state.get("fx_top_movers_line")
        if fx_t and fx_y and fx_t != fx_y:
            write_text(ws, f"A{r}", "- FX top movers changed vs yesterday."); r += 1
        elif fx_t:
            write_text(ws, f"A{r}", "- FX top movers: unchanged format/line."); r += 1

    # Save today state
    save_state(t_state, also_append_history=True)

    return r - 1
