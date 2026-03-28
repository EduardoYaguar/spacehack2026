"""
satellite_tools.py — Tools for the SatelliteAnalyst agent (Agent 1).

Ten tools read pre-computed satellite layer data from the grid JSON snapshots.

All modes (maritime, aviation, trucking):
    query_gee_no2       — Tropospheric NO2 column density (primary emissions signal)
    query_era5_wind     — Surface (10m) or jet-stream (250hPa) wind components

Maritime + trucking only:
    query_viirs_ships   — VIIRS nighttime radiance: ship traffic or road congestion proxy
    query_so2_hotspots  — SO2 hotspot detection for ECA violations / industrial confounds

Aviation + trucking:
    query_co            — CO total column (combustion tracer / congestion proxy)

Aviation only:
    query_turbulence    — Turbulence index at cruise level (CAT + convective turbulence)
    query_contrail_risk — Contrail formation probability (climate impact)
    query_cloud_top_height — Cloud top height (cumulonimbus / convection indicator)
    query_aerosol_index — UV Aerosol Index (dust, smoke — DXB proximity check)
    query_aod           — Aerosol Optical Depth at 550 nm (total aerosol loading)

All tools accept a `grid_path` argument so the LLM can pass the path it received in
the system prompt without needing a separate initialisation step.

Data sources referenced in the JSON (not live GEE calls in this implementation):
    NO2, SO2, CO, Aerosol : COPERNICUS/S5P/OFFL/L3_* (Sentinel-5P TROPOMI)
    Wind, Turbulence      : NOAA/GFS0P25 or ERA5 reanalysis
    Contrail, Cloud top   : Derived from ERA5 / GFS
    VIIRS                 : NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG
    AOD                   : MODIS Terra/Aqua or Sentinel-5P TROPOMI
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

# ---------------------------------------------------------------------------
# Module-level grid JSON cache
# ---------------------------------------------------------------------------
_grid_cache: dict[str, dict[str, Any]] = {}


def _load_grid(grid_path: str) -> dict[str, Any]:
    """Load and cache the grid JSON file. Resolves relative paths from workspace root."""
    if grid_path in _grid_cache:
        return _grid_cache[grid_path]

    path = Path(grid_path)
    if not path.exists():
        workspace = Path(__file__).resolve().parents[4]   # spacehack2026/
        alt = workspace / grid_path
        if alt.exists():
            path = alt
        else:
            return {"_error": f"Grid file not found: {grid_path}"}

    with open(path) as f:
        data = json.load(f)

    _grid_cache[str(path)] = data
    _grid_cache[grid_path] = data   # also cache under original key
    return data


def _cell_center(row: int, col: int, gdef: dict) -> tuple[float, float]:
    cs = gdef["cell_size_degrees"]
    lat = gdef["bounds"]["north"] - row * cs - cs / 2
    lon = gdef["bounds"]["west"] + col * cs + cs / 2
    return lat, lon


# ---------------------------------------------------------------------------
# Tool 1 — query_gee_no2
# ---------------------------------------------------------------------------

@tool
def query_gee_no2(grid_path: str, date_range_days: int = 7) -> dict:
    """
    Query tropospheric NO2 column density for the corridor grid.

    Reads the pre-computed NO2 layer from the satellite grid JSON snapshot.
    Returns per-cell statistics, hotspot locations, and data quality assessment.

    Business rules applied automatically:
    - If mean NO2 > 2.5e-5 mol/m² → trigger_so2_check=True (call query_so2_hotspots next).
    - If null_fraction > 0.30 → data_quality='poor'; consider re-calling with date_range_days=14.
    - Aviation mode: NO2 over Europe (western cols) reflects terrestrial sources, not aviation.
    - Trucking mode: high NO2 in NJ/Baltimore/DC corridors is structural baseline, not anomaly.

    Args:
        grid_path: Path to the grid JSON file (absolute or relative to workspace root).
        date_range_days: Temporal composite window; 7 = maritime default, 14 = aviation/trucking.
    """
    data = _load_grid(grid_path)
    if "_error" in data:
        return {"status": "error", "message": data["_error"]}

    mode = data.get("mode", "maritime")
    layers = data.get("layers", {})
    no2_layer = layers.get("no2_mol_m2", {})
    layer_data: list[list] = no2_layer.get("data", [])

    if not layer_data:
        return {"status": "error", "message": "no2_mol_m2 layer not found in grid payload"}

    gdef = data["grid_definition"]
    NO2_HOTSPOT_THRESHOLD = 2.5e-5  # mol/m²

    values: list[float] = []
    null_count = 0
    hotspots: list[dict] = []

    for r, row in enumerate(layer_data):
        for c, val in enumerate(row):
            if val is None:
                null_count += 1
                continue
            values.append(float(val))
            if float(val) > NO2_HOTSPOT_THRESHOLD:
                lat, lon = _cell_center(r, c, gdef)
                hotspots.append({
                    "row": r,
                    "col": c,
                    "lat": round(lat, 4),
                    "lon": round(lon, 4),
                    "no2_mol_m2": round(float(val), 10),
                })

    if not values:
        return {"status": "error", "message": "No valid NO2 data cells found"}

    total_cells = sum(len(row) for row in layer_data)
    null_fraction = null_count / max(total_cells, 1)
    mean_val = sum(values) / len(values)
    trigger_so2 = mean_val > NO2_HOTSPOT_THRESHOLD
    data_quality = "poor" if null_fraction > 0.30 else ("fair" if null_fraction > 0.10 else "good")

    notes: list[str] = []
    if data_quality == "poor":
        notes.append(
            f"High null fraction ({null_fraction:.1%}) — data_quality is 'poor'. "
            f"Consider re-calling with date_range_days=14 for better coverage."
        )
    if trigger_so2:
        notes.append(
            f"NO2 mean ({mean_val:.2e} mol/m²) exceeds 2.5e-5 threshold. "
            "Call query_so2_hotspots to check for ECA violations."
        )
    if mode == "aviation":
        notes.append(
            "Aviation: NO2 is a traffic proxy at tropospheric level. "
            "Cells over Europe (western cols) reflect terrestrial pollution, not flight emissions."
        )
    if mode == "trucking":
        notes.append(
            "Trucking: NY/NJ, Philadelphia, Baltimore, DC segments have structurally high NO2. "
            "Correlate with CO layer to distinguish diesel traffic from industrial point sources."
        )

    return {
        "status": "ok",
        "layer": "no2_mol_m2",
        "unit": "mol/m²",
        "mode": mode,
        "date_range_days": date_range_days,
        "mean": round(mean_val, 10),
        "max": round(max(values), 10),
        "min": round(min(values), 10),
        "valid_cells": len(values),
        "null_cells": null_count,
        "null_fraction": round(null_fraction, 4),
        "data_quality": data_quality,
        "hotspot_cells_count": len(hotspots),
        "hotspots": hotspots[:10],   # top 10 to stay within context limits
        "trigger_so2_check": trigger_so2,
        "notes": " | ".join(notes) if notes else "No anomalies detected.",
    }


# ---------------------------------------------------------------------------
# Tool 2 — query_era5_wind
# ---------------------------------------------------------------------------

@tool
def query_era5_wind(grid_path: str) -> dict:
    """
    Query ERA5/GFS wind components (U and V) for the corridor grid.

    Maritime and trucking: surface wind at 10m above ground.
    Aviation: jet-stream wind at 250 hPa (~10,600 m cruise level).

    Wind conventions:
    - wind_u_ms > 0 → blowing eastward (tailwind on eastbound legs)
    - wind_v_ms > 0 → blowing northward
    - For aviation (PVG→AMS, westward leg): high positive wind_u = headwind; use southern
      routes to find tailwind assistance or reduced headwind.

    Args:
        grid_path: Path to the grid JSON file (absolute or relative to workspace root).
    """
    data = _load_grid(grid_path)
    if "_error" in data:
        return {"status": "error", "message": data["_error"]}

    mode = data.get("mode", "maritime")
    layers = data.get("layers", {})

    u_data: list[list] = layers.get("wind_u_ms", {}).get("data", [])
    v_data: list[list] = layers.get("wind_v_ms", {}).get("data", [])

    if not u_data or not v_data:
        return {"status": "error", "message": "wind_u_ms or wind_v_ms layers not found in grid payload"}

    u_values: list[float] = []
    v_values: list[float] = []
    speed_values: list[float] = []

    for u_row, v_row in zip(u_data, v_data):
        for u_val, v_val in zip(u_row, v_row):
            if u_val is None or v_val is None:
                continue
            u_f, v_f = float(u_val), float(v_val)
            u_values.append(u_f)
            v_values.append(v_f)
            speed_values.append(math.sqrt(u_f ** 2 + v_f ** 2))

    if not u_values:
        return {"status": "error", "message": "No valid wind data cells found"}

    u_mean = sum(u_values) / len(u_values)
    v_mean = sum(v_values) / len(v_values)
    speed_mean = sum(speed_values) / len(speed_values)

    # Dominant direction classification
    dominant = []
    if abs(u_mean) > 0.5:
        dominant.append("easterly" if u_mean > 0 else "westerly")
    if abs(v_mean) > 0.5:
        dominant.append("southerly" if v_mean > 0 else "northerly")
    dominant_dir = "-".join(dominant) if dominant else "calm"

    notes: list[str] = []
    if mode == "aviation":
        notes.append(
            f"Jet stream at 250 hPa. Speed mean {speed_mean:.1f} m/s. "
            "Positive wind_u (eastward) = headwind for AMS-bound flights. "
            "CorridorOptimizer should prefer cells with high wind_u as tailwind assistance."
        )
        if speed_mean > 30:
            notes.append(
                f"Strong jet stream detected ({speed_mean:.0f} m/s mean). "
                "Route should exploit tailwind corridors to reduce fuel burn."
            )
    elif mode == "maritime":
        notes.append(
            "Surface wind used to estimate wave height (Pierson-Moskowitz: Hs = 0.0246 × V²). "
            f"Dominant direction: {dominant_dir}."
        )
        # Derived wave height estimate
        wave_mean = 0.0246 * speed_mean ** 2
        notes.append(f"Estimated mean significant wave height: {wave_mean:.2f} m.")
    elif mode == "trucking":
        notes.append(
            f"Surface wind at 10m. Dominant direction: {dominant_dir}. "
            "Wind drag is a minor factor for heavy trucks (~5% of fuel consumption); "
            "slope and congestion dominate."
        )

    return {
        "status": "ok",
        "mode": mode,
        "altitude": "250 hPa (~10,600 m cruise level)" if mode == "aviation" else "10 m surface",
        "wind_u_mean_ms": round(u_mean, 4),
        "wind_u_max_ms": round(max(u_values), 4),
        "wind_u_min_ms": round(min(u_values), 4),
        "wind_v_mean_ms": round(v_mean, 4),
        "wind_v_max_ms": round(max(v_values), 4),
        "wind_v_min_ms": round(min(v_values), 4),
        "wind_speed_mean_ms": round(speed_mean, 4),
        "wind_speed_max_ms": round(max(speed_values), 4),
        "valid_cells": len(u_values),
        "dominant_direction": dominant_dir,
        "notes": " | ".join(notes),
    }


# ---------------------------------------------------------------------------
# Tool 3 — query_viirs_ships
# ---------------------------------------------------------------------------

@tool
def query_viirs_ships(grid_path: str) -> dict:
    """
    Query VIIRS nighttime radiance as a ship traffic or road congestion density proxy.

    Maritime mode: reads viirs_radiance_nw — monthly composite of VIIRS Day/Night Band.
        Higher values (nW/cm²/sr) indicate denser structural shipping lanes.
        Max normalisation: 50 nW/cm²/sr. Do NOT raise WARN solely for high VIIRS — it is
        a structural monthly average, not a real-time event.

    Trucking mode: reads viirs_nw — same sensor but applied to highway congestion.
        Max normalisation: 60 nW/cm²/sr (higher ceiling for urban highway density).
        NY/NJ area reaches up to 158 nW/cm²/sr — truncated at normalisation max.

    Aviation mode: VIIRS is not applicable (aircraft do not follow surface shipping lanes).
        Returns an informational response without querying any data.

    Args:
        grid_path: Path to the grid JSON file (absolute or relative to workspace root).
    """
    data = _load_grid(grid_path)
    if "_error" in data:
        return {"status": "error", "message": data["_error"]}

    mode = data.get("mode", "maritime")

    if mode == "aviation":
        return {
            "status": "ok",
            "mode": "aviation",
            "applicable": False,
            "notes": (
                "VIIRS ship/road traffic proxy is not applicable for aviation mode. "
                "Aircraft routes are not constrained by surface shipping or road density."
            ),
        }

    layers = data.get("layers", {})

    if mode == "maritime":
        layer_key = "viirs_radiance_nw"
        norm_max = 50.0
        unit = "nW/cm²/sr"
        high_traffic_threshold = norm_max * 0.60   # >60% of normalisation max
        interpretation = "ship traffic lane density (monthly composite)"
    else:  # trucking
        layer_key = "viirs_nw"
        norm_max = 60.0
        unit = "nW/cm²/sr"
        high_traffic_threshold = norm_max * 0.60
        interpretation = "highway congestion proxy (monthly composite)"

    layer_data: list[list] = layers.get(layer_key, {}).get("data", [])
    if not layer_data:
        return {
            "status": "error",
            "message": f"Layer '{layer_key}' not found in grid payload for mode={mode}",
        }

    gdef = data["grid_definition"]
    values: list[float] = []
    high_traffic_cells: list[dict] = []

    for r, row in enumerate(layer_data):
        for c, val in enumerate(row):
            if val is None:
                continue
            v = float(val)
            values.append(v)
            if v > high_traffic_threshold:
                lat, lon = _cell_center(r, c, gdef)
                high_traffic_cells.append({
                    "row": r,
                    "col": c,
                    "lat": round(lat, 4),
                    "lon": round(lon, 4),
                    "viirs_radiance": round(v, 4),
                })

    if not values:
        return {"status": "error", "message": f"No valid {layer_key} data found"}

    mean_val = sum(values) / len(values)

    notes: list[str] = []
    notes.append(
        f"VIIRS is a monthly structural average — represents {interpretation}. "
        "High values indicate historically dense traffic, not a real-time event."
    )
    if mode == "maritime":
        notes.append(
            "Do not issue WARN solely based on high VIIRS. "
            "High-density shipping lanes (e.g., TSS straits) are expected to have high VIIRS."
        )
        # Jurong Island confound note
        notes.append(
            "Note: industrial radiance from Jurong Island (1.27°N, 103.68°E) may inflate "
            "VIIRS values in adjacent cells — cross-check with SO2 layer."
        )
    elif mode == "trucking":
        notes.append(
            "NY/NJ metropolitan area reaches 158 nW/cm²/sr — truncated to 60 nW/cm²/sr "
            "in green_score normalisation. Urban clusters are structural, not operational anomalies."
        )

    return {
        "status": "ok",
        "layer": layer_key,
        "unit": unit,
        "mode": mode,
        "applicable": True,
        "mean": round(mean_val, 4),
        "max": round(max(values), 4),
        "min": round(min(values), 4),
        "valid_cells": len(values),
        "high_traffic_cells_count": len(high_traffic_cells),
        "high_traffic_threshold": high_traffic_threshold,
        "high_traffic_cells": high_traffic_cells[:10],
        "notes": " | ".join(notes),
    }


# ---------------------------------------------------------------------------
# Tool 4 — query_so2_hotspots
# ---------------------------------------------------------------------------

@tool
def query_so2_hotspots(grid_path: str) -> dict:
    """
    Query SO2 column density hotspots for ECA violation detection and industrial confound filtering.

    Called ONLY when query_gee_no2 returns trigger_so2_check=True (NO2 mean > 2.5e-5 mol/m²).

    Maritime mode:
    - SO2 is the primary indicator of High-Sulfur Fuel Oil (HFO) use.
    - Cells within 0.2° of Jurong Island (1.27°N, 103.68°E) may have industrial SO2 —
      do NOT use as evidence of ECA violation. These are marked in industrial_confound_cells.
    - ECA violation risk = True if non-confound hotspots exist (SO2 > threshold).

    Trucking mode:
    - SO2 in the US is typically low (ULSD < 15 ppm sulfur) — high values indicate
      stationary industrial sources (coal plants, refineries) near the route, not trucks.
    - Cross-reference with known industrial emitters: Dominion Energy VA, Marcus Hook PA.

    Aviation mode: SO2 ECA rules do not apply. Returns informational response.

    Args:
        grid_path: Path to the grid JSON file (absolute or relative to workspace root).
    """
    data = _load_grid(grid_path)
    if "_error" in data:
        return {"status": "error", "message": data["_error"]}

    mode = data.get("mode", "maritime")

    if mode == "aviation":
        return {
            "status": "ok",
            "mode": "aviation",
            "applicable": False,
            "notes": (
                "SO2 ECA rules do not apply to aviation mode. "
                "Aviation uses aerosol_index and aod layers for air quality assessment."
            ),
        }

    layers = data.get("layers", {})
    so2_data: list[list] = layers.get("so2_mol_m2", {}).get("data", [])

    if not so2_data:
        return {
            "status": "error",
            "message": "so2_mol_m2 layer not found in grid payload",
        }

    gdef = data["grid_definition"]
    cs = gdef["cell_size_degrees"]

    # Thresholds
    SO2_HOTSPOT_THRESHOLD = 5e-5   # mol/m² — elevated SO2 signal
    JURONG_LAT, JURONG_LON = 1.27, 103.68   # Jurong Island industrial complex
    CONFOUND_RADIUS_DEG = 0.2

    values: list[float] = []
    null_count = 0
    hotspots: list[dict] = []
    industrial_confound: list[dict] = []

    for r, row in enumerate(so2_data):
        for c, val in enumerate(row):
            if val is None:
                null_count += 1
                continue
            v = float(val)
            values.append(v)

            if v > SO2_HOTSPOT_THRESHOLD:
                lat, lon = _cell_center(r, c, gdef)
                cell_info = {
                    "row": r,
                    "col": c,
                    "lat": round(lat, 4),
                    "lon": round(lon, 4),
                    "so2_mol_m2": round(v, 10),
                }

                # Check Jurong Island confound (maritime only)
                if mode == "maritime":
                    dist_deg = math.sqrt(
                        (lat - JURONG_LAT) ** 2 + (lon - JURONG_LON) ** 2
                    )
                    if dist_deg <= CONFOUND_RADIUS_DEG:
                        industrial_confound.append({**cell_info, "confound_source": "Jurong Island petrochemical"})
                        continue

                hotspots.append(cell_info)

    if not values:
        return {"status": "error", "message": "No valid SO2 data cells found"}

    total_cells = sum(len(row) for row in so2_data)
    null_fraction = null_count / max(total_cells, 1)
    mean_val = sum(values) / len(values)
    eca_risk = len(hotspots) > 0 and mode == "maritime"

    notes: list[str] = []
    if industrial_confound:
        notes.append(
            f"{len(industrial_confound)} SO2 hotspot(s) near Jurong Island excluded from ECA analysis "
            "(industrial petrochemical source — not attributable to vessel HFO use)."
        )
    if eca_risk:
        notes.append(
            f"{len(hotspots)} non-industrial SO2 hotspot(s) detected above {SO2_HOTSPOT_THRESHOLD:.0e} mol/m². "
            "ECA violation risk elevated — ships in these cells may be using high-sulfur fuel."
        )
    if mode == "trucking" and hotspots:
        notes.append(
            f"Trucking: {len(hotspots)} SO2 hotspot(s) likely from stationary industrial emitters "
            "(coal plants, refineries) — not from truck diesel (ULSD sulfur < 15 ppm)."
        )
    if null_fraction > 0.40:
        notes.append(
            f"SO2 layer has {null_fraction:.1%} null coverage — partial data. "
            "Cells without SO2 data are excluded from the ECA risk assessment."
        )

    return {
        "status": "ok",
        "layer": "so2_mol_m2",
        "unit": "mol/m²",
        "mode": mode,
        "applicable": True,
        "mean": round(mean_val, 10),
        "max": round(max(values), 10),
        "valid_cells": len(values),
        "null_cells": null_count,
        "null_fraction": round(null_fraction, 4),
        "hotspot_cells_count": len(hotspots),
        "hotspots": hotspots[:10],
        "industrial_confound_cells_count": len(industrial_confound),
        "industrial_confound_cells": industrial_confound[:5],
        "eca_violation_risk": eca_risk,
        "notes": " | ".join(notes) if notes else "No SO2 hotspots above threshold.",
    }


# ---------------------------------------------------------------------------
# Tool 5 — query_co  (aviation + trucking)
# ---------------------------------------------------------------------------

@tool
def query_co(grid_path: str) -> dict:
    """
    Query CO (carbon monoxide) total column density.

    Aviation mode (weight 0.05):
        Source: Sentinel-5P TROPOMI — COPERNICUS/S5P/OFFL/L3_CO, band CO_column_number_density.
        Role: Combustion tracer. High CO over established routes indicates anomalous
        combustion or dense air-traffic background in the corridor.
        Business rule: CO elevated over the Gulf region (DXB waypoint area) may reflect
        terrestrial petrochemical activity — verify cells are not over the Gulf itself
        before penalising the route.

    Trucking mode (weight 0.10):
        Same source. Role: stop-and-go traffic proxy.
        CO > 0.035 mol/m² on highway cells = severe congestion with incomplete combustion.
        Always correlate with viirs_nw: CO high + VIIRS high = active congestion confirmed;
        CO high + VIIRS low = likely non-road point source (industrial fire, facility).

    Maritime mode: not applicable (CO is not in the maritime green_score formula).

    Args:
        grid_path: Path to the grid JSON file (absolute or relative to workspace root).
    """
    data = _load_grid(grid_path)
    if "_error" in data:
        return {"status": "error", "message": data["_error"]}

    mode = data.get("mode", "maritime")

    if mode == "maritime":
        return {
            "status": "ok",
            "mode": "maritime",
            "applicable": False,
            "notes": "CO layer is not part of the maritime green_score formula. Tool not applicable.",
        }

    layers = data.get("layers", {})
    co_data: list[list] = layers.get("co_mol_m2", {}).get("data", [])

    if not co_data:
        return {"status": "error", "message": "co_mol_m2 layer not found in grid payload"}

    gdef = data["grid_definition"]

    # Trucking congestion threshold from data dict
    CONGESTION_THRESHOLD = 0.035   # mol/m²

    values: list[float] = []
    null_count = 0
    congestion_cells: list[dict] = []

    for r, row in enumerate(co_data):
        for c, val in enumerate(row):
            if val is None:
                null_count += 1
                continue
            v = float(val)
            values.append(v)
            if mode == "trucking" and v > CONGESTION_THRESHOLD:
                lat, lon = _cell_center(r, c, gdef)
                congestion_cells.append({
                    "row": r, "col": c,
                    "lat": round(lat, 4), "lon": round(lon, 4),
                    "co_mol_m2": round(v, 8),
                })

    if not values:
        return {"status": "error", "message": "No valid CO data cells found"}

    mean_val = sum(values) / len(values)
    total_cells = sum(len(row) for row in co_data)
    null_fraction = null_count / max(total_cells, 1)

    notes: list[str] = []
    if mode == "aviation":
        notes.append(
            "CO is a secondary combustion tracer in aviation (weight 0.05). "
            "Correlate with NO2: both elevated = high air-traffic density; "
            "CO alone elevated over Gulf = petrochemical terrestrial source near DXB."
        )
    elif mode == "trucking":
        notes.append(
            f"CO trucking threshold is 0.035 mol/m². "
            f"Found {len(congestion_cells)} congestion-flagged cell(s). "
            "Correlate with viirs_nw to confirm active vs structural congestion."
        )

    return {
        "status": "ok",
        "layer": "co_mol_m2",
        "unit": "mol/m²",
        "mode": mode,
        "applicable": True,
        "mean": round(mean_val, 8),
        "max": round(max(values), 8),
        "min": round(min(values), 8),
        "valid_cells": len(values),
        "null_cells": null_count,
        "null_fraction": round(null_fraction, 4),
        "congestion_cells_count": len(congestion_cells),   # trucking only; 0 for aviation
        "congestion_cells": congestion_cells[:10],
        "notes": " | ".join(notes),
    }


# ---------------------------------------------------------------------------
# Tool 6 — query_turbulence  (aviation only)
# ---------------------------------------------------------------------------

@tool
def query_turbulence(grid_path: str) -> dict:
    """
    Query the turbulence index at cruise level (aviation only, weight 0.15).

    Source: Derived from GFS/ERA5 wind shear and vorticity at cruise altitude.
    Unit: dimensionless index 0–30. Higher = more turbulent.
    Location in payload: derived_layers.turbulence_index

    Roles:
    - Clear Air Turbulence (CAT) and convective turbulence at FL340–FL390.
    - High index = increased fuel burn from vertical deviations, passenger safety risk.

    Business rule (from data dictionary):
    - Index > 15 over the Himalaya/Hindu Kush (~rows 20–30, cols ~85–100 in the
      PVG→AMS 60×125 grid at 1° resolution) is structurally expected due to jet
      stream wind shear over orography. The CorridorOptimizer should route around
      these cells even if the index is not anomalous.

    Args:
        grid_path: Path to the grid JSON file (absolute or relative to workspace root).
    """
    data = _load_grid(grid_path)
    if "_error" in data:
        return {"status": "error", "message": data["_error"]}

    mode = data.get("mode", "maritime")

    if mode != "aviation":
        return {
            "status": "ok",
            "mode": mode,
            "applicable": False,
            "notes": "Turbulence index is an aviation-only layer. Not applicable for this mode.",
        }

    # turbulence_index lives in derived_layers in the actual payload
    derived = data.get("derived_layers", {})
    turb_data: list[list] = derived.get("turbulence_index", {}).get("data", [])

    if not turb_data:
        return {"status": "error", "message": "turbulence_index not found in derived_layers"}

    gdef = data["grid_definition"]
    STRUCTURAL_THRESHOLD = 15.0   # index > 15 over Himalaya = structurally expected

    values: list[float] = []
    null_count = 0
    high_turb_cells: list[dict] = []

    for r, row in enumerate(turb_data):
        for c, val in enumerate(row):
            if val is None:
                null_count += 1
                continue
            v = float(val)
            values.append(v)
            if v > STRUCTURAL_THRESHOLD:
                lat, lon = _cell_center(r, c, gdef)
                # Flag whether this cell is in the Himalaya structural zone
                himalaya_zone = (20 <= r <= 30) and (85 <= c <= 100)
                high_turb_cells.append({
                    "row": r, "col": c,
                    "lat": round(lat, 4), "lon": round(lon, 4),
                    "turbulence_index": round(v, 4),
                    "himalaya_structural": himalaya_zone,
                })

    if not values:
        return {"status": "error", "message": "No valid turbulence_index data found"}

    mean_val = sum(values) / len(values)
    himalaya_cells = sum(1 for c in high_turb_cells if c["himalaya_structural"])
    non_structural = sum(1 for c in high_turb_cells if not c["himalaya_structural"])

    notes = [
        f"Turbulence index mean: {mean_val:.2f} (scale 0–30). "
        f"{len(high_turb_cells)} cell(s) above threshold {STRUCTURAL_THRESHOLD}.",
        f"Of those: {himalaya_cells} in Himalaya structural zone (expected), "
        f"{non_structural} outside structural zone (operationally significant).",
        "CorridorOptimizer should route around high-turbulence cells regardless of "
        "whether they are structural or episodic.",
    ]

    return {
        "status": "ok",
        "layer": "turbulence_index",
        "source": "derived_layers",
        "unit": "dimensionless 0–30",
        "mode": mode,
        "applicable": True,
        "mean": round(mean_val, 4),
        "max": round(max(values), 4),
        "min": round(min(values), 4),
        "valid_cells": len(values),
        "null_cells": null_count,
        "high_turbulence_cells_count": len(high_turb_cells),
        "himalaya_structural_cells": himalaya_cells,
        "non_structural_high_turb_cells": non_structural,
        "high_turbulence_cells": high_turb_cells[:10],
        "notes": " | ".join(notes),
    }


# ---------------------------------------------------------------------------
# Tool 7 — query_contrail_risk  (aviation only)
# ---------------------------------------------------------------------------

@tool
def query_contrail_risk(grid_path: str) -> dict:
    """
    Query contrail formation risk at cruise level (aviation only, weight 0.10).

    Source: Derived from ERA5 temperature and relative humidity at 250 hPa.
    Unit: probability 0.0–1.0. Higher = greater risk of persistent contrails.
    Location in payload: derived_layers.contrail_risk

    Role: Persistent contrails have a radiative forcing effect that amplifies the
    climate impact of aviation beyond direct CO2 emissions. Minimising contrail
    risk is an explicit objective of the green certification.

    Business rule (from data dictionary):
    - Cells with contrail_risk > 0.75 in the 40°N–60°N band (rows ~15–35 in the
      PVG→AMS 60×125 grid at 1° resolution) are high-climate-impact segments.
      The CorridorOptimizer may suggest a lower flight level as mitigation, but
      this is recorded as a note — not a hard routing constraint.
    - The CertificationJudge must report the mean contrail_risk for the European
      segment (cols ~0–40) and compare it to the P1 baseline.

    Args:
        grid_path: Path to the grid JSON file (absolute or relative to workspace root).
    """
    data = _load_grid(grid_path)
    if "_error" in data:
        return {"status": "error", "message": data["_error"]}

    mode = data.get("mode", "maritime")

    if mode != "aviation":
        return {
            "status": "ok",
            "mode": mode,
            "applicable": False,
            "notes": "Contrail risk is an aviation-only layer. Not applicable for this mode.",
        }

    derived = data.get("derived_layers", {})
    contrail_data: list[list] = derived.get("contrail_risk", {}).get("data", [])

    if not contrail_data:
        return {"status": "error", "message": "contrail_risk not found in derived_layers"}

    gdef = data["grid_definition"]
    HIGH_RISK_THRESHOLD = 0.75
    # 40°N–60°N corresponds to rows ~15–35 in the 60×125 grid (north=75°, cell=1°)
    PERSISTENT_BAND_ROW_MIN, PERSISTENT_BAND_ROW_MAX = 15, 35
    # European segment: cols ~0–40 (lon 0°–40°E)
    EUROPE_COL_MAX = 40

    values: list[float] = []
    null_count = 0
    high_risk_cells: list[dict] = []
    europe_values: list[float] = []

    for r, row in enumerate(contrail_data):
        for c, val in enumerate(row):
            if val is None:
                null_count += 1
                continue
            v = float(val)
            values.append(v)
            if c <= EUROPE_COL_MAX:
                europe_values.append(v)
            if v > HIGH_RISK_THRESHOLD:
                lat, lon = _cell_center(r, c, gdef)
                in_persistent_band = PERSISTENT_BAND_ROW_MIN <= r <= PERSISTENT_BAND_ROW_MAX
                high_risk_cells.append({
                    "row": r, "col": c,
                    "lat": round(lat, 4), "lon": round(lon, 4),
                    "contrail_risk": round(v, 4),
                    "in_persistent_band_40_60N": in_persistent_band,
                })

    if not values:
        return {"status": "error", "message": "No valid contrail_risk data found"}

    mean_val = sum(values) / len(values)
    europe_mean = round(sum(europe_values) / len(europe_values), 4) if europe_values else None
    in_band = sum(1 for c in high_risk_cells if c["in_persistent_band_40_60N"])

    notes = [
        f"Contrail risk mean: {mean_val:.3f}. "
        f"{len(high_risk_cells)} cell(s) above high-risk threshold ({HIGH_RISK_THRESHOLD}).",
        f"{in_band} high-risk cell(s) in the 40°N–60°N persistent contrail band.",
        f"European segment (cols 0–40) mean contrail risk: {europe_mean}.",
        "High-risk cells in the 40°N–60°N band in winter/spring are structurally expected "
        "(cold temps + high humidity at FL350). Consider lower flight level as mitigation.",
    ]

    return {
        "status": "ok",
        "layer": "contrail_risk",
        "source": "derived_layers",
        "unit": "probability 0.0–1.0",
        "mode": mode,
        "applicable": True,
        "mean": round(mean_val, 4),
        "max": round(max(values), 4),
        "min": round(min(values), 4),
        "valid_cells": len(values),
        "null_cells": null_count,
        "europe_segment_mean": europe_mean,
        "high_risk_cells_count": len(high_risk_cells),
        "high_risk_in_persistent_band_count": in_band,
        "high_risk_cells": high_risk_cells[:10],
        "notes": " | ".join(notes),
    }


# ---------------------------------------------------------------------------
# Tool 8 — query_cloud_top_height  (aviation only)
# ---------------------------------------------------------------------------

@tool
def query_cloud_top_height(grid_path: str) -> dict:
    """
    Query cloud top height at cruise level (aviation only, weight 0.10).

    Source: Derived from GFS cloud top pressure converted to altitude.
    Unit: metres. Normalisation max: 15,000 m. Value 0 = clear sky at that level.
    Location in payload: layers.cloud_top_height_m

    Role: Indicator of cumulonimbus and deep convection along the route.
    Cloud tops above 12,000 m indicate active convective systems that can force
    significant lateral or vertical deviations.

    Business rule (from data dictionary):
    - Cells over the Arabian Sea and northern India (~rows 30–40, cols ~50–80
      in the PVG→AMS grid) may show elevated cloud_top_height during monsoon
      transition. In March this is moderate; peak season is June–September.

    Args:
        grid_path: Path to the grid JSON file (absolute or relative to workspace root).
    """
    data = _load_grid(grid_path)
    if "_error" in data:
        return {"status": "error", "message": data["_error"]}

    mode = data.get("mode", "maritime")

    if mode != "aviation":
        return {
            "status": "ok",
            "mode": mode,
            "applicable": False,
            "notes": "Cloud top height is an aviation-only layer. Not applicable for this mode.",
        }

    layers = data.get("layers", {})
    cth_data: list[list] = layers.get("cloud_top_height_m", {}).get("data", [])

    if not cth_data:
        return {"status": "error", "message": "cloud_top_height_m not found in layers"}

    gdef = data["grid_definition"]
    CB_THRESHOLD = 12000.0  # metres — cumulonimbus / deep convection
    # Arabian Sea / N. India monsoon zone
    MONSOON_ROW_MIN, MONSOON_ROW_MAX = 30, 40
    MONSOON_COL_MIN, MONSOON_COL_MAX = 50, 80

    values: list[float] = []
    null_count = 0
    convective_cells: list[dict] = []

    for r, row in enumerate(cth_data):
        for c, val in enumerate(row):
            if val is None:
                null_count += 1
                continue
            v = float(val)
            values.append(v)
            if v > CB_THRESHOLD:
                lat, lon = _cell_center(r, c, gdef)
                monsoon_zone = (
                    MONSOON_ROW_MIN <= r <= MONSOON_ROW_MAX
                    and MONSOON_COL_MIN <= c <= MONSOON_COL_MAX
                )
                convective_cells.append({
                    "row": r, "col": c,
                    "lat": round(lat, 4), "lon": round(lon, 4),
                    "cloud_top_height_m": round(v, 1),
                    "monsoon_transition_zone": monsoon_zone,
                })

    if not values:
        return {"status": "error", "message": "No valid cloud_top_height_m data found"}

    mean_val = sum(values) / len(values)
    monsoon_cells = sum(1 for c in convective_cells if c["monsoon_transition_zone"])

    notes = [
        f"Cloud top height mean: {mean_val:.0f} m. "
        f"{len(convective_cells)} cell(s) above CB threshold ({CB_THRESHOLD:.0f} m).",
    ]
    if monsoon_cells:
        notes.append(
            f"{monsoon_cells} convective cell(s) in Arabian Sea / N. India monsoon zone. "
            "In March this is moderate — peak season is June–September."
        )

    return {
        "status": "ok",
        "layer": "cloud_top_height_m",
        "source": "layers",
        "unit": "metres",
        "mode": mode,
        "applicable": True,
        "mean": round(mean_val, 1),
        "max": round(max(values), 1),
        "min": round(min(values), 1),
        "valid_cells": len(values),
        "null_cells": null_count,
        "convective_cells_above_12000m_count": len(convective_cells),
        "monsoon_zone_convective_cells": monsoon_cells,
        "convective_cells": convective_cells[:10],
        "notes": " | ".join(notes),
    }


# ---------------------------------------------------------------------------
# Tool 9 — query_aerosol_index  (aviation only)
# ---------------------------------------------------------------------------

@tool
def query_aerosol_index(grid_path: str) -> dict:
    """
    Query UV Aerosol Index for dust, smoke, and absorbing aerosol detection (aviation only, weight 0.10).

    Source: Sentinel-5P TROPOMI — COPERNICUS/S5P/OFFL/L3_AER_AI, band absorbing_aerosol_index.
    Unit: dimensionless –1 to +5. Negative = non-absorbing aerosols or clear surface.
    Normalisation range: [–1, 5]. Location in payload: layers.aerosol_index.

    Role: Detects absorbing aerosols (Saharan dust, Arabian dust — shamal storms,
    biomass burning smoke) that reduce airport visibility and degrade airborne
    optical systems on approach.

    Business rule (from data dictionary):
    - Values > 2.0 over the Gulf region and Arabian Peninsula are frequent in March
      due to shamal dust storms. The SatelliteAnalyst must report the maximum
      aerosol_index within a 3-cell radius (~300 km at 1°/cell) around DXB
      (25.25°N, 55.36°E → row 49, col 55 in the 60×125 grid).
    - If aerosol_index > 2.5 in the DXB radius → set aerosol_dxb_alert=True.
      The CertificationJudge must issue at least a WARN for the DXB intermediate
      segment even if the global green_score is GREEN.

    Args:
        grid_path: Path to the grid JSON file (absolute or relative to workspace root).
    """
    data = _load_grid(grid_path)
    if "_error" in data:
        return {"status": "error", "message": data["_error"]}

    mode = data.get("mode", "maritime")

    if mode != "aviation":
        return {
            "status": "ok",
            "mode": mode,
            "applicable": False,
            "notes": "Aerosol index is an aviation-only layer. Not applicable for this mode.",
        }

    layers = data.get("layers", {})
    ai_data: list[list] = layers.get("aerosol_index", {}).get("data", [])

    if not ai_data:
        return {"status": "error", "message": "aerosol_index not found in layers"}

    gdef = data["grid_definition"]
    # DXB location in the 60×125 grid (1° cells, north=75°, west=0°)
    DXB_ROW, DXB_COL = 49, 55
    DXB_RADIUS_CELLS = 3          # ~300 km at 1° resolution
    ALERT_THRESHOLD = 2.5
    HOTSPOT_THRESHOLD = 2.0

    values: list[float] = []
    null_count = 0
    hotspot_cells: list[dict] = []
    dxb_values: list[float] = []

    for r, row in enumerate(ai_data):
        for c, val in enumerate(row):
            if val is None:
                null_count += 1
                continue
            v = float(val)
            values.append(v)

            # Collect values within DXB radius
            if abs(r - DXB_ROW) <= DXB_RADIUS_CELLS and abs(c - DXB_COL) <= DXB_RADIUS_CELLS:
                dxb_values.append(v)

            if v > HOTSPOT_THRESHOLD:
                lat, lon = _cell_center(r, c, gdef)
                in_dxb_radius = (
                    abs(r - DXB_ROW) <= DXB_RADIUS_CELLS
                    and abs(c - DXB_COL) <= DXB_RADIUS_CELLS
                )
                hotspot_cells.append({
                    "row": r, "col": c,
                    "lat": round(lat, 4), "lon": round(lon, 4),
                    "aerosol_index": round(v, 4),
                    "in_dxb_radius": in_dxb_radius,
                })

    if not values:
        return {"status": "error", "message": "No valid aerosol_index data found"}

    mean_val = sum(values) / len(values)
    dxb_max = round(max(dxb_values), 4) if dxb_values else None
    aerosol_dxb_alert = bool(dxb_max is not None and dxb_max > ALERT_THRESHOLD)

    notes = [
        f"Aerosol index mean: {mean_val:.3f} (scale –1 to +5). "
        f"{len(hotspot_cells)} cell(s) above hotspot threshold ({HOTSPOT_THRESHOLD}).",
        f"DXB radius ({DXB_RADIUS_CELLS} cells) max aerosol_index: {dxb_max}.",
    ]
    if aerosol_dxb_alert:
        notes.append(
            f"ALERT: aerosol_index {dxb_max} > {ALERT_THRESHOLD} near DXB. "
            "Likely shamal dust storm. CertificationJudge must issue at least WARN "
            "for the DXB segment regardless of global green_score."
        )
    else:
        notes.append("No aerosol alert near DXB.")

    return {
        "status": "ok",
        "layer": "aerosol_index",
        "source": "layers",
        "unit": "dimensionless –1 to +5",
        "mode": mode,
        "applicable": True,
        "mean": round(mean_val, 4),
        "max": round(max(values), 4),
        "min": round(min(values), 4),
        "valid_cells": len(values),
        "null_cells": null_count,
        "null_fraction": round(null_count / max(sum(len(r) for r in ai_data), 1), 4),
        "dxb_radius_cells": DXB_RADIUS_CELLS,
        "dxb_max_aerosol_index": dxb_max,
        "aerosol_dxb_alert": aerosol_dxb_alert,
        "hotspot_cells_count": len(hotspot_cells),
        "hotspot_cells": hotspot_cells[:10],
        "notes": " | ".join(notes),
    }


# ---------------------------------------------------------------------------
# Tool 10 — query_aod  (aviation only)
# ---------------------------------------------------------------------------

@tool
def query_aod(grid_path: str) -> dict:
    """
    Query Aerosol Optical Depth (AOD) at 550 nm — total aerosol loading (aviation only, weight 0.05).

    Source: MODIS Terra/Aqua or Sentinel-5P TROPOMI.
    Unit: dimensionless 0.0–1.0+. Values > 1.0 are possible in extreme dust events.
    Normalisation range: [0, 1]. Location in payload: layers.aod.

    Role: Quantitative complement to aerosol_index. While aerosol_index detects
    absorbing aerosols (dust, smoke), AOD measures total aerosol extinction including
    non-absorbing aerosols (sulfates, sea salt). High AOD reduces visibility and can
    affect airborne optical systems on approach.

    Relationship to aerosol_index (from data dictionary):
    - aerosol_index detects absorbing aerosols specifically.
    - AOD measures total aerosol load including non-absorbing.
    - Both layers must be evaluated together for the DXB segment.
    - A value of 84 in the raw MODIS internal scale ≈ 0.33 AOD physical units.
      Note: maritime mode uses a different scale (MODIS raw 0–256); aviation uses
      physical AOD (0.0–1.0+) directly.

    Args:
        grid_path: Path to the grid JSON file (absolute or relative to workspace root).
    """
    data = _load_grid(grid_path)
    if "_error" in data:
        return {"status": "error", "message": data["_error"]}

    mode = data.get("mode", "maritime")

    if mode != "aviation":
        return {
            "status": "ok",
            "mode": mode,
            "applicable": False,
            "notes": "AOD (aviation physical scale 0–1) is an aviation-only layer. Not applicable.",
        }

    layers = data.get("layers", {})
    aod_data: list[list] = layers.get("aod", {}).get("data", [])

    if not aod_data:
        return {"status": "error", "message": "aod not found in layers"}

    gdef = data["grid_definition"]
    HIGH_AOD_THRESHOLD = 0.5   # moderate-to-high aerosol load
    DXB_ROW, DXB_COL = 49, 55
    DXB_RADIUS_CELLS = 3

    values: list[float] = []
    null_count = 0
    high_aod_cells: list[dict] = []
    dxb_values: list[float] = []

    for r, row in enumerate(aod_data):
        for c, val in enumerate(row):
            if val is None:
                null_count += 1
                continue
            v = float(val)
            values.append(v)

            if abs(r - DXB_ROW) <= DXB_RADIUS_CELLS and abs(c - DXB_COL) <= DXB_RADIUS_CELLS:
                dxb_values.append(v)

            if v > HIGH_AOD_THRESHOLD:
                lat, lon = _cell_center(r, c, gdef)
                high_aod_cells.append({
                    "row": r, "col": c,
                    "lat": round(lat, 4), "lon": round(lon, 4),
                    "aod": round(v, 4),
                    "in_dxb_radius": (
                        abs(r - DXB_ROW) <= DXB_RADIUS_CELLS
                        and abs(c - DXB_COL) <= DXB_RADIUS_CELLS
                    ),
                })

    if not values:
        return {"status": "error", "message": "No valid AOD data found"}

    mean_val = sum(values) / len(values)
    dxb_mean_aod = round(sum(dxb_values) / len(dxb_values), 4) if dxb_values else None
    total_cells = sum(len(row) for row in aod_data)

    # Data dictionary specifies aviation AOD in physical units [0, 1+].
    # If mean > 5, values are in a raw non-physical scale — flag as scale mismatch.
    scale_mismatch = mean_val > 5.0
    data_quality = "scale_mismatch" if scale_mismatch else "ok"

    notes = [
        f"AOD mean: {mean_val:.3f}. {len(high_aod_cells)} cell(s) above {HIGH_AOD_THRESHOLD} threshold.",
        f"DXB radius mean AOD: {dxb_mean_aod}.",
        "Evaluate AOD together with aerosol_index: aerosol_index detects absorbing aerosols "
        "(dust/smoke); AOD captures total load including sulfates and sea salt.",
    ]
    if scale_mismatch:
        notes.append(
            f"DATA QUALITY WARNING: AOD values (mean={mean_val:.1f}) exceed the physical "
            "range [0, 1+] specified in the data dictionary. "
            "The payload appears to contain raw unscaled values. "
            "Use aerosol_index as the primary aerosol indicator for this corridor."
        )

    return {
        "status": "ok",
        "layer": "aod",
        "source": "layers",
        "unit": "dimensionless 0.0–1.0+",
        "mode": mode,
        "applicable": True,
        "data_quality": data_quality,
        "mean": round(mean_val, 4),
        "max": round(max(values), 4),
        "min": round(min(values), 4),
        "valid_cells": len(values),
        "null_cells": null_count,
        "null_fraction": round(null_count / max(total_cells, 1), 4),
        "high_aod_cells_count": len(high_aod_cells),
        "dxb_radius_mean_aod": dxb_mean_aod,
        "high_aod_cells": high_aod_cells[:10],
        "notes": " | ".join(notes),
    }
