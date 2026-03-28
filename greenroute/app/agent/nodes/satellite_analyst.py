"""
satellite_analyst.py — LangGraph node for the SatelliteAnalyst agent (Agent 1).

Uses a ReAct loop (via create_react_agent).

Tool call budgets per mode:
  Maritime / Trucking : up to 5 tool calls  (recursion_limit=12)
  Aviation            : up to 9 tool calls  (recursion_limit=20)

Tool call order — maritime / trucking:
  1. query_gee_no2          — always first
  2. query_gee_no2 again    — only if data_quality='poor' (>30% null)
  3. query_era5_wind        — always
  4. query_viirs_ships      — always (maritime + trucking)
  5. query_so2_hotspots     — only if NO2 trigger_so2_check=True

Tool call order — aviation:
  1. query_gee_no2          — always first
  2. query_gee_no2 again    — only if data_quality='poor'
  3. query_era5_wind        — always (jet stream at 250 hPa)
  4. query_co               — always
  5. query_turbulence       — always
  6. query_contrail_risk    — always
  7. query_cloud_top_height — always
  8. query_aerosol_index    — always (includes DXB proximity check)
  9. query_aod              — always

The node returns a state update with:
  - messages:            agent conversation history (accumulated)
  - satellite_report:    SatelliteReport as dict (parsed from agent's last message)
  - grid_snapshot_path:  resolved absolute path to the grid JSON used
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from app.agent.payload_registry import list_payloads, resolve_payload, resolve_payload_fallback
from app.agent.state import AgentState
from app.agent.tools.satellite_tools import (
    query_aod,
    query_aerosol_index,
    query_cloud_top_height,
    query_co,
    query_contrail_risk,
    query_era5_wind,
    query_gee_no2,
    query_so2_hotspots,
    query_turbulence,
    query_viirs_ships,
)
from app.config import CorridorCfg, get_corridor_config, get_settings
from app.models import Badge, SatelliteReport, TransportMode


# ---------------------------------------------------------------------------
# Grid path resolution
# ---------------------------------------------------------------------------

def _resolve_grid_path(corridor_cfg: CorridorCfg, window: str | None = None) -> str:
    """
    Return the absolute path to the satellite grid JSON for a corridor.

    Uses the PayloadRegistry as the single source of truth.
    Resolution order:
      1. If `window` is specified → use that exact snapshot (e.g. "P2", "latest-1").
      2. If `window` is None → use the default (most recent) snapshot for the corridor.
      3. If the default snapshot is missing → fall back through all windows newest-first.

    Raises FileNotFoundError when no snapshot exists for the corridor at all.
    """
    corridor_id = corridor_cfg.corridor_id
    if window:
        # Explicit window requested — honour it, let the registry raise if unknown.
        return resolve_payload(corridor_id, window=window)

    try:
        # Default: most recent snapshot (P1 or "latest")
        return resolve_payload(corridor_id)
    except FileNotFoundError:
        # Primary snapshot missing — fall back to the first available window.
        return resolve_payload_fallback(corridor_id)


# ---------------------------------------------------------------------------
# Green-score stats helper  (pre-computed before invoking the agent)
# ---------------------------------------------------------------------------

def _get_green_score_stats(grid_path: str) -> dict[str, Any]:
    """
    Read pre-computed green_score from the grid JSON.
    Returns mean/max/min, badge distribution, and payload metadata (mode, grid_id)
    without burning a tool call.

    The `payload_mode` key is the definitive transport mode read directly from the
    JSON's top-level `mode` field.  It is used in satellite_analyst_node to validate
    alignment with the corridor config and to drive mode-aware logic.
    """
    import json as _json
    try:
        with open(grid_path) as f:
            data = _json.load(f)
    except Exception as exc:
        return {"error": str(exc), "payload_mode": "maritime", "grid_id": ""}

    # Payload-level metadata
    payload_mode: str = data.get("mode", "maritime")
    grid_id: str = data.get("grid_id", "")

    # Trucking: derived_layers.green_score; all others: layers.green_score
    gs_layer = (
        data.get("derived_layers", {}).get("green_score")
        or data.get("layers", {}).get("green_score")
        or {}
    )
    gs_data: list[list] = gs_layer.get("data", [])
    values = [v for row in gs_data for v in row if v is not None]
    if not values:
        return {
            "payload_mode": payload_mode,
            "grid_id": grid_id,
            "mean": None, "max": None, "min": None,
            "green_cells": 0, "warn_cells": 0, "red_cells": 0,
        }

    mean_v = round(sum(values) / len(values), 2)
    return {
        "payload_mode": payload_mode,
        "grid_id": grid_id,
        "mean": mean_v,
        "max": round(max(values), 2),
        "min": round(min(values), 2),
        "green_cells": sum(1 for v in values if v >= 65),
        "warn_cells":  sum(1 for v in values if 45 <= v < 65),
        "red_cells":   sum(1 for v in values if v < 45),
        "total_valid": len(values),
    }


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

def _build_system_prompt(state: AgentState, cfg: CorridorCfg, grid_path: str, gs_stats: dict) -> str:
    # Payload mode is the ground truth — validated in satellite_analyst_node already.
    # Fall back to state transport_modes, then corridor config mode.
    mode = (
        gs_stats.get("payload_mode")
        or (state["transport_modes"][0] if state.get("transport_modes") else None)
        or cfg.mode
    )
    waypoints_str = (
        "\n".join(f"  - {w.name}: {w.lat}°N, {w.lon}°E" for w in cfg.waypoints)
        or "  None"
    )
    gs_mean_str = f"{gs_stats['mean']}" if gs_stats.get("mean") is not None else "unknown"
    badge_hint = (
        "GREEN (≥65)" if (gs_stats.get("mean") or 0) >= 65
        else "WARN (45–64)" if (gs_stats.get("mean") or 0) >= 45
        else "RED (<45)"
    )

    return f"""You are the SatelliteAnalyst for the GreenRoute Intelligence Platform.
Your task: analyze environmental satellite data for the corridor below and produce a structured SatelliteReport.

═══ CORRIDOR DETAILS ═══
- Corridor ID    : {cfg.corridor_id}
- Transport mode : {mode}
- Origin         : {cfg.origin_name} ({cfg.origin_lat}°N, {cfg.origin_lon}°E)
- Destination    : {cfg.destination_name} ({cfg.destination_lat}°N, {cfg.destination_lon}°E)
- Waypoints      :
{waypoints_str}
- Grid file      : {grid_path}
- Triggered by   : {state.get("triggered_by", "new_data")}

═══ PRE-COMPUTED GREEN SCORE CONTEXT (do NOT use a tool for this) ═══
- Overall green_score mean : {gs_mean_str}  →  expected badge: {badge_hint}
- Distribution             : GREEN≥65={gs_stats.get("green_cells", "?")}  WARN={gs_stats.get("warn_cells", "?")}  RED={gs_stats.get("red_cells", "?")}

{"═══ TOOL CALLING RULES — AVIATION (follow in this exact order) ═══" if mode == "aviation" else "═══ TOOL CALLING RULES (follow in this exact order) ═══"}
1. Always call query_gee_no2 first  (grid_path="{grid_path}", date_range_days={cfg.temporal_window_days})
2. If result has data_quality='poor' → call query_gee_no2 again with date_range_days=14
3. Always call query_era5_wind  (grid_path="{grid_path}")
{"4. Always call query_co  (grid_path='" + grid_path + "')" if mode == "aviation" else "4. Call query_viirs_ships  (grid_path='" + grid_path + "')  — maritime and trucking only"}
{"5. Always call query_turbulence  (grid_path='" + grid_path + "')" if mode == "aviation" else "5. Call query_so2_hotspots IF the NO2 result has trigger_so2_check=True  (grid_path='" + grid_path + "')"}
{"6. Always call query_contrail_risk  (grid_path='" + grid_path + "')" if mode == "aviation" else "Maximum 5 tool calls total."}
{"7. Always call query_cloud_top_height  (grid_path='" + grid_path + "')" if mode == "aviation" else ""}
{"8. Always call query_aerosol_index  (grid_path='" + grid_path + "')  — includes DXB proximity check" if mode == "aviation" else ""}
{"9. Always call query_aod  (grid_path='" + grid_path + "')" if mode == "aviation" else ""}
{"Maximum 9 tool calls total." if mode == "aviation" else ""}

═══ MODE-SPECIFIC BUSINESS RULES ═══
{"MARITIME:" if mode == "maritime" else "AVIATION:" if mode == "aviation" else "TRUCKING:"}
{"- Cells within 0.2° of Jurong Island (1.27°N, 103.68°E) have industrial SO2 — not vessel ECA violation." if mode == "maritime" else ""}
{"- VIIRS high values in shipping lanes are structural averages — do NOT raise WARN for VIIRS alone." if mode == "maritime" else ""}
{"- NO2 over Europe (western columns) is terrestrial — not aviation emissions." if mode == "aviation" else ""}
{"- CO elevated over Gulf region near DXB may reflect petrochemical terrestrial sources." if mode == "aviation" else ""}
{"- Turbulence index > 15 over Himalaya/Hindu Kush (~rows 20–30, cols 85–100) is structurally expected." if mode == "aviation" else ""}
{"- Contrail risk > 0.75 in 40°N–60°N band is high climate impact. Note but do not hard-block route." if mode == "aviation" else ""}
{"- If aerosol_index > 2.5 near DXB (3-cell radius) → aerosol_dxb_alert must appear in business_rule_triggers." if mode == "aviation" else ""}
{"- A WARN score (45–55) in aviation for March is seasonally expected — do NOT auto-escalate to RED." if mode == "aviation" else ""}
{"- CO high + NO2 high = traffic congestion. NO2 high + CO low = industrial point source." if mode == "trucking" else ""}
{"- SO2 high in trucking = stationary industrial source (coal plants, refineries), not truck diesel." if mode == "trucking" else ""}
{"- NJ/Baltimore/DC/Philadelphia NO2 is structurally high — not an anomaly." if mode == "trucking" else ""}

═══ REQUIRED OUTPUT ═══
After completing all tool calls, output your SatelliteReport as a JSON code block (```json ... ```) with exactly this structure:

{{
  "corridor_id": "{cfg.corridor_id}",
  "transport_mode": "{mode}",
  "analysis_timestamp": "<ISO 8601 UTC>",
  "grid_snapshot": "{grid_path}",
  "temporal_window": null,
  "overall_score": <use the pre-computed green_score mean: {gs_mean_str}>,
  "badge": "<GREEN if ≥65, WARN if 45–64, RED if <45>",
  "layers_analyzed": ["no2_mol_m2", "wind_u_ms", "wind_v_ms", ...],
  "layer_results": {{
    "no2_mol_m2": {{ "mean": ..., "max": ..., "hotspot_cells_count": ..., "data_quality": ... }},
    "wind": {{ "speed_mean_ms": ..., "u_mean": ..., "v_mean": ..., "dominant_direction": ... }},
    ...
  }},
  "anomalies": ["<description of any anomaly>"],
  "business_rule_triggers": ["<e.g. NO2 threshold exceeded — SO2 check triggered>"],
  "data_quality_flags": {{}},
  "reasoning": "<2-3 sentence summary of corridor environmental conditions>"
}}"""


# ---------------------------------------------------------------------------
# Report extraction
# ---------------------------------------------------------------------------

def _extract_json_block(text: str) -> dict | None:
    """Try to extract a JSON object from a markdown code block or raw text."""
    # Try ```json ... ``` block first
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try the last standalone JSON object in the text
    candidates = re.findall(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
    for raw in reversed(candidates):
        try:
            parsed = json.loads(raw)
            if "corridor_id" in parsed or "overall_score" in parsed:
                return parsed
        except json.JSONDecodeError:
            continue

    return None


def _build_fallback_report(
    state: AgentState,
    cfg: CorridorCfg,
    grid_path: str,
    gs_stats: dict,
) -> SatelliteReport:
    """Construct a minimal SatelliteReport when the agent's JSON cannot be parsed."""
    score = gs_stats.get("mean") or 50.0
    badge = Badge.GREEN if score >= 65 else (Badge.WARN if score >= 45 else Badge.RED)
    mode_str = state["transport_modes"][0] if state.get("transport_modes") else cfg.mode

    return SatelliteReport(
        corridor_id=state["corridor_id"],
        transport_mode=TransportMode(mode_str),
        analysis_timestamp=datetime.now(timezone.utc),
        grid_snapshot=grid_path,
        overall_score=score,
        badge=badge,
        reasoning="Report extracted from pre-computed green_score (agent JSON parse failed).",
        anomalies=["[fallback] Agent output JSON could not be parsed"],
    )


def _parse_report_from_raw(
    raw: dict,
    state: AgentState,
    cfg: CorridorCfg,
    grid_path: str,
    gs_stats: dict,
) -> SatelliteReport:
    """Build a SatelliteReport from the agent's extracted JSON dict."""
    mode_str = raw.get("transport_mode") or (
        state["transport_modes"][0] if state.get("transport_modes") else cfg.mode
    )
    score = float(raw.get("overall_score") or gs_stats.get("mean") or 50.0)
    badge_str = raw.get("badge", "")
    if badge_str in ("GREEN", "WARN", "RED"):
        badge = Badge(badge_str)
    else:
        badge = Badge.GREEN if score >= 65 else (Badge.WARN if score >= 45 else Badge.RED)

    return SatelliteReport(
        corridor_id=raw.get("corridor_id", state["corridor_id"]),
        transport_mode=TransportMode(mode_str),
        analysis_timestamp=datetime.now(timezone.utc),
        grid_snapshot=grid_path,
        temporal_window=raw.get("temporal_window"),
        overall_score=score,
        badge=badge,
        layers_analyzed=raw.get("layers_analyzed", []),
        anomalies=raw.get("anomalies", []),
        business_rule_triggers=raw.get("business_rule_triggers", []),
        data_quality_flags=raw.get("data_quality_flags", {}),
        reasoning=raw.get("reasoning", ""),
    )


# ---------------------------------------------------------------------------
# Node entry point
# ---------------------------------------------------------------------------

def satellite_analyst_node(state: AgentState) -> dict:
    """
    LangGraph node: SatelliteAnalyst.

    Resolves the grid path via PayloadRegistry, validates payload mode against
    the corridor config, builds a ReAct agent with all satellite tools, invokes
    it (max 5–9 tool calls depending on mode), parses the SatelliteReport from
    the agent's last message, and returns a state update.

    The temporal window is read from state["temporal_window"] when present
    (e.g. "P2" or "latest-1").  If absent, the most recent snapshot is used.

    Key outputs written to AgentState:
      - messages            : accumulated LangGraph message history
      - satellite_report    : SatelliteReport dict (includes `grid_path` alias
                              so corridor_optimizer can read it with .get("grid_path"))
      - grid_snapshot_path  : resolved absolute path to the grid JSON used
    """
    settings = get_settings()
    corridor_cfg = get_corridor_config(state["corridor_id"])

    # 1. Resolve grid path via PayloadRegistry.
    #    Optionally honour a temporal window from state (e.g. "P2", "latest-1").
    window: str | None = state.get("temporal_window")  # type: ignore[attr-defined]
    grid_path = _resolve_grid_path(corridor_cfg, window=window)

    # 2. Pre-compute green_score stats (avoids burning a tool call for context).
    #    Also returns payload_mode (the `mode` field from the JSON top-level).
    gs_stats = _get_green_score_stats(grid_path)

    # 3. Mode validation: ensure the payload mode matches the corridor config.
    payload_mode = gs_stats.get("payload_mode", corridor_cfg.mode)
    if payload_mode != corridor_cfg.mode:
        import warnings
        warnings.warn(
            f"[SatelliteAnalyst] Payload mode '{payload_mode}' does not match "
            f"corridor config mode '{corridor_cfg.mode}' for corridor "
            f"'{corridor_cfg.corridor_id}'. Using payload mode as authoritative.",
            stacklevel=2,
        )

    # 4. Build LLM
    llm = ChatAnthropic(
        model=settings.claude_agent_model,
        max_tokens=settings.claude_max_tokens,
        temperature=settings.claude_temperature,
        api_key=settings.anthropic_api_key,
    )

    # 5. Build the ReAct agent with all tools (mode-filtering handled inside each tool).
    #    All 10 tools are registered; each tool returns "N/A — not applicable for <mode>"
    #    when called for a mode it doesn't support, so the LLM learns to skip them.
    satellite_tools = [
        query_gee_no2,
        query_era5_wind,
        query_viirs_ships,
        query_so2_hotspots,
        # Aviation + trucking
        query_co,
        # Aviation only
        query_turbulence,
        query_contrail_risk,
        query_cloud_top_height,
        query_aerosol_index,
        query_aod,
    ]
    agent = create_react_agent(llm, satellite_tools)

    # 6. Build system prompt + initial task message.
    #    The system prompt is mode-aware (uses payload_mode from gs_stats).
    system_prompt = _build_system_prompt(state, corridor_cfg, grid_path, gs_stats)
    task_message = (
        f"Analyze the satellite environmental data for corridor '{state['corridor_id']}' "
        f"({payload_mode} mode). "
        f"Grid file: {grid_path}. "
        f"Follow the tool calling rules and output the final SatelliteReport JSON."
    )

    # 7. Run ReAct agent.
    #    recursion_limit ≈ 2 per tool call (LLM call + ToolNode call) + 2 buffer.
    #    Aviation needs up to 9 tool calls → limit 20; maritime/trucking up to 5 → limit 12.
    recursion_limit = 20 if payload_mode == "aviation" else 12

    result = agent.invoke(
        {
            "messages": [
                SystemMessage(content=system_prompt),
                HumanMessage(content=task_message),
            ]
        },
        config={"recursion_limit": recursion_limit},
    )

    # 8. Extract SatelliteReport from the last AI message.
    agent_messages = result.get("messages", [])
    satellite_report: SatelliteReport | None = None

    from langchain_core.messages import AIMessage
    for msg in reversed(agent_messages):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str) and msg.content.strip():
            raw_json = _extract_json_block(msg.content)
            if raw_json:
                satellite_report = _parse_report_from_raw(raw_json, state, corridor_cfg, grid_path, gs_stats)
                break

    if satellite_report is None:
        satellite_report = _build_fallback_report(state, corridor_cfg, grid_path, gs_stats)

    # 9. Serialise report and add `grid_path` alias.
    #    corridor_optimizer.py reads satellite_report.get("grid_path", "") to locate
    #    the grid file.  SatelliteReport stores this as `grid_snapshot`, so we inject
    #    the alias here to keep both consumers working without modifying either model.
    report_dict = satellite_report.model_dump(mode="json")
    report_dict["grid_path"] = grid_path          # alias for corridor_optimizer
    report_dict["payload_mode"] = payload_mode    # explicit mode from payload JSON

    return {
        "messages": agent_messages,
        "satellite_report": report_dict,
        "grid_snapshot_path": grid_path,
    }
