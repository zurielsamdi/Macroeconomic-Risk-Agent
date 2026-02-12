from __future__ import annotations

import hashlib
import random
from datetime import datetime
from typing import Any, Dict, List

from utils.state_store import merge_state


SIGMA_BY_LABEL = {"low": 0.0002, "medium": 0.0005, "high": 0.0009}
SPREAD_MULT = {"low": 1.0, "medium": 1.5, "high": 2.5}
SESSION_SPLIT = [("Asia", 1, 15), ("London", 16, 35), ("NY", 36, 50)]
SESSION_SIGMA_MULT = {"Asia": 0.8, "London": 1.0, "NY": 1.1}
SESSION_SPREAD_MULT = {"Asia": 1.30, "London": 0.90, "NY": 1.10}
SESSION_SIZE = {"Asia": (1, 2), "London": (2, 4), "NY": (1, 3)}
SESSION_HEDGE_COST = {"Asia": 1.15, "London": 0.90, "NY": 1.05}


def _find_write_row(ws, start: int = 1) -> int:
    r = max(start, ws.max_row + 1)
    while r > 1 and ws.cell(r, 1).value is None:
        r -= 1
    return r + 2


def _stable_seed(date_yyyy_mm_dd: str, pair: str) -> int:
    s = f"{date_yyyy_mm_dd}|{pair}|fx_mm"
    h = hashlib.sha256(s.encode("utf-8")).hexdigest()
    return int(h[:16], 16)


def _session_for_step(step: int) -> str:
    for name, s, e in SESSION_SPLIT:
        if s <= step <= e:
            return name
    return "NY"


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _simulate_pair(pair: str, spot: float, vol_label: str, event_high: bool, today: str) -> Dict[str, Any]:
    n_steps = 50
    seed = _stable_seed(today, pair)
    rng = random.Random(seed)
    base_sigma = SIGMA_BY_LABEL.get(vol_label, 0.0005)
    base_spread = 0.0001 * SPREAD_MULT.get(vol_label, 1.5)
    base_limit = 6 if event_high else 10

    mid = spot
    inv = 0
    hedge_actions = 0
    breached = False
    rows: List[List[Any]] = []
    spread_sum = 0.0
    cum_pnl = 0.0
    hedge_count_by_session = {"Asia": 0, "London": 0, "NY": 0}
    spread_by_session = {"Asia": [], "London": [], "NY": []}
    event_window_pnl = 0.0
    event_window_max_inv = 0
    event_window_triggered = bool(event_high)
    event_start, event_end = (40, 45) if event_high else (0, -1)

    for step in range(1, n_steps + 1):
        session = _session_for_step(step)
        in_event_window = 1 if (event_start <= step <= event_end) else 0

        sigma_mult = SESSION_SIGMA_MULT.get(session, 1.0)
        spread_mult = SESSION_SPREAD_MULT.get(session, 1.0)
        limit = float(base_limit)
        hedge_cost_mult = SESSION_HEDGE_COST.get(session, 1.0)

        if in_event_window:
            sigma_mult *= 2.0
            spread_mult *= 1.5
            limit *= 0.7
            hedge_cost_mult *= 1.5
        elif event_high and step > event_end:
            # post-event normalization toward normal
            decay = max(0.0, 1.0 - 0.08 * (step - event_end))
            sigma_mult *= (1.0 + decay)
            spread_mult *= (1.0 + 0.5 * decay)
            limit *= (1.0 - 0.3 * decay)
            hedge_cost_mult *= (1.0 + 0.5 * decay)

        sigma_t = base_sigma * sigma_mult
        mid *= (1.0 + rng.gauss(0.0, sigma_t))

        risk_off_prob = {"low": 0.25, "medium": 0.50, "high": 0.75}.get(vol_label, 0.50)
        p_buy = _clip(0.5 + 0.60 * (risk_off_prob - 0.5) - 0.25 * (inv / max(limit, 1.0)), 0.1, 0.9)

        trades_this_step = 1
        if session == "London":
            trades_this_step = 1 + (1 if rng.random() < 0.45 else 0)

        step_spread_sum = 0.0
        step_hedge_cost = 0.0
        step_realized = 0.0
        hedged = 0

        for _ in range(trades_this_step):
            lo, hi = SESSION_SIZE.get(session, (1, 3))
            size = rng.randint(lo, hi)

            spread_t = base_spread * spread_mult * (1.0 + 0.35 * abs(inv) / max(limit, 1.0))
            spread_t = _clip(spread_t, 0.00005, 0.00150)

            flow = "client_buy" if rng.random() < p_buy else "client_sell"
            if flow == "client_buy":
                inv -= size
            else:
                inv += size

            step_realized += spread_t * size * 10000.0 * 0.5
            step_spread_sum += spread_t
            spread_sum += spread_t
            spread_by_session[session].append(spread_t)

            if abs(inv) > limit:
                breached = True

            hedge_trigger = 0.8 * limit
            if abs(inv) >= hedge_trigger:
                hedge_size = abs(inv)
                if in_event_window and (session == "NY"):
                    # partial hedge in stressed event microstructure
                    hedge_units = max(1, int(round(0.5 * hedge_size)))
                else:
                    hedge_units = hedge_size

                if inv > 0:
                    inv -= hedge_units
                else:
                    inv += hedge_units

                hedge_actions += 1
                hedge_count_by_session[session] += 1
                hedged = 1

                hedge_cost = spread_t * hedge_cost_mult * hedge_units * 10000.0 * 0.25
                step_hedge_cost += hedge_cost

        step_pnl = step_realized - step_hedge_cost
        cum_pnl += step_pnl

        if in_event_window:
            event_window_pnl += step_pnl
            event_window_max_inv = max(event_window_max_inv, abs(inv))

        avg_step_spread = step_spread_sum / max(trades_this_step, 1)
        rows.append(
            [
                step,
                session,
                in_event_window,
                p_buy,
                mid,
                avg_step_spread,
                trades_this_step,
                inv,
                hedged,
                step_hedge_cost,
                step_pnl,
                cum_pnl,
            ]
        )

    if breached or hedge_actions >= 5:
        liq_label = "high"
    elif hedge_actions >= 2:
        liq_label = "medium"
    else:
        liq_label = "low"

    return {
        "pair": pair,
        "seed": seed,
        "inventory_end": inv,
        "hedge_actions": hedge_actions,
        "avg_spread": spread_sum / n_steps,
        "liquidity_risk_label": liq_label,
        "breached_limit": breached,
        "cum_pnl": cum_pnl,
        "hedge_count_by_session": hedge_count_by_session,
        "avg_spread_by_session": {
            k: (sum(v) / len(v) if v else 0.0) for k, v in spread_by_session.items()
        },
        "event_window_impact": {
            "triggered": event_window_triggered,
            "window_pnl": event_window_pnl,
            "window_max_inv": event_window_max_inv,
        },
        "rows": rows,
    }


def run_phase10_fx_mm(wb, predictive: Dict[str, Any], now_str: str) -> Dict[str, Any]:
    from utils.excel_writer import (
        ensure_sheet,
        write_table,
        write_text,
        TableSpec,
        autosize_columns_basic,
        freeze_panes,
    )

    try:
        ws_fx = ensure_sheet(wb, "FX_G10")
        ws_out = ensure_sheet(wb, "FX_MM_Sim")
        ws_comm = ensure_sheet(wb, "Desk_Commentary")

        fx_rows = []
        for r in range(2, ws_fx.max_row + 1):
            pair = ws_fx.cell(r, 1).value
            last = ws_fx.cell(r, 2).value
            if pair is None or last is None:
                continue
            fx_rows.append((str(pair).strip(), float(last)))

        pair = "USDCAD"
        spot = 1.35
        for p, px in fx_rows:
            if p == "USDCAD":
                pair = p
                spot = px
                break

        event_high = predictive.get("events", {}).get("overall_event_severity_label") == "high"
        vol_label = predictive.get("fx", {}).get(pair, {}).get(
            "fx_vol_risk_label", predictive.get("max_fx_vol_label", "medium")
        )

        today = datetime.strptime(now_str[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
        sim = _simulate_pair(pair, spot, vol_label, event_high, today)

        write_table(
            ws_out,
            spec=TableSpec(start_row=1, start_col=1, header=True),
            columns=[
                "Step",
                "Session",
                "EventWin",
                "p_buy",
                "Mid",
                "Spread_t",
                "Trades",
                "Inventory",
                "Hedged",
                "HedgeCost",
                "StepPnL",
                "CumPnL",
            ],
            rows=sim["rows"],
            number_formats=[None, None, "0", "0.00", "0.00000", "0.00000", "0", "0", "0", "0.0", "0.0", "0.0"],
        )
        freeze_panes(ws_out, "A2")
        autosize_columns_basic(ws_out, start_col=1, end_col=12)

        summary_rows = [
            ["Pair", pair],
            ["Seed", sim["seed"]],
            ["inventory_end", sim["inventory_end"]],
            ["hedge_actions", sim["hedge_actions"]],
            ["avg_spread", sim["avg_spread"]],
            ["liquidity_risk_label", sim["liquidity_risk_label"]],
            ["breached_limit", int(sim["breached_limit"])],
            ["cum_pnl", sim["cum_pnl"]],
            ["hedge_count_asia", sim["hedge_count_by_session"]["Asia"]],
            ["hedge_count_london", sim["hedge_count_by_session"]["London"]],
            ["hedge_count_ny", sim["hedge_count_by_session"]["NY"]],
            ["avg_spread_asia", sim["avg_spread_by_session"]["Asia"]],
            ["avg_spread_london", sim["avg_spread_by_session"]["London"]],
            ["avg_spread_ny", sim["avg_spread_by_session"]["NY"]],
            ["event_window_pnl", sim["event_window_impact"]["window_pnl"]],
            ["event_window_max_inv", sim["event_window_impact"]["window_max_inv"]],
        ]
        write_table(
            ws_out,
            spec=TableSpec(start_row=len(sim["rows"]) + 4, start_col=1, header=True),
            columns=["Metric", "Value"],
            rows=summary_rows,
            number_formats=[None, "0.00000"],
        )

        start = _find_write_row(ws_comm)
        write_text(ws_comm, f"A{start}", "FX MM Simulation", bold=True)
        spread_pips = sim["avg_spread"] * 10000.0
        breach_txt = "Inventory limit breached" if sim["breached_limit"] else "No inventory breach"
        write_text(
            ws_comm,
            f"A{start+1}",
            f"- {pair}: Asia/London/NY sessions active; event window={'active' if event_high else 'not active'}.",
        )
        write_text(
            ws_comm,
            f"A{start+2}",
            f"- Hedges by session: Asia {sim['hedge_count_by_session']['Asia']}, London {sim['hedge_count_by_session']['London']}, NY {sim['hedge_count_by_session']['NY']}.",
        )
        write_text(ws_comm, f"A{start+3}", f"- Inventory end={sim['inventory_end']}; liquidity={sim['liquidity_risk_label']}.")
        write_text(
            ws_comm,
            f"A{start+4}",
            "- Deterministic (date+pair|fx_mm) seed.",
        )
        write_text(
            ws_comm,
            f"A{start+5}",
            f"- Average spread: {spread_pips:.1f} pips ({sim['avg_spread']:.5f}); {breach_txt}.",
        )
        write_text(
            ws_comm,
            f"A{start+6}",
            f"- Event window impact: pnl {sim['event_window_impact']['window_pnl']:.1f}, max inv {sim['event_window_impact']['window_max_inv']}.",
        )

        mm = {
            "pair": pair,
            "inventory_end": sim["inventory_end"],
            "hedge_actions": sim["hedge_actions"],
            "avg_spread": sim["avg_spread"],
            "liquidity_risk_label": sim["liquidity_risk_label"],
            "breached_limit": sim["breached_limit"],
            "hedge_count_by_session": sim["hedge_count_by_session"],
            "avg_spread_by_session": sim["avg_spread_by_session"],
            "event_window_impact": sim["event_window_impact"],
            "cum_pnl": sim["cum_pnl"],
        }
        merge_state({"mm_summary": mm}, also_append_history=False)
        return mm
    except Exception:
        mm = {
            "pair": "USDCAD",
            "inventory_end": 0,
            "hedge_actions": 0,
            "avg_spread": 0.00015,
            "liquidity_risk_label": "medium",
            "breached_limit": False,
            "notes": ["insufficient data"],
        }
        merge_state({"mm_summary": mm}, also_append_history=False)
        try:
            ws_comm = wb["Desk_Commentary"]
            from utils.excel_writer import write_text

            write_text(ws_comm, f"A{ws_comm.max_row + 2}", "FX MM Simulation: insufficient data")
        except Exception:
            pass
        return mm
