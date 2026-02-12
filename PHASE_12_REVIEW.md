# Phase 12 Review

## Files changed
- `phase12_commentary.py`
- `run_morning_agent.py` (orchestration call)
- `utils/state_store.py` (merge helpers used for final append)
- `utils/excel_writer.py` (bullet block helper)
- `phase8_12_smoke_tests.py` (cleanup verification)

## New functions + signatures
- `phase12_commentary.py::run_phase12_commentary(wb, constraints, now_str) -> dict`
- Helpers:
  - `_load_api_key()`
  - `_extract_headlines(wb, n=5)`
  - `_build_templated_payload(constraints, state, headlines)`
  - `_build_morning_note_lines(payload, state, constraints)`
  - `_save_payload_json(payload, now_str)`
  - `_validate_payload(payload, constraints) -> (bool, reason)`
  - `_call_openai(prompt, api_key) -> dict`
  - `_render_morning_note(ws, lines)`

## Exact parameters/thresholds implemented
- API behavior:
  - if `OPENAI_API_KEY` exists, attempt OpenAI JSON generation (retry once on validation fail)
  - if key missing/API failure/validation failure, use deterministic templated JSON fallback
- Validation gate:
  - required top-level keys enforced
  - `trade_ideas` type + `len <= max_trades`
  - each trade idea must contain required schema keys
  - expression must include an allowed instrument
  - if `directional_bias_allowed=false`, rejects directional outright buy/sell ideas
- Fallback:
  - `trade_ideas=[]`
  - watchlist triggers populated
  - `"No trades due to elevated risk"` note when constrained
- Presentation cleanup:
  - no raw payload JSON is written into Excel cells
  - desk-facing header is `=== Morning Note (Auto) ===`
  - MM wording uses:
    - `"Deterministic (date+pair) seed"`
    - `"Inventory limit breached"` / `"No inventory breach"`
    - spread displayed with pips label
- Flows & Microstructure narrative:
  - adds concise block (3 bullets) summarizing:
    - FX session hedging/spread profile (Asia/London/NY)
    - event-window microstructure impact when triggered
    - rates flow profile (front-end share, hedge count, peak DV01)

## Where inputs are read from
- Constraints from Phase 11 function input
- State summaries from `state/last_state.json`:
  - `predictive_summary`, `dv01_summary`, `mm_summary`
- Headlines from `Headlines` sheet:
  - column `D` (`Title`) rows starting at row `5`

## Where outputs are written
- `Desk_Commentary`:
  - appends a single readable `"=== Morning Note (Auto) ==="` block
  - no raw JSON dump in cells
- State:
  - writes raw payload file: `state/llm_payload_YYYY-MM-DD.json`
  - merges `llm_summary` into `last_state.json`:
    - `trade_count`
    - `meta_note`
    - `watchlist_triggers`
    - `risk_state_labels`
    - `payload_path`
    - `fallback_used`
  - appends final enriched line to `state/state_history.jsonl` containing:
    - predictive summary
    - dv01 summary
    - mm summary
    - constraints summary

## How to verify quickly in Excel
1. Open `Desk_Commentary` and find `=== Morning Note (Auto) ===`.
2. Confirm there is no raw JSON block (no `{`-prefixed lines from payload dump).
3. Confirm FX MM lines use desk wording (`Deterministic (date+pair) seed`, inventory breach sentence).
4. Confirm `state/llm_payload_YYYY-MM-DD.json` exists and contains full payload JSON.
5. Confirm `state/last_state.json` has `llm_summary` with compact fields.
6. Confirm Morning Note includes `Flows & Microstructure` with 3 trader-readable bullets.

## Before/After (concise)
- Before: Phase 12 appended commentary plus full raw JSON payload into `Desk_Commentary`.
- After: `Desk_Commentary` contains only a trader-readable Morning Note; raw payload moved to dated file in `state/` for reproducibility/debug.

## Smoke test results
- `python phase8_12_smoke_tests.py`: PASS
- Phase 12 cleanup checks:
  - dated payload file is created
  - Morning Note header exists
  - no raw JSON opening brace in generated note lines
  - `Flows & Microstructure` marker exists in generated lines
