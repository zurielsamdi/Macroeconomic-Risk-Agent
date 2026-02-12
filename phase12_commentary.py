from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple

from utils.state_store import load_last_state, merge_state


REQUIRED_TRADE_KEYS = {
    "setup",
    "expression",
    "trigger",
    "risks",
    "invalidation",
    "why_fits_constraints",
    "dv01_impact",
    "liquidity_sensitivity",
    "confidence",
}


def _load_api_key() -> str:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if key:
        return key
    env_path = ".env"
    if not os.path.exists(env_path):
        return ""
    try:
        for line in open(env_path, "r", encoding="utf-8"):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("OPENAI_API_KEY="):
                return s.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        return ""
    return ""


def _extract_headlines(wb, n: int = 5) -> List[str]:
    if "Headlines" not in wb.sheetnames:
        return []
    ws = wb["Headlines"]
    out = []
    for r in range(5, ws.max_row + 1):
        title = ws.cell(r, 4).value
        if title is None:
            continue
        out.append(str(title).strip())
        if len(out) >= n:
            break
    return out


def _find_write_row(ws, start: int = 1) -> int:
    r = max(start, ws.max_row + 1)
    while r > 1 and ws.cell(r, 1).value is None:
        r -= 1
    return r + 2


def _title_case_label(v: str) -> str:
    return str(v or "").strip().title()


def _build_templated_payload(
    constraints: Dict[str, Any],
    state: Dict[str, Any],
    headlines: List[str],
) -> Dict[str, Any]:
    pred = state.get("predictive_summary", {})
    event_label = pred.get("overall_event_severity_label", "medium")
    payload = {
        "rates_commentary": [
            "Risk state likely elevated when event severity and rates volatility are both high.",
            f"US/CA rates volatility labels: {pred.get('us_rates_vol_label', 'n/a')} / {pred.get('ca_rates_vol_label', 'n/a')}.",
            "Regime persistence remains probability-weighted; watch front-end repricing triggers.",
        ],
        "fx_commentary": [
            f"FX volatility regime max label: {pred.get('max_fx_vol_label', 'n/a')}.",
            "Liquidity conditions can deteriorate around high-severity macro windows.",
            "Watchlist + triggers should dominate over directional conviction.",
        ],
        "calendar_commentary": [
            f"Overall event severity is {event_label}.",
            "Top macro releases should be treated as volatility catalysts rather than directional forecasts.",
            "Execution timing should avoid clustered releases where possible.",
        ],
        "headline_summary": headlines[:5],
        "predictive_outlook": [
            f"Regime persistence likely {'uncertain' if event_label == 'high' else 'moderately stable'}.",
            "No price-direction forecast; only risk-state framing and trigger monitoring.",
            "Maintain disciplined constraint-aware idea selection.",
        ],
        "trade_ideas": [],
        "watchlist_triggers": [
            "Event outcome surprise vs consensus",
            "Rates front-end move beyond high-risk threshold",
            "FX spread widening and repeated hedge activity",
        ],
        "meta_note": "No trades due to elevated risk" if constraints.get("risk_budget") == "low" else "Constraint-filtered idea space",
    }
    return payload


def _allowed_instrument(expression: str, allowed: List[str]) -> bool:
    s = expression.upper()
    return any(a.upper() in s for a in allowed)


def _is_directional_outright(text: str) -> bool:
    s = text.lower()
    if "spread" in s or "vs" in s or "hedge" in s:
        return False
    return bool(re.search(r"\b(buy|sell)\b", s))


def _validate_payload(payload: Dict[str, Any], constraints: Dict[str, Any]) -> Tuple[bool, str]:
    top_keys = [
        "rates_commentary",
        "fx_commentary",
        "calendar_commentary",
        "headline_summary",
        "predictive_outlook",
        "trade_ideas",
    ]
    for k in top_keys:
        if k not in payload:
            return False, f"missing key {k}"

    if not isinstance(payload["trade_ideas"], list):
        return False, "trade_ideas must be list"
    if len(payload["trade_ideas"]) > int(constraints.get("max_trades", 0)):
        return False, "violates max_trades"

    allowed = constraints.get("allowed_instruments", [])
    directional_allowed = bool(constraints.get("directional_bias_allowed", False))
    for i, idea in enumerate(payload["trade_ideas"]):
        if not isinstance(idea, dict):
            return False, f"trade idea {i} must be object"
        missing = REQUIRED_TRADE_KEYS - set(idea.keys())
        if missing:
            return False, f"trade idea {i} missing keys {sorted(missing)}"
        if not _allowed_instrument(str(idea.get("expression", "")), allowed):
            return False, f"trade idea {i} instrument not allowed"
        if not directional_allowed and (
            _is_directional_outright(str(idea.get("setup", "")))
            or _is_directional_outright(str(idea.get("expression", "")))
        ):
            return False, f"trade idea {i} directional while disallowed"
    return True, "ok"


def _call_openai(prompt: str, api_key: str) -> Dict[str, Any]:
    body = {
        "model": "gpt-4.1-mini",
        "messages": [
            {"role": "system", "content": "Return only valid JSON object. No markdown."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    txt = raw["choices"][0]["message"]["content"]
    return json.loads(txt)


def _format_pips(spread_decimal: float) -> str:
    return f"{spread_decimal * 10000.0:.1f} pips"


def _save_payload_json(payload: Dict[str, Any], now_str: str) -> str:
    d = now_str[:10]
    out = Path("state") / f"llm_payload_{d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(out)


def _build_morning_note_lines(
    payload: Dict[str, Any],
    state: Dict[str, Any],
    constraints: Dict[str, Any],
) -> List[str]:
    pred = state.get("predictive_summary", {})
    dv01 = state.get("dv01_summary", {})
    mm = state.get("mm_summary", {})

    event_label = _title_case_label(pred.get("overall_event_severity_label", "medium"))
    event_score = pred.get("overall_event_severity_score", "n/a")
    top_event_txt = ""
    cals = payload.get("calendar_commentary", [])
    if cals:
        top_event_txt = f" - {cals[0]}"

    us_vol = pred.get("us_rates_vol_label", "n/a")
    ca_vol = pred.get("ca_rates_vol_label", "n/a")
    fx_vol = pred.get("max_fx_vol_label", "n/a")
    us_rp = float(pred.get("us_regime_persistence_prob", 0.55) or 0.55)
    ca_rp = float(pred.get("ca_regime_persistence_prob", 0.55) or 0.55)

    net_dv01 = float(dv01.get("net_dv01", 0.0) or 0.0)
    stress_bp = int(dv01.get("stress_bp", 2) or 2)
    stress_dollar = float(dv01.get("stress_$", 0.0) or 0.0)
    front_end = float(dv01.get("front_end_concentration", 0.0) or 0.0)

    pair = str(mm.get("pair", "USDCAD"))
    hedges = int(mm.get("hedge_actions", 0) or 0)
    liq = _title_case_label(mm.get("liquidity_risk_label", "medium"))
    spread = float(mm.get("avg_spread", 0.00015) or 0.00015)
    breach_txt = "Inventory limit breached" if bool(mm.get("breached_limit", False)) else "No inventory breach"

    fx_top_line = state.get("fx_top_movers_line", "")
    fx_top_line = fx_top_line if fx_top_line else "FX top movers unavailable."

    lines: List[str] = [
        "=== Morning Note (Auto) ===",
        "Risk State:",
        f"- Event severity: {event_label} (score={event_score}){top_event_txt}",
        f"- Vol regime: Rates US {us_vol} / CA {ca_vol}; FX {fx_vol}",
        f"- Regime persistence: US {us_rp:.2f}; CA {ca_rp:.2f}",
        "Rates:",
        f"- Net DV01: {net_dv01:.0f} $/bp; Stress ({stress_bp}bp): ~${stress_dollar:,.0f}",
        f"- Front-end concentration: {front_end:.2f}",
        "- Key triggers: front-end repricing beyond threshold; surprise vs consensus",
        "FX / Liquidity:",
        f"- Top movers: {fx_top_line.replace('- FX: Top movers (abs daily %): ', '').strip()}",
        f"- MM sim ({pair}): vol={fx_vol}; hedges={hedges}; liquidity={liq.upper()}",
        "- Deterministic (date+pair) seed",
        f"- Average spread: {_format_pips(spread)} ({spread:.5f}); {breach_txt}",
        "Calendar:",
    ]
    for line in cals[:3]:
        lines.append(f"- {line}")
    lines.append("Headlines (top 5):")
    for h in payload.get("headline_summary", [])[:5]:
        lines.append(f"- {h}")
    lines.append("Trade Ideas:")

    trade_ideas = payload.get("trade_ideas", [])
    if not trade_ideas:
        lines.append("- NO TRADE (risk high). Watchlist only.")
    else:
        for idea in trade_ideas[: int(constraints.get("max_trades", 0))]:
            lines.append(f"- {idea.get('expression', '')}")
            lines.append(f"  trigger: {idea.get('trigger', '')}")
            lines.append(f"  invalidation: {idea.get('invalidation', '')}")
            lines.append(f"  risks: {idea.get('risks', '')}")

    hedge_by_sess = mm.get("hedge_count_by_session", {})
    avg_spread_sess = mm.get("avg_spread_by_session", {})
    ev_imp = mm.get("event_window_impact", {})
    flow_front_end_share = float(dv01.get("flow_front_end_share", 0.0) or 0.0)
    hedge_count_rates = int(dv01.get("hedge_count_rates", 0) or 0)
    peak_dv01 = float(dv01.get("dv01_peak_abs", 0.0) or 0.0)

    lines.append("Flows & Microstructure:")
    lines.append(
        "- FX flows: "
        f"Asia hedges {int(hedge_by_sess.get('Asia', 0))}, "
        f"London hedges {int(hedge_by_sess.get('London', 0))}, "
        f"NY hedges {int(hedge_by_sess.get('NY', 0))}; "
        f"spreads (pips) A/L/NY="
        f"{_format_pips(float(avg_spread_sess.get('Asia', 0.0) or 0.0))}/"
        f"{_format_pips(float(avg_spread_sess.get('London', 0.0) or 0.0))}/"
        f"{_format_pips(float(avg_spread_sess.get('NY', 0.0) or 0.0))}."
    )
    if bool(ev_imp.get("triggered", False)):
        lines.append(
            "- Event window widened microstructure: "
            f"window pnl {float(ev_imp.get('window_pnl', 0.0) or 0.0):.1f}, "
            f"max inv {int(ev_imp.get('window_max_inv', 0) or 0)}."
        )
    else:
        lines.append("- Event window not triggered; session conditions remained baseline.")
    lines.append(
        f"- Rates flows: front-end share {flow_front_end_share:.2f}; "
        f"hedged {hedge_count_rates} times; peak DV01 {peak_dv01:.0f}."
    )
    return lines


def _render_morning_note(ws, lines: List[str]):
    from utils.excel_writer import write_bullets

    start = _find_write_row(ws)
    body = lines[1:] if lines else []
    title = lines[0] if lines else "=== Morning Note (Auto) ==="
    write_bullets(ws, start_row=start, start_col=1, title=title, lines=body)


def run_phase12_commentary(wb, constraints: Dict[str, Any], now_str: str) -> Dict[str, Any]:
    from utils.excel_writer import ensure_sheet, write_text

    ws_comm = ensure_sheet(wb, "Desk_Commentary")
    state = load_last_state() or {}
    headlines = _extract_headlines(wb, n=8)
    api_key = _load_api_key()

    payload = _build_templated_payload(constraints, state, headlines)

    attempts = 0
    if api_key:
        while attempts < 2:
            attempts += 1
            try:
                prompt = json.dumps(
                    {
                        "now": now_str,
                        "constraints": constraints,
                        "state_summary": {
                            "predictive": state.get("predictive_summary", {}),
                            "dv01": state.get("dv01_summary", {}),
                            "mm": state.get("mm_summary", {}),
                        },
                        "headlines": headlines[:8],
                        "required_schema": {
                            "rates_commentary": "list[str] 3-6",
                            "fx_commentary": "list[str]",
                            "calendar_commentary": "list[str]",
                            "headline_summary": "list[str]",
                            "predictive_outlook": "list[str]",
                            "trade_ideas": "list[idea]",
                            "idea_fields": sorted(list(REQUIRED_TRADE_KEYS)),
                        },
                        "rules": [
                            "No directional forecast language",
                            "Respect constraints exactly",
                            "Return valid JSON only",
                        ],
                    }
                )
                candidate = _call_openai(prompt, api_key)
                ok, why = _validate_payload(candidate, constraints)
                if ok:
                    payload = candidate
                    break
                write_text(ws_comm, f"A{ws_comm.max_row + 2}", f"Phase12 validation retry: {why}")
            except Exception:
                continue

    ok, why = _validate_payload(payload, constraints)
    if not ok:
        payload = _build_templated_payload(constraints, state, headlines)
        payload["trade_ideas"] = []
        payload["meta_note"] = "No trades due to elevated risk"
        write_text(ws_comm, f"A{ws_comm.max_row + 2}", f"Phase12 fallback used: {why}")

    note_lines = _build_morning_note_lines(payload, state, constraints)
    _render_morning_note(ws_comm, note_lines)
    payload_path = _save_payload_json(payload, now_str)

    merge_state(
        {
            "llm_summary": {
                "trade_count": len(payload.get("trade_ideas", [])),
                "meta_note": payload.get("meta_note", ""),
                "watchlist_triggers": payload.get("watchlist_triggers", []),
                "risk_state_labels": {
                    "event": state.get("predictive_summary", {}).get("overall_event_severity_label", "medium"),
                    "rates_us": state.get("predictive_summary", {}).get("us_rates_vol_label", "medium"),
                    "rates_ca": state.get("predictive_summary", {}).get("ca_rates_vol_label", "medium"),
                    "fx_max": state.get("predictive_summary", {}).get("max_fx_vol_label", "medium"),
                },
                "payload_path": payload_path,
                "fallback_used": not bool(api_key) or attempts == 2,
            },
        },
        also_append_history=False,
    )
    merge_state(
        {
            "predictive_summary": state.get("predictive_summary", {}),
            "dv01_summary": state.get("dv01_summary", {}),
            "mm_summary": state.get("mm_summary", {}),
            "constraints_summary": {
                "directional_bias_allowed": constraints.get("directional_bias_allowed"),
                "risk_budget": constraints.get("risk_budget"),
                "max_trades": constraints.get("max_trades"),
                "allowed_instruments": constraints.get("allowed_instruments", []),
                "max_incremental_dv01": constraints.get("max_incremental_dv01"),
            },
        },
        also_append_history=True,
    )
    return payload
