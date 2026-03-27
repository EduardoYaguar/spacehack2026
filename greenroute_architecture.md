# GreenRoute Intelligence Platform — Arquitectura de Agentes

> Documento de planificación pre-implementación.
> Corredor: Port of Singapore (SGP) → Port Klang (PKL) · Modos: Marítimo + Aviación

---

## 1. Visión general del sistema

GreenRoute es un sistema multi-agente autónomo de ciclo cerrado. Consume datos satelitales reales de Google Earth Engine, analiza el corredor SGP_PKL, emite una certificación de carbono (GREEN / WARN / RED) y, cuando es necesario, calcula la ruta alternativa de menor emisión usando A* sobre una grilla de 40×50 celdas.

El orquestador no es un LLM. Es un coordinador Python puro implementado con LangGraph (StateGraph) que decide qué agentes invocar, en qué orden, y con qué inputs, según el trigger y los resultados intermedios.

---

## 2. Componentes principales

### 2.1 Orquestador (LangGraph StateGraph)

- Tipo: Coordinador Python, NO un LLM
- Framework: LangGraph StateGraph con AgentState compartido
- Responsabilidad: secuenciar los sub-agentes, enrutar condicionalmente, sintetizar el output final
- No toma decisiones de dominio — delega toda la lógica a los agentes

### 2.2 SatelliteAnalyst (Agente 1)

- Tipo: Agente LLM con loop ReAct
- Modelo: claude-haiku-4-5
- Responsabilidad: recuperar e interpretar todas las capas satelitales del corredor
- Output: SatelliteReport JSON
- Siempre se ejecuta primero, sin excepción

### 2.3 CertificationJudge (Agente 2)

- Tipo: Agente LLM con loop ReAct
- Modelo: claude-haiku-4-5
- Responsabilidad: emitir certificación GREEN / WARN / RED considerando contexto meteorológico
- Input: SatelliteReport del agente anterior + baselines.json
- Output: CertDecision JSON
- Siempre se ejecuta después del SatelliteAnalyst

### 2.4 CorridorOptimizer (Agente 3)

- Tipo: Agente LLM con loop ReAct + NetworkX
- Modelo: claude-haiku-4-5
- Responsabilidad: calcular la ruta de menor carbono mediante A* sobre la grilla satelital
- Input: SatelliteReport + decisión del CertificationJudge
- Output: RouteRecommendation JSON
- Solo se ejecuta bajo condiciones específicas (ver sección 4)

---

## 3. AgentState — Estado compartido del grafo

El estado fluye a través de todos los nodos del grafo. Cada agente lee lo que necesita y escribe solo su output.

```
AgentState
├── messages              List[BaseMessage]   — historial LangGraph
│
├── INPUT del corredor
│   ├── corridor_id       str                 — "SGP_PKL"
│   ├── transport_modes   List[str]           — ["maritime"] | ["maritime", "aviation"]
│   ├── triggered_by      str                 — scheduler | reroute_needed | degradation_event
│   ├── current_cert_status str               — GREEN | WARN | RED
│   └── last_score        float               — último score registrado
│
├── RESULTADOS por agente
│   ├── satellite_report  dict | None         — output de SatelliteAnalyst
│   ├── cert_decision     dict | None         — output de CertificationJudge
│   └── route_recommendation dict | None      — output de CorridorOptimizer
│
├── CONTROL de flujo
│   ├── run_optimizer     bool                — el juez decide si invocar optimizer
│   └── next_action       str | None
│
└── OUTPUT final
    ├── final_decision    dict | None         — GreenRouteDecision JSON
    └── pushed_to_firebase bool
```

---

## 4. Flujo de orquestamiento

### 4.1 Diagrama de flujo

```
START
  │
  ▼
┌─────────────────────────┐
│    SatelliteAnalyst     │  ← siempre primero
│  (ReAct · max 5 calls)  │
└────────────┬────────────┘
             │  satellite_report
             ▼
┌─────────────────────────┐
│   CertificationJudge    │  ← siempre segundo
│  (ReAct · max 4 calls)  │
└────────────┬────────────┘
             │
     ┌───────┴────────┐
     │  ¿run_optimizer?│
     └───────┬────────┘
         SI  │  NO
         │   └────────────────────────┐
         ▼                            ▼
┌─────────────────────┐    ┌──────────────────────┐
│  CorridorOptimizer  │    │  (skip optimizer)    │
│ (ReAct · max 5 calls│    └──────────┬───────────┘
└──────────┬──────────┘               │
           │                          │
           └──────────┬───────────────┘
                      ▼
          ┌───────────────────────┐
          │      synthesize       │
          │  (Python puro, no LLM)│
          └───────────┬───────────┘
                      │  final_decision JSON
                      ▼
                     END
```

### 4.2 Regla de activación del CorridorOptimizer

El nodo `should_run_optimizer` evalúa el estado tras CertificationJudge:

| Condición | ¿Corre optimizer? |
|---|---|
| triggered_by = "reroute_needed" | Siempre SÍ |
| triggered_by = "degradation_event" | SÍ |
| cert_decision = "RED" | SÍ |
| cert_decision = "WARN" | SÍ |
| cert_decision = "GREEN" y trigger = "scheduler" | NO |

### 4.3 Triggers del sistema

| Trigger | Descripción | Orden de agentes |
|---|---|---|
| scheduler | Ejecución periódica programada | Analyst → Judge → (Optimizer si WARN/RED) |
| reroute_needed | Operador solicita ruta alternativa | Analyst → Judge → Optimizer (forzado) |
| degradation_event | Degradación detectada en tiempo real | Analyst → Judge → Optimizer |

---

## 5. Detalle de cada agente

### 5.1 SatelliteAnalyst

**Loop ReAct — máximo 5 tool calls**

Reglas de uso de tools en orden:

1. Siempre llamar `query_gee_no2` primero
2. Si null_count > 30% de celdas → llamar de nuevo con date_range_days=14
3. Siempre llamar `query_era5_wind`
4. Llamar `query_viirs_ships` solo para segmentos marítimos
5. Llamar `query_so2_hotspots` si no2_mean > 2.5e-5 mol/m²
6. Si el mes es junio-octubre → alertar posible confound de fuegos en Sumatra

**Tools:**

| Tool | Fuente real (producción) | Propósito |
|---|---|---|
| query_gee_no2 | COPERNICUS/S5P/NRTI/L3_NO2 | NO2 troposférico — señal primaria de emisiones |
| query_era5_wind | NOAA/GFS0P25 | Viento superficie (barcos) y 250hPa (aviación) |
| query_viirs_ships | NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG | Densidad de tráfico marítimo (solo marítimo) |
| query_so2_hotspots | COPERNICUS/S5P/NRTI/L3_SO2 | Violaciones ECA, combustible HFO |

**Output — SatelliteReport:**

```json
{
  "corridor_id": "SGP_PKL",
  "analysis_timestamp": "2026-03-27T14:00:00Z",
  "transport_mode": "maritime",
  "cells_analyzed": 1180,
  "no2_mean": 1.89e-05,
  "no2_max": 4.21e-05,
  "no2_deviation_from_baseline_pct": 12.4,
  "no2_zscore": 1.3,
  "so2_mean": 3.2e-05,
  "so2_hotspots": 4,
  "wind_mean_favor": 0.61,
  "headwind_cells_pct": 0.18,
  "wave_mean_m": 0.42,
  "wave_hazard_cells": 2,
  "viirs_mean_traffic": 12.4,
  "viirs_high_traffic_cells": 87,
  "viirs_applicable": true,
  "overall_score": 68.2,
  "data_quality_flag": "good",
  "retrieval_notes": "Todos los layers recuperados. Sin eventos de fuego sobre Sumatra."
}
```

---

### 5.2 CertificationJudge

**Loop ReAct — máximo 4 tool calls**

Reglas críticas en orden estricto:

1. Siempre llamar `check_baseline_history` antes de decidir
2. Si z-score > 2.0 → DEBE llamar `detect_meteorological_confound`
3. Razonar sobre confounds específicos de Singapore:
   - Monzón SW (jun-sep): NO2 elevado por estancamiento atmosférico
   - Fuegos de turba en Sumatra (jun-oct): humo transfronterizo, NO son barcos
   - Paso de la ITCZ: concentración de emisiones
4. VIIRS es promedio mensual — tráfico alto ≠ emergencia
5. SO2 cerca de Jurong Island puede ser industrial, no barcos

**Umbrales de decisión:**

| Certificación | Condición |
|---|---|
| GREEN | score >= 65 Y tendencia estable o mejorando |
| WARN | score entre 45-64, O score >= 65 con tendencia negativa > 0.5/día |
| RED | score < 45, O 3+ WARNs consecutivos |

**Tools:**

| Tool | Propósito |
|---|---|
| check_baseline_history | Computa z-score del NO2 actual vs media estacional de baselines.json |
| detect_meteorological_confound | Verifica fuegos FIRMS + vientos ERA5 para descartar confounds |

**Output — CertDecision:**

```json
{
  "corridor_id": "SGP_PKL",
  "decision_timestamp": "2026-03-27T14:10:00Z",
  "decision": "GREEN",
  "confidence_pct": 84,
  "primary_driver": "NO2 dentro de norma estacional, viento favorable 61%",
  "is_met_confound": false,
  "confound_type": null,
  "badge_text": "Corredor certificado verde. NO2 en norma, SO2 en cumplimiento ECA.",
  "next_review_hours": 48,
  "reasoning_chain": ["..."]
}
```

---

### 5.3 CorridorOptimizer

**Loop ReAct — máximo 5 tool calls**

Reglas:

1. Siempre llamar `build_graph` primero (construye el DiGraph de NetworkX)
2. Luego llamar `run_astar` — el path DEBE pasar por Raffles Lighthouse y One Fathom Bank
3. Si el path no incluye los waypoints → llamar `build_graph` de nuevo con forced_waypoints
4. Llamar `compute_co2_edge_weights` para estimar ahorro vs ruta baseline
5. Para aviación: correr A* separado con pesos WEIGHTS_AVIATION

**Waypoints obligatorios (marítimo):**

| Waypoint | Coordenadas | Razón |
|---|---|---|
| Eastern Strait entry | 1.19°N, 104.10°E | Entrada de todos los barcos hacia el E |
| Raffles Lighthouse TSS | 1.17°N, 103.45°E | Salida occidental del Estrecho |
| One Fathom Bank | 2.92°N, 101.60°E | Aproximación al Estrecho de Malaca |

**Pesos de aristas:**

Marítimo:

```
no2=0.30 · so2=0.10 · wind=0.20 · wave=0.15 · viirs=0.15 · dist=0.10
```

Aviación:

```
no2=0.45 · so2=0.15 · wind=0.30 · dist=0.10
(wave y viirs no aplican)
```

**Tools:**

| Tool | Propósito |
|---|---|
| build_graph | Construye NetworkX DiGraph con 8-vecinos navegables |
| run_astar | A* con heurística haversine, waypoints forzados |
| compute_co2_edge_weights | Convierte costo del path en score 0-100 y % ahorro CO2 |

**Output — RouteRecommendation:**

```json
{
  "corridor_id": "SGP_PKL",
  "optimization_timestamp": "2026-03-27T14:15:00Z",
  "transport_mode": "maritime",
  "optimal_path_score": 74.8,
  "co2_saving_pct": 15.7,
  "optimal_path_cells": 41,
  "optimal_path_distance_km": 368,
  "chokepoints_on_path": ["Raffles Lighthouse TSS", "One Fathom Bank"],
  "feasibility_flag": true,
  "optimizer_notes": "Path óptimo añade 4.8% distancia pero evita 3 celdas con SO2 alto."
}
```

---

## 6. Capas satelitales (grilla 40×50)

La grilla cubre el bounding box del corredor con celdas de 0.1° (~11.1 km):

```
North: 4.5°N · South: 0.5°N · West: 99.5°E · East: 104.5°E
Celdas totales: 2,000 · Celdas navegables estimadas: ~1,200
```

| Capa | Variable | Fuente | Peso marítimo | Peso aviación |
|---|---|---|---|---|
| no2_mol_m2 | Dióxido de nitrógeno troposférico | Sentinel-5P TROPOMI | 0.30 | 0.45 |
| so2_mol_m2 | Dióxido de azufre (detector HFO) | Sentinel-5P TROPOMI | 0.10 | 0.15 |
| wind_u_ms / wind_v_ms | Viento superficial y jet stream | NOAA GFS 0.25° | 0.20 | 0.30 |
| wave_height_m | Altura de olas (Pierson-Moskowitz) | Derivado de GFS | 0.15 | N/A |
| viirs_radiance_nw | Densidad de tráfico (navegación) | VIIRS DNB mensual | 0.15 | N/A |
| dist | Distancia haversine normalizada | Calculado | 0.10 | 0.10 |

**Score de celda (0-100, mayor = más verde):**

```python
C_env = no2*0.30 + so2*0.10 + wind_cost*0.20 + wave*0.15 + viirs*0.15
H(cell) = (1 - C_env / 0.90) * 100
```

**Umbrales de badge por celda:**

```
GREEN : H >= 65
WARN  : 45 <= H < 65
RED   : H < 45
```

---

## 7. Output final — GreenRouteDecision

```json
{
  "corridor_id": "SGP_PKL",
  "timestamp": "2026-03-27T14:20:00Z",
  "transport_modes_evaluated": ["maritime", "aviation"],
  "certification": "GREEN",
  "confidence_pct": 84,
  "badge_text": "Corredor certificado verde. ECA en cumplimiento.",
  "overall_score": 68.2,
  "rerouting_recommended": false,
  "optimal_route_available": true,
  "co2_saving_pct": 15.7,
  "recommended_action": "Mantener ruta actual. Próxima revisión en 48 horas.",
  "next_review_hours": 48,
  "satellite_summary": {
    "no2_mean": 1.89e-05,
    "so2_hotspots": 4,
    "wind_favor": 0.61,
    "wave_max": 1.8,
    "viirs_traffic_mean": 12.4
  },
  "reasoning_chain": ["...traza completa de los 3 agentes..."],
  "audit_entry": "GREEN mantenido. Score 68.2/100. Sin confounds. SO2 en límites ECA.",
  "pushed_to_firebase": true
}
```

---

## 8. Arquitectura de memoria

| Scope | Qué contiene | Duración |
|---|---|---|
| In-context (messages) | Lista de mensajes dentro del loop ReAct de cada agente | Se reinicia en cada invocación del agente |
| Working memory (AgentState) | satellite_report, cert_decision, route_recommendation | Destruido al finalizar run_greenroute() |
| Persistente externa | baselines.json — medias mensuales NO2, conteo WARN consecutivos, audit log | Persiste entre ejecuciones |
| Firebase Realtime DB | GreenRouteDecision por corredor — leído por el dashboard React | En vivo, actualizado en cada ejecución |

---

## 9. Stack tecnológico

| Capa | Tecnología | Propósito |
|---|---|---|
| Orquestador | LangGraph StateGraph | Grafo de agentes con estado compartido |
| Agentes LLM | Anthropic SDK + claude-haiku-4-5 | Loops ReAct con tool use |
| Datos satelitales | Google Earth Engine (earthengine-api) | NO2, SO2, viento, VIIRS |
| Optimización de rutas | NetworkX | A* pathfinding en grilla 40×50 |
| API | FastAPI + uvicorn | Endpoints REST para el dashboard |
| Persistencia | baselines.json + Firebase Realtime DB | Histórico y sync en tiempo real |
| Frontend | React 18 + TypeScript | Dashboard de certificación |
| Mapa | react-leaflet | Visualización del corredor con celdas coloreadas |
| Charts | recharts | Tendencia NO2 y ahorro CO2 |
| Estilos | Tailwind CSS | Layout rápido |
| Deploy | Vercel / GitHub Pages | Tier gratuito |

---

## 10. Plan de implementación por fases

### Fase 1 — Datos y grilla

Objetivo: tener la grilla navegable con datos satelitales reales cargados y el scoring funcionando.

Tareas:
- Conectar Google Earth Engine y extraer NO2, SO2, viento, VIIRS para el bounding box
- Implementar la fórmula de normalización y score H(cell) para cada celda
- Exportar la grilla como JSON (maritime_grid_payload.json)
- Validar 5 celdas de muestra con scores esperados
- Sembrar baselines.json con medias mensuales históricas

Entregable: script Python que genera maritime_grid_payload.json validado

---

### Fase 2 — SatelliteAnalyst

Objetivo: el primer agente funcionando end-to-end con datos reales.

Tareas:
- Implementar las 4 tool functions leyendo desde el grid JSON
- Conectar el loop ReAct con las tools y el system prompt
- Verificar que el SatelliteReport JSON cumple el schema definido
- Manejar caso de alta cobertura nubosa (date_range_days=14)
- Manejar flag de temporada de fuegos en Sumatra

Entregable: run_satellite_analyst() retorna SatelliteReport válido

---

### Fase 3 — CertificationJudge

Objetivo: el juez certifica correctamente GREEN/WARN/RED considerando confounds.

Tareas:
- Implementar check_baseline_history leyendo baselines.json
- Implementar detect_meteorological_confound (FIRMS + ERA5 wind)
- Conectar el loop ReAct con ambas tools
- Probar caso de z-score > 2.0 con confound de fuegos activo
- Probar caso de 3 WARNs consecutivos → RED

Entregable: run_certification_judge() retorna CertDecision con reasoning_chain completo

---

### Fase 4 — CorridorOptimizer

Objetivo: A* calcula ruta óptima pasando por los waypoints obligatorios.

Tareas:
- Implementar build_graph usando NetworkX con los pesos del grid
- Implementar run_astar con haversine como heurística y waypoints forzados
- Implementar compute_co2_edge_weights con comparación vs baseline
- Probar modo marítimo y aviación por separado
- Verificar que Raffles Lighthouse y One Fathom Bank están en el path

Entregable: run_corridor_optimizer() retorna RouteRecommendation con path válido

---

### Fase 5 — Orquestador LangGraph

Objetivo: los 3 agentes corren en secuencia correcta según el trigger.

Tareas:
- Implementar AgentState con todos los campos
- Construir el StateGraph con los 4 nodos (analyst, judge, optimizer, synthesize)
- Implementar should_run_optimizer como edge condicional
- Implementar synthesize_node que ensambla el GreenRouteDecision
- Probar los 3 triggers: scheduler, reroute_needed, degradation_event
- Probar flujo corto (GREEN scheduler, sin optimizer) y largo (RED con optimizer)

Entregable: run_greenroute() funciona end-to-end para ambos flujos

---

### Fase 6 — API y persistencia

Objetivo: exponer el orquestador via FastAPI y sincronizar con Firebase.

Tareas:
- Implementar POST /corridor/run con CorridorRunRequest
- Implementar GET /corridor/status/{corridor_id}
- Escribir el resultado en baselines.json (actualizar last_cert_status, consecutive_warns)
- Conectar push_to_firebase() con Firebase Realtime DB
- Agregar manejo de errores y logging estructurado

Entregable: API corriendo localmente, output visible en Firebase

---

### Fase 7 — Dashboard React

Objetivo: el frontend consume Firebase y muestra la certificación en tiempo real.

Tareas:
- Scaffolding React + TypeScript + Tailwind
- Componente LeafletMap con celdas coloreadas GREEN/WARN/RED
- Componente BadgeRegistry con el GreenRouteDecision actual
- Componente AlertFeed con reasoning_chain y audit_entry
- Componente TrendChart (recharts) con histórico de NO2 y score
- Listener onValue() de Firebase para actualizaciones en tiempo real
- Deploy a Vercel

Entregable: Dashboard público mostrando certificación live del corredor SGP_PKL

---

## 11. Consideraciones de riesgo

### Cobertura nubosa alta (Sentinel-5P)
Singapore es tropical — la cobertura nubosa puede invalidar hasta el 50% de las celdas. El SatelliteAnalyst debe ampliar el composite a 14 días si null_count supera el 30%.

### Confound de fuegos en Sumatra (junio-octubre)
El humo transfronterizo puede elevar el NO2 2-3× sobre la línea base sin que los barcos sean responsables. El CertificationJudge DEBE verificar FIRMS antes de emitir WARN o RED en esta temporada. Emitir WARN condicional en lugar de REVOKE.

### SO2 de Jurong Island
El cluster petroquímico de Jurong Island (1.27°N, 103.68°E) emite SO2 de origen industrial. Las celdas en un radio de 0.2° de ese punto no deben usarse como evidencia de violación ECA por parte de barcos.

### VIIRS es promedio mensual
Un valor alto de radiance VIIRS no es una señal de emergencia. Es un proxy de densidad de tráfico estructural en esa lane. No disparar WARN por VIIRS alto aislado.

### Límite de tool calls por agente
El loop ReAct tiene un máximo de 5 calls por agente (4 para CertificationJudge). Si se alcanza el límite, se invoca un fallback que fuerza la respuesta final con lo recopilado hasta ese momento.
