from __future__ import annotations

import hashlib
import json
import math
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from freight_opt.config import load_config  # noqa: E402


RESULT_DIR = ROOT / "results" / "gurobi_v6_12" / "test"
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
    ("benders-cg", "Benders分解＋列生成", "mock"),
    ("tabular-hrl", "分层表格强化学习", "mock"),
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


def stable_unit(*parts: str) -> float:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    number = int.from_bytes(digest[:8], "big") / float(2**64 - 1)
    return 2.0 * number - 1.0


def mock_metric(method_id: str, case_id: str, metric: str, value: float | None) -> float | None:
    if value is None:
        return None
    unit = stable_unit("20260901", method_id, case_id, metric)
    if metric.endswith("OnTimeRate"):
        return min(1.0, max(0.0, value + 0.005 * unit))
    if metric in {"changedMissionTasks", "reroutedTons"}:
        return max(0.0, value * (1.0 + 0.08 * unit))
    return max(0.0, value * (1.0 + 0.04 * unit))


def aggregate_animation(solution: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    snapshots = []
    for snapshot in solution["plan_snapshots"]:
        flow_by_key: dict[tuple[Any, ...], float] = defaultdict(float)
        for itinerary in snapshot["cargo_itineraries"]:
            tons = float(itinerary["tons"])
            for leg in itinerary["legs"]:
                for segment in leg.get("segments", []):
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
                    for segment in mission["segments"]
                ],
            }
            for mission in snapshot["selected_missions"]
        ]
        nodes = []
        for node in snapshot["nodes"]:
            nodes.append({
                "nodeId": node["node_id"],
                "timeline": [
                    {
                        "slot": state["slot"],
                        "ownVehicles": state["own_vehicles"],
                        "handlingTons": state["handling_tons"],
                        "handlingCapacityTons": state["handling_capacity_tons"],
                        "handlingUtilization": state["handling_utilization"],
                        "inventoryTons": state["inventory_tons"],
                        "inventoryCost": state["inventory_cost"],
                        "releasedTons": state["released_tons"],
                        "cargoDepartureTons": state["cargo_departure_tons"],
                        "cargoArrivalTons": state["cargo_arrival_tons"],
                        "deliveredTons": state["delivered_tons"],
                        "ownVehicleDepartures": state["own_vehicle_departures"],
                        "externalVehicleDepartures": state["external_vehicle_departures"],
                    }
                    for state in node["timeline"]
                ],
            })
        snapshots.append({
            "snapshotId": snapshot["snapshot_id"],
            "decisionSlot": snapshot["decision_slot"],
            "decisionHour": snapshot["decision_hour"],
            "decisionType": snapshot["decision_type"],
            "triggerReasons": snapshot["trigger_reasons"],
            "objective": snapshot["objective"],
            "objectiveComponents": snapshot["objective_components"],
            "serviceRates": snapshot["service_rates"],
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
    animation_manifest = []
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

        actual = solution["actual"]
        components = solution["episode_objective_components"]
        rates = actual["service_rates"]
        runtime = float(solution["baseline"].get("runtime_seconds", 0.0)) + sum(
            float(step.get("runtime_seconds") or 0.0) for step in solution["rolling_steps"]
        )
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
        metric = {
            "methodId": "milp", "methodLabel": "MILP联合决策", "dataStatus": "real",
            "caseId": case_id, "category": category,
            "totalCost": solution["episode_objective"],
            "transportCost": components["transport"],
            "handlingCost": components["cargo_handling"],
            "inventoryCost": components["inventory_holding"],
            "transferCost": components["transfer"],
            "delayCost": components["delay"],
            "serviceShortfallCost": components["service_shortfall"],
            "changeCost": components["cumulative_change"],
            "runtimeSeconds": runtime,
            "completionHour": solution["completion_hour"],
            "urgentOnTimeRate": rates.get("urgent", {}).get("on_time_rate"),
            "standardOnTimeRate": rates.get("standard", {}).get("on_time_rate"),
            "economyOnTimeRate": rates.get("economy", {}).get("on_time_rate"),
            "changedMissionTasks": sum(
                float(step.get("change_metrics", {}).get("changed_future_mission_tasks") or 0.0)
                for step in solution["rolling_steps"]
            ),
            "reroutedTons": sum(
                float(step.get("change_metrics", {}).get("rerouted_previously_planned_tons") or 0.0)
                for step in solution["rolling_steps"]
            ),
            "caseStatus": solution["status"],
            "validationStatus": validation["status"],
            "baselineStatus": solution["baseline"]["status"],
            "finalStatus": actual["status"],
        }
        real_metrics.append(metric)

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

    assert first_case is not None
    all_metrics = list(real_metrics)
    metric_names = [
        "totalCost", "transportCost", "handlingCost", "inventoryCost",
        "transferCost", "delayCost", "serviceShortfallCost", "changeCost",
        "runtimeSeconds", "completionHour", "urgentOnTimeRate",
        "standardOnTimeRate", "economyOnTimeRate", "changedMissionTasks",
        "reroutedTons",
    ]
    for method_id, method_label, _ in METHODS[1:]:
        for real in real_metrics:
            mock = dict(real)
            mock.update({
                "methodId": method_id,
                "methodLabel": method_label,
                "dataStatus": "mock",
                "caseStatus": "mock_placeholder",
                "validationStatus": "not_run",
                "baselineStatus": "not_run",
                "finalStatus": "not_run",
            })
            for name in metric_names:
                mock[name] = mock_metric(method_id, real["caseId"], name, real.get(name))
            all_metrics.append(mock)

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
        "mockPolicy": (
            "Mock values are deterministic neutral perturbations for interface demonstration only. "
            "They are excluded from findings, rankings and significance claims."
        ),
    })
    write_json(OUTPUT_ROOT / "animation-manifest.json", {
        "defaultCaseId": "test_urgent_insert_002",
        "cases": animation_manifest,
        "methods": [
            {"methodId": "milp", "dataStatus": "real", "cases": animation_manifest},
            {"methodId": "benders-cg", "dataStatus": "mock", "cases": animation_manifest},
            {"methodId": "tabular-hrl", "dataStatus": "mock", "cases": animation_manifest},
        ],
    })
    manifest = {
        "schemaVersion": 1,
        "realMethod": "milp",
        "caseCount": 12,
        "files": {
            "foundation": "data/foundation.json",
            "cases": "data/cases.json",
            "comparison": "data/comparison.json",
            "animationManifest": "data/animation-manifest.json",
        },
        "source": "results/gurobi_v6_12/test",
        "sourceRawBytes": sum(
            (RESULT_DIR / f"{case_id}.json").stat().st_size for case_id in ordered_case_ids
        ),
    }
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
