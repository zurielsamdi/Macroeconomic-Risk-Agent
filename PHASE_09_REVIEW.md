# Phase 09 Review

## Files changed
- `phase9_dv01.py`
- `run_morning_agent.py` (orchestration call)

## New functions + signatures
- `phase9_dv01.py::run_phase9_dv01(wb, predictive) -> dict`
- `phase9_dv01.py::_stable_seed(date_yyyy_mm_dd, component) -> int`

## Exact parameters/thresholds implemented
- Starting inventory ($mm):
  - `US_2Y +5, US_5Y 0, US_10Y -3, US_30Y 0`
  - `CA_2Y +2, CA_5Y 0, CA_10Y 0, CA_30Y 0`
- DV01 per $1mm ($/bp):
  - `US_2Y 200, US_5Y 450, US_10Y 850, US_30Y 1600`
  - `CA_2Y 180, CA_5Y 420, CA_10Y 800, CA_30Y 1500`
- Flow tape simulation:
  - deterministic seed: `SHA256(f\"{YYYY-MM-DD}|rates_flow|tickets\")`
  - ticket count: `40` base, `+8` if event high, `+4` if rates high (clipped to `[30,60]`)
  - each ticket: session (`Asia/London/NY`), region (`US/CA`), tenor (`2Y/5Y/10Y/30Y`), direction (`pay/receive`), size (`1..5mm`)
  - event high increases front-end flow share (`2Y/5Y` upweight)
- Intraday risk controls:
  - `dv01_cap` by risk budget: `low=1500`, `medium=3000`, `high=5000`
  - if `|net_dv01| > cap`, hedge with `US_10Y` proxy (or `CA_10Y` if CA-heavy) back toward `0.7*cap`
  - track `hedge_count_rates` and `dv01_peak_abs`
- Core outputs:
  - `dv01_bucket = inv_mm * dv01_per_mm`
  - `net_dv01 = sum(dv01_bucket)`
  - `front_end_concentration = |US_2Y_dv01 + CA_2Y_dv01| / sum(|all_dv01|)`
  - `stress_bp = 5` if event high/rates high/peak breach else `2`
  - `stress_$ = max(|net_dv01|, peak_abs)*stress_bp`
- Warnings:
  - `"front-end risk elevated"` when `front_end_concentration >= 0.60` and event high
  - `"net DV01 elevated"` when `|net_dv01| >= 10000`
  - `"intraday peak DV01 breached cap"` when `peak_abs > cap`

## Where inputs are read from
- Function input: `predictive` dictionary from Phase 8
- `state/last_state.json` constraints summary (risk budget for cap selection)

## Where outputs are written
- `Rates_DV01`:
  - DV01 bucket table starts `A1`
  - `Flow Tape Summary` table starts below inventory table
  - summary metrics table starts below flow summary
- `Desk_Commentary`:
  - append `"Rates DV01"` bullet block with ticket/hedge/peak context
- State:
  - merges `dv01_summary` including:
    - `dv01_peak_abs`
    - `dv01_cap`
    - `hedge_count_rates`
    - `flow_front_end_share`

## How to verify quickly in Excel
1. Open `Rates_DV01` and confirm inventory table reflects post-flow inventory.
2. Confirm `Flow Tape Summary` block exists with tenor counts and net DV01 changes.
3. Confirm summary includes `dv01_cap`, `dv01_peak_abs`, and `hedge_count_rates`.
4. Check `Desk_Commentary` for ticket count, hedge count, and peak DV01 line.

## Smoke test results
- `python phase8_12_smoke_tests.py`: PASS
