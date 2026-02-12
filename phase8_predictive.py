from __future__ import annotations

from datetime import datetime
import math
from typing import Any, Dict, List, Tuple

from utils.state_store import load_last_state, load_state_history, merge_state


KEYWORDS = [
    "CPI",
    "PCE",
    "NFP",
    "PAYROLL",
    "EMPLOYMENT",
    "FOMC",
    "FED",
    "BOC",
    "RATE DECISION",
    "GDP",
    "RETAIL SALES",
    "INFLATION",
]

LABEL_RANK = {"low": 1, "medium": 2, "high": 3}


def _prob_from_label(label: str) -> float:
    return {"low": 0.25, "medium": 0.50, "high": 0.75}.get(label, 0.50)


def _rates_label(max_abs_chg_bp: float) -> str:
    if max_abs_chg_bp < 3.0:
        return "low"
    if max_abs_chg_bp < 7.0:
        return "medium"
    return "high"


def _fx_label(abs_chg_pct: float) -> str:
    if abs_chg_pct < 0.30:
        return "low"
    if abs_chg_pct <= 0.80:
        return "medium"
    return "high"


def _parse_table(ws) -> Tuple[List[str], List[Dict[str, Any]]]:
    headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
    cols: List[str] = []
    for h in headers:
        if h is None:
            cols.append("")
        else:
            cols.append(str(h).strip())
    out: List[Dict[str, Any]] = []
    for r in range(2, ws.max_row + 1):
        row = {}
        has_any = False
        for c, name in enumerate(cols, start=1):
            if not name:
                continue
            v = ws.cell(r, c).value
            row[name] = v
            if v is not None and str(v).strip() != "":
                has_any = True
        if has_any:
            out.append(row)
    return cols, out


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _to_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    s = str(v).strip().lower()
    if s.startswith("="):
        s = s[1:].strip()
    return s in {"true", "1", "yes", "y", "on"}


def _risk_label_from_text(risk_txt: str, importance: float) -> str:
    s = (risk_txt or "").strip().lower()
    if "high" in s:
        return "high"
    if "med" in s:
        return "medium"
    if importance >= 3:
        return "high"
    if importance >= 2:
        return "medium"
    return "low"


def _severity_score(event_name: str, base_label: str, vol_is_high: bool) -> int:
    score = {"low": 1, "medium": 2, "high": 3}[base_label]
    upper_name = (event_name or "").upper()
    if any(k in upper_name for k in KEYWORDS):
        score += 2
    if vol_is_high:
        score += 1
    return score


def _severity_label(score: int) -> str:
    if score <= 2:
        return "low"
    if score <= 4:
        return "medium"
    return "high"


def _event_rows_ahead(ws_events, today_str: str) -> List[Dict[str, Any]]:
    _, rows = _parse_table(ws_events)
    out = []
    for row in rows:
        if not _to_bool(row.get("Active")):
            continue
        d = row.get("Date")
        if d is None:
            continue
        if hasattr(d, "strftime"):
            ds = d.strftime("%Y-%m-%d")
        else:
            ds = str(d).strip()[:10]
        if ds >= today_str:
            out.append(row)
    return out


def _find_write_row(ws, start: int = 1) -> int:
    r = max(start, ws.max_row + 1)
    while r > 1 and ws.cell(r, 1).value is None:
        r -= 1
    return r + 2


def _conservative_predictive(reason: str) -> Dict[str, Any]:
    return {
        "rates": {
            "US": {
                "regime_persistence_prob": 0.55,
                "rates_vol_risk_label": "medium",
                "rates_vol_risk_prob": 0.50,
                "front_end_move_prob": 0.50,
                "confidence_label": "low",
                "reasons": [reason],
            },
            "CA": {
                "regime_persistence_prob": 0.55,
                "rates_vol_risk_label": "medium",
                "rates_vol_risk_prob": 0.50,
                "front_end_move_prob": 0.50,
                "confidence_label": "low",
                "reasons": [reason],
            },
        },
        "fx": {},
        "events": {
            "top_events": [],
            "overall_event_severity_label": "medium",
            "overall_event_severity_score": 3,
        },
        "regime_stats": {
            "US": {"confidence": "LOW", "persistence_prob": None, "vol_state": "UNKNOWN"},
            "CA": {"confidence": "LOW", "persistence_prob": None, "vol_state": "UNKNOWN"},
        },
        "max_fx_vol_label": "medium",
        "notes": ["insufficient data"],
    }


def compute_phase8_signals_for_test(
    max_abs_us_bp: float,
    max_abs_ca_bp: float,
    fx_abs_moves_pct: List[float],
    event_name: str,
    event_base_risk_label: str,
    same_regime_as_prev: bool,
) -> Dict[str, Any]:
    """
    Pure helper for smoke tests.
    """
    us_label = _rates_label(max_abs_us_bp)
    ca_label = _rates_label(max_abs_ca_bp)
    fx_labels = [_fx_label(abs(v)) for v in fx_abs_moves_pct]
    max_fx = "low"
    for l in fx_labels:
        max_fx = l if LABEL_RANK[l] > LABEL_RANK[max_fx] else max_fx
    vol_is_high = (us_label == "high") or (ca_label == "high") or (max_fx == "high")
    score = _severity_score(event_name, event_base_risk_label, vol_is_high)
    overall = _severity_label(score)
    bump = 0.10 if overall == "high" else 0.0

    p = 0.55 + (0.10 if same_regime_as_prev else 0.0)
    if max(max_abs_us_bp, max_abs_ca_bp) >= 7.0:
        p -= 0.15
    if overall == "high":
        p -= 0.10
    p = max(0.05, min(0.95, p))
    return {
        "overall_event_severity_label": overall,
        "overall_event_severity_score": score,
        "rates_vol_risk_label_us": us_label,
        "rates_vol_risk_prob_us": min(0.95, _prob_from_label(us_label) + bump),
        "regime_persistence_prob": p,
    }


def _fmt_date_key(v: Any) -> str:
    s = str(v or "").strip()
    if len(s) >= 10:
        return s[:10]
    return s


def _series_from_history(history: List[Dict[str, Any]], key: str) -> List[Tuple[str, float]]:
    out: List[Tuple[str, float]] = []
    for e in history:
        ds = _fmt_date_key(e.get("date"))
        series = e.get("series", {}) if isinstance(e.get("series"), dict) else {}
        x = _to_float(series.get(key), default=float("nan"))
        if ds and not math.isnan(x):
            out.append((ds, x))
    out.sort(key=lambda t: t[0])
    return out


def _mean_std(xs: List[float]) -> Tuple[float, float]:
    if not xs:
        return 0.0, 0.0
    m = sum(xs) / len(xs)
    var = sum((x - m) ** 2 for x in xs) / len(xs)
    return m, math.sqrt(max(0.0, var))


def _bucket_slope(level_bp: float) -> str:
    if level_bp < 0:
        return "INVERTED"
    if level_bp <= 100:
        return "NORMAL"
    return "STEEP"


def _regime_stats_for_series(points: List[Tuple[str, float]]) -> Dict[str, Any]:
    # points are date-sorted (date, slope_bp)
    vals = [v for _, v in points]
    n = len(vals)
    if n == 0:
        return {
            "current_2s10s_bp": None,
            "z_level": None,
            "z_change": None,
            "vol_ratio": None,
            "vol_state": "UNKNOWN",
            "regime_bucket": None,
            "transition_rate": None,
            "persistence_prob": None,
            "confidence": "LOW",
            "lookback_used": {"level": 0, "change": 0, "short_vol": 0, "long_vol": 0, "persistence": 0},
        }

    current = vals[-1]
    level_w = min(60, n)
    level_sample = vals[-level_w:]
    level_mean, level_std = _mean_std(level_sample)
    z_level = (current - level_mean) / level_std if level_std > 0 else None

    deltas = [vals[i] - vals[i - 1] for i in range(1, n)]
    d_n = len(deltas)
    change_w = min(60, d_n)
    z_change = None
    if d_n > 0 and change_w > 0:
        change_sample = deltas[-change_w:]
        d_mean, d_std = _mean_std(change_sample)
        z_change = (deltas[-1] - d_mean) / d_std if d_std > 0 else None

    short_w = min(20, d_n)
    long_w = min(120, d_n)
    vol_ratio = None
    if short_w >= 10 and long_w >= 40:
        _, short_std = _mean_std(deltas[-short_w:])
        _, long_std = _mean_std(deltas[-long_w:])
        vol_ratio = (short_std / long_std) if long_std > 0 else None

    if vol_ratio is None:
        vol_state = "UNKNOWN"
    elif vol_ratio < 0.8:
        vol_state = "LOW"
    elif vol_ratio <= 1.2:
        vol_state = "NORMAL"
    else:
        vol_state = "HIGH"

    bucket = _bucket_slope(current)
    persistence_w = min(60, n)
    transition_rate = None
    persistence_prob = None
    if persistence_w >= 20:
        b = [_bucket_slope(x) for x in vals[-persistence_w:]]
        transitions = sum(1 for i in range(1, len(b)) if b[i] != b[i - 1])
        transition_rate = transitions / float(max(1, len(b) - 1))
        persistence_prob = max(0.0, min(1.0, 1.0 - transition_rate))

    if level_w >= 60 and change_w >= 60 and long_w >= 40:
        conf = "HIGH"
    elif level_w >= 40 and change_w >= 40:
        conf = "MEDIUM"
    else:
        conf = "LOW"

    return {
        "current_2s10s_bp": current,
        "z_level": z_level,
        "z_change": z_change,
        "vol_ratio": vol_ratio,
        "vol_state": vol_state,
        "regime_bucket": bucket,
        "transition_rate": transition_rate,
        "persistence_prob": persistence_prob,
        "confidence": conf,
        "lookback_used": {
            "level": level_w,
            "change": change_w,
            "short_vol": short_w,
            "long_vol": long_w,
            "persistence": persistence_w if persistence_w >= 20 else 0,
        },
    }


def _fmt(v: Any, nd: int = 2, suffix: str = "") -> str:
    if v is None:
        return "n/a"
    try:
        return f"{float(v):.{nd}f}{suffix}"
    except Exception:
        return "n/a"


def run_phase8_predictive(wb, now_str: str) -> Dict[str, Any]:
    """
    Phase 8 Predictive State Engine.
    Reads workbook sheets as source-of-truth numeric inputs and writes Predictive_Outlook.
    """
    from utils.excel_writer import (
        ensure_sheet,
        write_text,
        write_table,
        TableSpec,
        freeze_panes,
        autosize_columns_basic,
    )

    try:
        ws_us = ensure_sheet(wb, "Curve_US")
        ws_ca = ensure_sheet(wb, "Curve_CA")
        ws_fx = ensure_sheet(wb, "FX_G10")
        ws_events = ensure_sheet(wb, "Macro_Events")
        ws_out = ensure_sheet(wb, "Predictive_Outlook")
        ws_comm = ensure_sheet(wb, "Desk_Commentary")

        _, us_rows = _parse_table(ws_us)
        _, ca_rows = _parse_table(ws_ca)
        _, fx_rows = _parse_table(ws_fx)

        us_chg = [abs(_to_float(r.get("Chg (bp)"), 0.0)) for r in us_rows if r.get("Tenor")]
        ca_chg = [abs(_to_float(r.get("Chg (bp)"), 0.0)) for r in ca_rows if r.get("Tenor")]
        us_max_abs = max(us_chg) if us_chg else 0.0
        ca_max_abs = max(ca_chg) if ca_chg else 0.0
        us_label = _rates_label(us_max_abs)
        ca_label = _rates_label(ca_max_abs)

        fx_map: Dict[str, Dict[str, Any]] = {}
        max_fx_label = "low"
        for r in fx_rows:
            pair = str(r.get("Pair") or "").strip()
            if not pair:
                continue
            abs_chg = abs(_to_float(r.get("Chg (%)"), 0.0))
            label = _fx_label(abs_chg)
            max_fx_label = label if LABEL_RANK[label] > LABEL_RANK[max_fx_label] else max_fx_label
            fx_map[pair] = {
                "fx_vol_risk_label": label,
                "fx_vol_risk_prob": _prob_from_label(label),
                "risk_off_prob": _prob_from_label(label),
                "reasons": [f"{pair} abs daily move {abs_chg:.2f}% -> {label} threshold bucket"],
            }

        vol_is_high = (us_label == "high") or (ca_label == "high") or (max_fx_label == "high")
        today = datetime.strptime(now_str[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
        raw_events = _event_rows_ahead(ws_events, today)
        scored_events = []
        for ev in raw_events:
            event_name = str(ev.get("Event") or "").strip()
            base = _risk_label_from_text(str(ev.get("Risk") or ""), _to_float(ev.get("Importance"), 0))
            score = _severity_score(event_name, base, vol_is_high)
            scored_events.append(
                {
                    "event_name": event_name,
                    "time": str(ev.get("Time") or "").strip(),
                    "country": str(ev.get("Region") or "").strip(),
                    "severity_score": int(score),
                    "severity_label": _severity_label(int(score)),
                }
            )
        scored_events.sort(key=lambda x: x["severity_score"], reverse=True)
        top_events = scored_events[:5]
        if top_events:
            overall_score = max(e["severity_score"] for e in top_events)
            overall_label = _severity_label(overall_score)
        else:
            overall_score = 1
            overall_label = "low"

        event_bump = 0.10 if overall_label == "high" else 0.0
        history = load_state_history()
        prev_state = history[-2] if len(history) >= 2 else None
        current_state = load_last_state() or {}

        us_regime_today = str(current_state.get("rates_regime_us") or "")
        ca_regime_today = str(current_state.get("rates_regime_ca") or "")
        us_regime_prev = str((prev_state or {}).get("rates_regime_us") or "")
        ca_regime_prev = str((prev_state or {}).get("rates_regime_ca") or "")

        large_move = max(us_max_abs, ca_max_abs) >= 7.0

        def regime_prob(today_regime: str, prev_regime: str) -> float:
            p = 0.55
            if today_regime and prev_regime and today_regime == prev_regime:
                p += 0.10
            if large_move:
                p -= 0.15
            if overall_label == "high":
                p -= 0.10
            return max(0.05, min(0.95, p))

        us_stats = _regime_stats_for_series(_series_from_history(history, "us_2s10s_bp"))
        ca_stats = _regime_stats_for_series(_series_from_history(history, "ca_2s10s_bp"))
        us_persist = us_stats.get("persistence_prob")
        ca_persist = ca_stats.get("persistence_prob")

        predictive = {
            "rates": {
                "US": {
                    "regime_persistence_prob": us_persist if us_persist is not None else regime_prob(us_regime_today, us_regime_prev),
                    "rates_vol_risk_label": us_label,
                    "rates_vol_risk_prob": min(0.95, _prob_from_label(us_label) + event_bump),
                    "front_end_move_prob": min(0.95, _prob_from_label(us_label) + event_bump),
                    "confidence_label": (us_stats.get("confidence") or "LOW").lower(),
                    "reasons": [
                        f"max abs daily bp move {us_max_abs:.1f}",
                        f"overall event severity {overall_label}",
                        f"history obs={us_stats.get('lookback_used', {}).get('level', 0)}",
                    ],
                },
                "CA": {
                    "regime_persistence_prob": ca_persist if ca_persist is not None else regime_prob(ca_regime_today, ca_regime_prev),
                    "rates_vol_risk_label": ca_label,
                    "rates_vol_risk_prob": min(0.95, _prob_from_label(ca_label) + event_bump),
                    "front_end_move_prob": min(0.95, _prob_from_label(ca_label) + event_bump),
                    "confidence_label": (ca_stats.get("confidence") or "LOW").lower(),
                    "reasons": [
                        f"max abs daily bp move {ca_max_abs:.1f}",
                        f"overall event severity {overall_label}",
                        f"history obs={ca_stats.get('lookback_used', {}).get('level', 0)}",
                    ],
                },
            },
            "fx": fx_map,
            "events": {
                "top_events": top_events,
                "overall_event_severity_label": overall_label,
                "overall_event_severity_score": overall_score,
            },
            "max_fx_vol_label": max_fx_label,
            "regime_stats": {"US": us_stats, "CA": ca_stats},
        }

        for p in fx_map.values():
            p["fx_vol_risk_prob"] = min(0.95, p["fx_vol_risk_prob"] + event_bump)
            p["risk_off_prob"] = min(0.95, p["risk_off_prob"] + event_bump)
            p["reasons"].append(f"event bump applied {event_bump:.2f}")

        rows = [
            ["Rates", "US", us_label, predictive["rates"]["US"]["rates_vol_risk_prob"], "vol risk"],
            ["Rates", "CA", ca_label, predictive["rates"]["CA"]["rates_vol_risk_prob"], "vol risk"],
            [
                "Events",
                "Overall",
                overall_label,
                min(0.95, _prob_from_label(overall_label)),
                f"score {overall_score}",
            ],
        ]
        for pair, obj in sorted(fx_map.items()):
            rows.append(["FX", pair, obj["fx_vol_risk_label"], obj["fx_vol_risk_prob"], "fx vol risk"])

        write_table(
            ws_out,
            spec=TableSpec(start_row=1, start_col=1, header=True),
            columns=["Category", "Item", "Label", "Prob", "Details"],
            rows=rows,
            number_formats=[None, None, None, "0.00", None],
        )
        freeze_panes(ws_out, "A2")
        autosize_columns_basic(ws_out, start_col=1, end_col=5)

        rr = len(rows) + 3
        write_text(ws_out, f"A{rr}", "Reasons", bold=True)
        rr += 1
        for k, obj in [("US", predictive["rates"]["US"]), ("CA", predictive["rates"]["CA"])]:
            write_text(ws_out, f"A{rr}", f"- {k}: " + "; ".join(obj["reasons"]))
            rr += 1
        for pair, obj in sorted(fx_map.items()):
            write_text(ws_out, f"A{rr}", f"- {pair}: " + "; ".join(obj["reasons"]))
            rr += 1
        for ev in top_events:
            write_text(
                ws_out,
                f"A{rr}",
                f"- Event: {ev['country']} {ev['event_name']} {ev['time']} score={ev['severity_score']} ({ev['severity_label']})",
            )
            rr += 1

        # Regime Persistence Stats table (below existing phase 8 blocks)
        rr += 1
        write_text(ws_out, f"A{rr}", "Regime Persistence Stats", bold=True)
        rr += 1
        stats_rows = [
            ["Current 2s10s (bp)", us_stats.get("current_2s10s_bp"), ca_stats.get("current_2s10s_bp")],
            [
                f"Z-score level (w={us_stats.get('lookback_used', {}).get('level', 0)}/{ca_stats.get('lookback_used', {}).get('level', 0)})",
                us_stats.get("z_level"),
                ca_stats.get("z_level"),
            ],
            [
                f"Z-score change (w={us_stats.get('lookback_used', {}).get('change', 0)}/{ca_stats.get('lookback_used', {}).get('change', 0)})",
                us_stats.get("z_change"),
                ca_stats.get("z_change"),
            ],
            ["Vol ratio (short/long)", us_stats.get("vol_ratio"), ca_stats.get("vol_ratio")],
            ["Vol state", us_stats.get("vol_state"), ca_stats.get("vol_state")],
            ["Regime bucket", us_stats.get("regime_bucket"), ca_stats.get("regime_bucket")],
            [
                f"Transition rate (w={us_stats.get('lookback_used', {}).get('persistence', 0)}/{ca_stats.get('lookback_used', {}).get('persistence', 0)})",
                us_stats.get("transition_rate"),
                ca_stats.get("transition_rate"),
            ],
            [
                f"Persistence probability (w={us_stats.get('lookback_used', {}).get('persistence', 0)}/{ca_stats.get('lookback_used', {}).get('persistence', 0)})",
                us_stats.get("persistence_prob"),
                ca_stats.get("persistence_prob"),
            ],
            ["Confidence", us_stats.get("confidence"), ca_stats.get("confidence")],
        ]
        write_table(
            ws_out,
            spec=TableSpec(start_row=rr, start_col=1, header=True),
            columns=["Metric", "US", "CA"],
            rows=stats_rows,
            number_formats=[None, "0.00", "0.00"],
        )
        rr = rr + len(stats_rows) + 1

        start = _find_write_row(ws_comm)
        write_text(ws_comm, f"A{start}", "Predictive Outlook", bold=True)
        write_text(
            ws_comm,
            f"A{start+1}",
            f"- Event severity: {overall_label} (score {overall_score}).",
        )
        write_text(
            ws_comm,
            f"A{start+2}",
            f"- Rates vol risk: US {us_label}, CA {ca_label}; FX max {max_fx_label}.",
        )
        write_text(
            ws_comm,
            f"A{start+3}",
            "- Regime persistence is probability-weighted and confidence-labeled.",
        )
        write_text(
            ws_comm,
            f"A{start+4}",
            f"- Regime stats: US z={_fmt(us_stats.get('z_level'))} (Δz={_fmt(us_stats.get('z_change'))}), vol={us_stats.get('vol_state','UNKNOWN')}, persistence={_fmt(us_stats.get('persistence_prob'))} (conf={us_stats.get('confidence','LOW')}).",
        )
        write_text(
            ws_comm,
            f"A{start+5}",
            f"- Regime stats: CA z={_fmt(ca_stats.get('z_level'))} (Δz={_fmt(ca_stats.get('z_change'))}), vol={ca_stats.get('vol_state','UNKNOWN')}, persistence={_fmt(ca_stats.get('persistence_prob'))} (conf={ca_stats.get('confidence','LOW')}).",
        )

        merge_state(
            {
                "predictive_summary": {
                    "overall_event_severity_label": overall_label,
                    "overall_event_severity_score": overall_score,
                    "us_rates_vol_label": us_label,
                    "ca_rates_vol_label": ca_label,
                    "max_fx_vol_label": max_fx_label,
                    "us_regime_persistence_prob": predictive["rates"]["US"]["regime_persistence_prob"],
                    "ca_regime_persistence_prob": predictive["rates"]["CA"]["regime_persistence_prob"],
                    "us_regime_confidence": us_stats.get("confidence", "LOW"),
                    "ca_regime_confidence": ca_stats.get("confidence", "LOW"),
                }
            },
            also_append_history=False,
        )
        return predictive
    except Exception as e:
        conservative = _conservative_predictive(str(e))
        try:
            ws_out = wb["Predictive_Outlook"]
            ws_comm = wb["Desk_Commentary"]
            from utils.excel_writer import write_text

            write_text(ws_out, "A1", "Predictive_Outlook", bold=True)
            write_text(ws_out, "A2", "insufficient data")
            write_text(ws_comm, f"A{ws_comm.max_row + 2}", "Predictive Outlook: insufficient data")
        except Exception:
            pass
        merge_state(
            {
                "predictive_summary": {
                    "overall_event_severity_label": "medium",
                    "overall_event_severity_score": 3,
                    "us_rates_vol_label": "medium",
                    "ca_rates_vol_label": "medium",
                    "max_fx_vol_label": "medium",
                }
            },
            also_append_history=False,
        )
        return conservative
