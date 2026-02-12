# Phase 10 Review

## Files changed
- `phase10_fx_mm.py`
- `run_morning_agent.py` (orchestration call)

## New functions + signatures
- `phase10_fx_mm.py::run_phase10_fx_mm(wb, predictive, now_str) -> dict`
- `phase10_fx_mm.py::_simulate_pair(pair, spot, vol_label, event_high, today) -> dict`
- `phase10_fx_mm.py::_session_for_step(step) -> str`
- `phase10_fx_mm.py::_clip(x, lo, hi) -> float`

## Exact parameters/thresholds implemented
- Pair: default `USDCAD` (from `FX_G10` if available)
- Steps: `N=50`, split sessions:
  - `Asia 1..15`
  - `London 16..35`
  - `NY 36..50`
- Deterministic seed: `SHA256(f\"{YYYY-MM-DD}|{PAIR}|fx_mm\")` -> int
- Sigma by vol label:
  - `low 0.0002`, `medium 0.0005`, `high 0.0009`
- Session dynamics:
  - sigma multiplier: `Asia 0.8`, `London 1.0`, `NY 1.1`
  - session spread multiplier: `Asia 1.30`, `London 0.90`, `NY 1.10`
  - flow sizes: `Asia 1..2`, `London 2..4`, `NY 1..3`
  - flow intensity: London can do `1-2 trades/step`
- Dynamic microstructure:
  - `p_buy = clip(0.5 + 0.60*(risk_off_prob-0.5) - 0.25*(inv/limit), 0.1, 0.9)`
  - `spread_t = base_spread * session_mult * (1 + 0.35*|inv|/limit)`, clipped to `[0.00005, 0.00150]`
  - hedge trigger at `0.8*limit`
- Event window (if event severity high): steps `40..45`
  - sigma `x2.0`
  - spread `x1.5`
  - limit `x0.7`
  - hedge cost multiplier `x1.5`
  - partial hedge during NY event window (50% size)
  - post-event normalization decay applied
- Liquidity risk label:
  - `high` if limit breached or hedge_actions `>=5`
  - `medium` if hedge_actions `2-4`
  - `low` otherwise

## Where inputs are read from
- `FX_G10`: columns `Pair` and `Last` (spot initialization)
- `predictive`: event severity + FX vol label

## Where outputs are written
- `FX_MM_Sim`:
  - step table starts `A1` with columns:
    - `Step, Session, EventWin, p_buy, Mid, Spread_t, Trades, Inventory, Hedged, HedgeCost, StepPnL, CumPnL`
  - summary metrics table starts below simulation table
  - summary includes:
    - `hedge_count_by_session`
    - `avg_spread_by_session`
    - `event_window_impact`
- `Desk_Commentary`:
  - append `"FX MM Simulation"` bullets in desk language
- State:
  - merges `mm_summary` with:
    - `hedge_count_by_session`
    - `avg_spread_by_session`
    - `event_window_impact`
    - `cum_pnl`

## How to verify quickly in Excel
1. Open `FX_MM_Sim` and verify session split (`Asia/London/NY`) in `Session` column.
2. Confirm `EventWin=1` appears in NY window when event risk is high.
3. Confirm `p_buy`, `Spread_t`, `HedgeCost`, `StepPnL`, and `CumPnL` are populated.
4. Confirm summary includes session hedge counts and event-window impact.
5. Re-run same date and confirm identical row outputs.

## Smoke test results
- `python phase8_12_smoke_tests.py`: PASS
- Determinism checks:
  - same date/pair => same `inventory_end`, `hedge_actions`, and full row sequence
  - session split assertions pass (`Asia`, `London`, `NY`)
