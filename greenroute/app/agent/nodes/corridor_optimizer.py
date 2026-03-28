"""
corridor_optimizer.py — Agent 3: CorridorOptimizer

ReAct loop (max 5 tool calls) that finds the greenest route through the
satellite grid and returns a RouteRecommendation JSON.

The decisive metric is green_score (0-100, higher = greener), a composite
already computed by the data pipeline from NO2, SO2, wind, wave, and VIIRS.
A* minimises cost = 100 - green_score. Individual layer values are
informational context only.

Reads from AgentState:
  - satellite_report  : produced by SatelliteAnalyst (must include grid_path)
  - cert_decision     : produced by CertificationJudge

Writes to AgentState:
  - route_recommendation : RouteRecommendation dict

Tool call rules:
  1. Always call build_graph first.
  2. Call run_astar — path MUST pass through all mandatory waypoints.
  3. If waypoints_missed is non-empty → call build_graph with forced_waypoints,
     then run_astar again. (counts as 2 more tool calls)
  4. Call score_path to get the final green score and comparison vs baseline.
  5. Return RouteRecommendation JSON. Stop.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

import anthropic

from app.agent.tools.optimizer_tools import (
    build_graph,
    run_astar,
    score_path,
)

# ---------------------------------------------------------------------------
# Model and limits
# ---------------------------------------------------------------------------
_MODEL = os.getenv("CLAUDE_AGENT_MODEL", "claude-haiku-4-5")
_MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS", "4096"))
_MAX_TOOL_CALLS = 5

# ---------------------------------------------------------------------------
# Tool schemas for the Anthropic API
# ---------------------------------------------------------------------------
_TOOLS: list[dict] = [
    {
        "name": "build_graph",
        "description": (
            "Build the navigable NetworkX DiGraph from a GEE grid JSON snapshot. "
            "Must be called first in every run. Reads mode, weights, and navigability "
            "from the file itself — works for maritime, aviation, and land grids. "
            "Pass forced_waypoints only when a previous run_astar call returned "
            "waypoints_missed; this rebuilds the graph with those points guaranteed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "grid_path": {
                    "type": "string",
                    "description": (
                        "Path to the GEE grid JSON file "
                        "(e.g. 'latest/maritime_portklang_singapore.json')."
                    ),
                },
                "forced_waypoints": {
                    "type": "array",
                    "description": (
                        "Optional. Override default waypoints for this mode. "
                        "Each item: {\"name\": str, \"lat\": float, \"lon\": float}."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "lat":  {"type": "number"},
                            "lon":  {"type": "number"},
                        },
                        "required": ["name", "lat", "lon"],
                    },
                },
            },
            "required": ["grid_path"],
        },
    },
    {
        "name": "run_astar",
        "description": (
            "Run segmented A* on the graph built by build_graph. "
            "Route: origin → mandatory waypoints (in order) → destination. "
            "A* cost is driven by green_score (cost = 100 - green_score). "
            "Heuristic: haversine distance (admissible). "
            "Check waypoints_missed — if non-empty, call build_graph with "
            "forced_waypoints and run_astar again before calling score_path."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "forced_waypoints": {
                    "type": "array",
                    "description": (
                        "Optional. Override default waypoints. "
                        "Use only when retrying after waypoints_missed. "
                        "Each item: {\"name\": str, \"lat\": float, \"lon\": float}."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "lat":  {"type": "number"},
                            "lon":  {"type": "number"},
                        },
                        "required": ["name", "lat", "lon"],
                    },
                },
            },
        },
    },
    {
        "name": "score_path",
        "description": (
            "Score the A* path using green_score as the decisive metric. "
            "Returns optimal_green_score, baseline_green_score, "
            "green_score_vs_baseline_pct, chokepoints_on_path, feasibility_flag, "
            "badge distribution (green/warn/red cells), and individual layer means "
            "as informational context. "
            "Call this after a successful run_astar with waypoints_missed empty."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """You are the CorridorOptimizer, Agent 3 in the GreenRoute pipeline.

Your task: find the greenest route through the satellite grid using A* and
return a RouteRecommendation JSON.

The decisive metric is green_score (0-100, higher = greener). It is a
composite already computed from NO2, SO2, wind, wave height, and VIIRS traffic.
A* minimises cost = 100 - green_score. You do not reason about individual
layers — green_score is the single source of truth for path quality.

## Strict tool call order (max {max_calls} calls total)

1. ALWAYS call build_graph first — pass the grid_path from the satellite_report.
2. Call run_astar — the path MUST hit all mandatory waypoints.
3. If run_astar returns waypoints_missed (non-empty list):
   - Call build_graph again with forced_waypoints set to the missed waypoints.
   - Call run_astar again.
   (This retry uses 2 additional tool calls — budget accordingly.)
4. Call score_path — only after a successful run_astar with waypoints_missed empty.
5. Return the RouteRecommendation JSON in your final text reply. Stop.

## RouteRecommendation JSON format (return exactly this structure)

```json
{{
  "corridor_id": "<from satellite_report>",
  "optimization_timestamp": "<ISO-8601 UTC>",
  "transport_mode": "<mode from grid>",
  "optimal_green_score": <float 0-100>,
  "baseline_green_score": <float 0-100>,
  "green_score_vs_baseline_pct": <float>,
  "optimal_path_cells": <int>,
  "optimal_path_distance_km": <float>,
  "chokepoints_on_path": [<strings>],
  "feasibility_flag": <bool>,
  "optimizer_notes": "<one-sentence summary>"
}}
```

## Rules

- Do NOT skip build_graph, even if a graph was built in a previous run.
- Do NOT call score_path if waypoints_missed is non-empty.
- optimizer_notes must state whether all waypoints were hit and the
  green_score-driven reason for the chosen path.
- If you exhaust tool calls before finishing, return the best partial
  RouteRecommendation with feasibility_flag = false.
""".format(max_calls=_MAX_TOOL_CALLS)

# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------
_TOOL_FN_MAP = {
    "build_graph": build_graph,
    "run_astar":   run_astar,
    "score_path":  score_path,
}


def _dispatch(tool_name: str, tool_input: dict) -> str:
    """Call the Python tool function and return its result as a JSON string."""
    fn = _TOOL_FN_MAP.get(tool_name)
    if fn is None:
        return json.dumps({"status": "error", "message": f"Unknown tool: {tool_name}"})
    try:
        result = fn(**tool_input)
    except Exception as exc:  # noqa: BLE001
        result = {"status": "error", "message": str(exc)}
    return json.dumps(result)


# ---------------------------------------------------------------------------
# JSON extraction from final LLM text
# ---------------------------------------------------------------------------
def _extract_route_recommendation(text: str) -> dict | None:
    """
    Pull the RouteRecommendation JSON block from the agent's final text reply.
    Tries a fenced code block first, then a bare JSON object.
    """
    # Fenced block: ```json ... ```
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

    # Bare JSON object (first { … } with "corridor_id")
    bare = re.search(r'(\{[^{}]*"corridor_id"[^{}]*\})', text, re.DOTALL)
    if bare:
        try:
            return json.loads(bare.group(1))
        except json.JSONDecodeError:
            pass

    return None


# ---------------------------------------------------------------------------
# Fallback RouteRecommendation (when agent exhausts tool calls)
# ---------------------------------------------------------------------------
def _fallback_recommendation(state: dict) -> dict:
    return {
        "corridor_id":                  state.get("corridor_id", "UNKNOWN"),
        "optimization_timestamp":       datetime.now(timezone.utc).isoformat(),
        "transport_mode":               (state.get("transport_modes") or ["maritime"])[0],
        "optimal_green_score":          0.0,
        "baseline_green_score":         0.0,
        "green_score_vs_baseline_pct":  0.0,
        "optimal_path_cells":           0,
        "optimal_path_distance_km":     0.0,
        "chokepoints_on_path":          [],
        "feasibility_flag":             False,
        "optimizer_notes":              "Fallback — optimizer exhausted tool call budget.",
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def run_corridor_optimizer(state: dict) -> dict:
    """
    Execute the CorridorOptimizer ReAct loop.

    Args:
        state : AgentState dict. Must contain:
                  - satellite_report (dict) with at least 'grid_path' and 'corridor_id'
                  - cert_decision    (dict)

    Returns:
        Partial AgentState update: {"route_recommendation": <RouteRecommendation dict>}
    """
    satellite_report: dict = state.get("satellite_report") or {}
    cert_decision: dict    = state.get("cert_decision") or {}

    grid_path = satellite_report.get("grid_path", "")
    corridor_id = state.get("corridor_id", satellite_report.get("corridor_id", "SGP_PKL"))
    transport_modes: list[str] = state.get("transport_modes", ["maritime"])

    # Build the initial user message with all relevant context
    user_content = (
        f"Optimize the carbon route for corridor '{corridor_id}'.\n\n"
        f"Grid file path: {grid_path}\n\n"
        f"Transport modes requested: {', '.join(transport_modes)}\n\n"
        f"Satellite report summary:\n{json.dumps(satellite_report, indent=2)}\n\n"
        f"Certification decision:\n{json.dumps(cert_decision, indent=2)}\n\n"
        "Follow your tool call rules exactly. Return the RouteRecommendation JSON."
    )

    messages: list[dict] = [{"role": "user", "content": user_content}]
    client = anthropic.Anthropic()
    tool_call_count = 0
    route_recommendation: dict | None = None

    # -----------------------------------------------------------------------
    # ReAct loop
    # -----------------------------------------------------------------------
    while True:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            tools=_TOOLS,
            messages=messages,
        )

        # Append assistant turn
        messages.append({"role": "assistant", "content": response.content})

        # --- End turn: extract final answer ---
        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    route_recommendation = _extract_route_recommendation(block.text)
                    break
            break

        # --- Tool use ---
        if response.stop_reason == "tool_use":
            tool_results: list[dict[str, Any]] = []

            for block in response.content:
                if block.type != "tool_use":
                    continue

                if tool_call_count >= _MAX_TOOL_CALLS:
                    # Budget exhausted — tell the model to answer now
                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     json.dumps({
                            "status":  "limit_reached",
                            "message": (
                                f"Maximum {_MAX_TOOL_CALLS} tool calls reached. "
                                "Return your best RouteRecommendation JSON now."
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

            # If budget is now exhausted, force a final answer on the next call
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
                        route_recommendation = _extract_route_recommendation(block.text)
                        break
                break

        else:
            # Unexpected stop reason — exit loop
            break

    # -----------------------------------------------------------------------
    # Build final output
    # -----------------------------------------------------------------------
    if route_recommendation is None:
        route_recommendation = _fallback_recommendation(state)

    # Guarantee required fields exist
    route_recommendation.setdefault("corridor_id", corridor_id)
    route_recommendation.setdefault(
        "optimization_timestamp", datetime.now(timezone.utc).isoformat()
    )
    route_recommendation.setdefault(
        "transport_mode", transport_modes[0] if transport_modes else "maritime"
    )

    return {"route_recommendation": route_recommendation}
