# GreenRoute Intelligence Platform — Boilerplate & Setup Guide

> Sistema multi-agente autónomo de certificación de carbono para el corredor **SGP → PKL**
> Stack: **LangGraph + Anthropic API + FastAPI** · Paquetes: **uv**

---

## Estructura del proyecto

```
greenroute/
│
├── app/
│   ├── __init__.py
│   ├── main.py                              # FastAPI app + middleware CORS
│   ├── config.py                            # Settings con pydantic-settings
│   ├── models.py                            # Pydantic models (request / response / schemas)
│   │
│   ├── agent/
│   │   ├── __init__.py                      # Exports: run_greenroute, agent_graph, AgentState
│   │   ├── graph.py                         # LangGraph StateGraph — orquestador Python puro
│   │   ├── state.py                         # AgentState TypedDict (estado compartido del grafo)
│   │   │
│   │   ├── nodes/
│   │   │   ├── __init__.py
│   │   │   ├── satellite_analyst.py         # Agente 1 — ReAct · max 5 tool calls
│   │   │   ├── certification_judge.py       # Agente 2 — ReAct · max 4 tool calls
│   │   │   ├── corridor_optimizer.py        # Agente 3 — ReAct + NetworkX · max 5 tool calls
│   │   │   └── synthesize.py                # Nodo Python puro — ensambla GreenRouteDecision
│   │   │
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── satellite_tools.py           # query_gee_no2 · query_era5_wind · query_viirs_ships · query_so2_hotspots
│   │       ├── judge_tools.py               # check_baseline_history · detect_meteorological_confound
│   │       └── optimizer_tools.py           # build_graph · run_astar · compute_co2_edge_weights
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── corridor.py                      # POST /corridor/run · GET /corridor/status/{corridor_id}
│   │   └── health.py                        # GET /health · GET /health/ping
│   │
│   └── services/
│       ├── __init__.py
│       ├── baseline_service.py              # Lectura y escritura de baselines.json
│       ├── firebase_service.py              # Push de GreenRouteDecision a Firebase Realtime DB
│       └── grid_service.py                  # Carga y normalización de maritime_grid_payload.json
│
├── data/
│   ├── baselines.json                       # Medias mensuales NO2 · consecutive_warns · audit log
│   └── maritime_grid_payload.json           # Grilla 40×50 con scores satelitales (generada en Fase 1)
│
├── tests/
│   ├── __init__.py
│   ├── test_satellite_analyst.py
│   ├── test_certification_judge.py
│   ├── test_corridor_optimizer.py
│   └── test_graph.py
│
├── scripts/
│   └── generate_grid.py                     # Fase 1: genera maritime_grid_payload.json desde GEE
│
├── .env                                     # Variables de entorno (NO subir a git)
├── .env.example                             # Plantilla de variables (sí subir a git)
├── .gitignore
├── pyproject.toml                           # Configuración del proyecto uv
└── README.md
```

---

## Responsabilidades por archivo

### app/agent/graph.py — Orquestador
- Tipo: coordinador **Python puro**, sin LLM
- Construye el `StateGraph` con los 4 nodos en secuencia fija
- Expone `run_greenroute()` como punto de entrada async

### app/agent/state.py — AgentState
Estado compartido TypedDict que fluye por todos los nodos:

| Campo | Tipo | Descripción |
|---|---|---|
| `messages` | `List[BaseMessage]` | Historial LangGraph |
| `corridor_id` | `str` | `"SGP_PKL"` \| `"PVG_DXB_AMS"` |
| `transport_modes` | `List[str]` | `["maritime"]` \| `["aviation"]` |
| `triggered_by` | `str` | `scheduler` \| `new_data` \| `voyage_completed` |
| `vehicle_track` | `dict \| None` | Track real del vehículo (AIS/ADS-B) |
| `satellite_report` | `dict \| None` | Output del SatelliteAnalyst |
| `route_recommendation` | `dict \| None` | Output del CorridorOptimizer |
| `cert_decision` | `dict \| None` | Output del CertificationJudge |
| `final_decision` | `dict \| None` | GreenRouteDecision JSON final |
| `pushed_to_firebase` | `bool` | Confirmación de sync con Firebase |

### app/agent/nodes/satellite_analyst.py — Agente 1
- Modelo: `claude-haiku-4-5`
- Loop ReAct · máximo **5 tool calls**
- Siempre se ejecuta primero
- Tools disponibles: `query_gee_no2`, `query_era5_wind`, `query_viirs_ships`, `query_so2_hotspots`
- Output escrito en `state["satellite_report"]` — incluye `grid_path`

### app/agent/nodes/corridor_optimizer.py — Agente 2 en el flujo
- Modelo: `claude-haiku-4-5`
- Loop ReAct + NetworkX · máximo **5 tool calls**
- Siempre se ejecuta después del SatelliteAnalyst
- Lee `state["satellite_report"]["grid_path"]` para construir el grafo
- Tools disponibles: `build_graph`, `run_astar`, `score_path`
- Output escrito en `state["route_recommendation"]`

### app/agent/nodes/certification_judge.py — Agente 3 en el flujo
- Modelo: `claude-haiku-4-5`
- Loop ReAct · máximo **4 tool calls**
- Siempre se ejecuta después del CorridorOptimizer
- Certifica el **vehículo** que siguió la ruta recomendada, no el corredor
- Tools disponibles: `check_track_compliance`, `verify_waypoint_passage`
- Output escrito en `state["cert_decision"]`

### app/agent/nodes/synthesize.py — Nodo final
- **Python puro, sin LLM**
- Ensambla `GreenRouteDecision` a partir de los 3 outputs anteriores
- Actualiza `baselines.json` via `baseline_service`
- Dispara push a Firebase via `firebase_service`

### app/agent/tools/satellite_tools.py
| Tool | Fuente real | Propósito |
|---|---|---|
| `query_gee_no2` | COPERNICUS/S5P/NRTI/L3_NO2 | NO2 troposférico — señal primaria |
| `query_era5_wind` | NOAA/GFS0P25 | Viento superficie y 250hPa |
| `query_viirs_ships` | NOAA/VIIRS/DNB/MONTHLY_V1 | Densidad tráfico marítimo |
| `query_so2_hotspots` | COPERNICUS/S5P/NRTI/L3_SO2 | Violaciones ECA / HFO |

### app/agent/tools/judge_tools.py
| Tool | Propósito |
|---|---|
| `check_track_compliance` | Compara track AIS/ADS-B contra ruta óptima, calcula desviación |
| `verify_waypoint_passage` | Confirma que el vehículo pasó por los waypoints obligatorios |

### app/agent/tools/optimizer_tools.py
| Tool | Propósito |
|---|---|
| `build_graph` | Construye NetworkX DiGraph con 8-vecinos navegables, modo-aware |
| `run_astar` | A* con heurística haversine y waypoints forzados |
| `score_path` | Score 0-100 del path óptimo vs baseline geodésica recta |

### app/routers/corridor.py
| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/corridor/run` | Ejecuta el pipeline completo con `CorridorRunRequest` |
| `GET` | `/corridor/status/{corridor_id}` | Retorna el último `GreenRouteDecision` del corredor |

### app/services/
| Servicio | Responsabilidad |
|---|---|
| `baseline_service.py` | CRUD sobre `data/baselines.json` — medias, z-scores, consecutive_warns |
| `firebase_service.py` | Push del `GreenRouteDecision` a Firebase Realtime DB |
| `grid_service.py` | Carga y normalización de `data/maritime_grid_payload.json` |

---

## Flujo de orquestamiento

```
START
  │
  ▼
┌───────────────────────────┐
│      SatelliteAnalyst     │  ← siempre primero
│   ReAct · max 5 calls     │
└─────────────┬─────────────┘
              │  satellite_report (con grid_path) → AgentState
              ▼
┌───────────────────────────┐
│    CorridorOptimizer      │  ← siempre segundo
│   ReAct · max 5 calls     │
└─────────────┬─────────────┘
              │  route_recommendation → AgentState
              ▼
┌───────────────────────────┐
│    CertificationJudge     │  ← siempre tercero
│   ReAct · max 4 calls     │  certifica el vehículo que siguió la ruta
└─────────────┬─────────────┘
              │  cert_decision → AgentState
              ▼
  ┌───────────────────────┐
  │       synthesize      │  ← Python puro, sin LLM
  │  GreenRouteDecision   │
  │  + push Firebase      │
  └───────────┬───────────┘
              │
             END
```

---

## Prerrequisitos

| Herramienta | Versión mínima |
|---|---|
| Python | 3.11+ |
| uv | 0.4+ |

---

## 1. Instalar uv

### macOS / Linux
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Windows (PowerShell)
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Verificar
```bash
uv --version
```

---

## 2. Clonar el repositorio

```bash
git clone https://github.com/tu-usuario/greenroute.git
cd greenroute
```

---

## 3. Crear el entorno virtual

```bash
uv venv --python 3.11
```

### Activar

```bash
# macOS / Linux
source .venv/bin/activate

# Windows CMD
.venv\Scripts\activate.bat

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

---

## 4. Instalar dependencias

```bash
# Solo producción
uv sync

# Producción + desarrollo (tests)
uv sync --extra dev
```

---

## 5. Variables de entorno

```bash
cp .env.example .env
```

Contenido del `.env`:

```env
# Anthropic
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Server
API_HOST=0.0.0.0
API_PORT=8000
DEBUG=True

# Claude — modelo para los 3 agentes
CLAUDE_AGENT_MODEL=claude-haiku-4-5
CLAUDE_MAX_TOKENS=4096
CLAUDE_TEMPERATURE=0.2

# Google Earth Engine
GEE_SERVICE_ACCOUNT=greenroute@your-project.iam.gserviceaccount.com
GEE_KEY_FILE=gee_service_account.json

# Firebase
FIREBASE_URL=https://your-project-default-rtdb.firebaseio.com
FIREBASE_CREDENTIALS_FILE=firebase_service_account.json

# Corredor
CORRIDOR_ID=SGP_PKL
GRID_FILE=data/maritime_grid_payload.json
BASELINES_FILE=data/baselines.json
```

---

## 6. Iniciar el servidor con uvicorn

### Desarrollo (hot-reload)

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Producción

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Con uv run (sin activar entorno manualmente)

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Con variables inline (útil para CI/CD)

```bash
ANTHROPIC_API_KEY=sk-ant-xxx uv run uvicorn app.main:app --reload --port 8000
```

---

## 7. Verificar que funciona

```bash
# Health check
curl http://localhost:8000/health/

# Ping
curl http://localhost:8000/health/ping

# Swagger UI — abrir en el navegador
http://localhost:8000/docs
```

### Test — nuevos datos satelitales (recalcular ruta óptima)

```bash
curl -X POST http://localhost:8000/corridor/run \
  -H "Content-Type: application/json" \
  -d '{
    "corridor_id": "SGP_PKL",
    "transport_modes": ["maritime"],
    "triggered_by": "new_data"
  }'
```

### Test — viaje completado (certificar vehículo)

```bash
curl -X POST http://localhost:8000/corridor/run \
  -H "Content-Type: application/json" \
  -d '{
    "corridor_id": "SGP_PKL",
    "transport_modes": ["maritime"],
    "triggered_by": "voyage_completed",
    "vehicle_track": {
      "vehicle_id": "IMO9876543",
      "voyage_id": "SGP_PKL_20260327_001",
      "ais_points": []
    }
  }'
```

### Consultar estado actual del corredor

```bash
curl http://localhost:8000/corridor/status/SGP_PKL
```

---

## pyproject.toml

```toml
[project]
name = "greenroute"
version = "1.0.0"
description = "Sistema multi-agente de certificación de carbono SGP→PKL"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "python-multipart>=0.0.12",
    "anthropic>=0.40.0",
    "langchain>=0.3.0",
    "langchain-anthropic>=0.3.0",
    "langchain-core>=0.3.0",
    "langgraph>=0.2.0",
    "pydantic>=2.9.0",
    "pydantic-settings>=2.6.0",
    "python-dotenv>=1.0.0",
    "networkx>=3.3",
    "earthengine-api>=0.1.400",
    "firebase-admin>=6.5.0",
    "numpy>=1.26.0",
    "httpx>=0.27.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.27.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
dev-dependencies = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.27.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

---

## .env.example

```env
ANTHROPIC_API_KEY=

API_HOST=0.0.0.0
API_PORT=8000
DEBUG=True

CLAUDE_AGENT_MODEL=claude-haiku-4-5
CLAUDE_MAX_TOKENS=4096
CLAUDE_TEMPERATURE=0.2

GEE_SERVICE_ACCOUNT=
GEE_KEY_FILE=gee_service_account.json

FIREBASE_URL=
FIREBASE_CREDENTIALS_FILE=firebase_service_account.json

CORRIDOR_ID=SGP_PKL
GRID_FILE=data/maritime_grid_payload.json
BASELINES_FILE=data/baselines.json
```

---

## .gitignore

```gitignore
# Entorno virtual
.venv/

# Variables de entorno y credenciales
.env
gee_service_account.json
firebase_service_account.json

# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/

# IDEs
.idea/
.vscode/

# Datos generados
data/maritime_grid_payload.json

# Logs
*.log
```

---

## Endpoints disponibles

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/` | Info de la API |
| `GET` | `/health/` | Health check |
| `GET` | `/health/ping` | Ping / pong |
| `POST` | `/corridor/run` | Ejecuta el pipeline completo |
| `GET` | `/corridor/status/{corridor_id}` | Último GreenRouteDecision del corredor |
| `GET` | `/docs` | Swagger UI |
| `GET` | `/redoc` | ReDoc |

---

## Comandos útiles de uv

| Comando | Descripción |
|---|---|
| `uv sync` | Instala todas las dependencias |
| `uv add <paquete>` | Agrega dependencia y actualiza `pyproject.toml` |
| `uv add --dev <paquete>` | Agrega dependencia de desarrollo |
| `uv remove <paquete>` | Elimina una dependencia |
| `uv run <comando>` | Ejecuta un comando dentro del entorno |
| `uv pip list` | Lista paquetes instalados |
| `uv lock` | Regenera `uv.lock` sin instalar |

---

## Troubleshooting

### `ANTHROPIC_API_KEY not set`
Verificar que el archivo `.env` existe y tiene el valor correcto:
```bash
cat .env | grep ANTHROPIC_API_KEY
```

### `ModuleNotFoundError`
El entorno virtual no está activo o `uv sync` no se ejecutó:
```bash
source .venv/bin/activate
uv sync
```

### `Address already in use` (puerto 8000 ocupado)
```bash
# Usar otro puerto
uvicorn app.main:app --reload --port 8001

# O liberar el puerto (macOS/Linux)
lsof -ti:8000 | xargs kill -9
```

### `earthengine-api` — autenticación GEE
Antes de la primera ejecución, autenticar la cuenta de servicio:
```bash
uv run python -c "import ee; ee.Authenticate()"
```
