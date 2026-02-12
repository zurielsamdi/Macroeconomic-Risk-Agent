from __future__ import annotations

import os

from phase8_predictive import compute_phase8_signals_for_test, _regime_stats_for_series
from phase10_fx_mm import _simulate_pair
from phase11_constraints import run_phase11_constraints
from phase12_commentary import _build_templated_payload, _build_morning_note_lines, _save_payload_json
from phase9_dv01 import _stable_seed as rates_seed


def test_phase8_done_case() -> None:
    out = compute_phase8_signals_for_test(
        max_abs_us_bp=8.1,
        max_abs_ca_bp=4.0,
        fx_abs_moves_pct=[0.35, 0.20],
        event_name="US CPI",
        event_base_risk_label="high",
        same_regime_as_prev=True,
    )
    assert out["overall_event_severity_label"] == "high"
    assert out["rates_vol_risk_prob_us"] >= 0.85  # 0.75 + 0.10 bump
    assert out["regime_persistence_prob"] < 0.55


def test_phase8_regime_stats_shape() -> None:
    pts = []
    base = 40.0
    for i in range(1, 75):
        # deterministic synthetic slope history with mild drift/twist
        v = base + (i * 0.3) + (2.0 if i % 7 == 0 else -1.0 if i % 11 == 0 else 0.0)
        pts.append((f"2026-01-{i:02d}" if i <= 31 else f"2026-02-{i-31:02d}", v))
    stats = _regime_stats_for_series(pts)
    assert "confidence" in stats
    assert stats["confidence"] in {"LOW", "MEDIUM", "HIGH"}
    pp = stats.get("persistence_prob")
    assert (pp is None) or (0.0 <= pp <= 1.0)


def test_phase11_done_case() -> None:
    predictive = {
        "events": {"overall_event_severity_label": "high"},
        "rates": {
            "US": {"rates_vol_risk_label": "high"},
            "CA": {"rates_vol_risk_label": "medium"},
        },
        "fx": {"USDCAD": {"fx_vol_risk_label": "medium"}},
        "max_fx_vol_label": "medium",
    }
    dv01 = {"net_dv01": 500.0}
    mm = {"liquidity_risk_label": "medium"}
    out = run_phase11_constraints(predictive=predictive, dv01=dv01, mm=mm, persist=False)
    assert out["directional_bias_allowed"] is False
    assert out["risk_budget"] == "low"


def test_phase10_determinism() -> None:
    a = _simulate_pair("USDCAD", 1.35, "high", True, "2026-02-10")
    b = _simulate_pair("USDCAD", 1.35, "high", True, "2026-02-10")
    assert a["inventory_end"] == b["inventory_end"]
    assert a["hedge_actions"] == b["hedge_actions"]
    assert a["rows"][0][1] == "Asia"
    assert a["rows"][15][1] == "London"
    assert a["rows"][35][1] == "NY"
    assert len(a["rows"][0]) >= 12  # session/p_buy/spread_t/hedge_cost/pnl columns exist
    assert a["rows"] == b["rows"]


def test_rates_seed_determinism() -> None:
    s1 = rates_seed("2026-02-10", "tickets")
    s2 = rates_seed("2026-02-10", "tickets")
    assert s1 == s2


def test_phase12_output_cleanup() -> None:
    constraints = {
        "risk_budget": "low",
        "max_trades": 2,
        "allowed_instruments": ["USDCAD"],
        "directional_bias_allowed": False,
    }
    state = {
        "predictive_summary": {
            "overall_event_severity_label": "high",
            "overall_event_severity_score": 6,
            "us_rates_vol_label": "low",
            "ca_rates_vol_label": "medium",
            "max_fx_vol_label": "high",
            "us_regime_persistence_prob": 0.42,
            "ca_regime_persistence_prob": 0.39,
        },
        "dv01_summary": {
            "net_dv01": -1190,
            "stress_bp": 5,
            "stress_$": 5950,
            "front_end_concentration": 0.35,
        },
        "mm_summary": {
            "pair": "USDCAD",
            "hedge_actions": 9,
            "avg_spread": 0.00019,
            "liquidity_risk_label": "high",
            "breached_limit": True,
            "hedge_count_by_session": {"Asia": 1, "London": 4, "NY": 4},
            "avg_spread_by_session": {"Asia": 0.00022, "London": 0.00016, "NY": 0.00020},
            "event_window_impact": {"triggered": True, "window_pnl": -12.3, "window_max_inv": 7},
        },
        "fx_top_movers_line": "- FX: Top movers (abs daily %): USDCHF -1.18%, USDNOK -0.96%, USDJPY -0.95%.",
    }
    state["dv01_summary"]["flow_front_end_share"] = 0.64
    state["dv01_summary"]["hedge_count_rates"] = 5
    state["dv01_summary"]["dv01_peak_abs"] = 3120.0
    payload = _build_templated_payload(constraints, state, ["h1", "h2", "h3", "h4", "h5"])
    lines = _build_morning_note_lines(payload, state, constraints)
    assert any("Morning Note (Auto)" in ln for ln in lines)
    assert not any(ln.strip().startswith("{") for ln in lines)
    assert any("Flows & Microstructure" in ln for ln in lines)
    path = _save_payload_json(payload, "2026-02-10 08:00:00")
    assert os.path.exists(path)


if __name__ == "__main__":
    test_phase8_done_case()
    test_phase8_regime_stats_shape()
    test_phase11_done_case()
    test_phase10_determinism()
    test_rates_seed_determinism()
    test_phase12_output_cleanup()
    print("phase8_12 smoke tests: PASS")
