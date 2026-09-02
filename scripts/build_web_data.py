from __future__ import annotations

import json
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from freight_opt.config import load_config  # noqa: E402


RESULT_DIR = ROOT / "results" / "gurobi_v6_12" / "test"
BENDERS_RESULT_DIR = ROOT / "results" / "benders_cg_v6_12" / "test"
BENDERS_MANIFEST = ROOT / "results" / "benders_cg_v6_12" / "run_manifest.json"
QLEARNING_RESULT_DIR = ROOT / "results" / "qlearning_v1" / "test"
QLEARNING_ROOT = ROOT / "results" / "qlearning_v1"
CASE_ROOT = ROOT / "data" / "frozen" / "test"
ACTIVE_INDEX = ROOT / "data" / "frozen" / "active_test_v6_12.json"
OUTPUT_ROOT = ROOT / "web" / "public" / "data"

CATEGORY_LABELS = {
    "normal": "正常波动",
    "urgent_insert": "紧急插单",
    "urgent_cancel": "紧急撤单",
    "vehicle_breakdown": "车辆故障",
}
METHODS = (
    ("milp", "MILP联合决策", "real"),
    ("benders-cg", "Benders分解＋列生成", "real"),
    ("tabular-hrl", "两层表格Q-learning", "real"),
)

COST_COMPONENTS = (
    ("transport", "运输成本", "transportCost"),
    ("cargo_handling", "装卸成本", "handlingCost"),
    ("inventory_holding", "留仓库存成本", "inventoryCost"),
    ("transfer", "中转成本", "transferCost"),
    ("delay", "延误成本", "delayCost"),
    ("service_shortfall", "服务短缺成本", "serviceShortfallCost"),
    ("cumulative_change", "变更成本", "changeCost"),
)

# This wall-clock interval was reconstructed from the first Gurobi log creation
# and the last independent-validation file write for the frozen v6_12 run.  It
# includes result serialization and validation, so the web UI must label it as
# inferred rather than as a solver-recorded field.
PARALLEL_RUN_EVIDENCE = {
    "start": "2026-09-01 00:06:51.797",
    "end": "2026-09-01 00:37:16.664",
    "seconds": 1824.867,
}


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))


def solution_runtime(solution: dict[str, Any]) -> float:
    return float(solution.get("baseline", {}).get("runtime_seconds", 0.0)) + sum(
        float(step.get("runtime_seconds") or 0.0)
        for step in solution.get("rolling_steps", [])
    )


def solution_metric(
    solution: dict[str, Any],
    validation: dict[str, Any],
    *,
    method_id: str,
    method_label: str,
    category: str,
) -> dict[str, Any]:
    actual = solution["actual"]
    components = solution["episode_objective_components"]
    rates = actual["service_rates"]
    return {
        "methodId": method_id,
        "methodLabel": method_label,
        "dataStatus": "real",
        "caseId": solution["case_id"],
        "category": category,
        "totalCost": solution["episode_objective"],
        "transportCost": components["transport"],
        "handlingCost": components["cargo_handling"],
        "inventoryCost": components["inventory_holding"],
        "transferCost": components["transfer"],
        "delayCost": components["delay"],
        "serviceShortfallCost": components["service_shortfall"],
        "changeCost": components["cumulative_change"],
        "runtimeSeconds": solution_runtime(solution),
        "completionHour": solution["completion_hour"],
        "urgentOnTimeRate": rates.get("urgent", {}).get("on_time_rate"),
        "standardOnTimeRate": rates.get("standard", {}).get("on_time_rate"),
        "economyOnTimeRate": rates.get("economy", {}).get("on_time_rate"),
        "changedMissionTasks": sum(
            float(
                step.get("change_metrics", {}).get("changed_future_mission_tasks")
                or step.get("change_metrics", {}).get("trip_delta")
                or 0.0
            )
            for step in solution["rolling_steps"]
        ),
        "reroutedTons": sum(
            float(
                step.get("change_metrics", {}).get("rerouted_previously_planned_tons")
                or step.get("change_metrics", {}).get("cargo_rerouted_tons")
                or 0.0
            )
            for step in solution["rolling_steps"]
        ),
        "caseStatus": solution["status"],
        "validationStatus": validation["status"],
        "baselineStatus": solution["baseline"]["status"],
        "finalStatus": actual["status"],
    }


def decomposition_phases(solution: dict[str, Any]) -> list[dict[str, Any]]:
    return [solution["baseline"], *solution.get("rolling_steps", [])]


def build_paired_analysis(
    milp_metrics: list[dict[str, Any]],
    benders_metrics: list[dict[str, Any]],
    benders_solutions: list[dict[str, Any]],
) -> dict[str, Any]:
    milp_by_case = {row["caseId"]: row for row in milp_metrics}
    benders_by_case = {row["caseId"]: row for row in benders_metrics}
    case_ids = sorted(set(milp_by_case) & set(benders_by_case))
    pairs = []
    for case_id in case_ids:
        milp = milp_by_case[case_id]
        benders = benders_by_case[case_id]
        relative_delta = (benders["totalCost"] - milp["totalCost"]) / abs(milp["totalCost"])
        pairs.append({
            "caseId": case_id,
            "category": milp["category"],
            "milpCost": milp["totalCost"],
            "bendersCost": benders["totalCost"],
            "relativeCostDelta": relative_delta,
            "milpRuntimeSeconds": milp["runtimeSeconds"],
            "bendersRuntimeSeconds": benders["runtimeSeconds"],
        })

    category_rows = []
    for category, label in CATEGORY_LABELS.items():
        category_pairs = [row for row in pairs if row["category"] == category]
        milp_mean = sum(row["milpCost"] for row in category_pairs) / len(category_pairs)
        benders_mean = sum(row["bendersCost"] for row in category_pairs) / len(category_pairs)
        category_rows.append({
            "category": category,
            "label": label,
            "count": len(category_pairs),
            "milpMeanCost": milp_mean,
            "bendersMeanCost": benders_mean,
            "relativeCostDelta": (benders_mean - milp_mean) / abs(milp_mean),
        })

    cost_deltas = []
    total_delta = sum(row["bendersCost"] - row["milpCost"] for row in pairs)
    for _, label, metric_key in COST_COMPONENTS:
        milp_total = sum(float(row[metric_key]) for row in milp_metrics)
        benders_total = sum(float(row[metric_key]) for row in benders_metrics)
        delta = benders_total - milp_total
        cost_deltas.append({
            "key": metric_key,
            "label": label,
            "milpTotal": milp_total,
            "bendersTotal": benders_total,
            "delta": delta,
            "shareOfNetDelta": None if total_delta == 0 else delta / total_delta,
        })

    phases = [phase for solution in benders_solutions for phase in decomposition_phases(solution)]
    termination_counts: dict[str, int] = defaultdict(int)
    phase_rows = []
    for solution in benders_solutions:
        for index, phase in enumerate(decomposition_phases(solution)):
            trace = phase.get("decomposition_trace", {})
            termination = str(trace.get("termination_reason") or "unknown")
            termination_counts[termination] += 1
            phase_rows.append({
                "caseId": solution["case_id"],
                "stage": "baseline" if index == 0 else f"slot_{phase.get('slot')}",
                "gap": float(phase.get("mip_gap") or 0.0),
                "terminationReason": termination,
            })
    worst_phase = max(phase_rows, key=lambda row: row["gap"])
    manifest = read_json(BENDERS_MANIFEST)
    started = manifest["started_at"]
    finished = manifest["finished_at"]
    from datetime import datetime
    elapsed_seconds = (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()

    milp_mean = sum(row["totalCost"] for row in milp_metrics) / len(milp_metrics)
    benders_mean = sum(row["totalCost"] for row in benders_metrics) / len(benders_metrics)
    milp_runtime_mean = sum(row["runtimeSeconds"] for row in milp_metrics) / len(milp_metrics)
    benders_runtime_mean = sum(row["runtimeSeconds"] for row in benders_metrics) / len(benders_metrics)
    best_pair = min(pairs, key=lambda row: row["relativeCostDelta"])
    worst_pair = max(pairs, key=lambda row: row["relativeCostDelta"])
    return {
        "pairedCases": len(pairs),
        "bothValidatedCases": sum(
            milp_by_case[row["caseId"]]["validationStatus"] == "pass"
            and benders_by_case[row["caseId"]]["validationStatus"] == "pass"
            for row in pairs
        ),
        "milpMeanCost": milp_mean,
        "bendersMeanCost": benders_mean,
        "weightedCostDeltaRate": (benders_mean - milp_mean) / abs(milp_mean),
        "meanPairwiseCostDeltaRate": sum(row["relativeCostDelta"] for row in pairs) / len(pairs),
        "milpMeanRuntimeSeconds": milp_runtime_mean,
        "bendersMeanRuntimeSeconds": benders_runtime_mean,
        "runtimeDeltaRate": (benders_runtime_mean - milp_runtime_mean) / milp_runtime_mean,
        "bendersBetterOrEqualCases": sum(row["bendersCost"] <= row["milpCost"] for row in pairs),
        "bestCase": best_pair,
        "worstCase": worst_pair,
        "categories": category_rows,
        "costDeltas": cost_deltas,
        "pairs": pairs,
        "convergence": {
            "phaseCount": len(phases),
            "gapReachedCount": termination_counts["gap_reached"],
            "innerTimeLimitCount": termination_counts["inner_time_limit"],
            "stalledDuplicateCutCount": termination_counts["stalled_duplicate_cut"],
            "warmStartOptimalCount": sum(
                phase.get("decomposition_trace", {}).get("master_feasibility_warm_start", {}).get("status") == "optimal"
                for phase in phases
            ),
            "recoveryOptimalCount": sum(
                phase.get("decomposition_trace", {}).get("recovery_status") == "optimal"
                for phase in phases
            ),
            "maxRecordedGap": worst_phase["gap"],
            "maxGapCaseId": worst_phase["caseId"],
            "maxGapStage": worst_phase["stage"],
            "runElapsedSeconds": elapsed_seconds,
            "runElapsedLabel": "1小时05分35秒",
            "statusScope": "fixed_mission_cargo_recovery",
        },
        "evidenceBoundary": (
            "12/12 complete and validation pass proves operational feasibility. "
            "A phase status of optimal applies to fixed-mission cargo recovery; "
            "it does not prove every joint Benders phase globally optimal."
        ),
    }


def qlearning_wall_timings() -> dict[str, Any]:
    journal_path = QLEARNING_ROOT / "run_journal.jsonl"
    events = [
        json.loads(line)
        for line in journal_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    pipeline_starts = [
        index for index, event in enumerate(events)
        if event.get("event") == "stage_update"
        and event.get("stage") == "pipeline"
        and event.get("status") == "running"
    ]
    run_events = events[pipeline_starts[-1]:]

    def stage_seconds(stage: str) -> float:
        starts = [
            event for event in run_events
            if event.get("stage") == stage and event.get("status") == "running"
        ]
        finishes = [
            event for event in run_events
            if event.get("stage") == stage and event.get("status") == "pass"
        ]
        if not starts or not finishes:
            return 0.0
        return (
            datetime.fromisoformat(finishes[-1]["timestamp_utc"])
            - datetime.fromisoformat(starts[0]["timestamp_utc"])
        ).total_seconds()

    starts: dict[tuple[str, int], datetime] = {}
    case_seconds: dict[str, float] = {}
    for event in run_events:
        if event.get("split") != "test" or "case_id" not in event:
            continue
        key = (str(event["case_id"]), int(event.get("attempt", 1)))
        if event.get("event") == "case_start":
            starts[key] = datetime.fromisoformat(event["timestamp_utc"])
        elif event.get("event") == "case_finish" and event.get("exit_code") == 0 and key in starts:
            case_seconds[key[0]] = (
                datetime.fromisoformat(event["timestamp_utc"]) - starts[key]
            ).total_seconds()
    return {
        "experiencePreparationSeconds": stage_seconds("prepare_experience"),
        "fiveSeedTrainingSeconds": stage_seconds("train_seeds"),
        "validationBatchSeconds": stage_seconds("validation_cases"),
        "testBatchSeconds": stage_seconds("test_cases"),
        "meanCaseProcessSeconds": sum(case_seconds.values()) / len(case_seconds),
        "caseProcessSeconds": case_seconds,
    }


def mission_statistics(solutions: list[dict[str, Any]]) -> dict[str, float]:
    totals = []
    external = []
    for solution in solutions:
        missions = solution["actual"].get("missions", {})
        totals.append(sum(float(value) for value in missions.values()))
        external.append(sum(
            float(value) for mission_id, value in missions.items()
            if str(mission_id).startswith("EXT_")
        ))
    return {
        "meanMissionTasks": sum(totals) / len(totals),
        "meanExternalMissionTasks": sum(external) / len(external),
    }


def build_three_method_analysis(
    milp_metrics: list[dict[str, Any]],
    benders_metrics: list[dict[str, Any]],
    qlearning_metrics: list[dict[str, Any]],
    milp_solutions: list[dict[str, Any]],
    benders_solutions: list[dict[str, Any]],
    qlearning_solutions: list[dict[str, Any]],
) -> dict[str, Any]:
    metrics_by_method = {
        "milp": milp_metrics,
        "benders-cg": benders_metrics,
        "tabular-hrl": qlearning_metrics,
    }
    solutions_by_method = {
        "milp": milp_solutions,
        "benders-cg": benders_solutions,
        "tabular-hrl": qlearning_solutions,
    }
    milp_by_case = {row["caseId"]: row for row in milp_metrics}
    summaries = []
    for method_id, metrics in metrics_by_method.items():
        mean_cost = sum(float(row["totalCost"]) for row in metrics) / len(metrics)
        mean_runtime = sum(float(row["runtimeSeconds"]) for row in metrics) / len(metrics)
        pairwise_gaps = [
            (float(row["totalCost"]) - float(milp_by_case[row["caseId"]]["totalCost"]))
            / abs(float(milp_by_case[row["caseId"]]["totalCost"]))
            for row in metrics
        ]
        summaries.append({
            "methodId": method_id,
            "label": next(label for key, label, _ in METHODS if key == method_id),
            "validatedCases": sum(row["validationStatus"] == "pass" for row in metrics),
            "meanCost": mean_cost,
            "meanRuntimeSeconds": mean_runtime,
            "meanPairwiseGapToMilp": sum(pairwise_gaps) / len(pairwise_gaps),
            **mission_statistics(solutions_by_method[method_id]),
        })

    categories = []
    for category, label in CATEGORY_LABELS.items():
        row: dict[str, Any] = {"category": category, "label": label}
        milp_rows = [item for item in milp_metrics if item["category"] == category]
        milp_category_by_case = {item["caseId"]: item for item in milp_rows}
        for method_id, metrics in metrics_by_method.items():
            selected = [item for item in metrics if item["category"] == category]
            row[method_id] = {
                "meanCost": sum(float(item["totalCost"]) for item in selected) / len(selected),
                "meanPairwiseGapToMilp": sum(
                    (float(item["totalCost"]) - float(milp_category_by_case[item["caseId"]]["totalCost"]))
                    / abs(float(milp_category_by_case[item["caseId"]]["totalCost"]))
                    for item in selected
                ) / len(selected),
            }
        categories.append(row)

    q_by_case = {row["caseId"]: row for row in qlearning_metrics}
    benders_by_case = {row["caseId"]: row for row in benders_metrics}
    q_gap_to_benders = sum(
        (q_by_case[case_id]["totalCost"] - benders_by_case[case_id]["totalCost"])
        / abs(benders_by_case[case_id]["totalCost"])
        for case_id in q_by_case
    ) / len(q_by_case)
    total_q_delta = sum(
        q_by_case[case_id]["totalCost"] - milp_by_case[case_id]["totalCost"]
        for case_id in q_by_case
    )
    q_cost_drivers = []
    for _, label, metric_key in COST_COMPONENTS:
        milp_mean = sum(float(row[metric_key]) for row in milp_metrics) / len(milp_metrics)
        q_mean = sum(float(row[metric_key]) for row in qlearning_metrics) / len(qlearning_metrics)
        delta = q_mean - milp_mean
        q_cost_drivers.append({
            "key": metric_key,
            "label": label,
            "milpMean": milp_mean,
            "qlearningMean": q_mean,
            "delta": delta,
            "shareOfGap": None if total_q_delta == 0 else delta * len(qlearning_metrics) / total_q_delta,
        })
    q_cost_drivers.sort(key=lambda item: abs(item["delta"]), reverse=True)

    ensemble = read_json(QLEARNING_ROOT / "models" / "ensemble.json")
    train_experience = read_json(QLEARNING_ROOT / "experience" / "train.json")
    validation_experience = read_json(QLEARNING_ROOT / "experience" / "validation.json")
    training_summary = read_json(QLEARNING_ROOT / "models" / "training_summary.json")
    traces = [item for solution in qlearning_solutions for item in solution.get("rl_action_trace", [])]
    test_states = {tuple(item["state"]) for item in traces}
    model_states = [tuple(int(value) for value in key.split("|")) for key in ensemble["q"]]
    wall = qlearning_wall_timings()
    q_summary = next(item for item in summaries if item["methodId"] == "tabular-hrl")
    milp_summary = next(item for item in summaries if item["methodId"] == "milp")
    transport_driver = next(item for item in q_cost_drivers if item["key"] == "transportCost")
    residual_gap_without_transport = (
        q_summary["meanCost"] - milp_summary["meanCost"] - transport_driver["delta"]
    ) / milp_summary["meanCost"]
    return {
        "caseCount": 12,
        "methodCaseValidationPasses": sum(
            row["validationStatus"] == "pass"
            for metrics in metrics_by_method.values() for row in metrics
        ),
        "methods": summaries,
        "categories": categories,
        "qlearningGapToBendersCg": q_gap_to_benders,
        "qlearningCostDrivers": q_cost_drivers,
        "qlearningDiagnostics": {
            "convergedSeeds": training_summary["converged_seed_count"],
            "totalSeeds": len(training_summary["seeds"]),
            "trainTransitions": train_experience["transition_count"],
            "validationTransitions": validation_experience["transition_count"],
            "learnedStateCount": len(model_states),
            "testUniqueStateCount": len(test_states),
            "capacityBinsUsed": len({state[1] for state in model_states}),
            "serviceRiskBinsUsed": len({state[2] for state in model_states}),
            "decisionCount": len(traces),
            "shieldChangedDecisions": sum(bool(item.get("feasibility_shield_used")) for item in traces),
            "meanMissionTasks": q_summary["meanMissionTasks"],
            "milpMeanMissionTasks": milp_summary["meanMissionTasks"],
            "meanExternalMissionTasks": q_summary["meanExternalMissionTasks"],
            "milpMeanExternalMissionTasks": milp_summary["meanExternalMissionTasks"],
            "residualGapIfTransportDeltaRemoved": residual_gap_without_transport,
            **wall,
        },
        "runtimeCaveat": (
            "runtimeSeconds accumulates accepted baseline and rolling-plan runtimes. "
            "Q-learning process wall time additionally includes rejected feasibility-shield candidates, IO and validation."
        ),
    }


def aggregate_animation(solution: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    travel_slots = {
        (edge["origin"], edge["destination"]): int(edge["travel_slots"])
        for edge in case["edges"]
    }
    node_by_id = {node["id"]: node for node in case["nodes"]}
    step_by_snapshot = {
        step["plan_after_snapshot_id"]: step
        for step in solution.get("rolling_steps", [])
    }

    def mission_segments(mission: dict[str, Any]) -> list[dict[str, Any]]:
        if mission.get("segments"):
            return mission["segments"]
        route = list(mission.get("route", []))
        departure = int(mission.get("departure_slot", 0))
        segments = []
        for origin, destination in zip(route, route[1:]):
            arrival = departure + travel_slots[(origin, destination)]
            segments.append({
                "origin": origin, "destination": destination,
                "departure_slot": departure, "arrival_slot": arrival,
            })
            departure = arrival
        return segments

    snapshots = []
    for snapshot_index, snapshot in enumerate(solution["plan_snapshots"]):
        raw_missions = snapshot.get("selected_missions", snapshot.get("missions", []))
        service_mission = {}
        for mission in raw_missions:
            service_mission.setdefault(mission.get("service_id"), mission)
        flow_by_key: dict[tuple[Any, ...], float] = defaultdict(float)
        for itinerary in snapshot["cargo_itineraries"]:
            tons = float(itinerary["tons"])
            if itinerary.get("legs"):
                itinerary_segments = [
                    segment
                    for leg in itinerary["legs"]
                    for segment in leg.get("segments", [])
                ]
            else:
                itinerary_segments = [
                    segment
                    for service_id in itinerary.get("service_ids", [])
                    for segment in mission_segments(service_mission[service_id])
                    if service_id in service_mission
                ]
            for segment in itinerary_segments:
                    key = (
                        segment["origin"], segment["destination"],
                        int(segment["departure_slot"]), int(segment["arrival_slot"]),
                        itinerary["product"],
                    )
                    flow_by_key[key] += tons
        cargo_flows = [
            {
                "origin": key[0], "destination": key[1],
                "departureSlot": key[2], "arrivalSlot": key[3],
                "product": key[4], "tons": round(tons, 5),
            }
            for key, tons in sorted(flow_by_key.items())
            if tons > 1e-7
        ]
        missions = [
            {
                "missionId": mission["mission_id"],
                "vehicleSource": mission["vehicle_source"],
                "mode": mission["mode"],
                "route": mission["route"],
                "vehicleCount": mission["vehicle_count"],
                "departureSlot": mission["departure_slot"],
                "arrivalSlot": mission["arrival_slot"],
                "segments": [
                    {
                        "origin": segment["origin"],
                        "destination": segment["destination"],
                        "departureSlot": segment["departure_slot"],
                        "arrivalSlot": segment["arrival_slot"],
                    }
                    for segment in mission_segments(mission)
                ],
            }
            for mission in raw_missions
        ]
        nodes = []
        for node in snapshot["nodes"]:
            case_node = node_by_id[node["node_id"]]
            nodes.append({
                "nodeId": node["node_id"],
                "timeline": [
                    {
                        "slot": state["slot"],
                        "ownVehicles": state["own_vehicles"],
                        "handlingTons": state["handling_tons"],
                        "handlingCapacityTons": state.get(
                            "handling_capacity_tons",
                            case_node["handling_capacity"][min(int(state["slot"]), len(case_node["handling_capacity"]) - 1)],
                        ),
                        "handlingUtilization": state.get(
                            "handling_utilization",
                            float(state["handling_tons"]) / max(
                                1.0,
                                float(case_node["handling_capacity"][min(int(state["slot"]), len(case_node["handling_capacity"]) - 1)]),
                            ),
                        ),
                        "inventoryTons": state["inventory_tons"],
                        "inventoryCost": state.get("inventory_cost", 0.0),
                        "releasedTons": state.get("released_tons", 0.0),
                        "cargoDepartureTons": state.get("cargo_departure_tons", 0.0),
                        "cargoArrivalTons": state.get("cargo_arrival_tons", 0.0),
                        "deliveredTons": state.get("delivered_tons", 0.0),
                        "ownVehicleDepartures": state.get("own_vehicle_departures", 0.0),
                        "externalVehicleDepartures": state.get("external_vehicle_departures", 0.0),
                    }
                    for state in node["timeline"]
                ],
            })
        step = step_by_snapshot.get(snapshot["snapshot_id"])
        source_plan = solution["baseline"] if snapshot_index == 0 else (step or solution["actual"])
        snapshots.append({
            "snapshotId": snapshot["snapshot_id"],
            "decisionSlot": snapshot["decision_slot"],
            "decisionHour": snapshot.get("decision_hour", int(snapshot["decision_slot"]) * 3),
            "decisionType": snapshot.get(
                "decision_type", "baseline" if snapshot_index == 0 else step.get("decision_type", "periodic")
            ),
            "triggerReasons": snapshot.get("trigger_reasons", [] if step is None else step.get("reasons", [])),
            "objective": snapshot.get("objective", source_plan.get("objective", 0.0)),
            "objectiveComponents": snapshot.get("objective_components", source_plan.get("objective_components", {})),
            "serviceRates": snapshot.get("service_rates", source_plan.get("service_rates", {})),
            "nodes": nodes,
            "missions": missions,
            "cargoFlows": cargo_flows,
        })
    undirected_edges = []
    seen_edges: set[tuple[str, str]] = set()
    for edge in case["edges"]:
        key = tuple(sorted((edge["origin"], edge["destination"])))
        if key in seen_edges:
            continue
        seen_edges.add(key)
        undirected_edges.append({
            "origin": key[0], "destination": key[1],
            "travelSlots": int(edge["travel_slots"]),
        })
    return {
        "schemaVersion": 1,
        "caseId": solution["case_id"],
        "category": solution["category"],
        "slotHours": 3,
        "observationSlots": 24,
        "event": solution.get("realized_event") or case["event"],
        "completionHour": solution["completion_hour"],
        "topology": {
            "nodes": [node["id"] for node in case["nodes"]],
            "edges": undirected_edges,
        },
        "rollingSteps": [
            {
                "slot": step["slot"], "hour": step["hour"],
                "decisionType": step["decision_type"], "reasons": step["reasons"],
                "status": step["status"], "changeCost": step["incurred_change_cost"],
                "before": step["plan_before_snapshot_id"],
                "after": step["plan_after_snapshot_id"],
            }
            for step in solution["rolling_steps"]
        ],
        "snapshots": snapshots,
    }


def main() -> None:
    config = load_config(ROOT / "config" / "base_config.yaml")
    active = read_json(ACTIVE_INDEX)
    ordered_case_ids = [
        case_id
        for category in config["datasets"]["categories"]
        for case_id in active["categories"][category]
    ]
    if len(ordered_case_ids) != 12 or len(set(ordered_case_ids)) != 12:
        raise RuntimeError("The active web set must contain exactly 12 unique cases")

    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    (OUTPUT_ROOT / "animations").mkdir(parents=True)
    (OUTPUT_ROOT / "case-details").mkdir(parents=True)

    first_case: dict[str, Any] | None = None
    summaries = []
    real_metrics = []
    milp_solutions = []
    benders_metrics = []
    benders_solutions = []
    qlearning_metrics = []
    qlearning_solutions = []
    animation_manifest = []
    benders_animation_manifest = []
    qlearning_animation_manifest = []
    solver_limit_hits = []
    gurobi_calls = 0
    for case_id in ordered_case_ids:
        category = next(
            category for category, values in active["categories"].items()
            if case_id in values
        )
        case_path = CASE_ROOT / category / f"{case_id}.json"
        case = read_json(case_path)
        solution = read_json(RESULT_DIR / f"{case_id}.json")
        validation = read_json(RESULT_DIR / f"{case_id}_validation.json")
        if solution.get("status") != "complete" or validation.get("status") != "pass":
            raise RuntimeError(f"{case_id} is not a complete validated MILP result")
        milp_solutions.append(solution)
        benders_solution = read_json(BENDERS_RESULT_DIR / f"{case_id}.json")
        benders_validation = read_json(BENDERS_RESULT_DIR / f"{case_id}_validation.json")
        if benders_solution.get("status") != "complete" or benders_validation.get("status") != "pass":
            raise RuntimeError(f"{case_id} is not a complete validated Benders-CG result")
        if benders_solution.get("run_id") != read_json(BENDERS_MANIFEST).get("run_id"):
            raise RuntimeError(f"{case_id} does not belong to the completed Benders-CG run")
        benders_solutions.append(benders_solution)
        qlearning_solution = read_json(QLEARNING_RESULT_DIR / f"{case_id}.json")
        qlearning_validation = read_json(QLEARNING_RESULT_DIR / f"{case_id}_validation.json")
        if qlearning_solution.get("status") != "complete" or qlearning_validation.get("status") != "pass":
            raise RuntimeError(f"{case_id} is not a complete validated Q-learning result")
        qlearning_solutions.append(qlearning_solution)
        if first_case is None:
            first_case = case

        forecast_total = sum(float(item["forecast_tons"]) for item in case["demand"])
        actual_total = sum(float(item["actual_tons"]) for item in case["demand"])
        batches: dict[int, dict[str, float]] = defaultdict(lambda: {"forecast": 0.0, "actual": 0.0})
        products: dict[str, dict[str, float]] = defaultdict(lambda: {"forecast": 0.0, "actual": 0.0})
        for demand in case["demand"]:
            if demand["id"].startswith("EMG_INSERT"):
                continue
            release = int(demand["release_slot"])
            batches[release]["forecast"] += float(demand["forecast_tons"])
            batches[release]["actual"] += float(demand["actual_tons"])
            products[demand["product"]]["forecast"] += float(demand["forecast_tons"])
            products[demand["product"]]["actual"] += float(demand["actual_tons"])
        event = solution.get("realized_event") or case["event"]
        summaries.append({
            "caseId": case_id,
            "category": category,
            "categoryLabel": CATEGORY_LABELS[category],
            "eventType": event["type"],
            "eventSlot": event.get("slot"),
            "eventHour": int(event["slot"]) * 3 if event.get("slot") is not None else None,
            "forecastTotal": round(forecast_total, 4),
            "actualTotal": round(actual_total, 4),
            "forecastErrorRate": round(actual_total / forecast_total - 1.0, 6),
            "completionHour": solution["completion_hour"],
            "batches": [
                {
                    "releaseHour": slot * 3,
                    "forecast": round(values["forecast"], 4),
                    "actual": round(values["actual"], 4),
                }
                for slot, values in sorted(batches.items())
            ],
            "products": {
                product: {key: round(value, 4) for key, value in values.items()}
                for product, values in products.items()
            },
        })

        detail = {
            "caseId": case_id,
            "category": category,
            "event": event,
            "nodes": case["nodes"],
            "demands": [
                {
                    "id": item["id"], "origin": item["origin"],
                    "destination": item["destination"], "product": item["product"],
                    "releaseHour": int(item["release_slot"]) * 3,
                    "forecastTons": item["forecast_tons"],
                    "actualTons": item["actual_tons"],
                }
                for item in case["demand"]
            ],
        }
        write_json(OUTPUT_ROOT / "case-details" / f"{case_id}.json", detail)

        runtime = solution_runtime(solution)
        gurobi_calls += 1 + len(solution["rolling_steps"])
        baseline = solution["baseline"]
        if baseline.get("status") == "time_limit":
            solver_limit_hits.append({
                "caseId": case_id,
                "callType": "day_start",
                "callLabel": "日初规划",
                "gap": float(baseline.get("mip_gap") or 0.0),
                "runtimeSeconds": float(baseline.get("runtime_seconds") or 0.0),
                "hour": 0,
            })
        for step in solution["rolling_steps"]:
            if step.get("status") != "time_limit":
                continue
            call_type = "event" if step.get("decision_type") == "event" else "periodic"
            solver_limit_hits.append({
                "caseId": case_id,
                "callType": call_type,
                "callLabel": "事件重调度" if call_type == "event" else "6小时滚动",
                "gap": float(step.get("mip_gap") or 0.0),
                "runtimeSeconds": float(step.get("runtime_seconds") or 0.0),
                "hour": int(step.get("hour") or 0),
            })
        metric = solution_metric(
            solution, validation,
            method_id="milp", method_label="MILP联合决策", category=category,
        )
        real_metrics.append(metric)
        benders_metrics.append(solution_metric(
            benders_solution, benders_validation,
            method_id="benders-cg", method_label="Benders分解＋列生成", category=category,
        ))
        qlearning_metrics.append(solution_metric(
            qlearning_solution, qlearning_validation,
            method_id="tabular-hrl", method_label="两层表格Q-learning", category=category,
        ))

        animation = aggregate_animation(solution, case)
        animation_path = OUTPUT_ROOT / "animations" / f"{case_id}.json"
        write_json(animation_path, animation)
        if animation_path.stat().st_size > 5 * 1024 * 1024:
            raise RuntimeError(f"Animation chunk exceeds 5 MB: {case_id}")
        animation_manifest.append({
            "caseId": case_id,
            "category": category,
            "url": f"data/animations/{case_id}.json",
            "bytes": animation_path.stat().st_size,
        })
        benders_animation = aggregate_animation(benders_solution, case)
        benders_animation_path = OUTPUT_ROOT / "animations" / "benders-cg" / f"{case_id}.json"
        write_json(benders_animation_path, benders_animation)
        if benders_animation_path.stat().st_size > 5 * 1024 * 1024:
            raise RuntimeError(f"Benders-CG animation chunk exceeds 5 MB: {case_id}")
        benders_animation_manifest.append({
            "caseId": case_id,
            "category": category,
            "url": f"data/animations/benders-cg/{case_id}.json",
            "bytes": benders_animation_path.stat().st_size,
        })
        qlearning_animation = aggregate_animation(qlearning_solution, case)
        qlearning_animation_path = OUTPUT_ROOT / "animations" / "qlearning" / f"{case_id}.json"
        write_json(qlearning_animation_path, qlearning_animation)
        if qlearning_animation_path.stat().st_size > 5 * 1024 * 1024:
            raise RuntimeError(f"Q-learning animation chunk exceeds 5 MB: {case_id}")
        qlearning_animation_manifest.append({
            "caseId": case_id,
            "category": category,
            "url": f"data/animations/qlearning/{case_id}.json",
            "bytes": qlearning_animation_path.stat().st_size,
        })

    assert first_case is not None
    all_metrics = [*real_metrics, *benders_metrics, *qlearning_metrics]

    nodes = []
    for node in first_case["nodes"]:
        capacities = [float(value) for value in node["handling_capacity"]]
        nodes.append({
            "nodeId": node["id"],
            "initialOwnVehicles": node["initial_own_vehicles"],
            "handlingMin": min(capacities),
            "handlingMax": max(capacities),
            "handlingAverage": round(sum(capacities) / len(capacities), 3),
            "externalVehicleMax": max(node["external_vehicle_limit"]),
        })
    edge_pairs = []
    seen: set[tuple[str, str]] = set()
    for edge in first_case["edges"]:
        key = tuple(sorted((edge["origin"], edge["destination"])))
        if key in seen:
            continue
        seen.add(key)
        edge_pairs.append({
            "origin": key[0], "destination": key[1],
            "travelSlots": edge["travel_slots"],
            "normalCost": edge["normal_cost"],
            "addedCost": edge["added_cost"],
            "outsourcedCost": edge["outsourced_cost"],
        })
    foundation = {
        "schemaVersion": 1,
        "storagePolicy": "仓储能力充足，不设置仓容上限；留仓按吨·时段计库存成本",
        "time": config["time"],
        "network": {
            "nodeCount": len(nodes), "undirectedEdgeCount": len(edge_pairs),
            "maxStringStops": config["network"]["max_string_stops"],
            "nodes": nodes, "edges": edge_pairs,
        },
        "vehicle": config["vehicle"],
        "products": config["products"],
        "cost": config["cost"],
        "demand": config["demand"],
        "events": config["events"],
        "datasets": {
            "frozenMasterCases": 20, "activeTestCases": 12,
            "activePerCategory": 3, "validationCases": 80,
        },
    }
    write_json(OUTPUT_ROOT / "foundation.json", foundation)
    write_json(OUTPUT_ROOT / "cases.json", {"cases": summaries})
    write_json(OUTPUT_ROOT / "comparison.json", {
        "schemaVersion": 1,
        "methods": [
            {"methodId": method_id, "label": label, "dataStatus": status}
            for method_id, label, status in METHODS
        ],
        "metrics": all_metrics,
        "pairedAnalysis": build_paired_analysis(real_metrics, benders_metrics, benders_solutions),
        "threeMethodAnalysis": build_three_method_analysis(
            real_metrics, benders_metrics, qlearning_metrics,
            milp_solutions, benders_solutions, qlearning_solutions,
        ),
        "experimentSummary": {
            "completedCases": len(real_metrics),
            "validatedCases": sum(metric["validationStatus"] == "pass" for metric in real_metrics),
            "gurobiCalls": gurobi_calls,
            "sumSolverSeconds": round(sum(metric["runtimeSeconds"] for metric in real_metrics), 3),
            "timeLimitCalls": len(solver_limit_hits),
            "parallelElapsedSeconds": PARALLEL_RUN_EVIDENCE["seconds"],
            "parallelElapsedLabel": "≈30分25秒",
            "parallelElapsedIsInferred": True,
            "parallelElapsedEvidence": (
                f"由首个Gurobi日志创建时间 {PARALLEL_RUN_EVIDENCE['start']} 至最后一个独立验证文件写入时间 "
                f"{PARALLEL_RUN_EVIDENCE['end']} 推算；包含结果写盘与独立验证。"
            ),
        },
        "solverLimitHits": solver_limit_hits,
        "mockPolicy": "No mock method metrics are present; all three methods use validated frozen-test results.",
    })
    write_json(OUTPUT_ROOT / "animation-manifest.json", {
        "defaultCaseId": "test_urgent_insert_002",
        "cases": animation_manifest,
        "methods": [
            {"methodId": "milp", "dataStatus": "real", "cases": animation_manifest},
            {"methodId": "benders-cg", "dataStatus": "real", "cases": benders_animation_manifest},
            {"methodId": "tabular-hrl", "dataStatus": "real", "cases": qlearning_animation_manifest},
        ],
    })
    manifest = {
        "schemaVersion": 1,
        "realMethods": ["milp", "benders-cg", "tabular-hrl"],
        "caseCount": 12,
        "files": {
            "foundation": "data/foundation.json",
            "cases": "data/cases.json",
            "comparison": "data/comparison.json",
            "animationManifest": "data/animation-manifest.json",
        },
        "sources": [
            "results/gurobi_v6_12/test",
            "results/benders_cg_v6_12/test",
            "results/qlearning_v1/test",
        ],
        "sourceRawBytesByMethod": {
            "milp": sum((RESULT_DIR / f"{case_id}.json").stat().st_size for case_id in ordered_case_ids),
            "benders-cg": sum((BENDERS_RESULT_DIR / f"{case_id}.json").stat().st_size for case_id in ordered_case_ids),
            "tabular-hrl": sum((QLEARNING_RESULT_DIR / f"{case_id}.json").stat().st_size for case_id in ordered_case_ids),
        },
    }
    manifest["sourceRawBytes"] = sum(manifest["sourceRawBytesByMethod"].values())
    write_json(OUTPUT_ROOT / "manifest.json", manifest)
    first_load_bytes = sum(
        (OUTPUT_ROOT / filename).stat().st_size
        for filename in ("manifest.json", "foundation.json", "cases.json", "comparison.json", "animation-manifest.json")
    )
    if first_load_bytes > 500 * 1024:
        raise RuntimeError(f"Initial static data exceeds 500 KB: {first_load_bytes}")
    print(json.dumps({
        "status": "pass",
        "cases": 12,
        "initial_data_bytes": first_load_bytes,
        "animation_max_bytes": max(item["bytes"] for item in animation_manifest),
        "source_raw_bytes": manifest["sourceRawBytes"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
