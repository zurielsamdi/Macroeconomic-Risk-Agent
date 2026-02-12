Phase 8–12 Requirements Spec (Lock This)
Global rules (apply to ALL phases)

No price direction forecasts. Only:

“risk state likely elevated”

“regime persistence likely/uncertain”

“watchlist + triggers”

Deterministic: Given same last_state.json + same inputs, outputs should match.

Any randomness (FX MM sim) must be seeded by date.

Fail-safe: If a module fails, write:

conservative values

“insufficient data” notes

still produce the Excel file

Explainable: Every probability/label must have a reason list.

PHASE 8 — Predictive State Engine
Purpose

Convert today + memory into probability-weighted risk states and event severity used by phases 9–12.

Inputs

state/last_state.json (today’s snapshot output of phases 1–7)

optionally state/state_history.jsonl (for rolling stats if you already store it)

calendar events for “today ahead” already in state

Outputs

Add predictive section inside state/last_state.json (or write state/predictive_state.json)

Write a Predictive_Outlook block into Excel

Required outputs (exact fields)

Rates (US and CA separately):

regime_persistence_prob ∈ [0.05, 0.95]

rates_vol_risk_label: low/medium/high

rates_vol_risk_prob: 0.25/0.50/0.75 (+ event bump)

front_end_move_prob: same probability bucket logic

confidence_label: low/medium/high

reasons: list[str] (must be non-empty)

FX:

For each G10 pair:

fx_vol_risk_label, fx_vol_risk_prob

risk_off_prob: 0.25/0.50/0.75

reasons: list[str]

Events:

top_events: up to 5 items with

event name, time, country

severity_score int

severity_label low/medium/high

overall_event_severity_label

overall_event_severity_score

Hard parameters (lock these)

Rates “large move” thresholds (bp):

low: max_abs_chg < 3

medium: 3–7

high: > 7

FX daily move thresholds (%):

low: < 0.30%

medium: 0.30–0.80%

high: > 0.80%

Event severity scoring:

base: low=1, med=2, high=3

+2 if event matches top-tier keywords:
["CPI","PCE","NFP","Payroll","Employment","FOMC","Fed","BoC","Rate Decision","GDP","Retail Sales","Inflation"]

+1 if current vol risk is high (rates OR FX)

label: score<=2 low, 3–4 medium, >=5 high

Regime persistence probability formula:

start = 0.55

+0.10 if yesterday regime == today regime

-0.15 if “large move” today (max_abs_chg_bp >= 7)

-0.10 if overall event severity is high

clip to [0.05, 0.95]

Event bump:

If overall event severity high: add +0.10 to vol risk probs (clip to 0.95)

Acceptance tests (must pass)

If tomorrow events include CPI (high) → overall severity = high; vol probs bumped; regime persistence reduced.

If max US chg_bp > 7 → rates vol label high.

PHASE 9 — Rates DV01 Engine
Purpose

Quantify risk like a desk: “Where is my DV01, what happens if front end moves?”

Inputs

today rates data from last_state

predictive event/vol flags from Phase 8

Outputs

dv01 section stored in state

Excel Rates_DV01 table + commentary block

DV01 model (simple but defensible)

Inventory (default, in $mm):

US_2Y +5

US_5Y 0

US_10Y -3

US_30Y 0

CA_2Y +2

CA_5Y 0

CA_10Y 0

CA_30Y 0

DV01 per $1mm (USD per bp):

US_2Y 200

US_5Y 450

US_10Y 850

US_30Y 1600

CA_2Y 180

CA_5Y 420

CA_10Y 800

CA_30Y 1500

Compute

dv01_bucket = inv_mm * dv01_per_mm

net_dv01 = sum(dv01_bucket)

front_end_concentration = |(US_2Y + CA_2Y dv01)| / sum(|all dv01|) (safe if 0)

stress_bp = 5 if event severity high OR rates vol high else 2

stress_$ = |net_dv01| * stress_bp

Trading/risk rules (desk-like)

If front_end_concentration >= 0.60 AND event severity high:

Flag “front-end risk elevated”

Recommend “reduce incremental DV01” in constraints later

If |net_dv01| is large relative to typical (set threshold 10,000 $/bp):

Add “net DV01 elevated” warning

Acceptance tests

front_end_concentration computed and non-NaN

stress_$ increases when event risk high

PHASE 10 — FX Market Making & Hedging
Purpose

Show you understand microstructure + inventory risk. This is a sim, not real trading.

Inputs

pick 1–2 pairs (start USDCAD)

vol/event risk from Phase 8

Outputs

mm section in state:

inventory_end, hedge_actions, avg_spread, liquidity_risk_label

Excel FX_MM_Sim table + commentary block

Sim rules (minimal but real)

Parameters

steps N = 50

seed = hash(date + pair) for determinism

Mid evolution

random walk with sigma by vol label:

low 0.0002

med 0.0005

high 0.0009

Spread

base_spread = 0.0001

multiplier: low 1.0, med 1.5, high 2.5

×1.25 if event severity high

Inventory

each step client flow buy/sell 50/50

size = 1–3 units from RNG

Inventory limit

base_limit 10

if event severity high → limit 6

Hedge rule

if |inv| ≥ 0.8*limit → hedge to flat

count hedge_actions

Liquidity risk label

high if breached OR hedge_actions ≥ 5

med if hedge_actions 2–4

low otherwise

Acceptance tests

event severity high tightens limit

high vol widens spreads

deterministic outputs given same date

PHASE 11 — Trade Constraint Builder (Governor)
Purpose

Turn the system into a disciplined “idea space,” so the LLM can’t freestyle.

Inputs

predictive (phase 8)

dv01 (phase 9)

mm (phase 10)

Output

constraints object stored in state + saved to JSON

Optional Excel summary

Constraint rules (lock these)

event_risk_level = overall_event_severity_label
volatility_regime = max(rates_vol_label, max_fx_vol_label)

directional_bias_allowed

false if event risk high OR volatility high

risk_budget

low if event risk high OR liquidity risk high

medium if volatility medium

high only if event low AND vol low AND liquidity low

max_trades

2 if risk low

3 if medium

4 if high

max_incremental_dv01

500 low

1500 medium

3000 high

allowed_instruments

only instruments you actually support:

FX pairs present in your state

(optional) “US 2s10s steepener (conceptual)” as a label ONLY

ETFs only if your project already uses them elsewhere

regime_alignment_required = true

Acceptance tests

if event risk high and vol high:

directional_bias_allowed must be false

risk_budget must be low

PHASE 12 — LLM Commentary + Trade Ideas
Purpose

Generate human-quality commentary + trade ideas constrained by Phase 11.

Inputs

current state snapshot + memory delta summary

predictive + dv01 + mm

constraints object

Output

One JSON payload validated and written to:

Desk_Commentary sheet

Email draft (later phase 13)

Strict JSON schema (must enforce)

Output must include:

rates_commentary (3–6 bullets)

fx_commentary

calendar_commentary

headline_summary

predictive_outlook

trade_ideas list length ≤ max_trades, where each item has:

setup

expression (must use allowed instrument)

trigger

risks

invalidation

why_fits_constraints

dv01_impact: increase/neutral/decrease

liquidity_sensitivity: low/medium/high

confidence: low/medium/high

Validation gate (non-negotiable)

Reject & retry once if:

invalid JSON

instrument not allowed

directional_bias_allowed false but idea is “buy/sell outright” (directional)

violates max_trades

Fallback if still invalid:

trade_ideas=[]

watchlist triggers only

“No trades due to elevated risk” text