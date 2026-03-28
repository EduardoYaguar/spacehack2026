"""
judge_tools.py — Tools for the CertificationJudge agent (Agent 3).

Two tools verify whether a vehicle followed the greenest recommended route:

  check_track_compliance
      Compares an AIS/ADS-B vehicle track against the corridor spine
      (origin → mandatory waypoints → destination) and the pre-computed
      green_score layer in the grid JSON.

      Outputs:
        • compliance_pct          — fraction of track within the mode-specific
                                    corridor width tolerance
        • deviation_mean_km       — mean cross-track distance from corridor spine
        • track_mean_green_score  — avg green_score of cells visited
        • green_score_delta       — track_mean - optimal_green_score (positive = better)
        • track_on_navigable_pct  — fraction of track on navigable cells (water/road)
        • verdict                 — "COMPLIANT" | "PARTIAL" | "NON_COMPLIANT"

  verify_waypoint_passage
      Checks whether a vehicle passed within the passage_radius of each
      mandatory waypoint for the corridor.

      Outputs:
        • waypoints_confirmed     — list of waypoint names passed
        • waypoints_missed        — list of waypoint names not passed
        • passage_details         — per-waypoint closest approach distance and coords

Both tools handle the case where no vehicle track is provided
(e.g., scheduler trigger, corridor-only assessment): they return the
corridor's environmental quality profile without a compliance decision.

Default passage radii (conservative):
  maritime  : 55 km   (5 grid cells at 11 km)
  aviation  : 166 km  (1.5 grid cells at 111 km)
  trucking  :  28 km  (5 grid cells at 5.6 km)
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from app.config import get_corridor_config


# ---------------------------------------------------------------------------
# Module-level grid JSON cache (shared with satellite_tools — keyed by path)
# ---------------------------------------------------------------------------
_grid_cache: dict[str, dict[str, Any]] = {}


def _load_grid(grid_path: str) -> dict[str, Any]:
    if grid_path in _grid_cache:
        return _grid_cache[grid_path]
    path = Path(grid_path)
    if not path.exists():
        workspace = Path(__file__).resolve().parents[4]
        alt = workspace / grid_path
        if alt.exists():
            path = alt
        else:
            return {"_error": f"Grid file not found: {grid_path}"}
    with open(path) as f:
        data = json.load(f)
    _grid_cache[str(path)] = data
    _grid_cache[grid_path] = data
    return data


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(min(a, 1.0)))


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing in degrees (0–360)."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = (math.cos(lat1) * math.sin(lat2)
         - math.sin(lat1) * math.cos(lat2) * math.cos(dlon))
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _cross_track_km(
    pt_lat: float, pt_lon: float,
    a_lat: float, a_lon: float,
    b_lat: float, b_lon: float,
) -> float:
    """
    Minimum distance (km) from point P to great-circle segment A→B.

    Uses the spherical cross-track / along-track formula.
    If the foot of the perpendicular falls outside the segment, returns
    the distance to the nearer endpoint.
    """
    R = 6371.0
    d_ab  = _haversine(a_lat, a_lon, b_lat, b_lon)
    d_apt = _haversine(a_lat, a_lon, pt_lat, pt_lon)

    if d_ab < 1e-6:        # degenerate segment
        return d_apt

    brng_ab  = _bearing(a_lat, a_lon, b_lat, b_lon)
    brng_apt = _bearing(a_lat, a_lon, pt_lat, pt_lon)

    angle_diff = math.radians(brng_apt - brng_ab)
    # Cross-track (perpendicular) distance
    dxt = abs(math.asin(max(-1.0, min(1.0,
        math.sin(d_apt / R) * math.sin(angle_diff)
    ))) * R)

    # Along-track distance — check the foot is inside [A, B]
    cos_dxt = math.cos(dxt / R)
    if abs(cos_dxt) < 1e-12:
        return dxt
    dat = math.acos(max(-1.0, min(1.0,
        math.cos(d_apt / R) / cos_dxt
    ))) * R

    if dat <= d_ab:
        return dxt
    # Foot is past B — return distance to the nearer endpoint
    return min(d_apt, _haversine(b_lat, b_lon, pt_lat, pt_lon))


def _min_spine_distance(
    pt_lat: float, pt_lon: float,
    spine: list[tuple[float, float]],
) -> float:
    """Return the minimum cross-track distance (km) from point to any spine segment."""
    if len(spine) < 2:
        if spine:
            return _haversine(pt_lat, pt_lon, spine[0][0], spine[0][1])
        return 0.0
    return min(
        _cross_track_km(pt_lat, pt_lon, spine[i][0], spine[i][1],
                        spine[i + 1][0], spine[i + 1][1])
        for i in range(len(spine) - 1)
    )


def _cell_center(row: int, col: int, gdef: dict) -> tuple[float, float]:
    cs  = gdef["cell_size_degrees"]
    lat = gdef["bounds"]["north"] - row * cs - cs / 2
    lon = gdef["bounds"]["west"]  + col * cs + cs / 2
    return lat, lon


def _coords_to_cell(lat: float, lon: float, gdef: dict) -> tuple[int, int]:
    cs  = gdef["cell_size_degrees"]
    row = int((gdef["bounds"]["north"] - lat) / cs)
    col = int((lon - gdef["bounds"]["west"]) / cs)
    row = max(0, min(gdef["rows"] - 1, row))
    col = max(0, min(gdef["cols"] - 1, col))
    return row, col


# ---------------------------------------------------------------------------
# Corridor spine builder
# ---------------------------------------------------------------------------

def _build_corridor_spine(
    data: dict,
    corridor_id: str,
) -> list[tuple[float, float]]:
    """
    Build the corridor spine as an ordered list of (lat, lon) checkpoints:
        origin → mandatory waypoints (in order) → destination

    Sources:
      - origin / destination: read from the grid JSON
      - waypoints: read from corridor config (most authoritative)
      - Aviation fallback: grid JSON `waypoint` field
    """
    origin = data.get("origin", {})
    dest   = data.get("destination", {})
    spine: list[tuple[float, float]] = [
        (float(origin.get("lat", 0)), float(origin.get("lon", 0)))
    ]

    # Mandatory waypoints from corridor config
    try:
        cfg = get_corridor_config(corridor_id)
        for w in cfg.waypoints:
            spine.append((w.lat, w.lon))
    except Exception:
        # Fallback: aviation grid JSON has a single `waypoint` field
        wp = data.get("waypoint")
        if wp:
            spine.append((float(wp["lat"]), float(wp["lon"])))

    spine.append((float(dest.get("lat", 0)), float(dest.get("lon", 0))))
    return spine


# ---------------------------------------------------------------------------
# Mode-aware default tolerances
# ---------------------------------------------------------------------------

_DEFAULT_TOLERANCE_KM: dict[str, float] = {
    # Maritime (SGP↔PKL): strait is narrow; optimal path deviates ≤35 km from
    # the great-circle spine. 55 km allows for AIS positional drift.
    "maritime": 55.0,

    # Aviation (PVG→DXB→AMS): jet-stream-optimised A* path deviates up to
    # 984 km north of the PVG→DXB→AMS great-circle spine (Central Asian
    # routing). Spine-based tolerance is not meaningful here — set to 1 200 km
    # so compliance_pct is always ~100 %.  Authoritative signals for aviation
    # are waypoint passage + green_score delta.
    "aviation": 1200.0,

    # Trucking (NY/NJ→Savannah): I-95 curves up to 65 km from the straight
    # line between Newark and Savannah. 75 km covers the full road corridor.
    "trucking": 75.0,
}

_DEFAULT_PASSAGE_RADIUS_KM: dict[str, float] = {
    "maritime": 55.0,    # 5 grid cells × 11 km
    "aviation": 166.0,   # 1.5 grid cells × 111 km — generous for ADS-B coverage gaps
    "trucking": 28.0,    # 5 grid cells × 5.6 km
}


# ---------------------------------------------------------------------------
# Tool 1 — check_track_compliance
# ---------------------------------------------------------------------------

@tool
def check_track_compliance(
    grid_path: str,
    corridor_id: str,
    vehicle_track: list,
    optimal_green_score: float,
    tolerance_km: float = 0.0,
) -> dict:
    """
    Compare an AIS/ADS-B vehicle track against the corridor's optimal green route.

    Measures two independent dimensions of compliance:
      1. Geographic compliance: what fraction of track positions fell within
         `tolerance_km` of the corridor spine (origin→waypoints→destination).
      2. Environmental quality: the mean green_score of the grid cells the
         vehicle actually traversed vs the optimal route's green_score.

    Handles the case where no vehicle track is provided (corridor-only assessment):
    returns the corridor's environmental quality profile with compliance_pct = None.

    Business rules applied automatically:
      - tolerance_km defaults to the mode-specific corridor width
        (maritime 55 km, aviation 166 km, trucking 28 km) when 0 is passed.
      - Track points outside the grid bounds are counted as off-corridor.
      - Null green_score cells (land, non-road) are excluded from the
        green_score mean; track_on_navigable_pct reports their fraction.

    Args:
        grid_path:            Absolute path to the grid JSON file.
        corridor_id:          One of "SGP_PKL", "PVG_DXB_AMS", "NYNJ_SAV".
        vehicle_track:        List of position dicts, each with at least "lat"
                              and "lon" keys (AIS/ADS-B records).
                              Pass [] when no vehicle track is available.
        optimal_green_score:  Green score of the CorridorOptimizer's optimal
                              path (from route_recommendation).
        tolerance_km:         Cross-track tolerance in km.  Pass 0 to use the
                              mode-specific default.
    """
    data = _load_grid(grid_path)
    if "_error" in data:
        return {"status": "error", "message": data["_error"]}

    mode   = data.get("mode", "maritime")
    gdef   = data["grid_definition"]

    # Tolerance
    tol_km = tolerance_km if tolerance_km > 0 else _DEFAULT_TOLERANCE_KM.get(mode, 55.0)

    # Green score layer (trucking: derived_layers; others: layers)
    gs_layer = (
        data.get("derived_layers", {}).get("green_score")
        or data.get("layers", {}).get("green_score")
        or {}
    )
    gs_data: list[list] = gs_layer.get("data", [])

    # Corridor spine
    spine = _build_corridor_spine(data, corridor_id)

    # ── No track provided ────────────────────────────────────────────────────
    if not vehicle_track:
        # Return corridor-level environmental context only
        gs_values = [v for row in gs_data for v in row if v is not None]
        corridor_mean = round(sum(gs_values) / len(gs_values), 2) if gs_values else None
        return {
            "status": "ok",
            "mode": mode,
            "no_track_provided": True,
            "corridor_mean_green_score": corridor_mean,
            "optimal_green_score": optimal_green_score,
            "compliance_pct": None,
            "deviation_mean_km": None,
            "track_mean_green_score": None,
            "green_score_delta": None,
            "track_on_navigable_pct": None,
            "verdict": "NO_TRACK",
            "notes": (
                "No vehicle track provided. Corridor environmental quality reported. "
                "Certification requires an AIS/ADS-B track."
            ),
        }

    # ── Analyse track ─────────────────────────────────────────────────────────
    within_tolerance: list[bool] = []
    deviations: list[float]      = []
    track_gs_values: list[float] = []
    navigable_count              = 0
    in_bounds_count              = 0
    off_corridor_segments: list[dict] = []

    for i, pt in enumerate(vehicle_track):
        try:
            pt_lat = float(pt["lat"])
            pt_lon = float(pt["lon"])
        except (KeyError, ValueError, TypeError):
            continue

        # Cross-track deviation from corridor spine
        dev_km = _min_spine_distance(pt_lat, pt_lon, spine)
        deviations.append(dev_km)
        compliant = dev_km <= tol_km
        within_tolerance.append(compliant)
        if not compliant:
            off_corridor_segments.append({
                "track_index": i,
                "lat": round(pt_lat, 5),
                "lon": round(pt_lon, 5),
                "deviation_km": round(dev_km, 2),
            })

        # Green score at this grid cell
        bounds = gdef["bounds"]
        if (bounds["south"] <= pt_lat <= bounds["north"]
                and bounds["west"] <= pt_lon <= bounds["east"]):
            in_bounds_count += 1
            row, col = _coords_to_cell(pt_lat, pt_lon, gdef)
            if gs_data and row < len(gs_data) and col < len(gs_data[row]):
                gs_val = gs_data[row][col]
                if gs_val is not None:
                    track_gs_values.append(float(gs_val))
                    navigable_count += 1

    if not deviations:
        return {
            "status": "error",
            "message": "No valid lat/lon positions found in vehicle_track.",
        }

    n = len(deviations)
    compliance_pct = round(100.0 * sum(within_tolerance) / n, 1)
    deviation_mean = round(sum(deviations) / n, 2)
    navigable_pct  = round(100.0 * navigable_count / max(in_bounds_count, 1), 1)

    track_mean_gs: float | None = None
    gs_delta: float | None      = None
    if track_gs_values:
        track_mean_gs = round(sum(track_gs_values) / len(track_gs_values), 2)
        gs_delta = round(track_mean_gs - optimal_green_score, 2)

    # Verdict thresholds
    if compliance_pct >= 85:
        verdict = "COMPLIANT"
    elif compliance_pct >= 70:
        verdict = "PARTIAL"
    else:
        verdict = "NON_COMPLIANT"

    notes: list[str] = []
    if mode == "aviation":
        notes.append(
            "Aviation compliance_pct uses a 1 200 km spine tolerance "
            "because jet-stream routing deviates up to 984 km from the great-circle. "
            "Use waypoint passage + green_score_delta as primary compliance signals."
        )
    if mode == "maritime" and track_mean_gs and track_mean_gs < 45:
        notes.append("Track passed through RED-score cells — high-emission lane detected.")
    if mode == "trucking" and navigable_pct < 80:
        notes.append(
            f"Only {navigable_pct:.0f}% of track on mapped road cells — "
            "possible off-highway routing."
        )

    # Limit off_corridor_segments to first 10 for readability
    return {
        "status": "ok",
        "mode": mode,
        "no_track_provided": False,
        "track_points_analysed": n,
        "tolerance_km": tol_km,
        "compliance_pct": compliance_pct,
        "deviation_mean_km": deviation_mean,
        "deviation_max_km": round(max(deviations), 2),
        "track_mean_green_score": track_mean_gs,
        "optimal_green_score": optimal_green_score,
        "green_score_delta": gs_delta,
        "track_on_navigable_pct": navigable_pct,
        "off_corridor_segments": off_corridor_segments[:10],
        "verdict": verdict,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Tool 2 — verify_waypoint_passage
# ---------------------------------------------------------------------------

@tool
def verify_waypoint_passage(
    corridor_id: str,
    vehicle_track: list,
    passage_radius_km: float = 0.0,
) -> dict:
    """
    Verify that a vehicle passed through all mandatory waypoints for the corridor.

    Mandatory waypoints per corridor:
      SGP_PKL     (maritime) : One Fathom Bank (2.92°N, 101.60°E)
                               Raffles Lighthouse TSS (1.17°N, 103.45°E)
      PVG_DXB_AMS (aviation) : Dubai Intl DXB (25.25°N, 55.36°E)
      NYNJ_SAV    (trucking) : None — no mandatory waypoints on I-95 corridor

    A waypoint is "confirmed" when the vehicle passes within `passage_radius_km`
    of its coordinates.  Defaults to the mode-specific corridor width
    (maritime 55 km, aviation 166 km, trucking 28 km) when 0 is passed.

    Handles the case where no vehicle track is provided: returns the corridor's
    waypoint list without a confirmation verdict.

    Args:
        corridor_id:        One of "SGP_PKL", "PVG_DXB_AMS", "NYNJ_SAV".
        vehicle_track:      List of position dicts with "lat" and "lon" keys.
                            Pass [] when no vehicle track is available.
        passage_radius_km:  Radius in km to consider a waypoint "passed".
                            Pass 0 to use the mode-specific default.
    """
    try:
        cfg = get_corridor_config(corridor_id)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    mode = cfg.mode

    # Passage radius
    radius_km = (
        passage_radius_km if passage_radius_km > 0
        else _DEFAULT_PASSAGE_RADIUS_KM.get(mode, 55.0)
    )

    waypoints = [
        {"name": w.name, "lat": w.lat, "lon": w.lon}
        for w in cfg.waypoints
    ]

    # ── No mandatory waypoints (trucking) ────────────────────────────────────
    if not waypoints:
        return {
            "status": "ok",
            "mode": mode,
            "corridor_id": corridor_id,
            "no_waypoints_required": True,
            "waypoints_confirmed": [],
            "waypoints_missed": [],
            "passage_details": [],
            "notes": (
                f"Corridor {corridor_id} ({mode}) has no mandatory waypoints. "
                "Waypoint compliance check not applicable."
            ),
        }

    # ── No track provided ────────────────────────────────────────────────────
    if not vehicle_track:
        return {
            "status": "ok",
            "mode": mode,
            "corridor_id": corridor_id,
            "no_track_provided": True,
            "no_waypoints_required": False,
            "waypoints_confirmed": [],
            "waypoints_missed": [w["name"] for w in waypoints],
            "passage_details": [
                {
                    "waypoint": w["name"],
                    "lat": w["lat"],
                    "lon": w["lon"],
                    "confirmed": False,
                    "closest_track_lat": None,
                    "closest_track_lon": None,
                    "closest_distance_km": None,
                    "passage_radius_km": radius_km,
                }
                for w in waypoints
            ],
            "notes": (
                "No vehicle track provided — waypoint passage cannot be verified."
            ),
        }

    # ── Check each waypoint ───────────────────────────────────────────────────
    confirmed: list[str]        = []
    missed: list[str]           = []
    details: list[dict]         = []

    for wp in waypoints:
        wp_lat = float(wp["lat"])
        wp_lon = float(wp["lon"])

        best_dist = float("inf")
        best_lat: float | None  = None
        best_lon: float | None  = None

        for pt in vehicle_track:
            try:
                pt_lat = float(pt["lat"])
                pt_lon = float(pt["lon"])
            except (KeyError, ValueError, TypeError):
                continue
            d = _haversine(pt_lat, pt_lon, wp_lat, wp_lon)
            if d < best_dist:
                best_dist = d
                best_lat  = pt_lat
                best_lon  = pt_lon

        passed = best_dist <= radius_km

        if passed:
            confirmed.append(wp["name"])
        else:
            missed.append(wp["name"])

        details.append({
            "waypoint": wp["name"],
            "required_lat": wp_lat,
            "required_lon": wp_lon,
            "confirmed": passed,
            "closest_track_lat": round(best_lat, 5) if best_lat is not None else None,
            "closest_track_lon": round(best_lon, 5) if best_lon is not None else None,
            "closest_distance_km": round(best_dist, 2) if best_dist < float("inf") else None,
            "passage_radius_km": radius_km,
        })

    # Advisory notes
    notes: list[str] = []
    if missed and mode == "maritime":
        notes.append(
            f"Waypoints missed: {missed}. Singapore Strait TSS routing requires "
            "passage through both One Fathom Bank and Raffles Lighthouse TSS."
        )
    if missed and mode == "aviation":
        notes.append(
            f"DXB waypoint not confirmed. Route may have bypassed the Gulf hub. "
            "Verify ADS-B coverage gap over Middle East."
        )

    return {
        "status": "ok",
        "mode": mode,
        "corridor_id": corridor_id,
        "no_track_provided": False,
        "no_waypoints_required": False,
        "passage_radius_km": radius_km,
        "waypoints_confirmed": confirmed,
        "waypoints_missed": missed,
        "all_waypoints_confirmed": len(missed) == 0,
        "passage_details": details,
        "notes": notes,
    }
