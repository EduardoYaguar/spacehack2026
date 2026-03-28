"""
test_optimizer.py -- Smoke-test the CorridorOptimizer tools WITHOUT the LLM.

Run from the workspace root (spacehack2026/):

    python greenroute/scripts/test_optimizer.py                        # maritime latest
    python greenroute/scripts/test_optimizer.py --all                  # all maritime snapshots
    python greenroute/scripts/test_optimizer.py --aviation             # aviation latest (p1)
    python greenroute/scripts/test_optimizer.py --aviation --all       # all aviation snapshots (p1/p2/p3)
    python greenroute/scripts/test_optimizer.py --terrestrial          # trucking latest (p1)
    python greenroute/scripts/test_optimizer.py --terrestrial --all    # all trucking snapshots (p1/p2/p3)
    python greenroute/scripts/test_optimizer.py <path/to/file.json>    # any specific snapshot

No API key required -- this tests the Python tools only.
"""

import sys
from pathlib import Path

# Make greenroute/ importable regardless of where the script is called from
_WORKSPACE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_WORKSPACE / "greenroute"))

from app.agent.tools.optimizer_tools import (
    build_graph,
    run_astar,
    score_path,
)

# ---------------------------------------------------------------------------
# Available snapshots (relative to workspace root)
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

TERRESTRIAL_SNAPSHOTS = [
    "terrestre_usa/p1/terrestrial_usa_p1.json",
    "terrestre_usa/p2/terrestrial_usa_p2.json",
    "terrestre_usa/p3/terrestrial_usa_p3.json",
]

SEP = "-" * 60


def _badge(score: float) -> str:
    if score >= 65:
        return "GREEN"
    if score >= 45:
        return "WARN"
    return "RED"


def run_test(grid_path: str) -> dict:
    print(f"\n{SEP}")
    print(f"  Snapshot: {grid_path}")
    print(SEP)

    # -- Step 1: build_graph --------------------------------------------------
    print("\n[1/3] build_graph ...")
    r1 = build_graph(grid_path)
    if r1["status"] != "ok":
        print(f"  ERROR: {r1['message']}")
        return r1

    print(f"  Mode        : {r1['mode']}")
    print(f"  Snapshot    : {r1['grid_snapshot']}")
    print(f"  Nodes       : {r1['nodes']}  |  Edges: {r1['edges']}")
    print(f"  Origin      : {r1['origin']['name']}  ({r1['origin']['lat']}, {r1['origin']['lon']})")
    print(f"  Destination : {r1['destination']['name']}  ({r1['destination']['lat']}, {r1['destination']['lon']})")
    print("  Waypoints resolved:")
    for wp in r1["waypoints_resolved"]:
        flag = "[ok]" if wp["navigable"] else "[x] NOT NAVIGABLE"
        print(f"    {flag}  {wp['name']}  ->  cell {wp['cell']}  "
              f"({wp['cell_lat']}N, {wp['cell_lon']}E)")

    # -- Step 2: run_astar ----------------------------------------------------
    print("\n[2/3] run_astar ...")
    r2 = run_astar()
    if r2["status"] != "ok":
        print(f"  ERROR: {r2['message']}")
        if r2.get("segment_errors"):
            for e in r2["segment_errors"]:
                print(f"    - {e}")
        return r2

    print(f"  Path cells   : {r2['path_cells']}")
    print(f"  Distance     : {r2['path_distance_km']} km")
    print(f"  Waypoints hit: {r2['waypoints_hit']}")
    if r2["waypoints_missed"]:
        print(f"  [!] Missed   : {r2['waypoints_missed']}")
    else:
        print("  All mandatory waypoints hit [ok]")
    print("  Path preview (lat, lon):")
    for pt in r2["path_preview"]:
        print(f"    {pt[0]}N  {pt[1]}E")

    # -- Step 3: score_path ---------------------------------------------------
    print("\n[3/3] score_path ...")
    r3 = score_path()
    if r3["status"] != "ok":
        print(f"  ERROR: {r3['message']}")
        return r3

    badge  = _badge(r3["optimal_green_score"])
    vs     = r3["green_score_vs_baseline_pct"]
    vs_str = f"+{vs}%" if vs >= 0 else f"{vs}%"

    print(f"  Optimal green score  : {r3['optimal_green_score']} / 100  =>  {badge}")
    print(f"  Baseline green score : {r3['baseline_green_score']} / 100  (shortest-distance route)")
    print(f"  vs baseline          : {vs_str}  ({'greener' if vs >= 0 else 'lower -- waypoint detour cost'})")
    print(f"  Optimal distance     : {r3['optimal_path_distance_km']} km  ({r3['optimal_path_cells']} cells)")
    print(f"  Baseline cells       : {r3['baseline_path_cells']}  (distance-optimal through same waypoints)")
    print(f"  Chokepoints          : {r3['chokepoints_on_path']}")
    print(f"  Badge distribution   : GREEN={r3['green_cells_on_path']}  "
          f"WARN={r3['warn_cells_on_path']}  RED={r3['red_cells_on_path']}")
    print(f"  Feasibility          : {'[ok] feasible' if r3['feasibility_flag'] else '[x] infeasible'}")
    print("  Baseline path preview (lat, lon) -- shortest-distance route:")
    preview = r3.get("baseline_path_coords", [])
    preview_show = (preview[:3] + preview[-3:]) if len(preview) > 6 else preview
    for pt in preview_show:
        print(f"    {pt[0]}N  {pt[1]}E")
    print("  Layer means (info only):")
    for k, v in r3["layer_means_on_path"].items():
        print(f"    {k:<25}: {v:.4e}")

    combined = {**r1, **r2, **r3}
    print(f"\n  Test passed for {grid_path}")
    return combined


def _print_summary(results: list[tuple[str, dict]]) -> None:
    print(f"\n{SEP}")
    print("  SUMMARY")
    print(SEP)
    header = f"  {'Snapshot':<45} {'GreenScore':>10}  {'vsBaseline':>10}  {'km':>8}  {'Cells':>6}"
    print(header)
    print("  " + "." * (len(header) - 2))
    for snap, r in results:
        if r.get("status") != "ok":
            print(f"  {snap:<45}  ERROR")
            continue
        score  = r.get("optimal_green_score", "-")
        vs     = r.get("green_score_vs_baseline_pct", "-")
        dist   = r.get("optimal_path_distance_km", "-")
        cells  = r.get("path_cells", "-")
        vs_str = f"{'+' if isinstance(vs, float) and vs >= 0 else ''}{vs}%" if isinstance(vs, float) else str(vs)
        print(f"  {snap:<45} {score:>10}  {vs_str:>10}  {dist:>8}  {cells:>6}")


def main():
    args = sys.argv[1:]

    aviation_mode     = "--aviation" in args
    terrestrial_mode  = "--terrestrial" in args
    run_all           = "--all" in args

    # Strip flags from args to get remaining positional file paths
    positional = [a for a in args if not a.startswith("--")]

    if positional:
        targets = positional
    elif run_all:
        if terrestrial_mode:
            targets = TERRESTRIAL_SNAPSHOTS
        elif aviation_mode:
            targets = AVIATION_SNAPSHOTS
        else:
            targets = MARITIME_SNAPSHOTS
    else:
        if terrestrial_mode:
            targets = [TERRESTRIAL_SNAPSHOTS[0]]
        elif aviation_mode:
            targets = [AVIATION_SNAPSHOTS[0]]
        else:
            targets = [MARITIME_SNAPSHOTS[0]]

    results = []
    for snap in targets:
        r = run_test(snap)
        results.append((snap, r))

    if len(targets) > 1:
        _print_summary(results)

    print(f"\n{SEP}\n")


if __name__ == "__main__":
    main()
