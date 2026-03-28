"""
corridor.py — Corridor API router.

POST /corridor/run
    Run the full multi-agent pipeline for a corridor.
    Returns GreenRouteDecision when the graph completes.

GET /corridor/status/{corridor_id}
    Return the last GreenRouteDecision for a corridor from baselines.json.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage

from app.agent.graph import graph
from app.models import (
    CorridorRunRequest,
    CorridorRunResponse,
    CorridorStatusResponse,
    GreenRouteDecision,
)
from app.services.baseline_service import load_baselines

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/corridor", tags=["corridor"])


@router.post("/run", response_model=CorridorRunResponse)
async def run_corridor(request: CorridorRunRequest) -> CorridorRunResponse:
    """
    Invoke the GreenRoute multi-agent pipeline.

    The pipeline runs synchronously (blocking).  For production use behind an
    async framework, wrap in a thread-pool executor.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    # Build initial AgentState
    initial_state: dict = {
        "messages": [
            HumanMessage(content=(
                f"Run corridor '{request.corridor_id}' "
                f"mode={[m.value for m in request.transport_modes]}"
            ))
        ],
        "corridor_id":     request.corridor_id,
        "transport_modes": [m.value for m in request.transport_modes],
        "triggered_by":    request.triggered_by.value,
        "vehicle_track":   (
            [p.model_dump() for p in request.vehicle_track]
            if request.vehicle_track else []
        ),
        "vehicle_id":      request.vehicle_id,
        "temporal_window": None,
        "grid_snapshot_path": None,
        "satellite_report":   None,
        "route_recommendation": None,
        "cert_decision":    None,
        "final_decision":   None,
        "pushed_to_firebase": False,
        "error":            None,
    }

    def _run():
        return graph.invoke(initial_state)

    try:
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            final_state = await loop.run_in_executor(pool, _run)
    except Exception as exc:
        logger.exception("Pipeline error for corridor %s", request.corridor_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    final_dict = final_state.get("final_decision")
    if final_dict is None:
        raise HTTPException(
            status_code=500,
            detail="Pipeline completed but produced no final_decision.",
        )

    try:
        decision = GreenRouteDecision.model_validate(final_dict)
    except Exception as exc:
        logger.error("Could not parse GreenRouteDecision: %s", exc)
        raise HTTPException(status_code=500, detail="Invalid pipeline output.") from exc

    return CorridorRunResponse(
        status="ok",
        corridor_id=request.corridor_id,
        decision=decision,
    )


@router.get("/status/{corridor_id}", response_model=CorridorStatusResponse)
async def corridor_status(corridor_id: str) -> CorridorStatusResponse:
    """
    Return basic status for a corridor (last badge + run timestamp from baselines.json).

    Does NOT re-run the pipeline.
    """
    import os
    baselines_path = os.getenv(
        "BASELINES_FILE",
        str(Path(__file__).resolve().parents[2] / "data" / "baselines.json"),
    )
    baselines = load_baselines(baselines_path)
    entry = baselines.get(corridor_id)

    if entry is None:
        # Unknown corridor — return empty status (200, not 404) so callers can
        # distinguish "never run" from "not found".
        return CorridorStatusResponse(corridor_id=corridor_id)

    # Reconstruct a minimal last_decision if audit_log has an entry
    last_decision = None
    audit_log = entry.get("audit_log") or []
    if audit_log:
        last_entry = audit_log[-1]
        last_run   = last_entry.get("timestamp")
        last_badge = last_entry.get("badge", "WARN")

        from datetime import datetime
        last_updated: datetime | None = None
        if last_run:
            try:
                last_updated = datetime.fromisoformat(last_run)
            except ValueError:
                pass

        return CorridorStatusResponse(
            corridor_id=corridor_id,
            last_updated=last_updated,
        )

    return CorridorStatusResponse(corridor_id=corridor_id)
