# GreenRoute Intelligence Platform — Setup & Run Guide

Multi-agent carbon certification system for shipping and aviation corridors.
**Stack:** LangGraph · Anthropic API · FastAPI · NetworkX · Python 3.11+

---

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| Python | 3.11+ | [python.org](https://www.python.org/downloads/) |
| uv | latest | see below |
| Git | any | [git-scm.com](https://git-scm.com/) |

### Install uv

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Verify
uv --version
```

---

## 1. Clone the Repository

```bash
git clone <repo-url>
cd spacehack2026
```

---

## 2. Create the Virtual Environment

All commands below run from `spacehack2026/` (the workspace root) unless noted.

```bash
# Create .venv with Python 3.11
uv venv --python 3.11

# Activate — macOS / Linux
source .venv/bin/activate

# Activate — Windows CMD
.venv\Scripts\activate.bat

# Activate — Windows PowerShell
.venv\Scripts\Activate.ps1
```

---

## 3. Install Dependencies

```bash
# Run from greenroute/ (where pyproject.toml lives)
cd greenroute

# Production dependencies only
uv sync

# Production + dev tools (pytest)
uv sync --extra dev
```

Core packages installed: `fastapi`, `uvicorn`, `anthropic`, `langchain`, `langgraph`,
`pydantic-settings`, `networkx`, `numpy`, `httpx`.

> **Optional:** Firebase push support requires `firebase-admin` (not in `pyproject.toml` by default).
> Install it only if you have Firebase credentials:
> ```bash
> uv add firebase-admin
> ```

---

## 4. Environment Variables

```bash
# From greenroute/
cp .env.template .env
```

Open `.env` and fill in your values:

```env
# ── Required ───────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-YOUR_KEY_HERE

# ── Claude model (all three agent nodes use this) ──────────────────────────
CLAUDE_AGENT_MODEL=claude-haiku-4-5
CLAUDE_MAX_TOKENS=4096
CLAUDE_TEMPERATURE=0.2

# ── Per-agent tool-call budgets ─────────────────────────────────────────────
SATELLITE_ANALYST_MAX_TOOL_CALLS=5
CORRIDOR_OPTIMIZER_MAX_TOOL_CALLS=5
CERTIFICATION_JUDGE_MAX_TOOL_CALLS=4

# ── API server ──────────────────────────────────────────────────────────────
API_HOST=0.0.0.0
API_PORT=8000
DEBUG=false

# ── Google Earth Engine (only needed to regenerate grid JSONs) ─────────────
GEE_SERVICE_ACCOUNT=greenroute@your-gcp-project.iam.gserviceaccount.com
GEE_KEY_FILE=gee_service_account.json

# ── Firebase Realtime DB (only needed for live dashboard push) ─────────────
FIREBASE_URL=https://your-project-default-rtdb.firebaseio.com
FIREBASE_CREDENTIALS_FILE=firebase_service_account.json

# ── Default corridor / data paths ──────────────────────────────────────────
CORRIDOR_ID=SGP_PKL
GRID_FILE=data/maritime_grid_payload.json
BASELINES_FILE=data/baselines.json
```

**Only `ANTHROPIC_API_KEY` is required** to run the agents.
GEE and Firebase credentials are optional — the pipeline runs without them.

---

## 5. Run the API Server

All commands from `greenroute/` (where `app/` lives):

```bash
# Development — hot reload
uv run uvicorn app.main:app --reload --port 8000

# Or with the venv active
uvicorn app.main:app --reload --port 8000
```

Server starts at `http://localhost:8000`.
Swagger UI: `http://localhost:8000/docs`

---

## 6. Verify the Server

```bash
# Health check
curl http://localhost:8000/health

# Expected: {"status":"ok"}
```

---

## 7. Run the Pipeline via API

### Maritime — Singapore Strait (SGP ↔ PKL)

**Corridor-level assessment (no vehicle):**
```bash
curl -X POST http://localhost:8000/corridor/run \
  -H "Content-Type: application/json" \
  -d '{
    "corridor_id": "SGP_PKL",
    "transport_modes": ["maritime"],
    "triggered_by": "new_data"
  }'
```

**Certify a vessel that completed a voyage:**
```bash
curl -X POST http://localhost:8000/corridor/run \
  -H "Content-Type: application/json" \
  -d '{
    "corridor_id": "SGP_PKL",
    "transport_modes": ["maritime"],
    "triggered_by": "voyage_completed",
    "vehicle_id": "IMO9876543",
    "vehicle_track": [
      {"lat": 2.99, "lon": 101.39},
      {"lat": 2.92, "lon": 101.60},
      {"lat": 1.17, "lon": 103.45},
      {"lat": 1.26, "lon": 103.84}
    ]
  }'
```

### Aviation — Shanghai → Dubai → Amsterdam (PVG → DXB → AMS)

```bash
curl -X POST http://localhost:8000/corridor/run \
  -H "Content-Type: application/json" \
  -d '{
    "corridor_id": "PVG_DXB_AMS",
    "transport_modes": ["aviation"],
    "triggered_by": "new_data"
  }'
```

### Trucking — Port NY/NJ → Savannah (NYNJ_SAV)

```bash
curl -X POST http://localhost:8000/corridor/run \
  -H "Content-Type: application/json" \
  -d '{
    "corridor_id": "NYNJ_SAV",
    "transport_modes": ["trucking"],
    "triggered_by": "scheduler"
  }'
```

### Check last run status

```bash
curl http://localhost:8000/corridor/status/SGP_PKL
curl http://localhost:8000/corridor/status/PVG_DXB_AMS
curl http://localhost:8000/corridor/status/NYNJ_SAV
```

---

## 8. Smoke Tests (No API Key Required)

These scripts test the A* pathfinding tools directly, without calling the LLM.
Run from the **workspace root** (`spacehack2026/`):

```bash
# Maritime — latest snapshot
python greenroute/scripts/test_optimizer.py

# Maritime — all three snapshots
python greenroute/scripts/test_optimizer.py --all

# Aviation — latest (P1)
python greenroute/scripts/test_optimizer.py --aviation

# Aviation — all windows (P1 / P2 / P3)
python greenroute/scripts/test_optimizer.py --aviation --all

# Trucking — latest (P1)
python greenroute/scripts/test_optimizer.py --terrestrial

# Trucking — all windows
python greenroute/scripts/test_optimizer.py --terrestrial --all

# Any specific snapshot
python greenroute/scripts/test_optimizer.py latest/maritime_portklang_singapore.json
```

### Generate route visualisation PNGs

```bash
# Maritime — single snapshot
python greenroute/scripts/visualize_route.py latest/maritime_portklang_singapore.json

# Maritime — all three snapshots
python greenroute/scripts/visualize_route.py --all

# Aviation — latest (P1)
python greenroute/scripts/visualize_route.py --aviation

# Aviation — all windows
python greenroute/scripts/visualize_route.py --aviation --all

# Trucking — latest (P1)
python greenroute/scripts/visualize_route.py --terrestrial

# Trucking — all windows
python greenroute/scripts/visualize_route.py --terrestrial --all
```

PNGs are saved next to the corresponding JSON file (e.g. `latest/map_route_optimal.png`).

---

## 9. Run Tests

From `greenroute/`:

```bash
# All tests
pytest tests/

# With verbose output
pytest -v tests/

# Single test file
pytest -v tests/test_corridor_optimizer.py
pytest -v tests/test_certification_judge.py
pytest -v tests/test_satellite_analyst.py
pytest -v tests/test_graph.py
```

---

## 10. Project Structure

```
spacehack2026/
├── greenroute/                          ← Python package root
│   ├── pyproject.toml
│   ├── .env.template                    ← copy to .env and fill in keys
│   ├── data/
│   │   └── baselines.json               ← NO2 baselines + audit log (auto-updated)
│   │
│   ├── app/
│   │   ├── main.py                      ← FastAPI app entry point
│   │   ├── config.py                    ← env vars + corridor configs (SGP_PKL, PVG_DXB_AMS, NYNJ_SAV)
│   │   ├── models.py                    ← Pydantic models for all agents
│   │   │
│   │   ├── agent/
│   │   │   ├── graph.py                 ← LangGraph StateGraph (4-node pipeline)
│   │   │   ├── state.py                 ← AgentState TypedDict
│   │   │   ├── payload_registry.py      ← maps corridor IDs to grid JSON paths
│   │   │   │
│   │   │   ├── nodes/
│   │   │   │   ├── satellite_analyst.py ← Agent 1: ReAct, max 5/9 tool calls
│   │   │   │   ├── corridor_optimizer.py← Agent 2: ReAct + NetworkX A*, max 5 calls
│   │   │   │   ├── certification_judge.py← Agent 3: ReAct, max 4 calls
│   │   │   │   └── synthesize.py        ← Node 4: pure Python, assembles final decision
│   │   │   │
│   │   │   └── tools/
│   │   │       ├── satellite_tools.py   ← 10 tools (NO2, wind, VIIRS, SO2, CO, turbulence…)
│   │   │       ├── optimizer_tools.py   ← build_graph, run_astar, score_path
│   │   │       └── judge_tools.py       ← check_track_compliance, verify_waypoint_passage
│   │   │
│   │   ├── routers/
│   │   │   ├── health.py                ← GET /health
│   │   │   └── corridor.py              ← POST /corridor/run, GET /corridor/status/{id}
│   │   │
│   │   └── services/
│   │       ├── baseline_service.py      ← read/update/save baselines.json
│   │       └── firebase_service.py      ← push GreenRouteDecision to Firebase
│   │
│   ├── scripts/
│   │   ├── test_optimizer.py            ← smoke test A* (no API key needed)
│   │   └── visualize_route.py           ← render route PNG over green score heatmap
│   │
│   └── tests/
│       ├── test_satellite_analyst.py
│       ├── test_corridor_optimizer.py
│       ├── test_certification_judge.py
│       └── test_graph.py
│
├── latest/                              ← maritime grid snapshots (3 windows)
├── latest-1/
├── latest-2/
├── aereo/p1/, aereo/p2/, aereo/p3/      ← aviation grid snapshots
└── terrestre_usa/p1/, p2/, p3/          ← trucking grid snapshots
```

---

## 11. Supported Corridors

| Corridor ID | Mode | Route | Grid size |
|---|---|---|---|
| `SGP_PKL` | Maritime | Port Klang ↔ Port of Singapore | 40 × 60 @ 0.1° |
| `PVG_DXB_AMS` | Aviation | Shanghai Pudong → Dubai → Amsterdam | 60 × 125 @ 1.0° |
| `NYNJ_SAV` | Trucking | Port NY/NJ → Port of Savannah (I-95) | 200 × 180 @ 0.05° |

### Mandatory waypoints

| Corridor | Waypoints |
|---|---|
| SGP_PKL | One Fathom Bank (2.92°N, 101.60°E) → Raffles Lighthouse (1.17°N, 103.45°E) |
| PVG_DXB_AMS | Dubai Intl DXB (25.25°N, 55.36°E) |
| NYNJ_SAV | None |

---

## 12. Agent Pipeline

```
START
  │
  ▼
SatelliteAnalyst      — reads grid JSON, queries 4–10 satellite layers
  │  satellite_report (overall_score, badge, layer_results, grid_path)
  ▼
CorridorOptimizer     — builds NetworkX graph, runs A*, scores vs baseline
  │  route_recommendation (optimal path cells, green score, waypoints validated)
  ▼
CertificationJudge    — checks vehicle track compliance and waypoint passage
  │  cert_decision (GREEN / WARN / RED certificate, compliance_pct)
  ▼
synthesize            — assembles GreenRouteDecision, updates baselines.json,
  │                     pushes to Firebase (if configured)
  ▼
END  →  GreenRouteDecision returned in API response
```

### Badge thresholds

| Badge | Green score |
|---|---|
| GREEN | ≥ 65 |
| WARN | 45 – 64 |
| RED | < 45 |

---

## 13. Temporal Windows

Each corridor has three pre-computed grid snapshots. Pass `temporal_window` in the API to pick a specific one:

| Corridor | Window values |
|---|---|
| SGP_PKL | `"latest"` (default), `"latest-1"`, `"latest-2"` |
| PVG_DXB_AMS | `"P1"` (default), `"P2"`, `"P3"` |
| NYNJ_SAV | `"P1"` (default), `"P2"`, `"P3"` |

Example:
```bash
curl -X POST http://localhost:8000/corridor/run \
  -H "Content-Type: application/json" \
  -d '{
    "corridor_id": "PVG_DXB_AMS",
    "transport_modes": ["aviation"],
    "triggered_by": "new_data",
    "temporal_window": "P2"
  }'
```

---

## 14. Troubleshooting

### `ANTHROPIC_API_KEY` error at startup

The key is read from `greenroute/.env`. Make sure:
```bash
cat greenroute/.env | grep ANTHROPIC_API_KEY
# should print: ANTHROPIC_API_KEY=sk-ant-...
```
The server must be started from `greenroute/`, not from `spacehack2026/`.

### `ModuleNotFoundError: No module named 'langgraph'`

The venv is not active, or `uv sync` was not run inside `greenroute/`:
```bash
cd greenroute
uv sync --extra dev
source ../.venv/bin/activate   # or .venv/bin/activate from greenroute/
```

### Port 8000 already in use

```bash
# Use a different port
uvicorn app.main:app --reload --port 8001

# Or kill what is using 8000 (macOS / Linux)
lsof -ti:8000 | xargs kill -9
```

### Grid file not found

Smoke tests and the agent pipeline both expect to find grid JSON files relative to the workspace root (`spacehack2026/`). Run scripts from `spacehack2026/`, not from inside `greenroute/`:
```bash
# Correct — from spacehack2026/
python greenroute/scripts/test_optimizer.py

# Wrong — from greenroute/
python scripts/test_optimizer.py
```

### Firebase push skipped

`pushed_to_firebase: false` in the response is normal if `FIREBASE_URL` is empty or `firebase-admin` is not installed. The rest of the pipeline still runs and returns a valid `GreenRouteDecision`.

### `uv` common commands

```bash
uv sync                  # install / update all dependencies
uv add <package>         # add a new dependency
uv add --dev <package>   # add a dev-only dependency
uv run <command>         # run a command inside the venv without activating it
uv pip list              # list installed packages
```
