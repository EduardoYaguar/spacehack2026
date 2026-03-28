"""
baseline_service.py — Corridor baseline tracking.

Reads and updates baselines.json after each pipeline run.
Tracks:
  - no2_mean        : exponential moving average of grid-mean NO₂
  - no2_std         : exponential moving std (initialised to 1e-5)
  - consecutive_warn: count of consecutive WARN/RED badges
  - last_badge      : most recent badge issued
  - audit_log       : rolling list of the last MAX_AUDIT_ENTRIES runs (newest-last)

Usage:
    baselines = load_baselines(path)
    baselines = update_baselines(baselines, corridor_id, satellite_report, badge)
    save_baselines(baselines, path)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Exponential moving average smoothing factor (0.1 = slow adaptation)
_EMA_ALPHA = 0.10
# Maximum audit log entries kept per corridor
_MAX_AUDIT_ENTRIES = 100


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def load_baselines(path: str | Path) -> dict:
    """
    Load baselines.json.  Returns an empty dict if the file is absent or invalid.
    """
    fpath = Path(path)
    if not fpath.exists():
        logger.warning("baselines.json not found at %s — starting empty.", fpath)
        return {}
    try:
        with fpath.open() as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning("baselines.json has unexpected format — resetting.")
            return {}
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load baselines.json: %s", exc)
        return {}


def save_baselines(baselines: dict, path: str | Path) -> None:
    """Persist baselines dict to JSON (atomic write via temp file)."""
    fpath = Path(path)
    fpath.parent.mkdir(parents=True, exist_ok=True)
    tmp = fpath.with_suffix(".tmp")
    try:
        with tmp.open("w") as f:
            json.dump(baselines, f, indent=2, default=str)
        tmp.replace(fpath)
    except OSError as exc:
        logger.error("Failed to save baselines.json: %s", exc)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def update_baselines(
    baselines: dict,
    corridor_id: str,
    satellite_report: dict,
    badge: str,
) -> dict:
    """
    Update the baseline entry for corridor_id with the latest run results.

    Args:
        baselines       : The dict loaded from baselines.json.
        corridor_id     : e.g. "SGP_PKL".
        satellite_report: The SatelliteReport dict from the satellite_analyst node.
        badge           : Final badge string from GreenRouteDecision ("GREEN"/"WARN"/"RED").

    Returns:
        The updated baselines dict (mutates in place and returns it).
    """
    entry = baselines.setdefault(corridor_id, _empty_entry())

    # ── Update NO₂ EMA ───────────────────────────────────────────────────────
    new_no2 = _extract_no2_mean(satellite_report)
    if new_no2 is not None:
        old_mean = float(entry.get("no2_mean") or 0.0)
        old_std  = float(entry.get("no2_std")  or 1e-5)

        new_mean = _ema(old_mean, new_no2, _EMA_ALPHA)
        new_std  = _ema_std(old_std, new_no2, new_mean, _EMA_ALPHA)

        entry["no2_mean"] = round(new_mean, 10)
        entry["no2_std"]  = round(max(new_std, 1e-7), 10)

    # ── Consecutive WARN/RED counter ─────────────────────────────────────────
    prev_badge = entry.get("last_badge")
    if badge in ("WARN", "RED"):
        entry["consecutive_warn"] = int(entry.get("consecutive_warn") or 0) + 1
    else:
        entry["consecutive_warn"] = 0

    entry["last_badge"]   = badge
    entry["last_run_at"]  = datetime.now(timezone.utc).isoformat()

    # ── Audit log ─────────────────────────────────────────────────────────────
    audit_entry: dict[str, Any] = {
        "timestamp":    entry["last_run_at"],
        "badge":        badge,
        "prev_badge":   prev_badge,
        "no2_value":    new_no2,
        "overall_score": satellite_report.get("overall_score"),
    }
    log: list = entry.setdefault("audit_log", [])
    log.append(audit_entry)
    # Keep only the last N entries
    if len(log) > _MAX_AUDIT_ENTRIES:
        entry["audit_log"] = log[-_MAX_AUDIT_ENTRIES:]

    return baselines


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _empty_entry() -> dict:
    return {
        "no2_mean":        0.0,
        "no2_std":         1e-5,
        "consecutive_warn": 0,
        "last_badge":      None,
        "last_run_at":     None,
        "audit_log":       [],
    }


def _extract_no2_mean(satellite_report: dict) -> float | None:
    """Extract grid-mean NO₂ from the satellite report dict, or None if absent."""
    # Try layer_results first (structured per-layer dict)
    layer_results = satellite_report.get("layer_results") or {}
    if "no2_mol_m2" in layer_results:
        val = layer_results["no2_mol_m2"].get("mean")
        if val is not None:
            return float(val)

    # Fallback: overall_score as a proxy (not the same unit, but better than nothing)
    return None


def _ema(old: float, new: float, alpha: float) -> float:
    """Exponential moving average."""
    return old + alpha * (new - old)


def _ema_std(old_std: float, new_val: float, new_mean: float, alpha: float) -> float:
    """Welford-style EMA standard deviation approximation."""
    diff = new_val - new_mean
    return (1 - alpha) * old_std + alpha * abs(diff)
