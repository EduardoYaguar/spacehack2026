"""
GreenRoute data models.

Three layers of models:
  1. Grid payload  — parsing the pre-computed satellite JSON files
  2. Agent I/O     — inputs/outputs of each LangGraph node
  3. API           — FastAPI request / response schemas
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ============================================================
# 1. Enums
# ============================================================

class TransportMode(str, Enum):
    MARITIME = "maritime"
    AVIATION = "aviation"
    TRUCKING = "trucking"


class Badge(str, Enum):
    GREEN = "GREEN"
    WARN = "WARN"
    RED = "RED"


class TriggerReason(str, Enum):
    SCHEDULER = "scheduler"
    NEW_DATA = "new_data"
    VOYAGE_COMPLETED = "voyage_completed"


# ============================================================
# 2. Grid payload models  (parsing satellite JSON files)
# ============================================================

class GridBounds(BaseModel):
    north: float
    south: float
    east: float
    west: float


class GridDefinition(BaseModel):
    bounds: GridBounds
    cell_size_degrees: float
    cell_size_approx_km: float
    rows: int
    cols: int
    total_cells: int
    # Maritime: navigable water cells (land_mask = 1)
    navigable_cells: Optional[int] = None
    land_mask_source: Optional[str] = None
    # Trucking: road cells (road_mask = 1)
    road_cells: Optional[int] = None
    road_mask_source: Optional[str] = None
    coordinate_system: str = "EPSG:4326"


class GridPoint(BaseModel):
    """Origin, destination, or waypoint on a corridor."""
    name: str
    lat: float
    lon: float


class TemporalWindow(BaseModel):
    """Time window used to composite satellite data (P1 / P2 / P3)."""
    label: str          # "P1"
    start: str          # ISO date "2026-03-04"
    end: str            # ISO date "2026-03-18"
    days: int


class LayerStats(BaseModel):
    mean: Optional[float] = None
    max: Optional[float] = None
    min: Optional[float] = None


class GridLayer(BaseModel):
    """
    One satellite/model data layer inside a grid payload.
    Field name 'description' can appear as 'desc' in trucking payloads.
    The data matrix is [rows][cols] of float | null (null on non-navigable cells).
    """
    description: Optional[str] = Field(None, alias="desc")
    source: Optional[str] = None
    gee_collection: Optional[str] = None
    unit: Optional[str] = None
    stats: Optional[LayerStats] = None
    valid_cells: Optional[int] = None
    data: list[list[Optional[float]]]

    model_config = {"populate_by_name": True}


class LandMask(BaseModel):
    """Maritime: binary water/land matrix. 1.0 = water (navigable), 0.0 = land."""
    description: str
    data: list[list[float]]


class RoadMask(BaseModel):
    """Trucking: binary road/no-road matrix. 1.0 = road (navigable), 0.0 = off-road."""
    desc: str
    data: list[list[float]]


class GridLayers(BaseModel):
    """
    All possible layers across all three modes.
    Only the fields relevant to each mode will be populated.

    Maritime (7 layers):
        no2_mol_m2, so2_mol_m2, wind_u_ms, wind_v_ms,
        wave_height_m, viirs_radiance_nw, green_score

    Aviation (10 layers):
        no2_mol_m2, co_mol_m2, wind_u_ms, wind_v_ms,
        turbulence_index, contrail_risk, cloud_top_height_m,
        aerosol_index, aod, green_score

    Trucking dynamic (10 layers — in 'layers' key of payload):
        no2_mol_m2, so2_mol_m2, co_mol_m2, temperature_k,
        wind_u_ms, wind_v_ms, viirs_nw, precip_mm, snow_cover, aod
    Note: trucking green_score lives in 'derived_layers', not here.
    """
    # Emissions — all modes
    no2_mol_m2: Optional[GridLayer] = None
    so2_mol_m2: Optional[GridLayer] = None   # maritime + trucking
    co_mol_m2: Optional[GridLayer] = None    # aviation + trucking

    # Wind — all modes (surface 10 m for maritime/trucking; 250 hPa for aviation)
    wind_u_ms: Optional[GridLayer] = None
    wind_v_ms: Optional[GridLayer] = None

    # Aerosol
    aerosol_index: Optional[GridLayer] = None   # aviation
    aod: Optional[GridLayer] = None             # aviation (physical 0–1) + trucking (MODIS 0–256)

    # Maritime-specific
    wave_height_m: Optional[GridLayer] = None
    viirs_radiance_nw: Optional[GridLayer] = None   # ship traffic proxy

    # Aviation-specific
    turbulence_index: Optional[GridLayer] = None
    contrail_risk: Optional[GridLayer] = None
    cloud_top_height_m: Optional[GridLayer] = None

    # Trucking-specific
    temperature_k: Optional[GridLayer] = None
    viirs_nw: Optional[GridLayer] = None    # road congestion proxy (different name from maritime)
    precip_mm: Optional[GridLayer] = None
    snow_cover: Optional[GridLayer] = None

    # Pre-computed composite score (maritime + aviation only; trucking uses derived_layers)
    green_score: Optional[GridLayer] = None


class StaticLayers(BaseModel):
    """Trucking-only static layers (time-invariant terrain properties)."""
    elevation_m: Optional[GridLayer] = None
    slope_deg: Optional[GridLayer] = None


class DerivedLayers(BaseModel):
    """Trucking-only derived layers computed from static + dynamic inputs."""
    green_score: Optional[GridLayer] = None


class EdgeCostWeightsPayload(BaseModel):
    """Edge cost weights as stored in corridoriq_config inside the JSON payload."""
    no2: float = 0.0
    so2: float = 0.0
    co: float = 0.0
    wind: float = 0.0
    wave: float = 0.0
    traffic: float = 0.0
    distance: float = 0.0
    turbulence: float = 0.0
    contrail: float = 0.0
    cloud_top: float = 0.0
    aerosol: float = 0.0
    aod: float = 0.0
    slope: float = 0.0
    congestion: float = 0.0
    precip: float = 0.0
    snow: float = 0.0


class NormRangePayload(BaseModel):
    min: float
    max: float


class CorridoriqConfig(BaseModel):
    """Optimizer configuration block embedded in every grid payload."""
    description: Optional[str] = None
    edge_cost_weights: EdgeCostWeightsPayload
    normalization: dict[str, NormRangePayload]
    # badge_thresholds stored as raw dict in JSON: {"GREEN": 65, "WARN": 45, "RED": 0}
    badge_thresholds: dict[str, Any]
    pathfinding_note: Optional[str] = None


class GridPayload(BaseModel):
    """
    Root model for all satellite grid JSON files.
    Handles maritime, aviation, and trucking payloads.
    """
    grid_id: str
    mode: TransportMode
    generated_at: datetime
    version: str

    origin: GridPoint
    destination: GridPoint
    waypoint: Optional[GridPoint] = None    # aviation only (DXB)
    window: Optional[TemporalWindow] = None  # aviation + trucking (P1/P2/P3)

    grid_definition: GridDefinition

    # Navigation masks (mode-dependent, mutually exclusive)
    land_mask: Optional[LandMask] = None    # maritime
    road_mask: Optional[RoadMask] = None    # trucking

    # Data layers
    layers: GridLayers
    static_layers: Optional[StaticLayers] = None    # trucking only
    derived_layers: Optional[DerivedLayers] = None  # trucking only (green_score)

    corridoriq_config: CorridoriqConfig

    def get_green_score_layer(self) -> Optional[GridLayer]:
        """Returns the green_score layer regardless of which sub-object holds it."""
        if self.derived_layers and self.derived_layers.green_score:
            return self.derived_layers.green_score
        return self.layers.green_score

    def get_navigability_mask(self) -> Optional[list[list[float]]]:
        """Returns the binary navigability mask (water mask or road mask)."""
        if self.land_mask:
            return self.land_mask.data
        if self.road_mask:
            return self.road_mask.data
        return None  # aviation: all cells navigable


# ============================================================
# 3. Satellite Analyst — tool output models
# ============================================================

class HotspotCell(BaseModel):
    """A single grid cell flagged as a pollution or risk hotspot."""
    row: int
    col: int
    lat: float
    lon: float
    value: float
    notes: str = ""


class LayerQueryResult(BaseModel):
    """
    Structured result returned by each satellite analyst tool to the LLM.
    Provides per-layer statistics and hotspot locations.
    """
    layer: str              # e.g. "no2_mol_m2"
    unit: str
    mean: float
    max: float
    min: float
    valid_cells: int
    hotspots: list[HotspotCell] = Field(default_factory=list)
    anomaly_flag: bool = False
    # Downstream action hints derived from business rules
    trigger_so2_check: bool = False     # NO2 mean > 2.5e-5
    trigger_co_check: bool = False      # trucking: NO2 high, check CO
    data_quality: str = "ok"           # "ok" | "low" | "partial"
    notes: str = ""


class NO2QueryResult(LayerQueryResult):
    """
    NO2 query result.
    Sets trigger_so2_check = True when mean > 2.5e-5 mol/m² (all modes).
    For trucking, also sets trigger_co_check = True to discriminate
    diesel traffic from industrial point sources.
    """
    layer: str = "no2_mol_m2"
    unit: str = "mol/m²"


class WindQueryResult(BaseModel):
    """
    Combined wind result (U + V components).
    Returns both components and the derived speed/direction summary.
    """
    layer_u: str = "wind_u_ms"
    layer_v: str = "wind_v_ms"
    unit: str = "m/s"
    # U component (east-west)
    u_mean: float
    u_max: float
    u_min: float
    # V component (north-south)
    v_mean: float
    v_max: float
    v_min: float
    # Derived
    speed_mean: float               # sqrt(u²+v²) mean
    speed_max: float
    # Aviation context
    is_jet_stream_level: bool = False  # True when wind is at 250 hPa
    dominant_direction: str = ""       # e.g. "westerly", "northeasterly"
    notes: str = ""


class VIIRSQueryResult(LayerQueryResult):
    """
    VIIRS radiance result.
    Maritime: ship traffic proxy (viirs_radiance_nw, max 47 nW/cm²/sr).
    Trucking: highway congestion proxy (viirs_nw, max 158 nW/cm²/sr).
    """
    is_structural_density: bool = True  # monthly composite — not a real-time event


class SO2HotspotResult(BaseModel):
    """
    SO2 hotspot detection result.
    Called conditionally by SatelliteAnalyst when NO2 exceeds threshold.
    Includes ECA violation check and industrial confound filtering.
    """
    layer: str = "so2_mol_m2"
    unit: str = "mol/m²"
    mean: float
    max: float
    valid_cells: int
    hotspots: list[HotspotCell] = Field(default_factory=list)
    # Maritime: cells within 0.2° of Jurong Island (1.27°N, 103.68°E)
    industrial_confound_cells: list[HotspotCell] = Field(default_factory=list)
    # Trucking: cells near known industrial emitters (power plants, refineries)
    industrial_confound_cells_count: int = 0
    eca_violation_risk: bool = False
    notes: str = ""


# ============================================================
# 4. Agent output models
# ============================================================

class SatelliteReport(BaseModel):
    """
    Output produced by the SatelliteAnalyst node.
    Consumed by CorridorOptimizer and CertificationJudge.
    """
    corridor_id: str
    transport_mode: TransportMode
    analysis_timestamp: datetime = Field(default_factory=datetime.utcnow)
    grid_snapshot: str = ""         # path of the grid file analysed
    temporal_window: Optional[str] = None  # "P1" / "P2" / "P3" or None for maritime

    # Composite score derived from layer means using mode-specific weights
    overall_score: float            # 0–100
    badge: Badge

    # Per-layer results keyed by layer name
    layer_results: dict[str, LayerQueryResult] = Field(default_factory=dict)
    wind_result: Optional[WindQueryResult] = None
    so2_hotspot_result: Optional[SO2HotspotResult] = None

    # Flags and advisories
    anomalies: list[str] = Field(default_factory=list)
    business_rule_triggers: list[str] = Field(default_factory=list)
    # layer_name → quality note (e.g. "low: 40% null cells above 65°N")
    data_quality_flags: dict[str, str] = Field(default_factory=dict)
    # Aviation: aerosol alert near DXB waypoint
    aerosol_dxb_alert: bool = False
    # Trucking: precipitation hazard flag
    weather_hazard: bool = False

    # LLM narrative
    reasoning: str = ""


class PathCell(BaseModel):
    """One cell on the optimal A* path."""
    row: int
    col: int
    lat: float
    lon: float
    green_score: Optional[float] = None


class RouteRecommendation(BaseModel):
    """
    Output produced by the CorridorOptimizer node.
    Contains the optimal green route and comparison to straight-line baseline.
    """
    corridor_id: str
    transport_mode: TransportMode
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    optimal_green_score: float      # mean green_score of path cells
    badge: Badge
    path_cells: list[PathCell]
    path_length_cells: int
    distance_km: float

    # Baseline comparison (straight geodesic from origin to destination)
    baseline_score: float
    improvement_vs_baseline_pct: float  # positive = better than baseline

    mandatory_waypoints_validated: list[str]  # names of waypoints the path passes through
    mandatory_waypoints_missed: list[str] = Field(default_factory=list)

    # Aviation note: potential contrail mitigation segments
    contrail_mitigation_segments: list[str] = Field(default_factory=list)
    # Trucking note: high-slope segments that could be bypassed
    high_slope_segments: list[str] = Field(default_factory=list)

    reasoning: str = ""


class CertDecision(BaseModel):
    """
    Output produced by the CertificationJudge node.
    Certifies whether a specific vehicle followed the recommended green route.
    """
    corridor_id: str
    transport_mode: TransportMode
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    vehicle_id: Optional[str] = None   # AIS MMSI (maritime) or ICAO hex (aviation)
    certificate: Badge
    confidence_pct: float              # 0–100

    track_compliance_pct: float        # % of actual track within optimal path corridor
    waypoints_verified: list[str]      # mandatory waypoints confirmed in track
    waypoints_missed: list[str] = Field(default_factory=list)

    # Seasonal context flag (aviation): WARN at 48–55 in boreal winter is expected
    seasonal_context_applied: bool = False

    # Weather advisories
    weather_advisory: Optional[str] = None  # e.g. "snow_chain_required"
    aerosol_advisory: Optional[str] = None  # e.g. "dust_storm_near_DXB"

    reasoning: str = ""


class GreenRouteDecision(BaseModel):
    """
    Final output of the full multi-agent pipeline.
    Assembled by the synthesize node and pushed to Firebase.
    """
    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    corridor_id: str
    transport_mode: TransportMode
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    triggered_by: TriggerReason

    satellite_report: SatelliteReport
    route_recommendation: RouteRecommendation
    cert_decision: Optional[CertDecision] = None

    final_badge: Badge
    final_score: float

    # Full reasoning chain from all agents
    reasoning_chain: list[str] = Field(default_factory=list)

    # Persistence
    pushed_to_firebase: bool = False
    firebase_path: Optional[str] = None  # e.g. "decisions/SGP_PKL/2026-03-28"

    # Baseline drift tracking (written back to baselines.json by synthesize)
    baseline_updated: bool = False
    consecutive_warn_count: int = 0


# ============================================================
# 5. API request / response models
# ============================================================

class VehicleTrackPoint(BaseModel):
    """One AIS/ADS-B position report for certification."""
    timestamp: datetime
    lat: float
    lon: float
    altitude_ft: Optional[float] = None   # aviation
    speed_kts: Optional[float] = None
    heading_deg: Optional[float] = None


class CorridorRunRequest(BaseModel):
    corridor_id: str
    transport_modes: list[TransportMode]
    triggered_by: TriggerReason = TriggerReason.NEW_DATA
    # Optional AIS/ADS-B track for vehicle certification
    vehicle_track: Optional[list[VehicleTrackPoint]] = None
    vehicle_id: Optional[str] = None


class CorridorRunResponse(BaseModel):
    status: str             # "ok" | "error"
    corridor_id: str
    message: Optional[str] = None
    decision: Optional[GreenRouteDecision] = None


class CorridorStatusResponse(BaseModel):
    corridor_id: str
    last_decision: Optional[GreenRouteDecision] = None
    last_updated: Optional[datetime] = None
