from __future__ import annotations

import hashlib
import random
from datetime import datetime
from typing import Any, Dict, List

from utils.state_store import merge_state, load_last_state


INVENTORY_MM = {
    "US_2Y": 5.0,
    "US_5Y": 0.0,
    "US_10Y": -3.0,
    "US_30Y": 0.0,
    "CA_2Y": 2.0,
    "CA_5Y": 0.0,
    "CA_10Y": 0.0,
    "CA_30Y": 0.0,
}

DV01_PER_MM = {
    "US_2Y": 200.0,
    "US_5Y": 450.0,
    "US_10Y": 850.0,
    "US_30Y": 1600.0,
    "CA_2Y": 180.0,
    "CA_5Y": 420.0,
    "CA_10Y": 800.0,
    "CA_30Y": 1500.0,
}

SESSIONS = ["Asia", "London", "NY"]
TENOR_WEIGHTS_BASE = {"2Y": 0.32, "5Y": 0.28, "10Y": 0.25, "30Y": 0.15}


def _find_write_row(ws, start: int = 1) -> int:
    r = max(start, ws.max_row + 1)
    while r > 1 and ws.cell(r, 1).value is None:
        r -= 1
    return r + 2


def _conservative() -> Dict[str, Any]:
    return {
        "net_dv01": 0.0,
        "front_end_concentration": 0.0,
        "stress_bp": 2,
        "stress_$": 0.0,
        "warnings": ["insufficient data"],
    }


def _stable_seed(date_yyyy_mm_dd: str, component: str) -> int:
    s = f"{date_yyyy_mm_dd}|rates_flow|{component}"
    h = hashlib.sha256(s.encode("utf-8")).hexdigest()
    return int(h[:16], 16)


def _ticket_count(event_high: bool, rates_high: bool) -> int:
    n = 40
    if event_high:
        n += 8
    if rates_high:
        n += 4
    return max(30, min(60, n))


def _weighted_choice(rng: random.Random, choices: Dict[str, float]) -> str:
    keys = list(choices.keys())
    vals = [max(0.0, float(choices[k])) for k in keys]
    s = sum(vals)
    if s <= 0:
        return keys[0]
    x = rng.random() * s
    acc = 0.0
    for k, v in zip(keys, vals):
        acc += v
        if x <= acc:
            return k
    return keys[-1]


def _conservative_date() -> str:
    st = load_last_state() or {}
    d = str(st.get("date") or "").strip()
    if len(d) == 10 and d[4] == "-" and d[7] == "-":
        return d
    return datetime.now().strftime("%Y-%m-%d")


def run_phase9_dv01(wb, predictive: Dict[str, Any]) -> Dict[str, Any]:
    from utils.excel_writer import (
        ensure_sheet,
        write_table,
        write_text,
        TableSpec,
        autosize_columns_basic,
        freeze_panes,
    )

    try:
        ws_out = ensure_sheet(wb, "Rates_DV01")
        ws_comm = ensure_sheet(wb, "Desk_Commentary")

        event_high = predictive.get("events", {}).get("overall_event_severity_label") == "high"
        us_rates_high = predictive.get("rates", {}).get("US", {}).get("rates_vol_risk_label") == "high"
        ca_rates_high = predictive.get("rates", {}).get("CA", {}).get("rates_vol_risk_label") == "high"
        rates_high = us_rates_high or ca_rates_high

        constraints_summary = (load_last_state() or {}).get("constraints_summary", {})
        risk_budget = constraints_summary.get("risk_budget", "medium")
        dv01_cap = {"low": 1500.0, "medium": 3000.0, "high": 5000.0}.get(risk_budget, 3000.0)

        today = _conservative_date()
        rng = random.Random(_stable_seed(today, "tickets"))
        n_tickets = _ticket_count(event_high=event_high, rates_high=rates_high)

        tenor_weights = dict(TENOR_WEIGHTS_BASE)
        if event_high:
            tenor_weights["2Y"] += 0.10
            tenor_weights["5Y"] += 0.08
            tenor_weights["10Y"] -= 0.10
            tenor_weights["30Y"] -= 0.08

        inv = dict(INVENTORY_MM)
        flow_count_by_tenor = {"2Y": 0, "5Y": 0, "10Y": 0, "30Y": 0}
        flow_net_dv01_by_tenor = {"2Y": 0.0, "5Y": 0.0, "10Y": 0.0, "30Y": 0.0}
        flow_front_end = 0
        hedge_count = 0
        peak_abs_net = 0.0
        tape_rows = []

        for i in range(n_tickets):
            session = SESSIONS[min(2, int(i * 3 / max(1, n_tickets)))]
            tenor = _weighted_choice(rng, tenor_weights)
            region = "US" if rng.random() < 0.65 else "CA"

            key = f"{region}_{tenor}"
            dv01_per_mm = DV01_PER_MM[key]
            size_mm = rng.randint(1, 5)

            receive_prob = 0.50
            if rates_high:
                receive_prob = 0.55
            if event_high and tenor in {"2Y", "5Y"}:
                receive_prob += 0.05
            direction = "receive" if rng.random() < receive_prob else "pay"

            delta_inv = float(size_mm) if direction == "receive" else -float(size_mm)
            inv[key] += delta_inv
            delta_dv01 = delta_inv * dv01_per_mm
            flow_count_by_tenor[tenor] += 1
            flow_net_dv01_by_tenor[tenor] += delta_dv01
            if tenor in {"2Y", "5Y"}:
                flow_front_end += 1

            net_dv01_now = sum(inv[b] * DV01_PER_MM[b] for b in inv)

            hedged = ""
            if abs(net_dv01_now) > dv01_cap:
                us_abs = abs(inv["US_2Y"] * DV01_PER_MM["US_2Y"]) + abs(inv["US_5Y"] * DV01_PER_MM["US_5Y"])
                ca_abs = abs(inv["CA_2Y"] * DV01_PER_MM["CA_2Y"]) + abs(inv["CA_5Y"] * DV01_PER_MM["CA_5Y"])
                hedge_key = "CA_10Y" if ca_abs > us_abs else "US_10Y"
                target_abs = 0.7 * dv01_cap
                reduce_needed = max(0.0, abs(net_dv01_now) - target_abs)
                hedge_mm = reduce_needed / max(1.0, DV01_PER_MM[hedge_key])
                if hedge_mm > 0:
                    if net_dv01_now > 0:
                        inv[hedge_key] -= hedge_mm
                    else:
                        inv[hedge_key] += hedge_mm
                    hedge_count += 1
                    hedged = f"hedge {hedge_key} {hedge_mm:.2f}mm"
                    net_dv01_now = sum(inv[b] * DV01_PER_MM[b] for b in inv)

            peak_abs_net = max(peak_abs_net, abs(net_dv01_now))
            tape_rows.append([i + 1, session, region, tenor, direction, size_mm, net_dv01_now, hedged])

        rows = []
        abs_sum = 0.0
        net = 0.0
        for k in INVENTORY_MM:
            bucket = inv[k] * DV01_PER_MM[k]
            abs_sum += abs(bucket)
            net += bucket
            rows.append([k, inv[k], DV01_PER_MM[k], bucket])

        us2 = inv["US_2Y"] * DV01_PER_MM["US_2Y"]
        ca2 = inv["CA_2Y"] * DV01_PER_MM["CA_2Y"]
        front_end_conc = abs(us2 + ca2) / abs_sum if abs_sum > 0 else 0.0

        stress_bp = 5 if (event_high or rates_high or peak_abs_net > dv01_cap) else 2
        stress_dollar = max(abs(net), peak_abs_net) * stress_bp

        warnings: List[str] = []
        if front_end_conc >= 0.60 and event_high:
            warnings.append("front-end risk elevated")
        if abs(net) >= 10000:
            warnings.append("net DV01 elevated")
        if peak_abs_net > dv01_cap:
            warnings.append("intraday peak DV01 breached cap")

        write_table(
            ws_out,
            spec=TableSpec(start_row=1, start_col=1, header=True),
            columns=["Bucket", "Inventory ($mm)", "DV01 per $1mm", "DV01 ($/bp)"],
            rows=rows,
            number_formats=[None, "0.0", "0", "0"],
        )
        freeze_panes(ws_out, "A2")

        flow_rows = [
            ["2Y_count", flow_count_by_tenor["2Y"]],
            ["5Y_count", flow_count_by_tenor["5Y"]],
            ["10Y_count", flow_count_by_tenor["10Y"]],
            ["30Y_count", flow_count_by_tenor["30Y"]],
            ["2Y_net_dv01_chg", flow_net_dv01_by_tenor["2Y"]],
            ["5Y_net_dv01_chg", flow_net_dv01_by_tenor["5Y"]],
            ["10Y_net_dv01_chg", flow_net_dv01_by_tenor["10Y"]],
            ["30Y_net_dv01_chg", flow_net_dv01_by_tenor["30Y"]],
            ["hedge_count", hedge_count],
            ["peak_abs_dv01_intraday", peak_abs_net],
        ]
        flow_start = len(rows) + 4
        write_table(
            ws_out,
            spec=TableSpec(start_row=flow_start, start_col=1, header=True),
            columns=["Flow Tape Summary", "Value"],
            rows=flow_rows,
            number_formats=[None, "0.00"],
        )

        summary_rows = [
            ["net_dv01", net],
            ["front_end_concentration", front_end_conc],
            ["stress_bp", stress_bp],
            ["stress_$", stress_dollar],
            ["dv01_cap", dv01_cap],
            ["dv01_peak_abs", peak_abs_net],
            ["hedge_count_rates", hedge_count],
            ["warnings", "; ".join(warnings) if warnings else "none"],
        ]
        write_table(
            ws_out,
            spec=TableSpec(start_row=flow_start + len(flow_rows) + 2, start_col=1, header=True),
            columns=["Metric", "Value"],
            rows=summary_rows,
            number_formats=[None, "0.00"],
        )
        autosize_columns_basic(ws_out, start_col=1, end_col=4)

        start = _find_write_row(ws_comm)
        write_text(ws_comm, f"A{start}", "Rates DV01", bold=True)
        lines = [
            f"- Net DV01: {net:.0f} $/bp; Stress ({stress_bp}bp): ~${stress_dollar:,.0f}.",
            f"- Front-end concentration: {front_end_conc:.2f}.",
            f"- Flow tape: {n_tickets} tickets; hedged {hedge_count} times; peak DV01 {peak_abs_net:.0f}.",
            f"- Event severity: {predictive.get('events', {}).get('overall_event_severity_label', 'unknown')}.",
        ]
        if front_end_conc >= 0.60 and event_high:
            lines.append("- front-end risk elevated; reduce incremental DV01.")
        if abs(net) >= 10000:
            lines.append("- net DV01 elevated relative to threshold 10,000 $/bp.")
        if len(lines) < 3:
            lines.append("- insufficient data; conservative risk framing applied.")
        for i, line in enumerate(lines[:6], start=1):
            write_text(ws_comm, f"A{start+i}", line)

        flow_front_end_share = (
            float(flow_count_by_tenor["2Y"] + flow_count_by_tenor["5Y"]) / float(max(1, n_tickets))
        )
        dv01 = {
            "net_dv01": net,
            "front_end_concentration": front_end_conc,
            "stress_bp": stress_bp,
            "stress_$": stress_dollar,
            "warnings": warnings,
            "dv01_peak_abs": peak_abs_net,
            "dv01_cap": dv01_cap,
            "hedge_count_rates": hedge_count,
            "flow_front_end_share": flow_front_end_share,
            "flow_tape_rows": tape_rows[:20],  # compact trace for state/debug
        }
        merge_state({"dv01_summary": dv01}, also_append_history=False)
        return dv01
    except Exception:
        dv01 = _conservative()
        try:
            ws_comm = wb["Desk_Commentary"]
            from utils.excel_writer import write_text

            write_text(ws_comm, f"A{ws_comm.max_row + 2}", "Rates DV01: insufficient data")
        except Exception:
            pass
        merge_state({"dv01_summary": dv01}, also_append_history=False)
        return dv01
