"""
synthesize.py — Agent 4 (pure Python): Synthesize

No LLM calls.  Assembles the GreenRouteDecision from the three upstream agent
outputs, updates the corridor baseline, and pushes the result to Firebase.

Reads from AgentState:
  - satellite_report      : SatelliteReport dict  (from satellite_analyst)
  - route_recommendation  : RouteRecommendation dict  (from corridor_optimizer)
  - cert_decision         : CertDecision dict  (from certification_judge)
  - corridor_id           : str
  - triggered_by          : str

Writes to AgentState:
  - final_decision        : GreenRouteDecision dict
  - pushed_to_firebase    : bool

Final badge logic:
  - If cert_decision is present → use cert_decision["certificate"]
  - Else                        → use route_recommendation["badge"]
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models import Badge, GreenRouteDecision, TransportMode, TriggerReason

logger = logging.getLogger(__name__)

# Resolved at import time; node functions use it as a default.
_DEFAULT_BASELINES_FILE = os.getenv(
    "BASELINES_FILE",
    str(Path(__file__).resolve().parents[3] / "data" / "baselines.json"),
)


# ─────────────────────────────────────────────────────────────────────────────
# LangGraph node entry point
# ─────────────────────────────────────────────────────────────────────────────

def synthesize_node(state: dict) -> dict:
    """
    LangGraph node: Synthesize.

    Args:
        state: AgentState dict.  Must contain satellite_report and
               route_recommendation.  cert_decision is optional.

    Returns:
        Partial AgentState update:
            {
                "final_decision":    <GreenRouteDecision dict>,
                "pushed_to_firebase": bool,
            }
    """
    satellite_report: dict      = state.get("satellite_report") or {}
    route_recommendation: dict  = state.get("route_recommendation") or {}
    cert_decision_raw: dict | None = state.get("cert_decision")

    corridor_id: str  = (
        state.get("corridor_id")
        or satellite_report.get("corridor_id", "UNKNOWN")
    )
    triggered_by_raw: str = state.get("triggered_by", "scheduler")

    # ── Final badge / score ───────────────────────────────────────────────────
    final_badge_str, final_score = _derive_final_badge(
        satellite_report, route_recommendation, cert_decision_raw
    )

    # ── Consecutive WARN count from baseline ─────────────────────────────────
    from app.services.baseline_service import load_baselines, update_baselines, save_baselines

    baselines_path = _DEFAULT_BASELINES_FILE
    baselines = load_baselines(baselines_path)
    baselines = update_baselines(
        baselines,
        corridor_id,
        satellite_report,
        final_badge_str,
    )
    consecutive_warn: int = int(
        (baselines.get(corridor_id) or {}).get("consecutive_warn") or 0
    )
    save_baselines(baselines, baselines_path)

    # ── Build reasoning chain ─────────────────────────────────────────────────
    reasoning_chain = _build_reasoning_chain(
        satellite_report, route_recommendation, cert_decision_raw
    )

    # ── Assemble GreenRouteDecision ───────────────────────────────────────────
    transport_mode_str = (
        satellite_report.get("transport_mode")
        or (state.get("transport_modes") or ["maritime"])[0]
    )
    try:
        transport_mode = TransportMode(transport_mode_str)
    except ValueError:
        transport_mode = TransportMode.MARITIME

    try:
        triggered_by = TriggerReason(triggered_by_raw)
    except ValueError:
        triggered_by = TriggerReason.SCHEDULER

    try:
        final_badge = Badge(final_badge_str)
    except ValueError:
        final_badge = Badge.WARN

    # Re-hydrate sub-models from dicts (lightweight — no LLM schema validation)
    sat_model   = _dict_to_satellite_report(satellite_report)
    route_model = _dict_to_route_recommendation(route_recommendation)
    cert_model  = _dict_to_cert_decision(cert_decision_raw)

    decision = GreenRouteDecision(
        corridor_id=corridor_id,
        transport_mode=transport_mode,
        triggered_by=triggered_by,
        satellite_report=sat_model,
        route_recommendation=route_model,
        cert_decision=cert_model,
        final_badge=final_badge,
        final_score=float(final_score),
        reasoning_chain=reasoning_chain,
        baseline_updated=True,
        consecutive_warn_count=consecutive_warn,
    )

    # ── Push to Firebase ──────────────────────────────────────────────────────
    from app.services.firebase_service import push_decision
    from app.config import get_settings

    settings = get_settings()
    decision_dict = json.loads(decision.model_dump_json())

    firebase_path = push_decision(
        decision_dict,
        firebase_url=settings.firebase_url,
        credentials_file=settings.firebase_credentials_file,
    )
    pushed = firebase_path is not None
    if pushed:
        decision.pushed_to_firebase = True
        decision.firebase_path = firebase_path

    # Re-serialise after potential mutation
    final_dict = json.loads(decision.model_dump_json())

    logger.info(
        "synthesize_node complete — corridor=%s badge=%s firebase=%s",
        corridor_id, final_badge_str, firebase_path or "skipped",
    )

    return {
        "final_decision":     final_dict,
        "pushed_to_firebase": pushed,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _derive_final_badge(
    satellite_report: dict,
    route_recommendation: dict,
    cert_decision: dict | None,
) -> tuple[str, float]:
    """
    Return (badge_str, final_score).

    Priority:
      1. cert_decision["certificate"]  (vehicle-level certification)
      2. route_recommendation["badge"] (corridor-level optimiser assessment)
      3. satellite_report["badge"]     (environmental quality only)
      4. "WARN"                        (fallback)
    """
    score = float(route_recommendation.get("optimal_green_score") or 50.0)

    if cert_decision:
        badge = str(cert_decision.get("certificate") or "WARN").upper()
        return badge, score

    badge = str(
        route_recommendation.get("badge")
        or satellite_report.get("badge")
        or "WARN"
    ).upper()
    return badge, score


def _build_reasoning_chain(
    satellite_report: dict,
    route_recommendation: dict,
    cert_decision: dict | None,
) -> list[str]:
    """Collect non-empty reasoning strings from all three agents."""
    chain: list[str] = []

    for label, source in [
        ("SatelliteAnalyst",   satellite_report),
        ("CorridorOptimizer",  route_recommendation),
        ("CertificationJudge", cert_decision or {}),
    ]:
        reasoning = (source.get("reasoning") or "").strip()
        if reasoning:
            chain.append(f"[{label}] {reasoning}")

    return chain


# ─────────────────────────────────────────────────────────────────────────────
# Lightweight re-hydration helpers (dict → Pydantic model)
# These exist because the upstream nodes serialise to plain dicts.
# We use model_validate with from_attributes=False for robustness.
# ─────────────────────────────────────────────────────────────────────────────

def _dict_to_satellite_report(d: dict) -> Any:
    from app.models import SatelliteReport
    try:
        return SatelliteReport.model_validate(d)
    except Exception:                                       # noqa: BLE001
        return SatelliteReport(
            corridor_id=d.get("corridor_id", "UNKNOWN"),
            transport_mode=d.get("transport_mode", "maritime"),
            overall_score=float(d.get("overall_score") or 50.0),
            badge=d.get("badge", "WARN"),
        )


def _dict_to_route_recommendation(d: dict) -> Any:
    from app.models import RouteRecommendation
    try:
        return RouteRecommendation.model_validate(d)
    except Exception:                                       # noqa: BLE001
        return RouteRecommendation(
            corridor_id=d.get("corridor_id", "UNKNOWN"),
            transport_mode=d.get("transport_mode", "maritime"),
            optimal_green_score=float(d.get("optimal_green_score") or 50.0),
            badge=d.get("badge", "WARN"),
            path_cells=[],
            path_length_cells=0,
            distance_km=0.0,
            baseline_score=float(d.get("baseline_score") or 50.0),
            improvement_vs_baseline_pct=float(
                d.get("improvement_vs_baseline_pct") or 0.0
            ),
            mandatory_waypoints_validated=[],
        )


def _dict_to_cert_decision(d: dict | None) -> Any | None:
    if not d:
        return None
    from app.models import CertDecision
    try:
        return CertDecision.model_validate(d)
    except Exception:                                       # noqa: BLE001
        return CertDecision(
            corridor_id=d.get("corridor_id", "UNKNOWN"),
            transport_mode=d.get("transport_mode", "maritime"),
            certificate=d.get("certificate", "WARN"),
            confidence_pct=float(d.get("confidence_pct") or 50.0),
            track_compliance_pct=float(d.get("track_compliance_pct") or 0.0),
            waypoints_verified=d.get("waypoints_verified") or [],
        )
