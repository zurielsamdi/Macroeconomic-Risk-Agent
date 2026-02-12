import requests

GROUP_BONDS = "https://www.bankofcanada.ca/valet/observations/group/bond_yields_benchmark/json"
GROUP_TBILLS = "https://www.bankofcanada.ca/valet/observations/group/tbill_tuesday/json"


def fetch_latest_and_prev_from_group(group_url: str, series_id: str) -> tuple[tuple[str, float], tuple[str, float]]:
    """
    Fetch latest + previous non-empty observations for a series from a BoC group endpoint.
    """
    r = requests.get(group_url, timeout=20)
    r.raise_for_status()
    data = r.json()

    obs = data.get("observations", [])
    values = []

    for o in obs:
        vobj = o.get(series_id)
        if not vobj:
            continue
        v = vobj.get("v")
        if v in (None, ""):
            continue
        values.append((o["d"], float(v)))

    if len(values) < 2:
        raise RuntimeError(f"Not enough valid observations for {series_id}")

    return values[-1], values[-2]

