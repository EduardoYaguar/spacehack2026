"""
optimizer_tools.py — Tools for CorridorOptimizer (Agent 3)

Three tool functions:
  build_graph  — Build NetworkX DiGraph from a GEE grid JSON snapshot
  run_astar    — Segmented A* with mandatory waypoints, haversine heuristic
  score_path   — Score the optimal path against a straight-line baseline

The decisive metric for A* is green_score (0-100, higher = greener).
It is a pre-computed composite from the JSON that already weighs NO2, SO2,
wind, wave height, and VIIRS traffic according to the mode's config.
The individual layer values are stored on nodes for informational output only.

Design notes:
  - Mode (maritime / aviation / land) is read from the grid JSON.
  - Weights and normalization come from corridoriq_config inside the JSON.
  - Graph and last-computed path are cached at module level across the three
    tool calls within a single agent run; reset on each build_graph call.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import networkx as nx

# ---------------------------------------------------------------------------
# Module-level cache  (build_graph → run_astar → score_path, in that order)
# ---------------------------------------------------------------------------
_graph: nx.DiGraph | None = None
_grid_data: dict[str, Any] | None = None
_last_path: list[tuple[int, int]] | None = None
_baseline_path: list[tuple[int, int]] | None = None   # distance-optimal path through same waypoints
_checkpoints: list[tuple[int, int]] | None = None     # [origin, wp1…wpN, dest] resolved cells

# ---------------------------------------------------------------------------
# Mandatory waypoints per mode  (PKL → SGP direction, matching JSON origin/dest)
# Aviation and land entries will be added when those JSONs arrive.
# ---------------------------------------------------------------------------
_DEFAULT_WAYPOINTS: dict[str, list[dict]] = {
    "maritime": [
        {"name": "One Fathom Bank",        "lat": 2.92, "lon": 101.60},
        {"name": "Raffles Lighthouse TSS", "lat": 1.17, "lon": 103.45},
    ],
    "aviation": [
        {"name": "Dubai Intl (DXB)", "lat": 25.25, "lon": 55.36},
    ],
    "land": [],
}

# ---------------------------------------------------------------------------
# Navigability rule per mode
# ---------------------------------------------------------------------------
def _is_navigable(land_value: float, mode: str) -> bool:
    if mode == "maritime":
        return land_value == 1.0
    if mode == "aviation":
        return True          # planes fly over everything
    if mode == "land":
        return land_value == 0.0
    return land_value == 1.0  # safe default


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


def _cell_center(row: int, col: int, gdef: dict) -> tuple[float, float]:
    cs = gdef["cell_size_degrees"]
    lat = gdef["bounds"]["north"] - row * cs - cs / 2
    lon = gdef["bounds"]["west"]  + col * cs + cs / 2
    return lat, lon


def _coords_to_cell(lat: float, lon: float, gdef: dict) -> tuple[int, int]:
    cs = gdef["cell_size_degrees"]
    row = int((gdef["bounds"]["north"] - lat) / cs)
    col = int((lon - gdef["bounds"]["west"]) / cs)
    row = max(0, min(gdef["rows"] - 1, row))
    col = max(0, min(gdef["cols"] - 1, col))
    return row, col


def _snap_to_navigable(
    cell: tuple[int, int], graph: nx.DiGraph, radius: int = 5
) -> tuple[int, int]:
    """Return cell if navigable, else nearest navigable within radius steps."""
    if cell in graph:
        return cell
    r, c = cell
    for d in range(1, radius + 1):
        for dr in range(-d, d + 1):
            for dc in range(-d, d + 1):
                if abs(dr) == d or abs(dc) == d:
                    candidate = (r + dr, c + dc)
                    if candidate in graph:
                        return candidate
    raise ValueError(f"No navigable cell within radius {radius} of {cell}")


# ---------------------------------------------------------------------------
# Cell traversal cost  (green_score is the decisive metric)
# ---------------------------------------------------------------------------

def _normalize_value(value: float | None, lo: float, hi: float) -> float:
    if value is None:
        return 0.5
    if hi == lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def _cell_cost(attrs: dict, cfg: dict, mode: str) -> float:
    """
    Traversal cost in [0, 100] — lower means greener / preferred by A*.

    Primary path: cost = 100 - green_score  (always used when green_score exists).
    Fallback: recompute from raw layers using corridoriq_config weights.
    The fallback makes the function work for any future mode whose JSON may
    not pre-compute green_score.
    """
    gs = attrs.get("green_score")
    if gs is not None:
        return 100.0 - float(gs)

    # Fallback — raw layer computation driven by the JSON's own config
    norm    = cfg.get("normalization", {})
    weights = cfg.get("edge_cost_weights", {})

    def _n(attr_key: str, norm_key: str, invert: bool = False) -> float:
        lo = norm.get(norm_key, {}).get("min", 0.0)
        hi = norm.get(norm_key, {}).get("max", 1.0)
        v  = _normalize_value(attrs.get(attr_key), lo, hi)
        return (1.0 - v) if invert else v

    cost = (_n("no2_mol_m2",    "no2_mol_m2")          * weights.get("no2",  0.30)
          + _n("so2_mol_m2",    "so2_mol_m2")          * weights.get("so2",  0.10)
          + _n("wind_speed_ms", "wind_speed", True)    * weights.get("wind", 0.20))

    if mode == "maritime":
        cost += (_n("wave_height_m",     "wave_height_m")     * weights.get("wave",    0.15)
               + _n("viirs_radiance_nw", "viirs_radiance_nw") * weights.get("traffic", 0.15))

    dist_w   = weights.get("distance", weights.get("dist", 0.10))
    non_dist = max(1.0 - dist_w, 1e-6)
    return (cost / non_dist) * 100.0


# ---------------------------------------------------------------------------
# Tool 1 — build_graph
# ---------------------------------------------------------------------------

def build_graph(
    grid_path: str,
    forced_waypoints: list[dict] | None = None,
) -> dict:
    """
    Build a NetworkX DiGraph from a GEE corridor grid JSON snapshot.

    Node cost = 100 - green_score  (green_score is the composite of all layers).
    Edge weight = destination_cost * (1 - dist_weight) + normalised_distance * dist_weight.

    Args:
        grid_path        : Path to the grid JSON (absolute or relative to workspace root).
        forced_waypoints : Override default waypoints. Use when run_astar previously
                           returned non-empty waypoints_missed.
    """
    global _graph, _grid_data, _last_path

    path = Path(grid_path)
    if not path.exists():
        workspace = Path(__file__).resolve().parents[4]  # spacehack2026/
        alt = workspace / grid_path
        if alt.exists():
            path = alt
        else:
            return {"status": "error", "message": f"Grid file not found: {grid_path}"}

    with open(path, "r") as f:
        raw = json.load(f)

    mode    = raw.get("mode", "maritime")
    gdef    = raw["grid_definition"]
    layers  = raw["layers"]
    cfg     = raw.get("corridoriq_config", {})

    # Aviation stores green_score and derived met fields in a separate top-level key.
    # Maritime stores green_score directly in layers.
    derived_layers = raw.get("derived_layers", {})

    # Land mask: aviation has no matrix — every cell is navigable.
    land_mask_raw = gdef.get("land_mask", raw.get("land_mask", {}))
    has_land_mask = isinstance(land_mask_raw, dict) and "data" in land_mask_raw
    land_mask_data = land_mask_raw["data"] if has_land_mask else None

    rows = gdef["rows"]
    cols = gdef["cols"]
    cs   = gdef["cell_size_degrees"]
    max_diag_km = _haversine(0.0, 0.0, cs * math.sqrt(2), cs * math.sqrt(2))
    dist_w = cfg.get("edge_cost_weights", {}).get(
        "distance", cfg.get("edge_cost_weights", {}).get("dist", 0.10))

    G = nx.DiGraph()

    # Nodes
    for r in range(rows):
        for c in range(cols):
            # Navigability check
            if land_mask_data is not None:
                if not _is_navigable(land_mask_data[r][c], mode):
                    continue
            # else: aviation — all cells navigable

            lat, lon = _cell_center(r, c, gdef)

            # green_score: check derived_layers first (aviation), then layers (maritime)
            if "green_score" in derived_layers:
                green_score = derived_layers["green_score"]["data"][r][c]
            else:
                green_score = layers["green_score"]["data"][r][c]

            # Wind components — always present (either surface or 250hPa for aviation)
            wu = (layers.get("wind_u_ms", {}).get("data", [[]])[r] or [None])[c] if "wind_u_ms" in layers else None
            wv = (layers.get("wind_v_ms", {}).get("data", [[]])[r] or [None])[c] if "wind_v_ms" in layers else None
            wu = wu or 0.0
            wv = wv or 0.0

            attrs: dict[str, Any] = {
                "lat":         lat,
                "lon":         lon,
                "green_score": green_score,
                "wind_u_ms":   wu,
                "wind_v_ms":   wv,
                "wind_speed_ms": math.sqrt(wu ** 2 + wv ** 2),
            }

            if mode == "maritime":
                # Maritime-specific layers (informational)
                attrs["no2_mol_m2"]        = layers["no2_mol_m2"]["data"][r][c]
                attrs["so2_mol_m2"]        = layers["so2_mol_m2"]["data"][r][c]
                attrs["wave_height_m"]     = layers["wave_height_m"]["data"][r][c]
                attrs["viirs_radiance_nw"] = layers["viirs_radiance_nw"]["data"][r][c]

            elif mode == "aviation":
                # Aviation-specific layers (informational)
                attrs["no2_mol_m2"]            = layers["no2_mol_m2"]["data"][r][c]
                attrs["co_mol_m2"]             = layers.get("co_mol_m2", {}).get("data", [[None]*cols]*rows)[r][c]
                attrs["ch4_ppb"]               = layers.get("ch4_ppb", {}).get("data", [[None]*cols]*rows)[r][c]
                attrs["cloud_top_height_m"]    = layers.get("cloud_top_height_m", {}).get("data", [[None]*cols]*rows)[r][c]
                attrs["aerosol_index"]         = layers.get("aerosol_index", {}).get("data", [[None]*cols]*rows)[r][c]
                attrs["turbulence_index"]      = derived_layers.get("turbulence_index", {}).get("data", [[None]*cols]*rows)[r][c]
                attrs["contrail_risk"]         = derived_layers.get("contrail_risk", {}).get("data", [[None]*cols]*rows)[r][c]
                attrs["wind_speed_250hpa_ms"]  = derived_layers.get("wind_speed_250hpa_ms", {}).get("data", [[None]*cols]*rows)[r][c]

            attrs["cost"] = _cell_cost(attrs, cfg, mode)
            G.add_node((r, c), **attrs)

    # 8-connected directed edges
    for (r, c) in list(G.nodes):
        lat_s = G.nodes[(r, c)]["lat"]
        lon_s = G.nodes[(r, c)]["lon"]
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                nb = (r + dr, c + dc)
                if nb not in G.nodes:
                    continue
                dist_km   = _haversine(lat_s, lon_s, G.nodes[nb]["lat"], G.nodes[nb]["lon"])
                dist_norm = dist_km / max_diag_km
                cost_dest = G.nodes[nb]["cost"]
                edge_w    = cost_dest * (1.0 - dist_w) + dist_norm * 100.0 * dist_w
                G.add_edge((r, c), nb, weight=edge_w, dist_km=dist_km)

    _graph         = G
    _grid_data     = raw
    _last_path     = None
    _baseline_path = None
    _checkpoints   = None

    # Resolve waypoints — use forced_waypoints, then defaults.
    # If the JSON has a singular "waypoint" field (aviation), incorporate it when defaults are empty.
    if forced_waypoints is not None:
        wps = forced_waypoints
    else:
        wps = _DEFAULT_WAYPOINTS.get(mode, [])
        if not wps and "waypoint" in raw and isinstance(raw["waypoint"], dict):
            wps = [raw["waypoint"]]
    resolved: list[dict] = []
    for wp in wps:
        cell = _coords_to_cell(wp["lat"], wp["lon"], gdef)
        try:
            cell      = _snap_to_navigable(cell, G)
            navigable = True
        except ValueError:
            navigable = False
        wp_lat, wp_lon = _cell_center(cell[0], cell[1], gdef)
        resolved.append({
            "name":          wp["name"],
            "requested_lat": wp["lat"],
            "requested_lon": wp["lon"],
            "cell":          list(cell),
            "cell_lat":      round(wp_lat, 4),
            "cell_lon":      round(wp_lon, 4),
            "navigable":     navigable,
        })

    return {
        "status":             "ok",
        "mode":               mode,
        "grid_snapshot":      raw.get("generated_at", "unknown"),
        "nodes":              G.number_of_nodes(),
        "edges":              G.number_of_edges(),
        "origin":             raw["origin"],
        "destination":        raw["destination"],
        "waypoints_resolved": resolved,
    }


# ---------------------------------------------------------------------------
# Tool 2 — run_astar
# ---------------------------------------------------------------------------

def run_astar(
    forced_waypoints: list[dict] | None = None,
) -> dict:
    """
    Segmented A* on the cached graph.

    Route: origin → [waypoint_1 … waypoint_N] → destination.
    Edge weight is driven by green_score (via cost = 100 - green_score).
    Heuristic: haversine distance to goal (admissible).

    If waypoints_missed is non-empty in the result, call build_graph with
    forced_waypoints and then run_astar again.
    """
    global _last_path, _checkpoints

    if _graph is None or _grid_data is None:
        return {"status": "error", "message": "No graph loaded. Call build_graph first."}

    G    = _graph
    gdef = _grid_data["grid_definition"]
    mode = _grid_data.get("mode", "maritime")

    try:
        origin_cell = _snap_to_navigable(
            _coords_to_cell(_grid_data["origin"]["lat"],
                            _grid_data["origin"]["lon"], gdef), G)
        dest_cell = _snap_to_navigable(
            _coords_to_cell(_grid_data["destination"]["lat"],
                            _grid_data["destination"]["lon"], gdef), G)
    except ValueError as exc:
        return {"status": "error", "message": f"Origin/destination snap failed: {exc}"}

    wps = forced_waypoints if forced_waypoints is not None else _DEFAULT_WAYPOINTS.get(mode, [])
    waypoint_cells: list[tuple[tuple[int, int], str]] = []
    for wp in wps:
        try:
            cell = _snap_to_navigable(_coords_to_cell(wp["lat"], wp["lon"], gdef), G)
            waypoint_cells.append((cell, wp.get("name", f"{wp['lat']},{wp['lon']}")))
        except ValueError as exc:
            return {"status": "error",
                    "message": f"Waypoint '{wp.get('name')}' unreachable: {exc}"}

    checkpoints = (
        [origin_cell]
        + [cell for cell, _ in waypoint_cells]
        + [dest_cell]
    )
    _checkpoints = checkpoints

    def heuristic(node: tuple, goal: tuple) -> float:
        return _haversine(G.nodes[node]["lat"], G.nodes[node]["lon"],
                          G.nodes[goal]["lat"],  G.nodes[goal]["lon"])

    full_path: list[tuple[int, int]] = []
    segment_errors: list[str] = []

    for i in range(len(checkpoints) - 1):
        src, dst = checkpoints[i], checkpoints[i + 1]
        try:
            seg = nx.astar_path(G, src, dst, heuristic=heuristic, weight="weight")
            if full_path:
                seg = seg[1:]
            full_path.extend(seg)
        except nx.NetworkXNoPath:
            segment_errors.append(f"No path: {src} -> {dst}")
        except nx.NodeNotFound as exc:
            segment_errors.append(f"Node not found: {exc}")

    if not full_path:
        return {
            "status":         "error",
            "message":        "A* found no valid path through all checkpoints.",
            "segment_errors": segment_errors,
        }

    _last_path = full_path

    total_dist_km = round(sum(
        _haversine(G.nodes[full_path[i]]["lat"], G.nodes[full_path[i]]["lon"],
                   G.nodes[full_path[i + 1]]["lat"], G.nodes[full_path[i + 1]]["lon"])
        for i in range(len(full_path) - 1)
    ), 1)

    path_set         = set(full_path)
    waypoints_hit    = [name for cell, name in waypoint_cells if cell in path_set]
    waypoints_missed = [name for cell, name in waypoint_cells if cell not in path_set]

    preview_cells = (full_path[:4] + full_path[-4:]) if len(full_path) > 8 else full_path
    path_preview  = [
        [round(G.nodes[cell]["lat"], 3), round(G.nodes[cell]["lon"], 3)]
        for cell in preview_cells
    ]

    return {
        "status":           "ok",
        "mode":             mode,
        "path_cells":       len(full_path),
        "path_distance_km": total_dist_km,
        "waypoints_hit":    waypoints_hit,
        "waypoints_missed": waypoints_missed,
        "segment_errors":   segment_errors,
        "path_preview":     path_preview,
        "note": (
            "All mandatory waypoints hit."
            if not waypoints_missed
            else (f"Missed: {waypoints_missed}. "
                  "Call build_graph with forced_waypoints, then run_astar again.")
        ),
    }


# ---------------------------------------------------------------------------
# Tool 3 — score_path
# ---------------------------------------------------------------------------

def score_path() -> dict:
    """
    Score the A* path using green_score as the decisive metric.

    optimal_green_score  = mean green_score of cells on the A* path.
    baseline_green_score = mean green_score of cells on the straight geodesic
                           between origin and destination.
    green_score_vs_baseline_pct = (optimal - baseline) / baseline * 100.
      Positive  = A* route is greener than going straight.
      Negative  = waypoint constraints force the path through lower-score cells.

    Individual layer means (NO2, SO2, wind, wave, VIIRS) are returned as
    informational context only — they do not override or replace green_score.
    """
    if _graph is None or _grid_data is None:
        return {"status": "error", "message": "No graph loaded. Call build_graph first."}
    if _last_path is None:
        return {"status": "error", "message": "No path computed. Call run_astar first."}

    global _baseline_path
    G    = _graph
    gdef = _grid_data["grid_definition"]
    mode = _grid_data.get("mode", "maritime")
    cfg  = _grid_data.get("corridoriq_config", {})

    # --- Green score stats along the path ---
    green_scores: list[float] = []
    warn_cells = 0
    red_cells  = 0

    # Layer accumulators — keys depend on mode; built dynamically
    layer_accum: dict[str, list[float]] = {}

    def _accum(key: str, value) -> None:
        if key not in layer_accum:
            layer_accum[key] = []
        layer_accum[key].append(float(value) if value is not None else 0.0)

    for r, c in _last_path:
        node = G.nodes[(r, c)]
        gs   = float(node.get("green_score") or (100.0 - node.get("cost", 50.0)))
        green_scores.append(gs)
        if gs < 45:
            red_cells  += 1
        elif gs < 65:
            warn_cells += 1

        # Collect whatever layer attributes exist on this node
        _accum("no2_mol_m2",  node.get("no2_mol_m2"))
        _accum("wind_speed_ms", node.get("wind_speed_ms",
                                         math.sqrt((node.get("wind_u_ms") or 0.0)**2
                                                   + (node.get("wind_v_ms") or 0.0)**2)))
        if mode == "maritime":
            _accum("so2_mol_m2",        node.get("so2_mol_m2"))
            _accum("wave_height_m",     node.get("wave_height_m"))
            _accum("viirs_radiance_nw", node.get("viirs_radiance_nw"))
        elif mode == "aviation":
            _accum("co_mol_m2",             node.get("co_mol_m2"))
            _accum("turbulence_index",      node.get("turbulence_index"))
            _accum("contrail_risk",         node.get("contrail_risk"))
            _accum("wind_speed_250hpa_ms",  node.get("wind_speed_250hpa_ms"))

    def _mean(lst: list[float]) -> float:
        return round(sum(lst) / len(lst), 6) if lst else 0.0

    optimal_green_score = round(_mean(green_scores), 1)

    # --- Baseline: distance-optimal A* through the same mandatory waypoints ---
    # This represents the conventional/standard route (shortest navigable path
    # through required stops) — what ships/planes do WITHOUT green optimization.
    # We run A* again using only dist_km as edge weight, ignoring green_score.
    def heuristic_bl(node: tuple, goal: tuple) -> float:
        return _haversine(G.nodes[node]["lat"], G.nodes[node]["lon"],
                          G.nodes[goal]["lat"],  G.nodes[goal]["lon"])

    baseline_cells: list[tuple[int, int]] = []
    if _checkpoints and len(_checkpoints) >= 2:
        for i in range(len(_checkpoints) - 1):
            src, dst = _checkpoints[i], _checkpoints[i + 1]
            try:
                seg = nx.astar_path(G, src, dst, heuristic=heuristic_bl, weight="dist_km")
                if baseline_cells:
                    seg = seg[1:]
                baseline_cells.extend(seg)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                pass

    _baseline_path = baseline_cells

    baseline_scores: list[float] = [
        float(G.nodes[cell].get("green_score") or (100.0 - G.nodes[cell].get("cost", 50.0)))
        for cell in baseline_cells
    ]
    baseline_green_score = round(_mean(baseline_scores), 1) if baseline_scores else optimal_green_score

    green_score_vs_baseline_pct = (
        round((optimal_green_score - baseline_green_score) / baseline_green_score * 100, 1)
        if baseline_green_score > 0 else 0.0
    )

    # --- Path distance ---
    total_dist_km = round(sum(
        _haversine(G.nodes[_last_path[i]]["lat"], G.nodes[_last_path[i]]["lon"],
                   G.nodes[_last_path[i + 1]]["lat"], G.nodes[_last_path[i + 1]]["lon"])
        for i in range(len(_last_path) - 1)
    ), 1)

    # --- Chokepoints confirmed on path ---
    path_set    = set(_last_path)
    chokepoints = []
    for wp in _DEFAULT_WAYPOINTS.get(mode, []):
        try:
            cell = _snap_to_navigable(_coords_to_cell(wp["lat"], wp["lon"], gdef), G)
            if cell in path_set:
                chokepoints.append(wp["name"])
        except ValueError:
            pass

    return {
        "status": "ok",
        # --- decisive metric ---
        "optimal_green_score":          optimal_green_score,
        "baseline_green_score":         baseline_green_score,
        "green_score_vs_baseline_pct":  green_score_vs_baseline_pct,
        # --- path geometry ---
        "optimal_path_cells":           len(_last_path),
        "optimal_path_distance_km":     total_dist_km,
        "chokepoints_on_path":          chokepoints,
        # --- badge distribution on path ---
        "green_cells_on_path":          len(green_scores) - warn_cells - red_cells,
        "warn_cells_on_path":           warn_cells,
        "red_cells_on_path":            red_cells,
        # Feasibility: path exists AND mean green score > 30 (absolute floor).
        # The red_cells threshold is mode-scaled — aviation corridors have far more RED
        # cells by nature (turbulence, contrail, jet-stream), so we use a fractional cap.
        "feasibility_flag": (
            len(_last_path) > 0
            and optimal_green_score > 30.0
            and red_cells / max(len(_last_path), 1) < 0.80
        ),
        # --- baseline path geometry (straight-line Bresenham geodesic) ---
        "baseline_path_cells":  len(baseline_cells),
        "baseline_path_coords": [
            [round(G.nodes[cell]["lat"], 3), round(G.nodes[cell]["lon"], 3)]
            for cell in baseline_cells
        ],
        # --- individual layer means (informational context, not used by A*) ---
        "layer_means_on_path": {k: _mean(v) for k, v in layer_accum.items()},
    }
