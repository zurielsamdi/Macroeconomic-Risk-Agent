# Macroeconomic Risk Agent

A Python framework that generates a daily macro market brief to help traders view the day's key risks, assess market conditions, and evaluate potential trade opportunities before the market opens. The system combines quantitative market analytics with an LLM-driven trade idea engine to produce a structured pre-market report.

## Features

- Monitors US and Canadian yield curves and G10 FX markets
- Scores macroeconomic events by expected market impact
- Identifies market regimes using rolling z-scores, volatility metrics, and historical persistence
- Simulates DV01 stress scenarios to quantify rates risk
- Simulates FX market-making P&L under different market conditions
- Uses an LLM to generate and justify macro trade and hedge ideas subject to predefined risk constraints
- Produces an automated Excel morning report with VBA formatting

## Output

The system generates a daily morning brief containing:

- Macro market summary
- Predictive outlook
- Rates and DV01 risk analysis
- FX market-making simulation
- LLM-generated trade and hedge ideas
- Constraint-filtered trade recommendations

**Architecture:** Python (Analytics + LLM) → Excel → VBA

