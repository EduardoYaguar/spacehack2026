# Architecture Comparison Report
## `greenroute_architecture.md` vs Current Implementation

> Analysis date: 2026-03-28
> Branch: `agent-satellite-analyst`
> Scope: code-only comparison — no runtime testing.
> Notation: **MATCH** = consistent, **EVOLVED** = intentional deliberate change, **INCONSISTENCY** = potential problem.

---

## 1. Pipeline Sequence

**MATCH.**  The overall flow matches the architecture diagram (§4.1) exactly:

```
START → satellite_analyst → corridor_optimizer → certification_judge → synthesize → END
```

| Architecture §4.1 | Implementation (`graph.py`) |
|---|---|
| satellite_analyst (max 5 calls) | `satellite_analyst_node` (5 maritime/trucking, 9 aviation) |
| corridor_optimizer (max 5 calls) | `run_corridor_optimizer` (max 5) |
| certification_judge (max 4 calls) | `certification_judge_node` (max 4) |
| synthesize (pure Python) | `synthesize_node` (pure Python, no LLM) |

---

## 2. Section 2 Agent Numbering — Doc Error

**INCONSISTENCY (doc-only, no code impact).**

Section 2 of the architecture document has the agent headers labelled backwards:

> "CorridorOptimizer (Agente 2 en el flujo, **implementado como Agente 3**)"
> "CertificationJudge (Agente 3 en el flujo, **implementado como Agente 2**)"

This is the opposite of both the §4.1 flow diagram and the actual `graph.py`.
The implementation is correct; the section headers in §2 are wrong.

---

## 3. Phase Plan (§10) — Execution Order Swapped

**EVOLVED (planning deviation, no runtime impact).**

| Architecture §10 phase | Planned subject | Actual build order |
|---|---|---|
| Phase 2 | SatelliteAnalyst | SatelliteAnalyst ✓ |
| Phase 3 | CertificationJudge | **CorridorOptimizer built here** |
| Phase 4 | CorridorOptimizer | **CertificationJudge built here** |
| Phase 5 | Orchestrator / LangGraph | Orchestrator / LangGraph ✓ |
| Phase 6 | API + persistence | API + persistence ✓ |

The CorridorOptimizer was built before the CertificationJudge, which is the logical dependency order (judge reads optimizer output). The architecture doc planned it the other way around. No runtime consequence.

---

## 4. Conditional Edge `should_run_optimizer` — Not Implemented

**INCONSISTENCY.**

Architecture §10 Phase 5 specifies:
> "Implementar `should_run_optimizer` como edge condicional … probar flujo corto (GREEN scheduler, sin optimizer)"

This implied that for a `scheduler` trigger with an existing GREEN status, the `CorridorOptimizer` could be skipped. The implementation has **no conditional edge** — every run always executes all four nodes sequentially. The current `graph.py` has only fixed edges.

Impact: minor over-computation on `scheduler` GREEN runs. No correctness issue.

---

## 5. Trigger Vocabulary Mismatch

**INCONSISTENCY (minor).**

| Architecture §4.2 | Implementation `TriggerReason` enum |
|---|---|
| `scheduler` | `scheduler` ✓ |
| `new_data` | `new_data` ✓ |
| `voyage_completed` | `voyage_completed` ✓ |
| `reroute_needed` (Phase 5 tasks) | **not present** |
| `degradation_event` (Phase 5 tasks) | **not present** |

`reroute_needed` and `degradation_event` appear only in the Phase 5 narrative, not in the main trigger table. They were dropped; the three main triggers are sufficient.

---

## 6. CertificationJudge Tools — Complete Redesign

**EVOLVED (intentional, significant).**

| Architecture §5.3 / Phase 3 | Implementation |
|---|---|
| `check_baseline_history` (reads baselines.json) | **not implemented** |
| `detect_meteorological_confound` (FIRMS + ERA5) | **not implemented** |
| (no equivalent) | `check_track_compliance` ← **new** |
| (no equivalent) | `verify_waypoint_passage` ← **new** |

The architecture designed the judge to certify **corridor quality** (baseline NO₂ drift, meteorological confounds). The implementation instead certifies **vehicle compliance** (did the ship/plane follow the optimal route?). Both are valid certification interpretations, but they are different tools with different logic. The baseline tracking (consecutive WARNs, audit log) moved to `baseline_service.py` instead of being a judge tool.

---

## 7. SatelliteReport Schema — Flat vs Structured

**EVOLVED (richer, but field names changed).**

Architecture §5.1 specifies a flat JSON with individual fields:

| Architecture field | Implementation |
|---|---|
| `no2_mean`, `no2_max` | Inside `layer_results["no2_mol_m2"]["mean"]` |
| `no2_deviation_from_baseline_pct` | **not present in model** |
| `no2_zscore` | **not present in model** |
| `wind_mean_favor`, `headwind_cells_pct` | Inside `wind_result` object |
| `wave_mean_m`, `wave_hazard_cells` | Inside `layer_results["wave_height_m"]` |
| `viirs_mean_traffic`, `viirs_high_traffic_cells` | Inside `layer_results["viirs_radiance_nw"]` |
| `viirs_applicable` | **not present** |
| `cells_analyzed` | **not present at report level** |
| `data_quality_flag` (single string) | `data_quality_flags` (dict per layer) |
| `retrieval_notes` | `reasoning` (renamed + expanded) |
| `overall_score`, `badge` | `overall_score`, `badge` ✓ |

Baseline deviation (`no2_deviation_from_baseline_pct`, `no2_zscore`) is a gap — the architecture expected the judge to receive z-scores in the satellite report, but they were moved to `baseline_service.py` and computed separately. The judge never receives them directly.

---

## 8. `layers_analyzed` — Parsed but Not Stored

**INCONSISTENCY (silent data loss).**

The system prompt instructs the SatelliteAnalyst to output a `layers_analyzed` list in the JSON, and `_parse_report_from_raw()` reads it:

```python
# satellite_analyst.py:313
layers_analyzed=raw.get("layers_analyzed", []),
```

But `SatelliteReport` in `models.py` has **no `layers_analyzed` field**.
Pydantic v2 silently discards unknown keyword arguments by default, so the value is parsed from the agent output and then dropped. The field is effectively a no-op.

---

## 9. RouteRecommendation Schema — Field Names Changed

**EVOLVED (better structure, some fields renamed or dropped).**

| Architecture §5.2 field | Implementation |
|---|---|
| `baseline_green_score` | `baseline_score` (renamed) |
| `green_score_vs_baseline_pct` | `improvement_vs_baseline_pct` (renamed, sign flipped: + = better) |
| `optimal_path_cells` (int count) | `path_length_cells` (renamed) + `path_cells` (list of PathCell objects) |
| `baseline_path_cells` | **not present** |
| `chokepoints_on_path` | **not present** (waypoint validation split into `mandatory_waypoints_validated`/`mandatory_waypoints_missed`) |
| `feasibility_flag` | **not present** |
| `optimizer_notes` | `reasoning` (renamed) |
| (not in architecture) | `contrail_mitigation_segments` ← new |
| (not in architecture) | `high_slope_segments` ← new |

`chokepoints_on_path` and `feasibility_flag` appear in the CorridorOptimizer's system prompt internally but are not model fields — the same silent-drop issue as `layers_analyzed`.

---

## 10. CertDecision Schema — Different Fields

**EVOLVED (deliberately different purpose).**

| Architecture §5.3 field | Implementation `CertDecision` |
|---|---|
| `voyage_id` | **not present** |
| `badge_text` | **not present** |
| `waypoints_confirmed` | `waypoints_verified` (renamed) |
| `green_score_during_voyage` | **not present** (covered by `track_mean_green_score` inside judge tool output) |
| (not in architecture) | `track_compliance_pct` ← new |
| (not in architecture) | `waypoints_missed` ← new |
| (not in architecture) | `seasonal_context_applied` ← new |
| (not in architecture) | `weather_advisory`, `aerosol_advisory` ← new |
| `certificate`, `confidence_pct` | `certificate`, `confidence_pct` ✓ |

Note: `verify_waypoint_passage` tool output uses `waypoints_confirmed` internally, while the model and system prompt use `waypoints_verified`. The mapping is handled by the LLM in the final JSON.

---

## 11. GreenRouteDecision Schema — Action Fields Removed

**EVOLVED (structural change).**

Architecture §7 envisions a decision focused on operational action:

| Architecture field | Implementation |
|---|---|
| `co2_saving_pct` | **not present** |
| `rerouting_recommended` | **not present** |
| `optimal_route_available` | **not present** |
| `recommended_action` | **not present** |
| `next_review_hours` | **not present** |
| `satellite_summary` (embedded mini-dict) | **not present** (full `satellite_report` embedded instead) |
| `audit_entry` (string) | `reasoning_chain` (list of strings) |
| `certification` | `final_badge` (renamed) |
| `transport_modes_evaluated` | **not present** (single `transport_mode`) |
| `badge_text` | **not present** |
| `pushed_to_firebase`, `corridor_id`, `timestamp` | ✓ present |
| (not in architecture) | `satellite_report`, `route_recommendation`, `cert_decision` ← full sub-models embedded |
| (not in architecture) | `baseline_updated`, `consecutive_warn_count`, `firebase_path` ← new |

The implementation embeds the complete sub-model outputs rather than a flattened summary. The dashboard-oriented fields (`co2_saving_pct`, `recommended_action`, `next_review_hours`) were not implemented.

---

## 12. Grid Dimensions — Spec vs Actual

**INCONSISTENCY (doc error).**

| Source | Rows × Cols | Total cells |
|---|---|---|
| Architecture §6 | 40 × 50 | 2,000 |
| Actual `maritime_portklang_singapore.json` | 40 × **60** | **2,400** |
| CLAUDE.md | 40 × 60 @ 0.1° | 2,400 |

The bounding box in the architecture (99.5°E–104.5°E = 5° longitude) at 0.1° resolution should produce 50 columns, but the actual file has 60 columns (covering 99.5°E–105.5°E). The architecture doc has a stale spec.

---

## 13. SatelliteAnalyst Tool Count Expanded

**EVOLVED (deliberate, aviation requires more data).**

| Architecture §5.1 tools | Implementation |
|---|---|
| `query_gee_no2` | ✓ |
| `query_era5_wind` | ✓ |
| `query_viirs_ships` | ✓ |
| `query_so2_hotspots` | ✓ |
| (not specified) | `query_co` ← new (aviation + trucking) |
| (not specified) | `query_turbulence` ← new (aviation) |
| (not specified) | `query_contrail_risk` ← new (aviation) |
| (not specified) | `query_cloud_top_height` ← new (aviation) |
| (not specified) | `query_aerosol_index` ← new (aviation) |
| (not specified) | `query_aod` ← new (aviation + trucking) |

The architecture was written for the maritime corridor only. Six aviation-specific tools were added to support the `PVG_DXB_AMS` corridor.

---

## 14. `query_viirs_ships` Applicability

**EVOLVED.**

Architecture §5.1: VIIRS tool applies to "segmentos marítimos" only.
Implementation: `query_viirs_ships` is used for **maritime AND trucking** (road congestion proxy — VIIRS nighttime radiance as a highway density indicator). The tool returns a mode-appropriate interpretation based on the payload.

---

## 15. Multi-Corridor Support

**EVOLVED (not in architecture).**

The architecture document focuses entirely on `SGP_PKL` (maritime). The implementation adds two additional corridors:

| Corridor | Mode | Payload files |
|---|---|---|
| `SGP_PKL` | Maritime | `latest/`, `latest-1/`, `latest-2/` |
| `PVG_DXB_AMS` | Aviation | `aereo/p1/`, `aereo/p2/`, `aereo/p3/` |
| `NYNJ_SAV` | Trucking | `terrestre_usa/p1/`, `p2/`, `p3/` |

The `PayloadRegistry` (`payload_registry.py`), `temporal_window` state field, and mode-aware tool logic all emerged from this expansion.

---

## 16. AgentState — Extra Fields Added

**EVOLVED (additive, no conflicts).**

| Architecture §3 | Implementation `state.py` |
|---|---|
| `messages` | ✓ |
| `corridor_id` | ✓ |
| `transport_modes` | ✓ |
| `triggered_by` | ✓ |
| `vehicle_track` | ✓ |
| `satellite_report` | ✓ |
| `route_recommendation` | ✓ |
| `cert_decision` | ✓ |
| `final_decision` | ✓ |
| `pushed_to_firebase` | ✓ |
| (not in architecture) | `vehicle_id` ← new |
| (not in architecture) | `temporal_window` ← new |
| (not in architecture) | `grid_snapshot_path` ← new |
| (not in architecture) | `error` ← new |

All architecture fields are present. The new fields support multi-corridor/multi-window routing and vehicle-level certification.

---

## Summary Table

| # | Topic | Status | Impact |
|---|---|---|---|
| 2 | Section 2 agent numbering in doc | INCONSISTENCY (doc error) | None on code |
| 3 | Phase build order swapped | EVOLVED | None |
| 4 | `should_run_optimizer` conditional edge | INCONSISTENCY | Minor over-computation |
| 5 | Missing trigger values `reroute_needed`/`degradation_event` | INCONSISTENCY (minor) | None |
| 6 | CertificationJudge tools redesigned | EVOLVED | Intentional, significant scope change |
| 7 | SatelliteReport flat → structured schema | EVOLVED | `no2_zscore`/baseline fields absent |
| 8 | `layers_analyzed` parsed but not stored | INCONSISTENCY | Silent field drop |
| 9 | RouteRecommendation field renames | EVOLVED | Schema breaking vs architecture spec |
| 10 | CertDecision fields changed | EVOLVED | Intentional, different certification model |
| 11 | GreenRouteDecision action fields absent | EVOLVED | Dashboard fields unimplemented |
| 12 | Grid 40×50 spec vs 40×60 actual | INCONSISTENCY (doc error) | None on code |
| 13 | Aviation tool set expanded (4→10) | EVOLVED | Positive expansion |
| 14 | VIIRS used for trucking too | EVOLVED | Intentional |
| 15 | Three corridors vs one | EVOLVED | Major positive expansion |
| 16 | AgentState extra fields | EVOLVED | Additive, no conflicts |

---

## Items Worth Addressing

These are the only items that could cause a real problem if left unresolved:

1. **`layers_analyzed` field** (§8) — either add the field to `SatelliteReport` or remove the parse call in `_parse_report_from_raw()` to avoid confusion.

2. **`no2_zscore` / baseline deviation in SatelliteReport** (§7) — the architecture expected the judge to receive these values from the satellite report. Since they now live only in `baselines.json`, the judge never sees them. If baseline-aware certification is needed in the future, the synthesize node or a new judge tool would need to inject them.

3. **`co2_saving_pct` and action fields in GreenRouteDecision** (§11) — if the React dashboard is built per the architecture spec (§10 Phase 7), it will expect these fields and find them absent. The dashboard will need to be updated to match the actual `GreenRouteDecision` schema.

4. **Section 2 agent numbering** (§2) — the headers in `greenroute_architecture.md` should be corrected so the doc is not misleading during onboarding.
