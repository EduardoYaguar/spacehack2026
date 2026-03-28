"""
run_pipeline.py — CLI entry point for the full GreenRoute multi-agent pipeline.

Runs the complete orchestration:
    SatelliteAnalyst → CorridorOptimizer → CertificationJudge → synthesize

No API server required.  Reads ANTHROPIC_API_KEY from greenroute/.env automatically.

Usage (run from workspace root: spacehack2026/):

    # Maritime — corridor-level assessment
    python greenroute/scripts/run_pipeline.py

    # Maritime — specify corridor and trigger
    python greenroute/scripts/run_pipeline.py --corridor SGP_PKL --trigger new_data

    # Aviation
    python greenroute/scripts/run_pipeline.py --corridor PVG_DXB_AMS

    # Trucking
    python greenroute/scripts/run_pipeline.py --corridor NYNJ_SAV

    # Specific temporal window
    python greenroute/scripts/run_pipeline.py --corridor PVG_DXB_AMS --window P2

    # Certify a vehicle (voyage_completed trigger)
    python greenroute/scripts/run_pipeline.py --corridor SGP_PKL --trigger voyage_completed \\
        --vehicle-id IMO9876543

    # Dry run — skip LLM calls, just validate graph wiring
    python greenroute/scripts/run_pipeline.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# ── Path setup ───────────────────────────────────────────────────────────────
# Make greenroute/ importable when running from workspace root
_WORKSPACE = Path(__file__).resolve().parents[2]   # spacehack2026/
_GREENROUTE = _WORKSPACE / "greenroute"
sys.path.insert(0, str(_GREENROUTE))

# ── Load .env before any app imports ─────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(_GREENROUTE / ".env")

# ── Validate API key early ────────────────────────────────────────────────────
if not os.getenv("ANTHROPIC_API_KEY") and "--dry-run" not in sys.argv:
    print("\n[ERROR] ANTHROPIC_API_KEY is not set.")
    print(f"  Create {_GREENROUTE / '.env'} from the template:")
    print(f"  cp {_GREENROUTE / '.env.template'} {_GREENROUTE / '.env'}")
    print("  Then fill in your key.\n")
    sys.exit(1)

# ── App imports (after path + env setup) ─────────────────────────────────────
from langchain_core.messages import HumanMessage

from app.agent.payload_registry import get_mode, list_payloads


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run the GreenRoute multi-agent pipeline from the terminal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--corridor", "-c",
        default="SGP_PKL",
        choices=["SGP_PKL", "PVG_DXB_AMS", "NYNJ_SAV"],
        help="Corridor to evaluate (default: SGP_PKL)",
    )
    p.add_argument(
        "--trigger", "-t",
        default="new_data",
        choices=["scheduler", "new_data", "voyage_completed"],
        help="Pipeline trigger reason (default: new_data)",
    )
    p.add_argument(
        "--window", "-w",
        default=None,
        help=(
            "Temporal window for the satellite grid snapshot. "
            "Maritime: latest | latest-1 | latest-2. "
            "Aviation/Trucking: P1 | P2 | P3. "
            "Omit to use the most recent."
        ),
    )
    p.add_argument(
        "--vehicle-id",
        default=None,
        help="IMO number (maritime) or ICAO hex (aviation) for voyage_completed trigger.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate graph wiring and payload registry without calling the LLM.",
    )
    p.add_argument(
        "--json-out",
        action="store_true",
        help="Print the full GreenRouteDecision JSON at the end.",
    )
    return p


# ─────────────────────────────────────────────────────────────────────────────
# Dry-run: just confirm everything resolves
# ─────────────────────────────────────────────────────────────────────────────

def dry_run(args: argparse.Namespace) -> None:
    print("\n── Dry-run mode (no LLM calls) ────────────────────────────────")

    # 1. Graph wiring
    from app.agent.graph import graph
    print(f"  Graph nodes  : {[n for n in graph.nodes if n != '__start__']}")

    # 2. Payload registry
    mode = get_mode(args.corridor)
    windows = list_payloads(args.corridor)
    print(f"  Corridor     : {args.corridor}  ({mode})")
    print(f"  Payloads:")
    for label, path, exists in windows:
        status = "OK" if exists else "MISSING"
        marker = "← default" if label in ("latest", "P1") else ""
        print(f"    [{status}]  {label}  {path}  {marker}")

    # 3. Env
    key = os.getenv("ANTHROPIC_API_KEY", "")
    key_display = f"{key[:12]}…" if len(key) > 12 else "(not set)"
    print(f"  API key      : {key_display}")
    print("\n  [OK] Graph wiring and payload registry look good.")
    print("  Remove --dry-run to run the full pipeline.\n")


# ─────────────────────────────────────────────────────────────────────────────
# Pretty-print helpers
# ─────────────────────────────────────────────────────────────────────────────

def _badge_color(badge: str) -> str:
    colors = {"GREEN": "\033[92m", "WARN": "\033[93m", "RED": "\033[91m"}
    reset = "\033[0m"
    return f"{colors.get(badge, '')}{badge}{reset}"


def print_separator(title: str) -> None:
    width = 60
    print(f"\n{'─' * width}")
    print(f"  {title}")
    print('─' * width)


def print_satellite_report(report: dict) -> None:
    print_separator("① SatelliteAnalyst")
    badge = _badge_color(report.get("badge", "?"))
    print(f"  Corridor     : {report.get('corridor_id')}")
    print(f"  Mode         : {report.get('transport_mode')}")
    print(f"  Overall score: {report.get('overall_score'):.1f}  →  {badge}")
    anomalies = report.get("anomalies") or []
    if anomalies:
        print(f"  Anomalies    : {', '.join(anomalies)}")
    triggers = report.get("business_rule_triggers") or []
    if triggers:
        print(f"  Triggers     : {', '.join(triggers)}")
    reasoning = (report.get("reasoning") or "").strip()
    if reasoning:
        print(f"  Reasoning    : {reasoning[:200]}")


def print_route_recommendation(rec: dict) -> None:
    print_separator("② CorridorOptimizer")
    badge = _badge_color(rec.get("badge", "?"))
    print(f"  Optimal score: {rec.get('optimal_green_score', '?')}  →  {badge}")
    print(f"  Baseline score: {rec.get('baseline_score', '?')}")
    improvement = rec.get("improvement_vs_baseline_pct", 0)
    sign = "+" if improvement >= 0 else ""
    print(f"  vs Baseline  : {sign}{improvement:.1f}%")
    print(f"  Path cells   : {rec.get('path_length_cells', '?')}")
    print(f"  Distance     : {rec.get('distance_km', '?'):.1f} km")
    wp_ok  = rec.get("mandatory_waypoints_validated") or []
    wp_miss = rec.get("mandatory_waypoints_missed") or []
    if wp_ok:
        print(f"  Waypoints ✓  : {', '.join(wp_ok)}")
    if wp_miss:
        print(f"  Waypoints ✗  : {', '.join(wp_miss)}")
    reasoning = (rec.get("reasoning") or "").strip()
    if reasoning:
        print(f"  Reasoning    : {reasoning[:200]}")


def print_cert_decision(cert: dict) -> None:
    print_separator("③ CertificationJudge")
    cert_badge = _badge_color(cert.get("certificate", "?"))
    print(f"  Certificate  : {cert_badge}")
    print(f"  Confidence   : {cert.get('confidence_pct', '?'):.0f}%")
    compliance = cert.get("track_compliance_pct", 0)
    print(f"  Track comply : {compliance:.1f}%")
    wp_ok   = cert.get("waypoints_verified") or []
    wp_miss = cert.get("waypoints_missed") or []
    if wp_ok:
        print(f"  Waypoints ✓  : {', '.join(wp_ok)}")
    if wp_miss:
        print(f"  Waypoints ✗  : {', '.join(wp_miss)}")
    if cert.get("seasonal_context_applied"):
        print("  Seasonal ctx : applied (aviation boreal winter)")
    if cert.get("weather_advisory"):
        print(f"  Weather      : {cert['weather_advisory']}")
    if cert.get("aerosol_advisory"):
        print(f"  Aerosol      : {cert['aerosol_advisory']}")
    reasoning = (cert.get("reasoning") or "").strip()
    if reasoning:
        print(f"  Reasoning    : {reasoning[:200]}")


def print_final_decision(decision: dict) -> None:
    print_separator("④ Synthesize — GreenRouteDecision")
    badge = _badge_color(decision.get("final_badge", "?"))
    print(f"  Decision ID  : {decision.get('decision_id', '?')}")
    print(f"  Final badge  : {badge}")
    print(f"  Final score  : {decision.get('final_score', '?'):.1f}")
    print(f"  Consecutive W: {decision.get('consecutive_warn_count', 0)}")
    print(f"  Firebase     : {'pushed ✓' if decision.get('pushed_to_firebase') else 'skipped'}")
    chain = decision.get("reasoning_chain") or []
    if chain:
        print("  Reasoning chain:")
        for line in chain:
            print(f"    • {line[:160]}")


# ─────────────────────────────────────────────────────────────────────────────
# Main pipeline runner
# ─────────────────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    from app.agent.graph import graph

    mode = get_mode(args.corridor)

    # Minimal vehicle track for voyage_completed (empty = corridor-level assessment)
    vehicle_track: list = []

    print(f"\n{'═' * 60}")
    print(f"  GreenRoute Pipeline")
    print(f"  Corridor  : {args.corridor}  ({mode})")
    print(f"  Trigger   : {args.trigger}")
    if args.window:
        print(f"  Window    : {args.window}")
    if args.vehicle_id:
        print(f"  Vehicle   : {args.vehicle_id}")
    print(f"{'═' * 60}")

    initial_state = {
        "messages": [
            HumanMessage(content=(
                f"Run GreenRoute pipeline for corridor '{args.corridor}' "
                f"({mode} mode), trigger='{args.trigger}'"
            ))
        ],
        "corridor_id":          args.corridor,
        "transport_modes":      [mode],
        "triggered_by":         args.trigger,
        "vehicle_track":        vehicle_track,
        "vehicle_id":           args.vehicle_id,
        "temporal_window":      args.window,
        "grid_snapshot_path":   None,
        "satellite_report":     None,
        "route_recommendation": None,
        "cert_decision":        None,
        "final_decision":       None,
        "pushed_to_firebase":   False,
        "error":                None,
    }

    print("\nStarting agents …  (this may take 30–120 s depending on the corridor)\n")
    t0 = time.time()

    try:
        final_state = graph.invoke(initial_state)
    except KeyboardInterrupt:
        print("\n[INTERRUPTED]")
        sys.exit(0)
    except Exception as exc:
        print(f"\n[PIPELINE ERROR] {exc}")
        raise

    elapsed = time.time() - t0

    # ── Print per-agent summaries ─────────────────────────────────────────────
    sat  = final_state.get("satellite_report") or {}
    rec  = final_state.get("route_recommendation") or {}
    cert = final_state.get("cert_decision") or {}
    dec  = final_state.get("final_decision") or {}

    if sat:
        print_satellite_report(sat)
    if rec:
        print_route_recommendation(rec)
    if cert:
        print_cert_decision(cert)
    if dec:
        print_final_decision(dec)

    print(f"\n{'═' * 60}")
    print(f"  Pipeline complete in {elapsed:.1f}s")
    print(f"{'═' * 60}\n")

    # ── Optional full JSON dump ───────────────────────────────────────────────
    if args.json_out and dec:
        print("\n── Full GreenRouteDecision JSON ──")
        print(json.dumps(dec, indent=2, default=str))


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()

    if args.dry_run:
        dry_run(args)
    else:
        run(args)
