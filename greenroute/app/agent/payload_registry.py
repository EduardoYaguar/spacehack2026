"""
payload_registry.py — Authoritative mapping of corridor IDs to satellite grid JSON files.

Each corridor has one or more temporal snapshots.  The default window is always
the most recent one (P1 for aviation/trucking, "latest" for maritime).

Folder structure (relative to workspace root = spacehack2026/):
┌─────────────────────┬────────────────────────────────────────────────────────────────┐
│ Mode                │ Paths                                                          │
├─────────────────────┼────────────────────────────────────────────────────────────────┤
│ maritime  SGP_PKL   │ latest/maritime_portklang_singapore.json    (most recent)       │
│                     │ latest-1/maritime_portklang_singapore.json                      │
│                     │ latest-2/maritime_portklang_singapore.json                      │
├─────────────────────┼────────────────────────────────────────────────────────────────┤
│ aviation  PVG_DXB_  │ aereo/p1/aviation_payload_p1.json          (P1 – most recent)  │
│           AMS       │ aereo/p2/aviation_payload_p2.json          (P2)                │
│                     │ aereo/p3/aviation_payload_p3.json          (P3 – oldest)       │
├─────────────────────┼────────────────────────────────────────────────────────────────┤
│ trucking  NYNJ_SAV  │ terrestre_usa/p1/terrestrial_usa_p1.json   (P1 – most recent)  │
│                     │ terrestre_usa/p2/terrestrial_usa_p2.json   (P2)                │
│                     │ terrestre_usa/p3/terrestrial_usa_p3.json   (P3 – oldest)       │
└─────────────────────┴────────────────────────────────────────────────────────────────┘

Usage
─────
    from app.agent.payload_registry import resolve_payload, list_payloads

    # Most recent payload for a corridor (default behaviour)
    path = resolve_payload("SGP_PKL")           # → absolute path to latest maritime JSON
    path = resolve_payload("PVG_DXB_AMS")       # → absolute path to aereo/p1/...
    path = resolve_payload("NYNJ_SAV")          # → absolute path to terrestre_usa/p1/...

    # Specific temporal window
    path = resolve_payload("PVG_DXB_AMS", window="P2")   # → aereo/p2/aviation_payload_p2.json
    path = resolve_payload("SGP_PKL", window="latest-1")  # → latest-1/maritime_...json

    # Inspect available windows for a corridor
    windows = list_payloads("PVG_DXB_AMS")
    # → [("P1", <abs_path>), ("P2", <abs_path>), ("P3", <abs_path>)]
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Workspace root (spacehack2026/)  — all relative payload paths resolve here
# ---------------------------------------------------------------------------
_WORKSPACE = Path(__file__).resolve().parents[3]   # greenroute/app/agent/ → spacehack2026/


# ---------------------------------------------------------------------------
# Registry definition
# Each entry:
#   "mode"     : transport mode string matching the JSON's top-level "mode" field
#   "payloads" : ordered dict of {window_label: relative_path}, newest first
#   "default"  : window_label to use when no specific window is requested
# ---------------------------------------------------------------------------
_REGISTRY: dict[str, dict] = {
    # ── Maritime: Port Klang ↔ Singapore ───────────────────────────────────
    "SGP_PKL": {
        "mode": "maritime",
        "payloads": {
            "latest":   "latest/maritime_portklang_singapore.json",
            "latest-1": "latest-1/maritime_portklang_singapore.json",
            "latest-2": "latest-2/maritime_portklang_singapore.json",
        },
        "default": "latest",
    },

    # ── Aviation: Shanghai (PVG) → Dubai (DXB) → Amsterdam (AMS) ──────────
    "PVG_DXB_AMS": {
        "mode": "aviation",
        "payloads": {
            "P1": "aereo/p1/aviation_payload_p1.json",
            "P2": "aereo/p2/aviation_payload_p2.json",
            "P3": "aereo/p3/aviation_payload_p3.json",
        },
        "default": "P1",
    },

    # ── Trucking: Port NY/NJ (Newark) → Port of Savannah ──────────────────
    "NYNJ_SAV": {
        "mode": "trucking",
        "payloads": {
            "P1": "terrestre_usa/p1/terrestrial_usa_p1.json",
            "P2": "terrestre_usa/p2/terrestrial_usa_p2.json",
            "P3": "terrestre_usa/p3/terrestrial_usa_p3.json",
        },
        "default": "P1",
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_payload(
    corridor_id: str,
    window: Optional[str] = None,
    *,
    must_exist: bool = True,
) -> str:
    """
    Return the absolute path to the satellite grid JSON for a corridor.

    Args:
        corridor_id : One of "SGP_PKL", "PVG_DXB_AMS", "NYNJ_SAV".
        window      : Temporal window label ("P1"/"P2"/"P3" for aviation/trucking;
                      "latest"/"latest-1"/"latest-2" for maritime).
                      If None, the most recent snapshot is returned.
        must_exist  : If True (default), raises FileNotFoundError when the file
                      is absent from disk.  Set to False to get the expected path
                      even if the file hasn't been generated yet.

    Returns:
        Absolute path string to the grid JSON file.

    Raises:
        ValueError        — unknown corridor_id or unknown window label.
        FileNotFoundError — file not found on disk (only when must_exist=True).
    """
    if corridor_id not in _REGISTRY:
        raise ValueError(
            f"Unknown corridor '{corridor_id}'. "
            f"Available: {sorted(_REGISTRY)}"
        )

    entry = _REGISTRY[corridor_id]
    label = window or entry["default"]

    if label not in entry["payloads"]:
        raise ValueError(
            f"Unknown window '{label}' for corridor '{corridor_id}'. "
            f"Available windows: {list(entry['payloads'])}"
        )

    rel_path = entry["payloads"][label]
    abs_path = _WORKSPACE / rel_path

    if must_exist and not abs_path.exists():
        raise FileNotFoundError(
            f"Grid payload not found on disk: {abs_path}\n"
            f"(corridor={corridor_id}, window={label}, relative={rel_path})"
        )

    return str(abs_path)


def resolve_payload_fallback(corridor_id: str) -> str:
    """
    Return the absolute path to the first available snapshot for a corridor,
    trying windows in newest-first order.

    Useful when only some temporal windows exist on disk (e.g., partial data
    pipeline runs).  Raises FileNotFoundError if NO window file exists.
    """
    if corridor_id not in _REGISTRY:
        raise ValueError(
            f"Unknown corridor '{corridor_id}'. "
            f"Available: {sorted(_REGISTRY)}"
        )

    entry = _REGISTRY[corridor_id]
    for label, rel_path in entry["payloads"].items():
        abs_path = _WORKSPACE / rel_path
        if abs_path.exists():
            return str(abs_path)

    raise FileNotFoundError(
        f"No grid payload found for corridor '{corridor_id}'. "
        f"Searched paths: {[str(_WORKSPACE / p) for p in entry['payloads'].values()]}"
    )


def list_payloads(corridor_id: str) -> list[tuple[str, str, bool]]:
    """
    List all defined temporal windows for a corridor.

    Returns:
        List of (window_label, absolute_path, exists_on_disk) tuples,
        ordered newest-first.
    """
    if corridor_id not in _REGISTRY:
        raise ValueError(f"Unknown corridor '{corridor_id}'. Available: {sorted(_REGISTRY)}")

    entry = _REGISTRY[corridor_id]
    return [
        (label, str(_WORKSPACE / rel), (_WORKSPACE / rel).exists())
        for label, rel in entry["payloads"].items()
    ]


def get_mode(corridor_id: str) -> str:
    """Return the transport mode for a corridor ('maritime'|'aviation'|'trucking')."""
    if corridor_id not in _REGISTRY:
        raise ValueError(f"Unknown corridor '{corridor_id}'. Available: {sorted(_REGISTRY)}")
    return _REGISTRY[corridor_id]["mode"]


def all_corridors() -> list[str]:
    """Return all registered corridor IDs."""
    return list(_REGISTRY)
