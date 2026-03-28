"""
AgentState — shared state flowing through the LangGraph graph.

Each agent reads what it needs and writes only its own output field.
The messages list is accumulated across all nodes via add_messages.
"""
from __future__ import annotations

from typing import Annotated, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    # ── LangGraph message history (accumulated across all nodes) ──────────────
    messages: Annotated[list[BaseMessage], add_messages]

    # ── Pipeline inputs (set once at graph entry, read by all nodes) ──────────
    corridor_id: str
    transport_modes: list[str]          # ["maritime"] | ["aviation"] | ["trucking"]
    triggered_by: str                   # "scheduler" | "new_data" | "voyage_completed"

    # Optional vehicle track for CertificationJudge
    vehicle_track: Optional[list[dict]] # AIS/ADS-B position records
    vehicle_id: Optional[str]           # IMO number (maritime) or ICAO hex (aviation)

    # ── Resolved at runtime by satellite_analyst_node ─────────────────────────
    grid_snapshot_path: str             # absolute path to the grid JSON file used

    # ── Agent outputs (set sequentially, read by downstream agents) ───────────
    satellite_report: Optional[dict]        # SatelliteReport  serialised to dict
    route_recommendation: Optional[dict]    # RouteRecommendation serialised to dict
    cert_decision: Optional[dict]           # CertDecision serialised to dict
    final_decision: Optional[dict]          # GreenRouteDecision serialised to dict

    # ── Persistence ───────────────────────────────────────────────────────────
    pushed_to_firebase: bool

    # ── Error propagation ─────────────────────────────────────────────────────
    error: Optional[str]
