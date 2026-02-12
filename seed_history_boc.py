from __future__ import annotations

import argparse
import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from utils.state_store import (
    LAST_STATE_PATH,
    load_last_state,
    load_state_history,
    save_state_history_trimmed,
)


BOC_BASE = "https://www.bankofcanada.ca/valet/observations"
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

CA_2Y_SERIES = "BD.CDN.2YR.DQ.YLD"
CA_10Y_SERIES = "BD.CDN.10YR.DQ.YLD"


def _iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _to_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip()
        if s == "" or s == ".":
            return None
        return float(s)
    except Exception:
        return None


def fetch_boc_series(series_id: str, start_date: str, end_date: str) -> Dict[str, float]:
    """
    Fetch BoC Valet daily series and return {YYYY-MM-DD: value}.
    """
    url = f"{BOC_BASE}/{series_id}/json"
    params = {"start_date": start_date, "end_date": end_date}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    out: Dict[str, float] = {}
    for obs in data.get("observations", []):
        ds = str(obs.get("d") or "").strip()
        vobj = obs.get(series_id)
        if not ds or not isinstance(vobj, dict):
            continue
        v = _to_float(vobj.get("v"))
        if v is None:
            continue
        out[ds] = v
    return out


def _get_fred_key() -> Optional[str]:
    key = os.getenv("FRED_API_KEY")
    if key:
        return key
    env = Path(".env")
    if not env.exists():
        return None
    try:
        for line in env.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("FRED_API_KEY="):
                return s.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        return None
    return None


def fetch_fred_series(series_id: str, start_date: str, end_date: str) -> Dict[str, float]:
    key = _get_fred_key()
    if not key:
        return {}
    params = {
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
        "observation_start": start_date,
        "observation_end": end_date,
        "sort_order": "asc",
    }
    r = requests.get(FRED_BASE, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    out: Dict[str, float] = {}
    for obs in data.get("observations", []):
        ds = str(obs.get("date") or "").strip()
        v = _to_float(obs.get("value"))
        if not ds or v is None:
            continue
        out[ds] = v
    return out


def _base_entry_for_date(ds: str) -> Dict[str, Any]:
    return {
        "date": ds,
        "events_active_count": 0,
        "fx_top_movers_line": None,
        "rates_regime_ca": None,
        "rates_regime_ca_streak": 0,
        "rates_regime_us": None,
        "rates_regime_us_streak": 0,
        "series": {"us_2s10s_bp": None, "ca_2s10s_bp": None},
    }


def _upsert_history(
    history: List[Dict[str, Any]],
    ca_slope: Dict[str, float],
    us_slope: Dict[str, float],
) -> Tuple[List[Dict[str, Any]], int]:
    # De-dup existing by date: keep last occurrence
    by_date: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for e in history:
        ds = str(e.get("date") or "").strip()[:10]
        if not ds:
            continue
        if ds not in by_date:
            order.append(ds)
        by_date[ds] = e

    appended = 0
    all_dates = sorted(set(list(ca_slope.keys()) + list(us_slope.keys())))
    for ds in all_dates:
        if ds not in by_date:
            by_date[ds] = _base_entry_for_date(ds)
            order.append(ds)
            appended += 1
        entry = by_date[ds]
        if not isinstance(entry.get("series"), dict):
            entry["series"] = {"us_2s10s_bp": None, "ca_2s10s_bp": None}

        # Upsert CA if available (including backfill when null)
        if ds in ca_slope:
            cur = _to_float(entry["series"].get("ca_2s10s_bp"))
            if cur is None:
                entry["series"]["ca_2s10s_bp"] = float(ca_slope[ds])

        # Optional US slope
        if ds in us_slope:
            curu = _to_float(entry["series"].get("us_2s10s_bp"))
            if curu is None:
                entry["series"]["us_2s10s_bp"] = float(us_slope[ds])

    out = [by_date[ds] for ds in sorted(by_date.keys())]
    return out, appended


def _update_last_state_from_history(history: List[Dict[str, Any]]) -> None:
    today = _iso(date.today())
    last = load_last_state()

    if last and str(last.get("date") or "")[:10] == today:
        # Preserve today's last_state, just ensure "series" object exists.
        if not isinstance(last.get("series"), dict):
            last["series"] = {"us_2s10s_bp": None, "ca_2s10s_bp": None}
        LAST_STATE_PATH.write_text(json.dumps(last, indent=2, sort_keys=True), encoding="utf-8")
        return

    if not history:
        return

    latest = history[-1]
    if not isinstance(latest.get("series"), dict):
        latest["series"] = {"us_2s10s_bp": None, "ca_2s10s_bp": None}
    LAST_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_STATE_PATH.write_text(json.dumps(latest, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed state history with BoC/FRED slope series.")
    ap.add_argument("--years", type=int, default=2, help="Years of history to seed (default: 2)")
    ap.add_argument("--max-entries", type=int, default=800, help="Retention cap for history (default: 800)")
    args = ap.parse_args()

    end_d = date.today() - timedelta(days=1)
    start_d = end_d - timedelta(days=max(1, int(args.years)) * 365)
    start_date = _iso(start_d)
    end_date = _iso(end_d)

    # Fetch CA series (required)
    y2_ca = fetch_boc_series(CA_2Y_SERIES, start_date, end_date)
    y10_ca = fetch_boc_series(CA_10Y_SERIES, start_date, end_date)
    print(f"CA points fetched: 2Y={len(y2_ca)}, 10Y={len(y10_ca)}")

    ca_slope: Dict[str, float] = {}
    for ds in sorted(set(y2_ca.keys()) & set(y10_ca.keys())):
        ca_slope[ds] = (y10_ca[ds] - y2_ca[ds]) * 100.0
    print(f"CA slope points computed: {len(ca_slope)}")
    if len(ca_slope) == 0:
        print("WARNING: No CA slope points computed (missing overlapping observations).")

    # Fetch optional US slope from FRED
    us_slope: Dict[str, float] = {}
    try:
        y2_us = fetch_fred_series("DGS2", start_date, end_date)
        y10_us = fetch_fred_series("DGS10", start_date, end_date)
        for ds in sorted(set(y2_us.keys()) & set(y10_us.keys())):
            us_slope[ds] = (y10_us[ds] - y2_us[ds]) * 100.0
        if us_slope:
            print(f"US slope points computed (optional): {len(us_slope)}")
        else:
            print("US slope skipped (no FRED key or no overlap).")
    except Exception as e:
        print(f"US slope skipped due to fetch error: {e}")

    history = load_state_history()
    existing_dates = {str(e.get('date') or '')[:10] for e in history if e.get("date")}
    print(f"Existing history dates: {len(existing_dates)}")

    updated, appended = _upsert_history(history, ca_slope=ca_slope, us_slope=us_slope)
    save_state_history_trimmed(updated, max_entries=max(1, int(args.max_entries)))
    final = load_state_history()
    _update_last_state_from_history(final)

    missing_warn = len(set(ca_slope.keys()) - {str(e.get('date') or '')[:10] for e in final})
    print(f"New days appended: {appended}")
    print(f"History entries after trim: {len(final)} (cap={int(args.max_entries)})")
    if missing_warn > 0:
        print(f"WARNING: {missing_warn} computed CA slope dates not present after trim.")


if __name__ == "__main__":
    main()

