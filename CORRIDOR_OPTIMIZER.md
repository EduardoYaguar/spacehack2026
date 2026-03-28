# CorridorOptimizer — Agent 3

> Finds the lowest-carbon route through a satellite grid using A* pathfinding.
> Part of the **GreenRoute Intelligence Platform**.
> Supports maritime (SGP ↔ PKL), aviation (PVG → DXB → AMS), and terrestrial trucking (Port NY/NJ → Port of Savannah) corridors.

---

## What it does

The CorridorOptimizer receives a satellite grid snapshot (GEE JSON) and a certification
decision from the upstream agents, then returns the **optimal route** — the path that
minimises environmental cost while passing through all mandatory waypoints.

It runs as an LLM agent (claude-haiku-4-5) with a ReAct loop that calls three Python
tools in a fixed sequence. The LLM handles reasoning and retries; the tools do the
actual computation.

---

## Inputs / Outputs

| | Field | Type | Description |
|---|---|---|---|
| **In** | `satellite_report` | dict | Output of SatelliteAnalyst. Must include `grid_path`. |
| **In** | `cert_decision` | dict | Output of CertificationJudge. |
| **Out** | `route_recommendation` | dict | RouteRecommendation JSON (see schema below). |

### RouteRecommendation schema

```json
{
  "corridor_id":                 "SGP_PKL",
  "optimization_timestamp":      "2026-03-27T18:21:00Z",
  "transport_mode":              "maritime",
  "optimal_green_score":         64.8,
  "baseline_green_score":        67.8,
  "green_score_vs_baseline_pct": -4.4,
  "optimal_path_cells":          33,
  "optimal_path_distance_km":    456.9,
  "chokepoints_on_path":         ["One Fathom Bank", "Raffles Lighthouse TSS"],
  "feasibility_flag":            true,
  "optimizer_notes":             "All waypoints hit. A* chose greener path despite slight score trade-off vs straight line."
}
```

---

## The decisive metric: green_score

`green_score` (0–100, higher = greener) is pre-computed by the data pipeline and baked
into every JSON cell. It is a composite that already weighs all mode-specific layers.
**It is the single source of truth for A* path quality.** Individual layer values are
stored for informational output only — they do not influence pathfinding.

A* traversal cost: `cost = 100 − green_score` (lower cost = greener = preferred).

Badge thresholds:

| Badge | Score |
|---|---|
| GREEN | >= 65 |
| WARN  | 45 – 64 |
| RED   | < 45 |

---

## Maritime mode

**Corridor:** Port Klang (PKL) → Port of Singapore (SGP)

**Grid:** 40 rows × 60 cols, 0.1°/cell (~11 km), N 4.5 / S 0.5 / W 99.5 / E 105.5

**Navigability:** water cells only (land_mask = 1)

**Layers contributing to green_score:**

| Layer | Weight | Description |
|---|---|---|
| NO2 | 0.30 | Tropospheric nitrogen dioxide — shipping emissions proxy |
| SO2 | 0.10 | Sulfur dioxide — heavy-fuel combustion indicator |
| Wind cost | 0.20 | Surface wind speed — resistance proxy |
| Wave height | 0.15 | Significant wave height — sea state |
| VIIRS radiance | 0.15 | Night-light proxy for vessel traffic density |

**green_score formula:**
```
C_env      = 0.30*NO2 + 0.10*SO2 + 0.20*wind_cost + 0.15*wave + 0.15*traffic
green_score = 100 * (1 - C_env / 0.90)
```

**Mandatory waypoints:**

| Waypoint | Coordinates | Purpose |
|---|---|---|
| One Fathom Bank | 2.92°N, 101.60°E | Entry to the Strait of Malacca from the north |
| Raffles Lighthouse TSS | 1.17°N, 103.45°E | Western exit of the Singapore Strait |

**Typical scores:** Mostly GREEN (65+). The corridor is relatively clean.

---

## Aviation mode

**Corridor:** Shanghai Pudong (PVG) → Dubai Intl (DXB) → Amsterdam Schiphol (AMS)

**Grid:** 60 rows × 125 cols, 1.0°/cell (~111 km), N 75 / S 15 / W 0 / E 125

**Navigability:** all cells (aircraft fly over everything — no land mask matrix)

**Layers contributing to green_score** (from `derived_layers` in the JSON):

| Layer | Weight | Description |
|---|---|---|
| Wind (250 hPa) | 0.35 | Jet-stream wind speed — fuel burn proxy |
| Turbulence index | 0.15 | Clear-air turbulence risk |
| Contrail risk | 0.10 | Ice-supersaturation — persistent contrail formation |
| NO2 | 0.10 | Tropospheric NO2 — aviation traffic density |
| CO | 0.05 | Carbon monoxide |
| Cloud top height | 0.10 | Deep convection / thunderstorm avoidance |
| Aerosol index | 0.10 | Dust / smoke optical depth |
| AOD | 0.05 | Aerosol optical depth |

**green_score location in JSON:** `derived_layers.green_score` (NOT `layers`)

**Mandatory waypoint:**

| Waypoint | Coordinates | Purpose |
|---|---|---|
| Dubai Intl (DXB) | 25.25°N, 55.36°E | Mandatory refuelling/waypoint hub |

**Typical scores:** Mostly WARN/RED (40–50). The PVG→DXB→AMS corridor crosses harsh
jet-stream and high-turbulence regions. A green_score of ~45 is expected — not an error.

**Time windows available:** P1 (Mar 4–18), P2, P3 — three snapshots in `aereo/`

---

## Terrestrial / Trucking mode

**Corridor:** Port NY/NJ (Newark) → Port of Savannah

**Grid:** 200 rows × 180 cols, 0.05°/cell (~5.6 km), N 41.5 / S 31.5 / W -82.5 / E -73.5

**Navigability:** road cells only — derived from TIGER/2016 road network (interstates + US highways, 5 km buffer). Stored in top-level `road_mask` key (1.0 = road, 0.0 = non-road).

**Layers contributing to green_score** (pre-computed in `derived_layers`):

| Layer | Weight | Description |
|---|---|---|
| NO2 | 0.20 | Tropospheric nitrogen dioxide — traffic emissions |
| Slope | 0.20 | Terrain slope (degrees) — fuel consumption proxy |
| Congestion | 0.20 | VIIRS night-light — road traffic density |
| CO | 0.10 | Carbon monoxide — combustion completeness |
| Precipitation | 0.08 | Precip rate (mm/hr) — road condition |
| Snow cover | 0.07 | Snow coverage (%) — road condition |
| SO2 | 0.05 | Sulfur dioxide |
| Wind | 0.05 | Surface wind speed — aerodynamic drag |
| AOD | 0.05 | Aerosol optical depth — air quality |

**green_score location in JSON:** `derived_layers.green_score` (NOT `layers`)

**Mandatory waypoints:** none — direct Port NY/NJ → Port of Savannah

**Typical scores:** Mostly GREEN (≥65). The US East Coast I-95 corridor is well-maintained and relatively clean.

**Time windows available:** P1, P2, P3 — three snapshots in `terrestre_usa/`

---

## How it works

### 1. Grid input

The optimizer receives a GEE JSON snapshot. Each snapshot has the same schema but
different values (satellite data updates by time window). The file contains:

- **`grid_definition`** — bounding box, cell count, cell size
- **`land_mask`** — 2D matrix for maritime (1.0 = water); absent for aviation/trucking
- **`road_mask`** — 2D matrix for trucking (1.0 = road cell); absent for maritime/aviation
- **`layers`** — per-cell values for mode-specific atmospheric layers
- **`derived_layers`** — aviation and trucking: `green_score` + mode-specific derived fields
- **`corridoriq_config`** — weights used to compute green_score

### 2. Graph construction (`build_graph`)

- One **node** per navigable cell
- **8-connected directed edges** to all navigable neighbours (including diagonals)
- Edge weight = `destination_cost * (1 - dist_weight) + normalised_haversine * dist_weight`
  (90% environmental cost, 10% distance penalty; ratios come from JSON config)
- Mode-aware: maritime = water only, aviation = all cells, trucking = road cells only

### 3. A* pathfinding (`run_astar`)

Segmented through mandatory waypoints:

```
Maritime:   Port Klang  ->  One Fathom Bank  ->  Raffles Lighthouse TSS  ->  Port of Singapore
Aviation:   PVG  ->  Dubai Intl (DXB)  ->  AMS
Trucking:   Port NY/NJ  ->  Port of Savannah  (no intermediate waypoints)
```

Each segment runs a separate A* with haversine heuristic (admissible).

If `waypoints_missed` is non-empty, the LLM retries via `build_graph(forced_waypoints=...)`.

### 4. Scoring (`score_path`)

- **Optimal score** = mean green_score of cells on the A* path
- **Baseline score** = mean green_score along the straight geodesic (Bresenham walk)
- **vs baseline %** = `(optimal - baseline) / baseline * 100`
  - Positive = A* route is greener than going straight
  - Negative = waypoint constraints force a slight detour through lower-score cells (normal)

---

## Tool call rules (enforced via system prompt)

The agent has a strict **5 tool call budget** and must follow this order:

```
1. build_graph(grid_path)          <- grid_path comes from satellite_report
      |
2. run_astar()
      |-- waypoints_missed empty? --.
      YES                            NO
       |                              |
3. score_path()                  3. build_graph(forced_waypoints=missed)
       |                              |
  return RouteRecommendation     4. run_astar()
                                      |
                                 5. score_path()
                                      |
                                 return RouteRecommendation
```

If the budget is exhausted, the agent returns the best partial result with
`feasibility_flag = false`.

**Position in pipeline:** Agent 3 always runs second, immediately after SatelliteAnalyst.
The CertificationJudge (Agent 2 in implementation, third in the flow) then uses this
`RouteRecommendation` to certify individual vehicles that followed the optimal path.

---

## File layout

```
spacehack2026/
├── aereo/
│   ├── p1/aviation_payload_p1.json   <- aviation grid, window P1 (Mar 4-18)
│   ├── p2/aviation_payload_p2.json   <- aviation grid, window P2
│   └── p3/aviation_payload_p3.json   <- aviation grid, window P3
├── latest/maritime_portklang_singapore.json    <- maritime grid (latest)
├── latest-1/maritime_portklang_singapore.json
├── latest-2/maritime_portklang_singapore.json
├── terrestre_usa/
│   ├── p1/terrestrial_usa_p1.json   <- trucking grid, window P1
│   ├── p2/terrestrial_usa_p2.json   <- trucking grid, window P2
│   └── p3/terrestrial_usa_p3.json   <- trucking grid, window P3
└── greenroute/
    ├── app/agent/
    │   ├── nodes/corridor_optimizer.py   <- LLM ReAct agent (max 5 tool calls)
    │   └── tools/optimizer_tools.py      <- 3 pure Python tools + graph/path cache
    └── scripts/
        ├── test_optimizer.py             <- smoke test (no API key needed)
        └── visualize_route.py            <- renders route PNG from any snapshot
```

---

## Testing

### Without an API key (tools only)

```bash
# From spacehack2026/ (workspace root)

# Maritime — latest snapshot (default)
python greenroute/scripts/test_optimizer.py

# Maritime — all three snapshots
python greenroute/scripts/test_optimizer.py --all

# Aviation — latest snapshot (p1)
python greenroute/scripts/test_optimizer.py --aviation

# Aviation — all three windows (p1/p2/p3)
python greenroute/scripts/test_optimizer.py --aviation --all

# Terrestrial (trucking) — latest snapshot (p1)
python greenroute/scripts/test_optimizer.py --terrestrial

# Terrestrial — all three windows (p1/p2/p3)
python greenroute/scripts/test_optimizer.py --terrestrial --all

# Any specific JSON
python greenroute/scripts/test_optimizer.py aereo/p2/aviation_payload_p2.json
python greenroute/scripts/test_optimizer.py terrestre_usa/p2/terrestrial_usa_p2.json
```

Expected output (maritime, abbreviated):

```
[1/3] build_graph ...
  Mode        : maritime
  Nodes       : 892  |  Edges: 5264
  Waypoints resolved:
    [ok]  One Fathom Bank        ->  cell [14, 19]  (3.05N, 101.45E)
    [ok]  Raffles Lighthouse TSS ->  cell [33, 39]  (1.15N, 103.45E)

[2/3] run_astar ...
  Path cells   : 33
  Distance     : 456.9 km
  Waypoints hit: ['One Fathom Bank', 'Raffles Lighthouse TSS']
  All mandatory waypoints hit [ok]

[3/3] score_path ...
  Optimal green score  : 64.8 / 100  =>  WARN
  Baseline green score : 67.8 / 100  (straight line)
  vs baseline          : -4.4%  (lower score -- waypoint constraints)
  Chokepoints          : ['One Fathom Bank', 'Raffles Lighthouse TSS']
  Feasibility          : [ok] feasible
```

Expected output (aviation p1, abbreviated):

```
[1/3] build_graph ...
  Mode        : aviation
  Nodes       : 7500  |  Edges: 58894
  Waypoints resolved:
    [ok]  Dubai Intl (DXB)  ->  cell [49, 55]  (25.5N, 55.5E)

[2/3] run_astar ...
  Path cells   : 118
  Distance     : 13243.1 km
  Waypoints hit: ['Dubai Intl (DXB)']
  All mandatory waypoints hit [ok]

[3/3] score_path ...
  Optimal green score  : 45.3 / 100  =>  WARN
  Baseline green score : 45.7 / 100  (straight line)
  vs baseline          : -0.9%  (lower score -- waypoint constraints)
  Chokepoints          : ['Dubai Intl (DXB)']
  Feasibility          : [ok] feasible
  Layer means (info only):
    no2_mol_m2               : 3.2000e-05
    turbulence_index         : 3.9491e+00
    contrail_risk            : 1.0000e+00
    wind_speed_250hpa_ms     : 9.6331e+00
```

### Visualisation (route PNG)

```bash
# Maritime -- latest snapshot (saved next to the JSON)
python greenroute/scripts/visualize_route.py latest/maritime_portklang_singapore.json

# Maritime -- all three snapshots
python greenroute/scripts/visualize_route.py --all

# Aviation -- latest snapshot (p1)
python greenroute/scripts/visualize_route.py --aviation

# Aviation -- all three windows (p1/p2/p3)
python greenroute/scripts/visualize_route.py --aviation --all

# Terrestrial (trucking) -- latest snapshot (p1)
python greenroute/scripts/visualize_route.py --terrestrial

# Terrestrial -- all three windows (p1/p2/p3)
python greenroute/scripts/visualize_route.py --terrestrial --all

# Any specific JSON
python greenroute/scripts/visualize_route.py aereo/p2/aviation_payload_p2.json
python greenroute/scripts/visualize_route.py terrestre_usa/p2/terrestrial_usa_p2.json

# Custom output path (single target only)
python greenroute/scripts/visualize_route.py latest/maritime_portklang_singapore.json --out output/route.png
```

Output files are saved as `map_route_optimal.png` next to the input JSON
(e.g. `terrestre_usa/p1/map_route_optimal.png`).

The PNG shows:
- Green score heatmap as background (same colormap as the GEE layer maps)
- White route line with cyan glow
- Cyan diamond markers at mandatory waypoints (maritime/aviation only)
- Stats box: green score, vs-baseline %, distance, badge distribution
- Maritime: land fill + coastline overlay; Aviation: full-grid heatmap; Trucking: non-road background fill

### Full LLM agent test (requires ANTHROPIC_API_KEY)

```bash
export ANTHROPIC_API_KEY=sk-ant-...

python - <<'EOF'
import sys
sys.path.insert(0, 'greenroute')

from app.agent.nodes.corridor_optimizer import run_corridor_optimizer

state = {
    "corridor_id": "SGP_PKL",
    "transport_modes": ["maritime"],
    "satellite_report": {
        "corridor_id": "SGP_PKL",
        "grid_path": "latest/maritime_portklang_singapore.json",
        "overall_score": 64.8,
    },
    "cert_decision": {"decision": "WARN", "confidence_pct": 78},
}

result = run_corridor_optimizer(state)
import json
print(json.dumps(result["route_recommendation"], indent=2))
EOF
```

---

## Dependencies

All managed by `uv`. The optimizer specifically requires:

| Package | Purpose |
|---|---|
| `networkx` | DiGraph construction and A* pathfinding |
| `anthropic` | LLM ReAct loop (full agent only) |
| `matplotlib` | Route PNG visualisation |
| `numpy` | Grid array operations in visualize_route.py |

```bash
uv sync
# or:
pip install networkx anthropic matplotlib numpy
```
