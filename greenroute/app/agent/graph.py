"""
graph.py — LangGraph StateGraph orchestrator for GreenRoute.

Full pipeline (Phase 4):
    START → satellite_analyst → corridor_optimizer → certification_judge → synthesize → END

The orchestrator is a pure Python coordinator — it does NOT call any LLM directly.
All domain logic lives in the agent nodes.

Data flow between nodes
───────────────────────
satellite_analyst_node writes to AgentState:
  • satellite_report      — SatelliteReport dict, includes keys:
        "corridor_id", "transport_mode", "overall_score", "badge",
        "grid_snapshot" (path), "grid_path" (alias consumed by corridor_optimizer),
        "payload_mode"  (mode read from the grid JSON — authoritative for routing)
  • grid_snapshot_path    — absolute path to the grid JSON used
  • messages              — accumulated LangGraph message history

run_corridor_optimizer writes to AgentState:
  • route_recommendation  — RouteRecommendation dict, includes keys:
        "corridor_id", "transport_mode", "optimal_green_score", "baseline_green_score",
        "green_score_vs_baseline_pct", "optimal_path_cells", "optimal_path_distance_km",
        "chokepoints_on_path", "feasibility_flag", "optimizer_notes"

certification_judge_node writes to AgentState:
  • cert_decision         — CertDecision dict with certificate (GREEN/WARN/RED)

synthesize_node writes to AgentState:
  • final_decision        — GreenRouteDecision dict (full pipeline output)
  • pushed_to_firebase    — bool
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agent.nodes.satellite_analyst import satellite_analyst_node
from app.agent.nodes.corridor_optimizer import run_corridor_optimizer
from app.agent.nodes.certification_judge import certification_judge_node
from app.agent.nodes.synthesize import synthesize_node
from app.agent.state import AgentState


def build_graph():
    """
    Build and compile the GreenRoute multi-agent graph.

    Phase 4: satellite_analyst → corridor_optimizer → certification_judge → synthesize.
    """
    builder = StateGraph(AgentState)

    # ── Agent nodes ──────────────────────────────────────────────────────────
    builder.add_node("satellite_analyst",   satellite_analyst_node)
    builder.add_node("corridor_optimizer",  run_corridor_optimizer)
    builder.add_node("certification_judge", certification_judge_node)
    builder.add_node("synthesize",          synthesize_node)

    # ── Edges ─────────────────────────────────────────────────────────────────
    builder.add_edge(START,                  "satellite_analyst")
    builder.add_edge("satellite_analyst",    "corridor_optimizer")
    builder.add_edge("corridor_optimizer",   "certification_judge")
    builder.add_edge("certification_judge",  "synthesize")
    builder.add_edge("synthesize",           END)

    return builder.compile()


# Module-level compiled graph instance (imported by FastAPI and test scripts)
graph = build_graph()
