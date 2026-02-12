from __future__ import annotations

from typing import Any, Dict, List

from utils.state_store import merge_state


RANK = {"low": 1, "medium": 2, "high": 3}


def _max_label(labels: List[str]) -> str:
    best = "low"
    for l in labels:
        if RANK.get(l, 1) > RANK.get(best, 1):
            best = l
    return best


def run_phase11_constraints(
    predictive: Dict[str, Any],
    dv01: Dict[str, Any],
    mm: Dict[str, Any],
    persist: bool = True,
) -> Dict[str, Any]:
    event_risk = predictive.get("events", {}).get("overall_event_severity_label", "medium")
    rates_labels = [
        predictive.get("rates", {}).get("US", {}).get("rates_vol_risk_label", "medium"),
        predictive.get("rates", {}).get("CA", {}).get("rates_vol_risk_label", "medium"),
    ]
    fx_labels = [v.get("fx_vol_risk_label", "medium") for v in predictive.get("fx", {}).values()]
    max_fx = _max_label(fx_labels) if fx_labels else predictive.get("max_fx_vol_label", "medium")
    vol_regime = _max_label(rates_labels + [max_fx])
    liq = mm.get("liquidity_risk_label", "medium")

    directional_bias_allowed = not (event_risk == "high" or vol_regime == "high")

    if event_risk == "high" or liq == "high":
        risk_budget = "low"
    elif vol_regime == "medium":
        risk_budget = "medium"
    elif event_risk == "low" and vol_regime == "low" and liq == "low":
        risk_budget = "high"
    else:
        risk_budget = "medium"

    max_trades = {"low": 2, "medium": 3, "high": 4}[risk_budget]
    max_incremental_dv01 = {"low": 500, "medium": 1500, "high": 3000}[risk_budget]
    allowed_instruments = sorted(list(predictive.get("fx", {}).keys()))

    rationale = [
        f"event_risk_level={event_risk}",
        f"volatility_regime={vol_regime}",
        f"liquidity_risk_label={liq}",
        f"net_dv01={dv01.get('net_dv01', 0):.0f}",
    ]
    if not directional_bias_allowed:
        rationale.append("directional bias disabled due to high event/vol risk")
    if risk_budget == "low":
        rationale.append("risk budget constrained by event/liquidity regime")

    constraints = {
        "event_risk_level": event_risk,
        "volatility_regime": vol_regime,
        "directional_bias_allowed": directional_bias_allowed,
        "risk_budget": risk_budget,
        "max_trades": max_trades,
        "max_incremental_dv01": max_incremental_dv01,
        "allowed_instruments": allowed_instruments,
        "regime_alignment_required": True,
        "rationale": rationale,
    }

    if persist:
        merge_state(
            {
                "constraints_summary": {
                    "directional_bias_allowed": directional_bias_allowed,
                    "risk_budget": risk_budget,
                    "max_trades": max_trades,
                    "allowed_instruments": allowed_instruments,
                    "max_incremental_dv01": max_incremental_dv01,
                }
            },
            also_append_history=False,
        )
    return constraints
