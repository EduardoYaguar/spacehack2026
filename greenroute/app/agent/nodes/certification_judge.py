"""
certification_judge.py — Agent 3: CertificationJudge

ReAct loop (max 4 tool calls) that certifies whether a vehicle followed the
greenest route recommended by the CorridorOptimizer, and issues a GREEN /
WARN / RED certificate.

Reads from AgentState:
  - satellite_report      : SatelliteReport dict (from SatelliteAnalyst)
  - route_recommendation  : RouteRecommendation dict (from CorridorOptimizer)
  - vehicle_track         : list[dict] AIS/ADS-B positions, or None
  - vehicle_id            : str | None

Writes to AgentState:
  - cert_decision         : CertDecision dict

Certification context (two modes):
  voyage_completed  —  A vehicle finished a voyage. The judge checks whether
                       its AIS/ADS-B track complied with the optimal route.
                       Tools are called with the real vehicle_track.

  scheduler / new_data — No vehicle track is provided. The judge evaluates
                         the corridor's current environmental quality and issues
                         a corridor-level certificate (not vehicle-specific).
                         Tools are called with vehicle_track = [].

Tool call order (max 4 calls total):
  1. ALWAYS call check_track_compliance first.
     - Pass grid_path and corridor_id from satellite_report.
     - Pass vehicle_track ([] if no vehicle).
     - Pass optimal_green_score from route_recommendation.
  2. ALWAYS call verify_waypoint_passage.
     - Pass corridor_id and vehicle_track ([] if no vehicle).
  3-4. Optional: use remaining budget for follow-up if compliance is
       borderline (70-85%) or waypoints are ambiguous.
  Final: return CertDecision JSON. Stop.

Decision rules applied by the LLM:
  GREEN  : compliance_pct >= 85% AND all mandatory waypoints confirmed
           AND route_recommendation.optimal_green_score >= 45
  WARN   : compliance_pct >= 70% OR optimal_green_score in [45, 65)
           OR satellite_report contains WARN anomalies
  RED    : compliance_pct < 70% OR critical waypoints missed
           OR optimal_green_score < 45 AND no confound explanation
  NO_TRACK (scheduler): inherit badge from route_recommendation score;
           set track_compliance_pct = 0, waypoints_verified = []
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import anthropic

from app.agent.tools.judge_tools import (
    check_track_compliance,
    verify_waypoint_passage,
)

# ---------------------------------------------------------------------------
# Model and limits
# ---------------------------------------------------------------------------
_MODEL          = os.getenv("CLAUDE_AGENT_MODEL", "claude-haiku-4-5")
_MAX_TOKENS     = int(os.getenv("CLAUDE_MAX_TOKENS", "4096"))
_MAX_TOOL_CALLS = 4

# ---------------------------------------------------------------------------
# Tool schemas  (Anthropic API format)
# ---------------------------------------------------------------------------
_TOOLS: list[dict] = [
    {
        "name": "check_track_compliance",
        "description": (
            "Compare a vehicle's AIS/ADS-B track against the corridor spine "
            "(origin → mandatory waypoints → destination) and the pre-computed "
            "green_score layer in the grid JSON.\n\n"
            "Returns compliance_pct (% of track within tolerance), "
            "deviation_mean_km, track_mean_green_score, green_score_delta "
            "(track vs optimal), track_on_navigable_pct, and verdict "
            "(COMPLIANT / PARTIAL / NON_COMPLIANT / NO_TRACK).\n\n"
            "Pass vehicle_track=[] when no track is available (scheduler mode). "
            "Pass tolerance_km=0 to use the mode-appropriate default "
            "(maritime 55 km, aviation 1 200 km, trucking 75 km)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "grid_path": {
                    "type": "string",
                    "description": (
                        "Absolute path to the satellite grid JSON file. "
                        "Read from satellite_report['grid_path']."
                    ),
                },
                "corridor_id": {
                    "type": "string",
                    "description": "One of 'SGP_PKL', 'PVG_DXB_AMS', 'NYNJ_SAV'.",
                },
                "vehicle_track": {
                    "type": "array",
                    "description": (
                        "List of position records, each with at least 'lat' and 'lon' keys. "
                        "Pass [] for scheduler/new_data triggers (no vehicle to certify)."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "lat": {"type": "number"},
                            "lon": {"type": "number"},
                        },
                    },
                },
                "optimal_green_score": {
                    "type": "number",
                    "description": (
                        "The optimal green_score from route_recommendation "
                        "(float 0-100). Used to compute green_score_delta."
                    ),
                },
                "tolerance_km": {
                    "type": "number",
                    "description": (
                        "Cross-track tolerance in km. Pass 0 to use the "
                        "mode-specific default."
                    ),
                },
            },
            "required": ["grid_path", "corridor_id", "vehicle_track",
                         "optimal_green_score"],
        },
    },
    {
        "name": "verify_waypoint_passage",
        "description": (
            "Check whether a vehicle passed through all mandatory waypoints "
            "for the corridor.\n\n"
            "Mandatory waypoints:\n"
            "  SGP_PKL     : One Fathom Bank + Raffles Lighthouse TSS\n"
            "  PVG_DXB_AMS : Dubai Intl (DXB)\n"
            "  NYNJ_SAV    : none\n\n"
            "Returns waypoints_confirmed, waypoints_missed, all_waypoints_confirmed, "
            "and per-waypoint closest approach distance.\n\n"
            "Pass vehicle_track=[] for scheduler/new_data triggers. "
            "Pass passage_radius_km=0 to use the mode-specific default."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "corridor_id": {
                    "type": "string",
                    "description": "One of 'SGP_PKL', 'PVG_DXB_AMS', 'NYNJ_SAV'.",
                },
                "vehicle_track": {
                    "type": "array",
                    "description": (
                        "List of position records with 'lat' and 'lon' keys. "
                        "Pass [] when no track is available."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "lat": {"type": "number"},
                            "lon": {"type": "number"},
                        },
                    },
                },
                "passage_radius_km": {
                    "type": "number",
                    "description": (
                        "Radius in km to consider a waypoint 'passed'. "
                        "Pass 0 to use the mode-specific default."
                    ),
                },
            },
            "required": ["corridor_id", "vehicle_track"],
        },
    },
]

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """\
You are the CertificationJudge, Agent 3 in the GreenRoute Intelligence Platform.

Your task: certify whether the route recommended by the CorridorOptimizer \
is environmentally sound, and — when a vehicle track is available — whether \
the vehicle followed it. Issue a GREEN / WARN / RED certificate.

You receive three data sources:
  satellite_report      — environmental conditions from SatelliteAnalyst
  route_recommendation  — greenest A* route from CorridorOptimizer
                          (optimal_green_score, chokepoints_on_path,
                          feasibility_flag, optimizer_notes)
  vehicle_track         — AIS/ADS-B positions ([] when no vehicle)

## Strict tool call order (max {max_calls} calls total)

1. ALWAYS call check_track_compliance first.
   - grid_path           : satellite_report["grid_path"]
   - corridor_id         : from satellite_report or route_recommendation
   - vehicle_track       : pass the vehicle track as-is ([] if none)
   - optimal_green_score : route_recommendation["optimal_green_score"]
   - tolerance_km        : 0  (use mode default)

2. ALWAYS call verify_waypoint_passage.
   - corridor_id         : same corridor_id
   - vehicle_track       : same track ([] if none)
   - passage_radius_km   : 0  (use mode default)

3-4. Optional: use remaining budget only if compliance is borderline or
     waypoints result is ambiguous. Do NOT repeat a call without new inputs.

5. Return the CertDecision JSON in your final text reply. Stop.

## Decision rules

NO VEHICLE TRACK (check_track_compliance returns verdict="NO_TRACK"):
  Inherit certificate from route_recommendation optimal_green_score:
    >= 65  →  GREEN
    45-64  →  WARN
    < 45   →  RED
  Set track_compliance_pct = 0, waypoints_verified = [].
  reasoning must explain this is a corridor-level assessment.

WITH VEHICLE TRACK:
  Step 1 — base certificate from compliance_pct:
    >= 85 %  →  GREEN
    70-84 %  →  WARN
    < 70 %   →  RED

  Step 2 — downgrade if mandatory waypoints missed:
    Any waypoint missed  →  drop one level (GREEN→WARN, WARN→RED, RED stays)

  Step 3 — apply environmental context:
    satellite_report badge RED + no confound  →  floor certificate at WARN
    satellite_report aerosol_dxb_alert = true →  add aerosol_advisory
    satellite_report weather_hazard = true     →  add weather_advisory
    Aviation WARN score 45-55 in Dec-Mar       →  seasonal_context_applied=true,
    do NOT escalate to RED.

  confidence_pct:
    Start at 95. Subtract 5 per missed waypoint. Subtract 10 for borderline
    compliance (70-85 %). Subtract 10 if satellite data_quality is not 'good'.
    Minimum 30.

## CertDecision JSON format (return exactly this structure)

```json
{{
  "corridor_id": "<corridor_id>",
  "transport_mode": "<maritime|aviation|trucking>",
  "vehicle_id": "<vehicle_id or null>",
  "certificate": "<GREEN|WARN|RED>",
  "confidence_pct": <float 0-100>,
  "track_compliance_pct": <float 0-100>,
  "waypoints_verified": [<strings>],
  "waypoints_missed": [<strings>],
  "seasonal_context_applied": <bool>,
  "weather_advisory": "<string or null>",
  "aerosol_advisory": "<string or null>",
  "reasoning": "<2-3 sentences citing compliance_pct and at least one other metric>"
}}
```

## Rules

- Do NOT invent tool results. Only use what the tools return.
- reasoning MUST cite compliance_pct and at least one other metric
  (green_score_delta, deviation_mean_km, or waypoint passage result).
- If you exhaust tool calls before finishing, return the best partial
  CertDecision with confidence_pct = 40 and reasoning explaining the gap.
""".format(max_calls=_MAX_TOOL_CALLS)

# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------
_TOOL_FN_MAP = {
    "check_track_compliance":  check_track_compliance,
    "verify_waypoint_passage": verify_waypoint_passage,
}


def _dispatch(tool_name: str, tool_input: dict) -> str:
    """Invoke the Python tool and return its result as a JSON string."""
    fn = _TOOL_FN_MAP.get(tool_name)
    if fn is None:
        return json.dumps({"status": "error",
                           "message": f"Unknown tool: {tool_name}"})
    try:
        # judge_tools are @tool-decorated — .invoke() is the safe call API
        result = fn.invoke(tool_input)
    except Exception as exc:          # noqa: BLE001
        result = {"status": "error", "message": str(exc)}
    return json.dumps(result)


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

def _extract_cert_decision(text: str) -> dict | None:
    """
    Extract the CertDecision JSON block from the agent's final text.
    Tries a fenced ```json block first, then a bare object containing
    "certificate".
    """
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

    bare = re.search(r'(\{[^{}]*"certificate"[^{}]*\})', text, re.DOTALL)
    if bare:
        try:
            return json.loads(bare.group(1))
        except json.JSONDecodeError:
            pass

    return None


# ---------------------------------------------------------------------------
# Fallback CertDecision
# ---------------------------------------------------------------------------

def _fallback_cert_decision(
    state: dict,
    satellite_report: dict,
    route_recommendation: dict,
) -> dict:
    """Minimal CertDecision when the agent's JSON cannot be parsed."""
    score    = float(route_recommendation.get("optimal_green_score") or 50.0)
    corridor = (state.get("corridor_id")
                or satellite_report.get("corridor_id", "UNKNOWN"))
    mode     = (satellite_report.get("transport_mode")
                or (state.get("transport_modes") or ["maritime"])[0])

    if score >= 65:
        cert = "GREEN"
    elif score >= 45:
        cert = "WARN"
    else:
        cert = "RED"

    return {
        "corridor_id":              corridor,
        "transport_mode":           mode,
        "vehicle_id":               state.get("vehicle_id"),
        "certificate":              cert,
        "confidence_pct":           40.0,
        "track_compliance_pct":     0.0,
        "waypoints_verified":       [],
        "waypoints_missed":         [],
        "seasonal_context_applied": False,
        "weather_advisory":         None,
        "aerosol_advisory":         None,
        "reasoning": (
            f"Fallback — agent JSON could not be parsed. "
            f"Certificate inherited from optimal_green_score={score:.1f}."
        ),
    }


# ---------------------------------------------------------------------------
# Main entry point (LangGraph node)
# ---------------------------------------------------------------------------

def certification_judge_node(state: dict) -> dict:
    """
    LangGraph node: CertificationJudge.

    Reads satellite_report, route_recommendation, and vehicle_track from
    AgentState, runs a ReAct loop (max 4 tool calls), and writes cert_decision.

    Args:
        state : AgentState dict. Must contain satellite_report and
                route_recommendation from upstream nodes.

    Returns:
        Partial AgentState update: {"cert_decision": <CertDecision dict>}
    """
    satellite_report: dict     = state.get("satellite_report") or {}
    route_recommendation: dict = state.get("route_recommendation") or {}
    vehicle_track: list        = state.get("vehicle_track") or []
    vehicle_id:    str | None  = state.get("vehicle_id")
    corridor_id:   str         = (
        state.get("corridor_id")
        or satellite_report.get("corridor_id", "SGP_PKL")
    )
    triggered_by: str = state.get("triggered_by", "scheduler")

    # Grid path for check_track_compliance (injected by satellite_analyst_node)
    grid_path: str = (
        satellite_report.get("grid_path")
        or satellite_report.get("grid_snapshot")
        or state.get("grid_snapshot_path", "")
    )

    # ── Build initial user message ───────────────────────────────────────────
    has_track    = bool(vehicle_track)
    track_desc   = (
        f"{len(vehicle_track)} AIS/ADS-B positions"
        if has_track
        else "no vehicle track (corridor-level assessment)"
    )

    # Truncate vehicle_track in the prompt: pass all points to tools,
    # but show only the first 5 in the context summary.
    track_preview = json.dumps(vehicle_track[:5], indent=2)
    if len(vehicle_track) > 5:
        track_preview += f"\n  ... ({len(vehicle_track) - 5} more points omitted)"

    user_content = (
        f"Certify corridor '{corridor_id}' based on the outputs below.\n\n"
        f"Trigger      : {triggered_by}\n"
        f"Vehicle ID   : {vehicle_id or 'N/A'}\n"
        f"Vehicle track: {track_desc}\n\n"
        f"═══ Satellite Report (SatelliteAnalyst output) ═══\n"
        f"{json.dumps(satellite_report, indent=2, default=str)}\n\n"
        f"═══ Route Recommendation (CorridorOptimizer output) ═══\n"
        f"{json.dumps(route_recommendation, indent=2, default=str)}\n\n"
        f"═══ Vehicle Track preview ═══\n"
        f"{track_preview}\n\n"
        "Follow the tool call rules in the system prompt. "
        "Return the CertDecision JSON when done."
    )

    messages: list[dict] = [{"role": "user", "content": user_content}]
    client          = anthropic.Anthropic()
    tool_call_count = 0
    cert_decision: dict | None = None

    # ── ReAct loop ───────────────────────────────────────────────────────────
    while True:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            tools=_TOOLS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        # End turn: extract final answer
        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    cert_decision = _extract_cert_decision(block.text)
                    break
            break

        # Tool use
        if response.stop_reason == "tool_use":
            tool_results: list[dict[str, Any]] = []

            for block in response.content:
                if block.type != "tool_use":
                    continue

                if tool_call_count >= _MAX_TOOL_CALLS:
                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps({
                            "status":  "limit_reached",
                            "message": (
                                f"Maximum {_MAX_TOOL_CALLS} tool calls reached. "
                                "Return your best CertDecision JSON now."
                            ),
                        }),
                    })
                else:
                    result_str = _dispatch(block.name, block.input)
                    tool_call_count += 1
                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     result_str,
                    })

            messages.append({"role": "user", "content": tool_results})

            # Budget exhausted — force final answer
            if tool_call_count >= _MAX_TOOL_CALLS:
                final = client.messages.create(
                    model=_MODEL,
                    max_tokens=_MAX_TOKENS,
                    system=_SYSTEM_PROMPT,
                    tools=_TOOLS,
                    messages=messages,
                )
                messages.append({"role": "assistant", "content": final.content})
                for block in final.content:
                    if hasattr(block, "text"):
                        cert_decision = _extract_cert_decision(block.text)
                        break
                break

        else:
            # Unexpected stop reason
            break

    # ── Resolve result ───────────────────────────────────────────────────────
    if cert_decision is None:
        cert_decision = _fallback_cert_decision(
            state, satellite_report, route_recommendation
        )

    # Guarantee all required fields are present
    cert_decision.setdefault("corridor_id",              corridor_id)
    cert_decision.setdefault(
        "transport_mode",
        satellite_report.get("transport_mode",
            (state.get("transport_modes") or ["maritime"])[0]),
    )
    cert_decision.setdefault("vehicle_id",               vehicle_id)
    cert_decision.setdefault("waypoints_verified",       [])
    cert_decision.setdefault("waypoints_missed",         [])
    cert_decision.setdefault("seasonal_context_applied", False)
    cert_decision.setdefault("weather_advisory",         None)
    cert_decision.setdefault("aerosol_advisory",         None)
    cert_decision.setdefault("confidence_pct",           50.0)
    cert_decision.setdefault("track_compliance_pct",     0.0)
    cert_decision.setdefault("reasoning",                "")

    return {"cert_decision": cert_decision}
