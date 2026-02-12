from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional, List


STATE_DIR = Path("state")
LAST_STATE_PATH = STATE_DIR / "last_state.json"
HISTORY_PATH = STATE_DIR / "state_history.jsonl"


def _ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def load_last_state() -> Optional[Dict[str, Any]]:
    _ensure_state_dir()
    if not LAST_STATE_PATH.exists():
        return None
    try:
        return json.loads(LAST_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_state(state: Dict[str, Any], also_append_history: bool = True) -> None:
    _ensure_state_dir()
    LAST_STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    if also_append_history:
        entries = load_state_history()
        entries.append(state)
        save_state_history_trimmed(entries, max_entries=365)


def load_state_history() -> List[Dict[str, Any]]:
    _ensure_state_dir()
    if not HISTORY_PATH.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            out.append(json.loads(s))
        except Exception:
            continue
    return out


def save_state_history_trimmed(entries: List[Dict[str, Any]], max_entries: int = 365) -> None:
    """
    Persist state history as JSONL with bounded growth.
    Uses atomic replace to avoid partial writes.
    """
    _ensure_state_dir()
    keep = entries[-max_entries:] if len(entries) > max_entries else list(entries)
    tmp = HISTORY_PATH.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for e in keep:
            f.write(json.dumps(e) + "\n")
    os.replace(tmp, HISTORY_PATH)


def merge_state(
    updates: Dict[str, Any],
    also_append_history: bool = False,
) -> Dict[str, Any]:
    """
    Merge updates into last_state and persist.
    Dict values merge one level deep; scalars overwrite.
    Returns the merged state payload.
    """
    base = load_last_state() or {}
    for k, v in updates.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            merged = dict(base[k])
            merged.update(v)
            base[k] = merged
        else:
            base[k] = v
    save_state(base, also_append_history=also_append_history)
    return base


def safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if s == "":
            return None
        # handle "85 bp" style
        s = s.replace("bp", "").replace("bps", "").strip()
        return float(s)
    except Exception:
        return None


def delta(a: Optional[float], b: Optional[float]) -> Optional[float]:
    # a = today, b = yesterday
    if a is None or b is None:
        return None
    return a - b


def fmt_delta(x: Optional[float], unit: str = "") -> str:
    if x is None:
        return "n/a"
    sign = "+" if x > 0 else ""
    if unit:
        return f"{sign}{x:.2f}{unit}"
    return f"{sign}{x:.2f}"
