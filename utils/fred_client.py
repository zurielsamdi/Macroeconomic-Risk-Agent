import os
from datetime import date, timedelta
import requests
from dotenv import load_dotenv

BASE_URL = "https://api.stlouisfed.org/fred/series/observations"


def _get_fred_key() -> str:
    load_dotenv()
    key = os.getenv("FRED_API_KEY")
    if not key:
        raise RuntimeError("FRED_API_KEY not found in .env")
    return key


def fetch_latest_and_prev(series_id: str) -> tuple[tuple[str, float], tuple[str, float]]:
    """
    Fetches the latest observation and the previous observation for a FRED series.

    Returns:
      ((latest_date, latest_value), (prev_date, prev_value))

    Why:
    - We need the latest yield and the day-over-day change.
    """
    key = _get_fred_key()

    params = {
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 10,  # enough to skip '.' missing values
    }

    r = requests.get(BASE_URL, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()

    obs = data.get("observations", [])
    clean = []
    for o in obs:
        v = o.get("value")
        if v is None or v == ".":
            continue
        clean.append((o["date"], float(v)))

    if len(clean) < 2:
        raise RuntimeError(f"Not enough valid observations for {series_id}")

    latest = clean[0]
    prev = clean[1]
    return latest, prev
