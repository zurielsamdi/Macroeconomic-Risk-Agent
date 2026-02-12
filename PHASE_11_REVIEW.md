# Phase 11 Review

## Files changed
- `phase11_constraints.py`
- `run_morning_agent.py` (orchestration call)

## New functions + signatures
- `phase11_constraints.py::run_phase11_constraints(predictive, dv01, mm, persist=True) -> dict`

## Exact parameters/thresholds implemented
- `event_risk_level = predictive.events.overall_event_severity_label`
- `volatility_regime = max(rates US/CA vol labels, max FX vol label)`
- `directional_bias_allowed = False` if event high OR volatility high
- `risk_budget`:
  - `low` if event high OR liquidity high
  - `medium` if volatility medium
  - `high` only if event low AND volatility low AND liquidity low
  - otherwise `medium`
- `max_trades`: low `2`, medium `3`, high `4`
- `max_incremental_dv01`: low `500`, medium `1500`, high `3000`
- `allowed_instruments`: FX pairs present in Phase 8 predictive FX map
- `regime_alignment_required = True`
- `rationale`: non-empty list with regime/risk reasons

## Where inputs are read from
- Function inputs:
  - `predictive` from Phase 8
  - `dv01` from Phase 9
  - `mm` from Phase 10

## Where outputs are written
- State:
  - merges `constraints_summary` into `last_state.json`

## How to verify quickly in Excel
1. Run pipeline and inspect `state/last_state.json` for `constraints_summary`.
2. Confirm `directional_bias_allowed` and `risk_budget` change when event/vol/liquidity labels are changed upstream.

## Smoke test results
- `python phase8_12_smoke_tests.py`: PASS
- Phase 11 done test asserts:
  - event high + vol high => `directional_bias_allowed == false`
  - `risk_budget == low`

