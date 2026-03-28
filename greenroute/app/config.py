from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# ============================================================
# Environment settings
# ============================================================

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # API server
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    debug: bool = False

    # Anthropic / Claude
    anthropic_api_key: str = Field(..., validation_alias="ANTHROPIC_API_KEY")
    claude_agent_model: str = "claude-haiku-4-5"
    claude_max_tokens: int = 4096
    claude_temperature: float = 0.2

    # Per-agent tool-call budgets (ReAct loop limits)
    satellite_analyst_max_tool_calls: int = 5
    corridor_optimizer_max_tool_calls: int = 5
    certification_judge_max_tool_calls: int = 4

    # Google Earth Engine
    gee_service_account: str = ""
    gee_key_file: str = "gee_service_account.json"

    # Firebase Realtime DB
    firebase_url: str = ""
    firebase_credentials_file: str = "firebase_service_account.json"

    # Default corridor / data paths
    corridor_id: str = "SGP_PKL"
    grid_file: str = "data/maritime_grid_payload.json"
    baselines_file: str = "data/baselines.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ============================================================
# Static corridor configuration  (not env-var driven)
# ============================================================

@dataclass
class WaypointCfg:
    name: str
    lat: float
    lon: float


@dataclass
class EdgeCostWeightsCfg:
    """
    A* edge cost weights that sum to 1.0.
    Only the fields used by each mode are non-zero.
    """
    # Emissions (all modes)
    no2: float = 0.0
    so2: float = 0.0
    co: float = 0.0
    aod: float = 0.0
    aerosol: float = 0.0

    # Wind / meteorology
    wind: float = 0.0       # combined wind_u + wind_v cost

    # Maritime-specific
    wave: float = 0.0
    traffic: float = 0.0    # VIIRS ship traffic

    # Aviation-specific
    turbulence: float = 0.0
    contrail: float = 0.0
    cloud_top: float = 0.0

    # Trucking-specific
    slope: float = 0.0
    congestion: float = 0.0  # VIIRS road congestion
    precip: float = 0.0
    snow: float = 0.0

    # Shared distance penalty
    distance: float = 0.0


@dataclass
class NormalizationRangesCfg:
    """
    [min, max] clamp ranges applied before weighting.
    For wind in aviation mode, higher speed = better (tailwind logic — inverted in optimizer).
    """
    no2_mol_m2: tuple[float, float] = (0.0, 2e-4)
    so2_mol_m2: tuple[float, float] = (0.0, 1e-4)
    co_mol_m2: tuple[float, float] = (0.0, 0.05)
    wind_speed: tuple[float, float] = (0.0, 15.0)   # overridden per mode
    wave_height_m: tuple[float, float] = (0.0, 6.0)
    viirs_radiance_nw: tuple[float, float] = (0.0, 50.0)  # maritime ship traffic
    viirs_nw_road: tuple[float, float] = (0.0, 60.0)      # trucking road congestion
    turbulence_index: tuple[float, float] = (0.0, 30.0)
    contrail_risk: tuple[float, float] = (0.0, 1.0)
    cloud_top_height_m: tuple[float, float] = (0.0, 15000.0)
    aerosol_index: tuple[float, float] = (-1.0, 5.0)
    aod_aviation: tuple[float, float] = (0.0, 1.0)
    slope_deg: tuple[float, float] = (0.0, 10.0)
    precip_mm: tuple[float, float] = (0.0, 5.0)
    snow_ndsi: tuple[float, float] = (0.0, 100.0)
    aod_modis_raw: tuple[float, float] = (0.0, 256.0)  # trucking: MODIS internal scale


@dataclass
class BadgeThresholdsCfg:
    green_gte: float = 65.0   # score >= green_gte → GREEN
    warn_gte: float = 45.0    # score >= warn_gte  → WARN, else RED


@dataclass
class BusinessRulesCfg:
    """
    Thresholds that trigger conditional tool calls or advisory flags.
    """
    # SatelliteAnalyst: call query_so2_hotspots when NO2 exceeds this
    no2_hotspot_threshold_mol_m2: float = 2.5e-5

    # Aviation: report aerosol max in DXB radius when index > this
    aerosol_index_dxb_alert: float = 2.5
    # Radius in grid cells around DXB to check aerosol
    aerosol_dxb_radius_cells: int = 3

    # Trucking: mark weather_hazard when precipitation > this in >20% of segment
    precip_hazard_threshold_mm: float = 1.5
    precip_hazard_fraction: float = 0.20

    # Trucking: snow advisory
    snow_chain_required_ndsi: float = 40.0

    # Aviation: CertJudge contextualise WARN in boreal winter (don't auto-RED)
    aviation_seasonal_warn_min_score: float = 45.0
    aviation_seasonal_warn_max_score: float = 55.0


@dataclass
class CorridorCfg:
    corridor_id: str
    mode: str                      # "maritime" | "aviation" | "trucking"
    description: str
    grid_paths: list[str]          # relative to workspace root, newest-first
    origin_name: str
    origin_lat: float
    origin_lon: float
    destination_name: str
    destination_lat: float
    destination_lon: float
    waypoints: list[WaypointCfg]   # mandatory path checkpoints (ordered)
    temporal_window_days: int
    edge_cost_weights: EdgeCostWeightsCfg = field(default_factory=EdgeCostWeightsCfg)
    normalization: NormalizationRangesCfg = field(default_factory=NormalizationRangesCfg)
    badge_thresholds: BadgeThresholdsCfg = field(default_factory=BadgeThresholdsCfg)
    business_rules: BusinessRulesCfg = field(default_factory=BusinessRulesCfg)


# ============================================================
# Maritime — SGP ↔ PKL  (Singapore Strait, 40×60 @ 0.1°)
# ============================================================
_MARITIME_WEIGHTS = EdgeCostWeightsCfg(
    no2=0.30,
    so2=0.10,
    wind=0.20,
    wave=0.15,
    traffic=0.15,
    distance=0.10,
)

_MARITIME_NORM = NormalizationRangesCfg(
    no2_mol_m2=(0.0, 2e-4),
    so2_mol_m2=(0.0, 1e-4),
    wind_speed=(0.0, 15.0),
    wave_height_m=(0.0, 6.0),
    viirs_radiance_nw=(0.0, 50.0),
)

MARITIME_CFG = CorridorCfg(
    corridor_id="SGP_PKL",
    mode="maritime",
    description="Singapore Strait — Port Klang ↔ Port of Singapore",
    grid_paths=[
        "latest/maritime_portklang_singapore.json",
        "latest-1/maritime_portklang_singapore.json",
        "latest-2/maritime_portklang_singapore.json",
    ],
    origin_name="Port Klang, Malaysia",
    origin_lat=2.99,
    origin_lon=101.39,
    destination_name="Port of Singapore",
    destination_lat=1.26,
    destination_lon=103.84,
    waypoints=[
        WaypointCfg("One Fathom Bank", lat=2.92, lon=101.60),
        WaypointCfg("Raffles Lighthouse", lat=1.17, lon=103.45),
    ],
    temporal_window_days=7,
    edge_cost_weights=_MARITIME_WEIGHTS,
    normalization=_MARITIME_NORM,
)


# ============================================================
# Aviation — PVG → DXB → AMS  (60×125 @ 1.0°)
# ============================================================
_AVIATION_WEIGHTS = EdgeCostWeightsCfg(
    wind=0.35,
    turbulence=0.15,
    contrail=0.10,
    no2=0.10,
    cloud_top=0.10,
    aerosol=0.10,
    co=0.05,
    aod=0.05,
)

_AVIATION_NORM = NormalizationRangesCfg(
    no2_mol_m2=(0.0, 2e-4),
    co_mol_m2=(0.0, 0.05),
    wind_speed=(0.0, 60.0),   # jet stream at 250 hPa — higher = better (tailwind)
    turbulence_index=(0.0, 30.0),
    contrail_risk=(0.0, 1.0),
    cloud_top_height_m=(0.0, 15000.0),
    aerosol_index=(-1.0, 5.0),
    aod_aviation=(0.0, 1.0),
)

AVIATION_CFG = CorridorCfg(
    corridor_id="PVG_DXB_AMS",
    mode="aviation",
    description="Long-haul — Shanghai Pudong (PVG) → Dubai Intl (DXB) → Amsterdam Schiphol (AMS)",
    grid_paths=[
        "aereo/p1/aviation_payload_p1.json",
        "aereo/p2/aviation_payload_p2.json",
        "aereo/p3/aviation_payload_p3.json",
    ],
    origin_name="Shanghai Pudong (PVG)",
    origin_lat=31.14,
    origin_lon=121.81,
    destination_name="Amsterdam Schiphol (AMS)",
    destination_lat=52.31,
    destination_lon=4.76,
    waypoints=[
        WaypointCfg("Dubai Intl (DXB)", lat=25.25, lon=55.36),
    ],
    temporal_window_days=14,
    edge_cost_weights=_AVIATION_WEIGHTS,
    normalization=_AVIATION_NORM,
)


# ============================================================
# Trucking — NY/NJ → Savannah  (200×180 @ 0.05°)
# ============================================================
_TRUCKING_WEIGHTS = EdgeCostWeightsCfg(
    no2=0.20,
    so2=0.05,
    co=0.10,
    slope=0.20,
    congestion=0.20,
    wind=0.05,
    precip=0.08,
    snow=0.07,
    aod=0.05,
)

_TRUCKING_NORM = NormalizationRangesCfg(
    no2_mol_m2=(0.0, 2e-4),
    so2_mol_m2=(0.0, 1e-4),
    co_mol_m2=(0.0, 0.05),
    wind_speed=(0.0, 15.0),
    slope_deg=(0.0, 10.0),
    viirs_nw_road=(0.0, 60.0),
    precip_mm=(0.0, 5.0),
    snow_ndsi=(0.0, 100.0),
    aod_modis_raw=(0.0, 256.0),
)

TRUCKING_CFG = CorridorCfg(
    corridor_id="NYNJ_SAV",
    mode="trucking",
    description="US East Coast I-95 — Port NY/NJ (Newark) → Port of Savannah",
    grid_paths=[
        "terrestre_usa/p1/terrestrial_usa_p1.json",
        "terrestre_usa/p2/terrestrial_usa_p2.json",
        "terrestre_usa/p3/terrestrial_usa_p3.json",
    ],
    origin_name="Port NY/NJ (Newark)",
    origin_lat=40.68,
    origin_lon=-74.15,
    destination_name="Port of Savannah",
    destination_lat=32.08,
    destination_lon=-81.09,
    waypoints=[],   # no mandatory waypoints on this corridor
    temporal_window_days=14,
    edge_cost_weights=_TRUCKING_WEIGHTS,
    normalization=_TRUCKING_NORM,
)


# ============================================================
# Corridor registry
# ============================================================
CORRIDOR_CONFIGS: dict[str, CorridorCfg] = {
    "SGP_PKL": MARITIME_CFG,
    "PVG_DXB_AMS": AVIATION_CFG,
    "NYNJ_SAV": TRUCKING_CFG,
}


def get_corridor_config(corridor_id: str) -> CorridorCfg:
    if corridor_id not in CORRIDOR_CONFIGS:
        raise ValueError(
            f"Unknown corridor '{corridor_id}'. "
            f"Available: {list(CORRIDOR_CONFIGS)}"
        )
    return CORRIDOR_CONFIGS[corridor_id]
