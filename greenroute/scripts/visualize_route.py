"""
visualize_route.py -- Render the A* optimal route onto the green score heatmap.

Produces a PNG matching the visual style of the GEE layer maps in /latest/ and
the aviation images in /aereo/.

Usage (run from workspace root, spacehack2026/):

    # Maritime -- single snapshot (saved next to the JSON)
    python greenroute/scripts/visualize_route.py latest/maritime_portklang_singapore.json

    # Maritime -- all three snapshots
    python greenroute/scripts/visualize_route.py --all

    # Aviation -- latest snapshot (p1)
    python greenroute/scripts/visualize_route.py --aviation

    # Aviation -- all three windows (p1/p2/p3)
    python greenroute/scripts/visualize_route.py --aviation --all

    # Any specific JSON
    python greenroute/scripts/visualize_route.py aereo/p2/aviation_payload_p2.json

    # Custom output path (single target only)
    python greenroute/scripts/visualize_route.py latest/maritime_portklang_singapore.json --out output/route.png

No API key required.
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless rendering -- no display needed

import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

# ---------------------------------------------------------------------------
# Make greenroute/ importable
# ---------------------------------------------------------------------------
_WORKSPACE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_WORKSPACE / "greenroute"))

import app.agent.tools.optimizer_tools as ot
from app.agent.tools.optimizer_tools import build_graph, run_astar, score_path

# ---------------------------------------------------------------------------
# Colour palette -- matches the dark theme of the existing layer maps
# ---------------------------------------------------------------------------
BG_COLOR       = "#0d0f17"
LAND_COLOR     = "#1a1d2e"
COAST_COLOR    = "#3a3d52"
TEXT_COLOR     = "#e8eaf0"
DIM_TEXT       = "#8890aa"

ROUTE_GLOW     = "#00e5ff"
ROUTE_LINE     = "#ffffff"
BASELINE_COLOR = "#ffff00"   # pure yellow — distinct from the red/orange/green heatmap
WAYPOINT_COLOR = "#00e5ff"
ORIGIN_COLOR   = "#00e5ff"
DEST_COLOR     = "#00e5ff"

# Green-score colormap: red (0) -> amber (45) -> green (100)
_CMAP = mcolors.LinearSegmentedColormap.from_list(
    "greenroute",
    [
        (0.00, "#d32f2f"),
        (0.44, "#e65100"),
        (0.45, "#ff9800"),
        (0.64, "#ffc107"),
        (0.65, "#66bb6a"),
        (1.00, "#1b5e20"),
    ],
)
_NORM = mcolors.Normalize(vmin=0, vmax=100)


# ---------------------------------------------------------------------------
# Core rendering function
# ---------------------------------------------------------------------------

def render_route(grid_path: str, output_path: str | None = None) -> Path:
    """
    Build the graph, run A*, score the path, and render a route PNG.

    Args:
        grid_path   : Path to the GEE grid JSON (relative to workspace root or absolute).
        output_path : Where to save the PNG.  Defaults to the folder of the JSON,
                      named 'map_route_optimal.png'.

    Returns the Path where the PNG was saved.
    """
    # -- Run optimizer tools ---------------------------------------------------
    r_build = build_graph(grid_path)
    if r_build["status"] != "ok":
        raise RuntimeError(f"build_graph failed: {r_build['message']}")

    r_astar = run_astar()
    if r_astar["status"] != "ok":
        raise RuntimeError(f"run_astar failed: {r_astar['message']}")

    r_score = score_path()
    if r_score["status"] != "ok":
        raise RuntimeError(f"score_path failed: {r_score['message']}")

    # -- Access module-level cache ---------------------------------------------
    G    = ot._graph
    grid = ot._grid_data
    path = ot._last_path

    gdef  = grid["grid_definition"]
    mode  = grid.get("mode", "maritime")

    rows  = gdef["rows"]
    cols  = gdef["cols"]
    cs    = gdef["cell_size_degrees"]
    north = gdef["bounds"]["north"]
    south = gdef["bounds"]["south"]
    west  = gdef["bounds"]["west"]
    east  = gdef["bounds"]["east"]

    # -- Detect land mask availability -----------------------------------------
    # Maritime: land_mask is a top-level key with {"data": [[...]]}
    # Aviation: land_mask field is a descriptive string -- no matrix
    lm_raw = gdef.get("land_mask", grid.get("land_mask", {}))
    has_land_mask = isinstance(lm_raw, dict) and "data" in lm_raw
    land_mask_data = lm_raw["data"] if has_land_mask else None

    # -- green_score source: derived_layers (aviation) or layers (maritime) ----
    layers         = grid["layers"]
    derived_layers = grid.get("derived_layers", {})
    if "green_score" in derived_layers:
        gs_source = derived_layers["green_score"]["data"]
    else:
        gs_source = layers["green_score"]["data"]

    # -- Build 2-D green score array -------------------------------------------
    green_arr = np.full((rows, cols), np.nan)
    for r in range(rows):
        for c in range(cols):
            navigable = (land_mask_data[r][c] == 1.0) if has_land_mask else True
            if navigable:
                v = gs_source[r][c]
                if v is not None:
                    green_arr[r, c] = float(v)

    # Corner arrays for pcolormesh (rows+1) x (cols+1)
    lat_edges = np.array([north - r * cs for r in range(rows + 1)])
    lon_edges = np.array([west  + c * cs for c in range(cols + 1)])
    lon_grid, lat_grid = np.meshgrid(lon_edges, lat_edges)

    # -- Route geometry --------------------------------------------------------
    path_lats = [G.nodes[cell]["lat"] for cell in path]
    path_lons = [G.nodes[cell]["lon"] for cell in path]

    # Baseline geometry: distance-optimal A* through the same mandatory waypoints.
    # This is the conventional/standard route — shortest navigable path through required stops.
    # Populated by score_path(); drawn distinctly to compare vs the green-optimized route.
    baseline = ot._baseline_path or []
    baseline_lats = [G.nodes[cell]["lat"] for cell in baseline if cell in G]
    baseline_lons = [G.nodes[cell]["lon"] for cell in baseline if cell in G]

    # -- Figure dimensions: wider for aviation's 125-degree grid ---------------
    lon_span = east - west
    lat_span = north - south
    if lon_span > 30:   # aviation
        fig_w, fig_h = 18, 8
    else:               # maritime (narrow corridor)
        fig_w, fig_h = 10, 8

    fig, ax = plt.subplots(figsize=(fig_w, fig_h), facecolor=BG_COLOR)
    ax.set_facecolor(BG_COLOR)

    # -- Layer 1: land fill (maritime only) ------------------------------------
    if has_land_mask:
        land_arr = np.where(np.array(land_mask_data) == 0.0, 1.0, np.nan)
        land_cmap = mcolors.ListedColormap([LAND_COLOR])
        ax.pcolormesh(
            lon_grid, lat_grid, land_arr,
            cmap=land_cmap, vmin=0, vmax=2,
            shading="flat", rasterized=True, zorder=1,
        )

    # -- Layer 2: green score heatmap ------------------------------------------
    masked_green = np.ma.masked_invalid(green_arr)
    pcm = ax.pcolormesh(
        lon_grid, lat_grid, masked_green,
        cmap=_CMAP, norm=_NORM,
        shading="flat", alpha=0.85, rasterized=True, zorder=2,
    )

    # -- Layer 3: coastline (maritime only -- too slow and meaningless for aviation)
    if has_land_mask:
        for r in range(rows):
            for c in range(cols):
                if land_mask_data[r][c] != 1.0:
                    continue
                cw = west  + c * cs
                ce = west  + (c + 1) * cs
                cs_ = north - (r + 1) * cs
                cn = north - r * cs
                for nr, nc, edge in [(r-1,c,"top"),(r+1,c,"bottom"),(r,c-1,"left"),(r,c+1,"right")]:
                    is_land_nb = (
                        nr < 0 or nr >= rows or nc < 0 or nc >= cols
                        or land_mask_data[nr][nc] == 0.0
                    )
                    if is_land_nb:
                        if edge == "top":
                            ax.plot([cw, ce], [cn, cn], color=COAST_COLOR, lw=0.4, zorder=3, solid_capstyle="butt")
                        elif edge == "bottom":
                            ax.plot([cw, ce], [cs_, cs_], color=COAST_COLOR, lw=0.4, zorder=3, solid_capstyle="butt")
                        elif edge == "left":
                            ax.plot([cw, cw], [cs_, cn], color=COAST_COLOR, lw=0.4, zorder=3, solid_capstyle="butt")
                        elif edge == "right":
                            ax.plot([ce, ce], [cs_, cn], color=COAST_COLOR, lw=0.4, zorder=3, solid_capstyle="butt")

    # -- Layer 4: baseline route (shortest-distance through same waypoints) ---
    if baseline_lats:
        # Glow layer
        ax.plot(baseline_lons, baseline_lats,
                color=BASELINE_COLOR, linewidth=10, alpha=0.18,
                solid_capstyle="round", solid_joinstyle="round",
                zorder=8)
        # Dashed line on top
        ax.plot(baseline_lons, baseline_lats,
                color=BASELINE_COLOR, linewidth=2.0, alpha=0.95,
                linestyle="--", dashes=(3, 3),
                solid_capstyle="round", solid_joinstyle="round",
                zorder=9)

    # -- Layer 5: optimal route glow + line ------------------------------------
    ax.plot(path_lons, path_lats,
            color=ROUTE_GLOW, linewidth=7, alpha=0.25,
            solid_capstyle="round", solid_joinstyle="round", zorder=10)
    ax.plot(path_lons, path_lats,
            color=ROUTE_LINE, linewidth=1.8, alpha=0.95,
            solid_capstyle="round", solid_joinstyle="round", zorder=11)

    # -- Layer 6: mandatory waypoints ------------------------------------------
    # Use JSON's own waypoint field for aviation (DXB), defaults for maritime
    wps_for_plot = ot._DEFAULT_WAYPOINTS.get(mode, [])
    if not wps_for_plot and "waypoint" in grid and isinstance(grid["waypoint"], dict):
        wps_for_plot = [grid["waypoint"]]

    for wp in wps_for_plot:
        try:
            cell = ot._snap_to_navigable(ot._coords_to_cell(wp["lat"], wp["lon"], gdef), G)
            wp_lat, wp_lon = G.nodes[cell]["lat"], G.nodes[cell]["lon"]
        except ValueError:
            wp_lat, wp_lon = wp["lat"], wp["lon"]

        ax.scatter(wp_lon, wp_lat,
                   marker="D", s=55, color=WAYPOINT_COLOR,
                   edgecolors="white", linewidths=0.6, zorder=15)
        ax.annotate(
            wp["name"],
            xy=(wp_lon, wp_lat),
            xytext=(6, 4), textcoords="offset points",
            color=WAYPOINT_COLOR, fontsize=7.5, fontweight="semibold", zorder=16,
        )

    # -- Layer 7: origin and destination ---------------------------------------
    origin = grid["origin"]
    dest   = grid["destination"]

    ax.scatter(origin["lon"], origin["lat"],
               marker="^", s=90, color=ORIGIN_COLOR,
               edgecolors="white", linewidths=0.8, zorder=15)
    ax.annotate(origin["name"],
                xy=(origin["lon"], origin["lat"]),
                xytext=(6, 4), textcoords="offset points",
                color=ORIGIN_COLOR, fontsize=8.5, fontweight="bold", zorder=16)

    ax.scatter(dest["lon"], dest["lat"],
               marker="s", s=70, color=DEST_COLOR,
               edgecolors="white", linewidths=0.8, zorder=15)
    ax.annotate(dest["name"],
                xy=(dest["lon"], dest["lat"]),
                xytext=(6, -12), textcoords="offset points",
                color=DEST_COLOR, fontsize=8.5, fontweight="bold", zorder=16)

    # -- Colorbar --------------------------------------------------------------
    cbar = fig.colorbar(pcm, ax=ax, fraction=0.025, pad=0.01)
    cbar.ax.yaxis.set_tick_params(color=DIM_TEXT, labelcolor=DIM_TEXT, labelsize=7.5)
    cbar.outline.set_edgecolor(COAST_COLOR)
    cbar.set_label("Green Score (0-100)", color=DIM_TEXT, fontsize=8)
    for thresh, label in [(45, "WARN>=45"), (65, "GREEN>=65")]:
        cbar.ax.axhline(thresh, color="white", linewidth=0.8, alpha=0.6)
        cbar.ax.text(2.6, thresh, label, color="white",
                     fontsize=6.5, va="center", alpha=0.7)

    # -- Axes formatting -------------------------------------------------------
    ax.set_xlim(west, east)
    ax.set_ylim(south, north)
    ax.set_aspect("equal")

    # Tick interval: coarse for wide aviation grid, fine for maritime
    lon_tick = 10.0 if lon_span > 30 else 1.0
    lat_tick = 5.0  if lat_span > 20 else 0.5
    ax.xaxis.set_major_locator(mticker.MultipleLocator(lon_tick))
    ax.yaxis.set_major_locator(mticker.MultipleLocator(lat_tick))
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}E"))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:.0f}N"))
    ax.tick_params(colors=DIM_TEXT, labelsize=7.5, length=3)
    for spine in ax.spines.values():
        spine.set_edgecolor(COAST_COLOR)

    # -- Stats box (top-left) --------------------------------------------------
    gs         = r_score["optimal_green_score"]
    vs         = r_score["green_score_vs_baseline_pct"]
    badge_color = "#4caf50" if gs >= 65 else "#ff9800" if gs >= 45 else "#f44336"
    badge_label = "GREEN"   if gs >= 65 else "WARN"    if gs >= 45 else "RED"
    vs_sign = "+" if vs >= 0 else ""
    stats_lines = [
        f"  Green score   {gs:.1f}/100  [{badge_label}]",
        f"  vs baseline   {vs_sign}{vs:.1f}%  (shortest-dist route = {r_score['baseline_green_score']:.1f})",
        f"  Distance      {r_score['optimal_path_distance_km']:.1f} km  ({r_score['optimal_path_cells']} cells)",
        f"  Waypoints     {', '.join(r_score['chokepoints_on_path']) or 'none'}",
        f"  Path badge    GREEN={r_score['green_cells_on_path']}  WARN={r_score['warn_cells_on_path']}  RED={r_score['red_cells_on_path']}",
    ]
    ax.text(
        0.013, 0.985, "\n".join(stats_lines),
        transform=ax.transAxes,
        va="top", ha="left",
        fontsize=7.5, color=TEXT_COLOR, linespacing=1.55,
        bbox=dict(facecolor="#1a1d2e", edgecolor=badge_color,
                  boxstyle="round,pad=0.4", alpha=0.85, linewidth=1.2),
        zorder=20,
    )

    # -- Legend symbols --------------------------------------------------------
    legend_handles = [
        plt.Line2D([0], [0], color=ROUTE_LINE, linewidth=1.8, label="Optimal route (A*)"),
        plt.Line2D([0], [0], color=BASELINE_COLOR, linewidth=1.4, linestyle="--",
                   dashes=(6, 4), label="Baseline (shortest-distance route)"),
        plt.Line2D([0], [0], marker="D", color="none",
                   markerfacecolor=WAYPOINT_COLOR, markeredgecolor="white",
                   markersize=7, label="Mandatory waypoint"),
        plt.Line2D([0], [0], marker="^", color="none",
                   markerfacecolor=ORIGIN_COLOR, markeredgecolor="white",
                   markersize=8, label=origin["name"]),
        plt.Line2D([0], [0], marker="s", color="none",
                   markerfacecolor=DEST_COLOR, markeredgecolor="white",
                   markersize=7, label=dest["name"]),
    ]
    if has_land_mask:
        legend_handles.insert(0,
            mpatches.Patch(facecolor=LAND_COLOR, edgecolor=COAST_COLOR, label="Land"))
    ax.legend(
        handles=legend_handles,
        loc="lower left", fontsize=7.5,
        facecolor="#1a1d2e", edgecolor=COAST_COLOR,
        labelcolor=TEXT_COLOR, framealpha=0.88,
    )

    # -- Title -----------------------------------------------------------------
    snap_ts = grid.get("generated_at", "")
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(snap_ts.replace("Z", "+00:00"))
        snap_label = dt.strftime("%b %d, %Y  %H:%M UTC")
    except Exception:
        snap_label = snap_ts

    # Include time window label (P1/P2/P3) for aviation
    window = grid.get("window", {})
    mode_label = "Aviation" if mode == "aviation" else "Maritime"
    if window:
        win_label  = window.get("label", "")
        win_start  = window.get("start", "")
        win_end    = window.get("end", "")
        subtitle = (
            f"A* pathfinding on green score grid  |  "
            f"Window {win_label}: {win_start} to {win_end}  |  Snapshot: {snap_label}"
        )
    else:
        subtitle = f"A* pathfinding on green score grid  |  Snapshot: {snap_label}"

    fig.text(
        0.01, 0.99,
        f"{mode_label} Optimal Route -- {origin['name']} -> {dest['name']}",
        color=TEXT_COLOR, fontsize=11, fontweight="bold", va="top", ha="left",
    )
    fig.text(
        0.01, 0.965, subtitle,
        color=DIM_TEXT, fontsize=8, va="top", ha="left",
    )

    plt.tight_layout(rect=[0, 0, 1, 0.96])

    # -- Save ------------------------------------------------------------------
    if output_path is None:
        grid_file = Path(grid_path)
        if not grid_file.is_absolute():
            grid_file = _WORKSPACE / grid_path
        output_path = str(grid_file.parent / "map_route_optimal.png")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)
    print(f"  Saved: {out}")
    return out


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
MARITIME_SNAPSHOTS = [
    "latest/maritime_portklang_singapore.json",
    "latest-1/maritime_portklang_singapore.json",
    "latest-2/maritime_portklang_singapore.json",
]

AVIATION_SNAPSHOTS = [
    "aereo/p1/aviation_payload_p1.json",
    "aereo/p2/aviation_payload_p2.json",
    "aereo/p3/aviation_payload_p3.json",
]


def main():
    args = sys.argv[1:]
    out_path = None

    if "--out" in args:
        idx = args.index("--out")
        out_path = args[idx + 1]
        args = [a for i, a in enumerate(args) if i not in (idx, idx + 1)]

    aviation_mode = "--aviation" in args
    run_all       = "--all" in args
    positional    = [a for a in args if not a.startswith("--")]

    if positional:
        targets = positional
    elif run_all:
        targets = AVIATION_SNAPSHOTS if aviation_mode else MARITIME_SNAPSHOTS
    else:
        targets = [AVIATION_SNAPSHOTS[0] if aviation_mode else MARITIME_SNAPSHOTS[0]]

    for snap in targets:
        print(f"\nRendering route for: {snap}")
        try:
            render_route(snap, out_path if len(targets) == 1 else None)
        except Exception as exc:
            print(f"  ERROR: {exc}")
            raise


if __name__ == "__main__":
    main()
