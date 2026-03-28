# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GreenRoute Intelligence Platform — a multi-agent carbon certification system for shipping/aviation corridors. Uses satellite data to compute lowest-carbon routes via A* pathfinding and certifies vehicles that followed them.

## Development Commands

```bash
# Install (uses uv package manager, Python 3.11+)
uv venv --python 3.11
uv sync --extra dev

# Run API server (from greenroute/)
uv run uvicorn app.main:app --reload --port 8000

# Run tests
pytest greenroute/tests/
pytest -v greenroute/tests/test_corridor_optimizer.py

# Smoke tests (no API key needed — test pathfinding directly)
python greenroute/scripts/test_optimizer.py                 # maritime latest
python greenroute/scripts/test_optimizer.py --all           # all maritime snapshots
python greenroute/scripts/test_optimizer.py --aviation      # aviation
python greenroute/scripts/test_optimizer.py --terrestrial   # trucking

# Generate route visualization PNGs
python greenroute/scripts/visualize_route.py latest/maritime_portklang_singapore.json
python greenroute/scripts/visualize_route.py --all
```

## Architecture

### Multi-Agent Pipeline (LangGraph StateGraph)

Four nodes execute in fixed sequence, sharing `AgentState` (TypedDict):

1. **SatelliteAnalyst** (`nodes/satellite_analyst.py`) — Queries Google Earth Engine via ReAct loop (max 5 tool calls). Tools: `query_gee_no2`, `query_era5_wind`, `query_viirs_ships`, `query_so2_hotspots`. Outputs `SatelliteReport` with `overall_score` (0–100).

2. **CorridorOptimizer** (`nodes/corridor_optimizer.py`) — A* pathfinding on satellite grid via ReAct loop (max 5 tool calls). Tools: `build_graph()` (NetworkX 8-connected DiGraph), `run_astar()` (haversine heuristic + mandatory waypoints), `score_path()` (compare vs baseline). Edge weight: `destination_cost * 0.9 + normalized_haversine * 0.1`. Outputs `RouteRecommendation`.

3. **CertificationJudge** (`nodes/certification_judge.py`) — Certifies vehicles against optimal route (max 4 tool calls). Tools: `check_track_compliance()`, `verify_waypoint_passage()`. Outputs `CertDecision` (GREEN/WARN/RED).

4. **synthesize** (`nodes/synthesize.py`) — Pure Python (no LLM). Assembles `GreenRouteDecision`, updates `baselines.json`, pushes to Firebase.

### Green Score Formula

```
C_env = 0.30*NO2 + 0.10*SO2 + 0.20*wind_cost + 0.15*wave + 0.15*traffic
green_score = 100 * (1 - C_env / 0.90)
```
Badges: GREEN ≥ 65, WARN 45–64, RED < 45.

### Supported Corridors

| Corridor | Mode | Grid | Data Path |
|---|---|---|---|
| SGP ↔ PKL | Maritime | 40×60 @ 0.1° | `latest/maritime_portklang_singapore.json` |
| PVG → DXB → AMS | Aviation | 60×125 @ 1.0° | `aereo/p[1-3]/aviation_payload_p[1-3].json` |
| NY/NJ → Savannah | Trucking | 200×180 @ 0.05° | `terrestre_usa/p[1-3]/terrestrial_usa_p[1-3].json` |

Maritime mandatory waypoints: One Fathom Bank (2.92°N, 101.60°E) → Raffles Lighthouse (1.17°N, 103.45°E).

### Key State Fields

`AgentState` fields passed between agents: `corridor_id`, `transport_modes`, `triggered_by`, `vehicle_track` (AIS/ADS-B), `satellite_report`, `route_recommendation`, `cert_decision`, `final_decision`, `pushed_to_firebase`.

### Data Persistence

- `greenroute/data/baselines.json` — Monthly NO₂ medians, z-scores, consecutive WARN counts, audit log
- Firebase Realtime DB — `GreenRouteDecision` pushed after each run
- Satellite grid JSON files — Pre-computed `green_score` per cell (not queried live in optimizer)

## Implementation Status

Most app source files are **empty stubs** — the architecture is designed but awaiting implementation:
- Empty stubs: `app/main.py`, `app/config.py`, `app/models.py`, `app/agent/graph.py`, `app/agent/state.py`, all agent nodes, all routers, all services, `app/agent/tools/satellite_tools.py`, `app/agent/tools/judge_tools.py`
- **Functional:** `scripts/test_optimizer.py` and `scripts/visualize_route.py` contain working pathfinding and visualization logic that can be referenced when implementing `optimizer_tools.py`

## Environment Variables

```env
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_AGENT_MODEL=claude-haiku-4-5
CLAUDE_MAX_TOKENS=4096
CLAUDE_TEMPERATURE=0.2
GEE_SERVICE_ACCOUNT=...         # Google Earth Engine
GEE_KEY_FILE=gee_service_account.json
FIREBASE_URL=https://...firebaseio.com
FIREBASE_CREDENTIALS_FILE=firebase_service_account.json
CORRIDOR_ID=SGP_PKL
GRID_FILE=data/maritime_grid_payload.json
BASELINES_FILE=data/baselines.json
```

## Reference Docs

- `GREENROUTE_SETUP.md` — Full setup, API endpoints, and troubleshooting
- `greenroute_architecture.md` — Detailed agent design, state flows, and implementation phases
- `CORRIDOR_OPTIMIZER.md` — A* pathfinding agent, grid formats, and testing instructions
- `data-dicts/` — Schema definitions for maritime, aviation, and terrestrial grid JSON formats
