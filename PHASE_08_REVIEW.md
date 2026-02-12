# Phase 08 Review

## Files changed
- `phase8_predictive.py`
- `phase7_memory_delta.py` (daily series persistence into state)
- `utils/state_store.py` (state merge + bounded history helpers)
- `run_morning_agent.py` (orchestration call)

## New functions + signatures
- `phase8_predictive.py::run_phase8_predictive(wb, now_str) -> dict`
- `phase8_predictive.py::compute_phase8_signals_for_test(...) -> dict`
- `phase8_predictive.py::_regime_stats_for_series(points) -> dict`
- `utils/state_store.py::save_state_history_trimmed(entries, max_entries=365) -> None`

## Exact parameters/thresholds implemented
- Rates vol thresholds (bp): `<3 low`, `3-<7 medium`, `>=7 high`
- FX vol thresholds (%): `<0.30 low`, `0.30-0.80 medium`, `>0.80 high`
- Vol probabilities: `low=0.25, medium=0.50, high=0.75`
- Event bump: `+0.10` to vol probs when overall event severity `high`, clipped `<=0.95`
- Regime persistence formula:
  - start `0.55`
  - `+0.10` if previous regime equals current regime
  - `-0.15` if large move (`max_abs_chg_bp >= 7`)
  - `-0.10` if overall event severity high
  - clip `[0.05, 0.95]`
- Event severity score:
  - base: `low=1, medium=2, high=3`
  - `+2` if event keyword matches top-tier list
  - `+1` if rates high vol OR max FX high vol
  - label: `<=2 low`, `3-4 medium`, `>=5 high`
- Historical regime persistence stats (new):
  - persisted series per run in state:
    - `series.us_2s10s_bp`
    - `series.ca_2s10s_bp`
    - optional `series.us_3m10y_bp`, `series.ca_3m10y_bp` when available
  - windows:
    - level `60` (min confidence threshold `20`)
    - change `60` (min confidence threshold `20`)
    - short vol `20` (min `10`)
    - long vol `120` (min `40`)
    - persistence lookback `60` (min `20`)
  - formulas:
    - `z_level = (S_t - mean(S_w)) / std(S_w)`
    - `z_change = (ΔS_t - mean(ΔS_w)) / std(ΔS_w)`
    - `vol_ratio = std(ΔS_short)/std(ΔS_long)`
    - vol state: `<0.8 LOW`, `0.8-1.2 NORMAL`, `>1.2 HIGH`
    - regime bucket: `INVERTED(<0)`, `NORMAL(0..100)`, `STEEP(>100)`
    - transition rate over buckets: `transitions/(N-1)`
    - persistence probability: `1 - transition_rate` (clamped `[0,1]`)
  - confidence:
    - `HIGH` if level/change >=60 and long-vol >=40
    - `MEDIUM` if level/change >=40
    - `LOW` otherwise

## Where inputs are read from
- `Curve_US`: row 1 headers, using column `Chg (bp)` for max absolute move
- `Curve_CA`: row 1 headers, using column `Chg (bp)` for max absolute move
- `FX_G10`: row 1 headers, using columns `Pair`, `Chg (%)`
- `Macro_Events`: active forward-looking rows (`Active==TRUE` and `Date>=today`)
- Previous state context:
  - `state/last_state.json`
  - `state/state_history.jsonl` (uses second-last entry as prior regime reference)
  - historical numeric series from `state_history.jsonl[].series.*`

## Where outputs are written
- `Predictive_Outlook`:
  - table starts `A1` (`Category, Item, Label, Prob, Details`)
  - reasons block starts below table
  - new table below reasons: `"Regime Persistence Stats"` (US/CA columns)
- `Desk_Commentary`:
  - append block `"Predictive Outlook"` at next available row
  - add two concise regime-stat lines for US/CA (`z`, `Δz`, vol state, persistence, confidence)
- State:
  - Phase 7 now persists `series` into `last_state.json` and appended history lines
  - history retention bounded to last `365` entries
  - Phase 8 merges `predictive_summary` including persistence/confidence fields

## How to verify quickly in Excel
1. Open `Predictive_Outlook` and confirm US/CA/FX rows have labels + probabilities.
2. Confirm event severity row and reasons exist.
3. Confirm `"Regime Persistence Stats"` table appears below existing Phase 8 block.
4. In `Desk_Commentary`, confirm appended Predictive block includes US/CA regime-stat lines.
5. Confirm values render `n/a` gracefully when history is short.

## Why This Is More Agentic
- Phase 8 is now stateful across days via persisted slope series rather than single-day heuristics only.
- Regime persistence is derived from observed transition behavior in the time series.
- Vol state and z-scores make risk framing adaptive to historical context while remaining deterministic and explainable.

## Smoke test results
- `python phase8_12_smoke_tests.py`: PASS
- Phase 8 done test asserts:
  - high-impact event => overall severity high
  - vol probabilities bumped
  - regime persistence reduced
- Regime stats smoke test asserts:
  - `regime_stats` confidence in `{LOW, MEDIUM, HIGH}`
  - persistence probability is `None` or in `[0,1]`
