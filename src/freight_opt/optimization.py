from __future__ import annotations

import math
import time
import copy
import os
import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

import gurobipy as gp
from gurobipy import GRB

from .candidates import (
    Itinerary,
    Mission,
    build_rides,
    build_services_and_missions,
    generate_itineraries,
)


STATUS_NAMES = {
    GRB.LOADED: "loaded",
    GRB.OPTIMAL: "optimal",
    GRB.INFEASIBLE: "infeasible",
    GRB.INF_OR_UNBD: "infeasible_or_unbounded",
    GRB.UNBOUNDED: "unbounded",
    GRB.CUTOFF: "cutoff",
    GRB.ITERATION_LIMIT: "iteration_limit",
    GRB.NODE_LIMIT: "node_limit",
    GRB.TIME_LIMIT: "time_limit",
    GRB.SOLUTION_LIMIT: "solution_limit",
    GRB.INTERRUPTED: "interrupted",
    GRB.NUMERIC: "numeric",
    GRB.SUBOPTIMAL: "suboptimal",
}


def determine_reoptimization_slot(case: dict[str, Any], config: dict[str, Any]) -> tuple[int, list[str]]:
    event = case["event"]
    if event["type"] != "none" and event.get("slot") is not None:
        return int(event["slot"]), [event["type"]]
    step = int(config["time"]["rolling_interval_slots"])
    return step, ["periodic_rolling"]


def trigger_reasons_at_slot(
    case: dict[str, Any], config: dict[str, Any], slot: int,
    current_plan: dict[str, Any] | None = None,
) -> list[str]:
    reasons: set[str] = set()
    event = case["event"]
    if event["type"] != "none" and event.get("slot") == slot:
        reasons.add(event["type"])
    if slot % int(config["time"]["rolling_interval_slots"]) == 0:
        reasons.add("periodic_rolling")
    return sorted(reasons)


def build_information_case(case: dict[str, Any], slot: int) -> dict[str, Any]:
    planning_case = copy.deepcopy(case)
    event = case["event"]
    event_has_occurred = event["type"] != "none" and event.get("slot") is not None and int(event["slot"]) <= slot
    cancelled = {
        item["demand_id"]: float(item["cancel_tons"])
        for item in (event.get("demand_adjustments") or [])
    } if event_has_occurred and event["type"] == "urgent_cancel" else {}
    for record in planning_case["demand"]:
        if record["id"].startswith("EMG_INSERT"):
            planned = float(record["actual_tons"]) if event_has_occurred else 0.0
        elif int(record["release_slot"]) <= slot:
            planned = float(record["actual_tons"])
        else:
            planned = max(0.0, float(record["forecast_tons"]) - cancelled.get(record["id"], 0.0))
        record["planning_tons"] = round(planned, 8)
    return planning_case


def _known_information_snapshot(
    planning_case: dict[str, Any], demand_field: str, decision_slot: int, slot_hours: int
) -> dict[str, Any]:
    event = planning_case.get("event", {})
    event_known = (
        event.get("type") not in (None, "none")
        and event.get("slot") is not None
        and int(event["slot"]) <= decision_slot
    )
    demands = []
    for record in planning_case["demand"]:
        release_slot = int(record["release_slot"])
        if record["id"].startswith("EMG_INSERT") and not event_known:
            source = "not_announced"
        elif release_slot <= decision_slot or demand_field == "actual_tons":
            source = "actual_observed"
        else:
            source = "forecast"
        demands.append({
            "demand_id": record["id"],
            "origin": record["origin"],
            "destination": record["destination"],
            "product": record["product"],
            "release_slot": release_slot,
            "known_tons": round(float(record[demand_field]), 8),
            "quantity_source": source,
            "admission_status": record.get("admission_status"),
        })
    return {
        "decision_slot": decision_slot,
        "decision_hour": decision_slot * slot_hours,
        "demand_field": demand_field,
        "demands": demands,
        "known_event": copy.deepcopy(event) if event_known else None,
    }


def _event_breakdown(case: dict[str, Any], include_event: bool) -> dict[tuple[str, int], int]:
    event = case["event"]
    if include_event and event["type"] == "vehicle_breakdown":
        return {(event["node"], int(event["slot"])): int(event["vehicle_count"])}
    return {}


def _resolve_breakdown_event(
    case: dict[str, Any], current_plan: dict[str, Any], slot: int,
) -> dict[str, Any] | None:
    """Resolve one failed vehicle from vehicles physically present at the event time.

    Cases fix the exogenous event time and magnitude.  The affected node is resolved
    against the latest published plan because vehicle locations are endogenous and
    may differ across solution methods.
    """
    event = copy.deepcopy(case["event"])
    count = int(event.get("vehicle_count") or 0)
    inventory = current_plan.get("vehicle_inventory", {})
    candidates = sorted(
        node["id"] for node in case["nodes"]
        if float(inventory.get(f"{node['id']}#{slot}", 0.0)) + 1e-7 >= count
    )
    if not candidates:
        return None
    preferred = event.get("node")
    if preferred in candidates:
        selected = preferred
    else:
        digest = hashlib.sha256(f"{case['case_id']}|{slot}|breakdown".encode("utf-8")).digest()
        selected = candidates[int.from_bytes(digest[:8], "big") % len(candidates)]
    event.update({
        "slot": slot,
        "node": selected,
        "selection_policy": "runtime_available_own_vehicle",
        "available_own_vehicles_before_failure": float(inventory[f"{selected}#{slot}"]),
    })
    return event


def _resolve_cancel_event(
    case: dict[str, Any], current_plan: dict[str, Any], slot: int,
) -> dict[str, Any] | None:
    """Resolve a cancellation only against cargo not departed at the event time."""
    event = copy.deepcopy(case["event"])
    target = float(event.get("tons") or 0.0)
    departed_by_demand: dict[str, float] = defaultdict(float)
    for item in current_plan.get("itineraries", []):
        if int(item.get("departure", 0)) < slot:
            departed_by_demand[item["demand_id"]] += float(item["tons"])
    candidates = []
    for record in case["demand"]:
        if record["id"].startswith("EMG_INSERT"):
            continue
        cancellable = max(
            0.0,
            float(record["actual_tons"]) - departed_by_demand.get(record["id"], 0.0),
        )
        if cancellable > 1e-7:
            candidates.append((record, cancellable))
    if sum(value for _, value in candidates) + 1e-7 < target:
        return None

    by_origin: dict[str, list[tuple[dict[str, Any], float]]] = defaultdict(list)
    for record, available in candidates:
        by_origin[record["origin"]].append((record, available))
    feasible_origins = sorted(
        origin for origin, values in by_origin.items()
        if sum(available for _, available in values) + 1e-7 >= target
    )
    digest = hashlib.sha256(f"{case['case_id']}|{slot}|cancel".encode("utf-8")).digest()
    if feasible_origins:
        origin = feasible_origins[int.from_bytes(digest[:8], "big") % len(feasible_origins)]
        selected_pool = by_origin[origin]
    else:
        origin = None
        selected_pool = candidates
    selected_pool = sorted(
        selected_pool,
        key=lambda item: hashlib.sha256(
            f"{case['case_id']}|{slot}|{item[0]['id']}".encode("utf-8")
        ).digest(),
    )
    remaining = target
    adjustments = []
    for record, available in selected_pool:
        cancelled = min(available, remaining)
        if cancelled > 1e-7:
            adjustments.append({
                "demand_id": record["id"],
                "cancel_tons": round(cancelled, 8),
            })
            remaining -= cancelled
        if remaining <= 1e-7:
            break
    if remaining > 1e-6:
        return None
    event.update({
        "slot": slot,
        "origin": origin,
        "demand_adjustments": adjustments,
        "selection_policy": "runtime_unshipped_cargo",
    })
    return event


def _resource_name(service_id: str, segment_index: int) -> str:
    return f"{service_id}#{segment_index}"


def solve_static(
    case: dict[str, Any],
    config: dict[str, Any],
    demand_field: str,
    *,
    reference: dict[str, Any] | None = None,
    change_slot: int | None = None,
    include_event: bool = False,
    verification: bool = False,
    output_log: str | None = None,
    model_context: dict[str, Any] | None = None,
    fixed_missions: dict[str, float] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    if model_context is not None and "services" in model_context:
        services = model_context["services"]
        all_missions = model_context["missions"]
        rides_by_origin = model_context["rides_by_origin"]
    else:
        services, all_missions = build_services_and_missions(case, config)
        rides_by_origin = build_rides(services)
        if model_context is not None:
            model_context.update({
                "services": services,
                "missions": all_missions,
                "rides_by_origin": rides_by_origin,
                "itinerary_cache": {},
            })
    itinerary_cache: dict[tuple[Any, ...], list[Itinerary]] = (
        model_context.setdefault("itinerary_cache", {})
        if model_context is not None else {}
    )
    cache_hits_before = int(model_context.get("itinerary_cache_hits", 0)) if model_context else 0
    cache_misses_before = int(model_context.get("itinerary_cache_misses", 0)) if model_context else 0

    def cached_itineraries(record: dict[str, Any]) -> list[Itinerary]:
        key = (
            record["id"], record["origin"], record["destination"], record["product"],
            int(record["release_slot"]),
            int(record.get("service_clock_slot", record["release_slot"])),
            str(record.get("candidate_key", record["id"])),
        )
        if key in itinerary_cache:
            if model_context is not None:
                model_context["itinerary_cache_hits"] = int(
                    model_context.get("itinerary_cache_hits", 0)
                ) + 1
        else:
            if model_context is not None:
                model_context["itinerary_cache_misses"] = int(
                    model_context.get("itinerary_cache_misses", 0)
                ) + 1
            itinerary_cache[key] = generate_itineraries(
                record, config, services, rides_by_origin
            )
        return itinerary_cache[key]

    missions = list(all_missions)
    active_demand = [
        record for record in case["demand"]
        if float(record[demand_field]) > 1e-9
        and record.get("admission_status") != "rejected"
    ]
    event = case.get("event", {})
    pending_insert_id = None
    if include_event and event.get("type") == "urgent_insert":
        candidate_id = event.get("demand_id")
        candidate_record = next(
            (record for record in active_demand if record["id"] == candidate_id), None
        )
        if candidate_record is not None and candidate_record.get("admission_status") is None:
            pending_insert_id = candidate_id
    itinerary_by_demand: dict[str, list[Itinerary]] = {}
    itinerary_admission_slot: dict[str, int] = {}
    for record in active_demand:
        if record["id"] == pending_insert_id:
            requested_slot = int(record["release_slot"])
            itineraries = []
            for admission_slot in range(requested_slot, int(config["time"]["observation_slots"])):
                admission_record = copy.deepcopy(record)
                admission_record["release_slot"] = admission_slot
                admission_record["service_clock_slot"] = requested_slot
                admission_record["candidate_key"] = f"{record['id']}_ADM{admission_slot}"
                slot_itineraries = cached_itineraries(admission_record)
                for itinerary in slot_itineraries:
                    itinerary_admission_slot[itinerary.id] = admission_slot
                itineraries.extend(slot_itineraries)
        else:
            itineraries = cached_itineraries(record)
        if not itineraries:
            if record["id"] == pending_insert_id:
                itinerary_by_demand[record["id"]] = []
                continue
            return {
                "case_id": case["case_id"], "status": "candidate_infeasible",
                "message": f"No legal itinerary for {record['id']}",
                "runtime_seconds": time.perf_counter() - started,
            }
        itinerary_by_demand[record["id"]] = itineraries

    used_services = {
        resource[0]
        for itineraries in itinerary_by_demand.values()
        for itinerary in itineraries
        for resource in itinerary.resource_keys
    }
    missions = [
        mission for mission in missions
        if mission.service_id in used_services or len(services[mission.service_id].route) == 2
    ]

    model = gp.Model(f"freight_{case['case_id']}_{demand_field}")
    model.Params.OutputFlag = 1 if output_log else 0
    if output_log:
        log_path = os.path.relpath(output_log, Path.cwd()) if Path(output_log).is_absolute() else output_log
        model.Params.LogFile = log_path
        model.Params.LogToConsole = 0
    model.Params.Seed = int(config["solver"]["random_seed"] % 2_000_000_000)
    model.Params.Threads = int(config["solver"].get("threads_per_worker", 0))
    model.Params.MIPGap = 0.0 if verification else float(config["solver"]["target_mip_gap"])
    if not verification:
        model.Params.TimeLimit = float(config["solver"]["formal_time_limit_seconds"])

    mission_vars: dict[str, gp.Var] = {}
    mission_by_id = {mission.id: mission for mission in missions}
    missions_by_service: dict[str, list[Mission]] = defaultdict(list)
    for mission in missions:
        variable_type = GRB.BINARY if mission.mode == "normal" else GRB.INTEGER
        mission_vars[mission.id] = model.addVar(
            lb=0, ub=mission.upper_bound, vtype=variable_type, name=f"y[{mission.id}]"
        )
        missions_by_service[mission.service_id].append(mission)
        if reference is not None:
            mission_vars[mission.id].Start = float(reference.get("missions", {}).get(mission.id, 0.0))
        if fixed_missions is not None:
            model.addConstr(
                mission_vars[mission.id] == float(fixed_missions.get(mission.id, 0.0)),
                name=f"decomposition_mission_fixed[{mission.id}]",
            )

    templates: dict[str, list[Mission]] = defaultdict(list)
    for mission in missions:
        if mission.template_id:
            templates[mission.template_id].append(mission)
    for template_id, variants in templates.items():
        model.addConstr(
            gp.quicksum(mission_vars[mission.id] for mission in variants) <= 1,
            name=f"normal_choice[{template_id}]",
        )

    node_by_id = {node["id"]: node for node in case["nodes"]}
    horizon = int(config["time"]["observation_slots"])
    own_missions = [mission for mission in missions if mission.vehicle_source == "own"]
    breakdown = _event_breakdown(case, include_event)
    vehicle_vars: dict[tuple[str, int], gp.Var] = {}
    total_own = sum(int(node["initial_own_vehicles"]) for node in case["nodes"])
    for node_id, node in node_by_id.items():
        for slot in range(horizon + 1):
            vehicle_vars[(node_id, slot)] = model.addVar(
                lb=0, ub=total_own, vtype=GRB.INTEGER, name=f"v[{node_id},{slot}]"
            )
        model.addConstr(
            vehicle_vars[(node_id, 0)] == int(node["initial_own_vehicles"]),
            name=f"initial_vehicle[{node_id}]",
        )
    for node_id in node_by_id:
        for slot in range(horizon):
            departures = gp.quicksum(
                mission_vars[mission.id] for mission in own_missions
                if mission.origin == node_id and mission.departure == slot
            )
            arrivals = gp.quicksum(
                mission_vars[mission.id] for mission in own_missions
                if mission.destination == node_id and mission.arrival == slot + 1
            )
            loss = breakdown.get((node_id, slot), 0)
            model.addConstr(
                vehicle_vars[(node_id, slot + 1)]
                == vehicle_vars[(node_id, slot)] - loss - departures + arrivals,
                name=f"vehicle_balance[{node_id},{slot}]",
            )
            if loss:
                model.addConstr(
                    vehicle_vars[(node_id, slot)] >= loss,
                    name=f"breakdown_available[{node_id},{slot}]",
                )

    for node_id, node in node_by_id.items():
        for slot in range(horizon):
            external = gp.quicksum(
                mission_vars[mission.id] for mission in missions
                if mission.vehicle_source == "external"
                and mission.origin == node_id and mission.departure == slot
            )
            model.addConstr(
                external <= int(node["external_vehicle_limit"][slot]),
                name=f"external_limit[{node_id},{slot}]",
            )

    demand_vars: dict[tuple[str, str], gp.Var] = {}
    itinerary_by_id: dict[str, Itinerary] = {}
    demand_by_id = {record["id"]: record for record in active_demand}
    admission_vars: dict[int, gp.Var] = {}
    admission_reject_var: gp.Var | None = None
    for record in active_demand:
        variables = []
        for itinerary in itinerary_by_demand[record["id"]]:
            itinerary_by_id[itinerary.id] = itinerary
            variable = model.addVar(
                lb=0, ub=float(record[demand_field]), vtype=GRB.CONTINUOUS,
                name=f"x[{itinerary.id}]",
            )
            demand_vars[(record["id"], itinerary.id)] = variable
            variables.append(variable)
        if record["id"] == pending_insert_id:
            total = float(record[demand_field])
            slots = sorted({
                itinerary_admission_slot[itinerary.id]
                for itinerary in itinerary_by_demand[record["id"]]
            })
            for admission_slot in slots:
                admission_vars[admission_slot] = model.addVar(
                    vtype=GRB.BINARY, name=f"insert_admit[{admission_slot}]"
                )
                model.addConstr(
                    gp.quicksum(
                        demand_vars[(record["id"], itinerary.id)]
                        for itinerary in itinerary_by_demand[record["id"]]
                        if itinerary_admission_slot[itinerary.id] == admission_slot
                    ) == total * admission_vars[admission_slot],
                    name=f"insert_allocation[{record['id']},{admission_slot}]",
                )
            admission_reject_var = model.addVar(vtype=GRB.BINARY, name="insert_reject")
            model.addConstr(
                gp.quicksum(admission_vars.values()) + admission_reject_var == 1,
                name=f"insert_admission_choice[{record['id']}]",
            )
        else:
            model.addConstr(
                gp.quicksum(variables) == float(record[demand_field]),
                name=f"demand_allocation[{record['id']}]",
            )

    if reference is not None:
        reference_flow = {
            (item["demand_id"], item["itinerary_id"]): float(item["tons"])
            for item in reference.get("itineraries", [])
        }
        reference_totals: dict[str, float] = defaultdict(float)
        for (demand_id, _), tons in reference_flow.items():
            reference_totals[demand_id] += tons
        for record in active_demand:
            total = float(record[demand_field])
            baseline_total = reference_totals.get(record["id"], 0.0)
            for itinerary in itinerary_by_demand[record["id"]]:
                variable = demand_vars[(record["id"], itinerary.id)]
                if baseline_total > 1e-9:
                    variable.Start = reference_flow.get((record["id"], itinerary.id), 0.0) * total / baseline_total
                else:
                    variable.Start = total if itinerary is itinerary_by_demand[record["id"]][0] else 0.0

    resource_flow_expr: dict[tuple[str, int], gp.LinExpr] = defaultdict(gp.LinExpr)
    demand_resource_flow_expr: dict[tuple[str, str, int], gp.LinExpr] = defaultdict(gp.LinExpr)
    handling_expr: dict[tuple[str, int], gp.LinExpr] = defaultdict(gp.LinExpr)
    storage_expr: dict[tuple[str, int], gp.LinExpr] = defaultdict(gp.LinExpr)
    for (demand_id, itinerary_id), variable in demand_vars.items():
        itinerary = itinerary_by_id[itinerary_id]
        for resource in itinerary.resource_keys:
            resource_flow_expr[resource] += variable
            demand_resource_flow_expr[(demand_id, resource[0], resource[1])] += variable
        for node_id, slot, operations in itinerary.handling_operations:
            handling_expr[(node_id, slot)] += operations * variable
        for node_id, slot in itinerary.storage_occupancy:
            storage_expr[(node_id, slot)] += variable

    capacity = float(config["vehicle"]["capacity_equivalent_tons"])
    for service in services.values():
        supplied = capacity * gp.quicksum(
            mission_vars[mission.id] for mission in missions_by_service[service.id]
        )
        for segment in service.segments:
            model.addConstr(
                resource_flow_expr[(service.id, segment.index)] <= supplied,
                name=f"trip_capacity[{service.id},{segment.index}]",
            )

    for node_id, node in node_by_id.items():
        for slot in range(horizon):
            model.addConstr(
                handling_expr[(node_id, slot)] <= float(node["handling_capacity"][slot]),
                name=f"handling[{node_id},{slot}]",
            )

    service_tons: dict[str, float] = defaultdict(float)
    service_tons_expr: dict[str, gp.LinExpr] = defaultdict(gp.LinExpr)
    ontime_expr: dict[str, gp.LinExpr] = defaultdict(gp.LinExpr)
    for record in active_demand:
        product = record["product"]
        total = float(record[demand_field])
        service_tons[product] += total
        if record["id"] == pending_insert_id and admission_reject_var is not None:
            service_tons_expr[product] += total * (1 - admission_reject_var)
        else:
            service_tons_expr[product] += total
        for itinerary in itinerary_by_demand[record["id"]]:
            if itinerary.delay_slots == 0:
                ontime_expr[product] += demand_vars[(record["id"], itinerary.id)]
    service_shortfall_vars: dict[str, gp.Var] = {}
    for product, maximum_total in service_tons.items():
        shortfall = model.addVar(
            lb=0.0, ub=maximum_total, name=f"service_shortfall[{product}]"
        )
        service_shortfall_vars[product] = shortfall
        model.addConstr(
            ontime_expr[product] + shortfall
            >= float(config["products"][product]["minimum_on_time_rate"])
            * service_tons_expr[product],
            name=f"service_level_soft[{product}]",
        )

    if reference is not None and change_slot is not None:
        for mission in missions:
            if mission.departure < change_slot:
                model.addConstr(
                    mission_vars[mission.id] == float(reference["missions"].get(mission.id, 0.0)),
                    name=f"executed_mission_fixed[{mission.id}]",
                )
        reference_demand_resource = reference.get("demand_resource_flow", {})
        past_keys = {
            key for key in demand_resource_flow_expr
            if services[key[1]].segments[key[2]].departure < change_slot
        }
        past_keys.update(
            tuple([parts[0], parts[1], int(parts[2])])
            for name in reference_demand_resource
            for parts in [name.split("|")]
            if parts[0] in demand_by_id
            and parts[1] in services
            and services[parts[1]].segments[int(parts[2])].departure < change_slot
        )
        for demand_id, service_id, segment_index in sorted(past_keys):
            key_name = f"{demand_id}|{service_id}|{segment_index}"
            model.addConstr(
                demand_resource_flow_expr[(demand_id, service_id, segment_index)]
                == float(reference_demand_resource.get(key_name, 0.0)),
                name=f"executed_cargo_fixed[{demand_id},{service_id},{segment_index}]",
            )

    transport_expr = gp.quicksum(
        mission.cost * mission_vars[mission.id] for mission in missions
    )
    handling_cost = float(config["cost"]["handling_per_ton_operation"])
    inventory_holding_cost = float(config["cost"]["inventory_holding_per_ton_slot"])
    transfer_cost = float(config["cost"]["transfer_extra_per_ton"])
    cargo_handling_expr = gp.quicksum(
        handling_cost * (2 + 2 * itinerary_by_id[itinerary_id].transfers) * variable
        for (_, itinerary_id), variable in demand_vars.items()
    )
    inventory_holding_expr = gp.quicksum(
        inventory_holding_cost * itinerary_by_id[itinerary_id].holding_slots * variable
        for (_, itinerary_id), variable in demand_vars.items()
    )
    transfer_expr = gp.quicksum(
        transfer_cost * itinerary_by_id[itinerary_id].transfers * variable
        for (_, itinerary_id), variable in demand_vars.items()
    )
    delay_expr = gp.quicksum(
        float(config["products"][demand_by_id[demand_id]["product"]]["delay_cost_per_ton_slot"])
        * itinerary_by_id[itinerary_id].delay_slots * variable
        for (demand_id, itinerary_id), variable in demand_vars.items()
    )
    cargo_expr = cargo_handling_expr + inventory_holding_expr + transfer_expr + delay_expr
    service_shortfall_expr = gp.quicksum(
        float(config["products"][product]["service_shortfall_penalty_per_ton"]) * variable
        for product, variable in service_shortfall_vars.items()
    )
    change_expr: gp.LinExpr = gp.LinExpr(0.0)
    trip_delta_vars: list[gp.Var] = []
    cargo_delta_vars: list[gp.Var] = []
    trip_denominator = 1.0
    cargo_denominator = 1.0
    if reference is not None and change_slot is not None:
        future_missions = [mission for mission in missions if mission.departure >= change_slot]
        baseline_trip_total = sum(
            float(reference["missions"].get(mission.id, 0.0)) for mission in future_missions
        )
        demand_vehicle_equivalent = sum(float(record[demand_field]) for record in active_demand) / capacity
        trip_denominator = max(1.0, baseline_trip_total + demand_vehicle_equivalent)
        for mission in future_missions:
            delta = model.addVar(lb=0, name=f"trip_delta[{mission.id}]")
            baseline = float(reference["missions"].get(mission.id, 0.0))
            model.addConstr(delta >= mission_vars[mission.id] - baseline)
            model.addConstr(delta >= baseline - mission_vars[mission.id])
            trip_delta_vars.append(delta)

        # Compare only cargo that existed in both plans.  New demand and removed
        # demand do not create a cargo-route change charge.  The half-L1 distance
        # between future itinerary allocations equals rerouted tons.
        reference_items_by_demand: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in reference.get("itineraries", []):
            reference_items_by_demand[item["demand_id"]].append(item)
        common_future_tons = 0.0
        for record in active_demand:
            demand_id = record["id"]
            reference_items = reference_items_by_demand.get(demand_id, [])
            reference_future = [item for item in reference_items if int(item["arrival"]) > change_slot]
            reference_future_total = sum(float(item["tons"]) for item in reference_future)
            completed_reference = sum(
                float(item["tons"]) for item in reference_items if int(item["arrival"]) <= change_slot
            )
            current_future_total = max(0.0, float(record[demand_field]) - completed_reference)
            overlap = min(reference_future_total, current_future_total)
            if overlap <= 1e-9:
                continue
            common_future_tons += overlap
            current_scale = overlap / current_future_total
            reference_scale = overlap / reference_future_total
            reference_flow = {
                item["itinerary_id"]: float(item["tons"]) * reference_scale
                for item in reference_future
            }
            current_itineraries = {
                itinerary.id: itinerary
                for itinerary in itinerary_by_demand[demand_id]
                if itinerary.arrival > change_slot
            }
            itinerary_ids = sorted(set(reference_flow) | set(current_itineraries))
            for itinerary_id in itinerary_ids:
                current_variable = demand_vars.get((demand_id, itinerary_id))
                current_expression = current_scale * current_variable if current_variable is not None else 0.0
                baseline = reference_flow.get(itinerary_id, 0.0)
                delta = model.addVar(lb=0, name=f"cargo_delta[{demand_id},{itinerary_id}]")
                model.addConstr(delta >= current_expression - baseline)
                model.addConstr(delta >= baseline - current_expression)
                cargo_delta_vars.append(delta)
        cargo_denominator = max(1.0, common_future_tons)

        reference_cost = max(1.0, float(reference["objective"]))
        rho = float(config["cost"]["balanced_change_penalty_ratio"])
        trip_weight = float(config["cost"]["trip_change_weight"])
        cargo_weight = float(config["cost"]["cargo_change_weight"])
        change_expr = rho * reference_cost * (
            trip_weight * gp.quicksum(trip_delta_vars) / trip_denominator
            + cargo_weight * 0.5 * gp.quicksum(cargo_delta_vars) / cargo_denominator
        )

    operating_cost_expr = (
        transport_expr + cargo_expr + service_shortfall_expr + change_expr
    )
    if pending_insert_id is not None and admission_reject_var is not None:
        requested_slot = int(demand_by_id[pending_insert_id]["release_slot"])
        admission_delay_expr = gp.quicksum(
            (slot - requested_slot) * variable
            for slot, variable in admission_vars.items()
        )
        model.ModelSense = GRB.MINIMIZE
        model.setObjectiveN(
            admission_reject_var, 0, priority=3, weight=1.0,
            abstol=0.0, reltol=0.0, name="avoid_insert_rejection",
        )
        model.setObjectiveN(
            admission_delay_expr, 1, priority=2, weight=1.0,
            abstol=0.0, reltol=0.0, name="earliest_insert_admission",
        )
        model.setObjectiveN(
            operating_cost_expr, 2, priority=1, weight=1.0,
            name="minimum_operating_cost",
        )
    else:
        admission_delay_expr = gp.LinExpr(0.0)
        model.setObjective(operating_cost_expr, GRB.MINIMIZE)
    model.optimize()

    status = STATUS_NAMES.get(model.Status, f"status_{model.Status}")
    result: dict[str, Any] = {
        "case_id": case["case_id"],
        "demand_field": demand_field,
        "status": status,
        "has_solution": model.SolCount > 0,
        "runtime_seconds": model.Runtime,
        "wall_seconds": time.perf_counter() - started,
        "candidate_counts": {
            "services": len(services), "missions": len(missions),
            "demands": len(active_demand),
            "itineraries": sum(len(value) for value in itinerary_by_demand.values()),
            "variables": model.NumVars, "constraints": model.NumConstrs,
            "itinerary_cache_entries": len(itinerary_cache),
            "itinerary_cache_hits_this_solve": (
                int(model_context.get("itinerary_cache_hits", 0)) - cache_hits_before
                if model_context is not None else 0
            ),
            "itinerary_cache_misses_this_solve": (
                int(model_context.get("itinerary_cache_misses", 0)) - cache_misses_before
                if model_context is not None else len(active_demand)
            ),
        },
    }
    if model.SolCount <= 0:
        if model.Status in (GRB.INFEASIBLE, GRB.INF_OR_UNBD):
            model.computeIIS()
            result["iis_constraints"] = [constraint.ConstrName for constraint in model.getConstrs() if constraint.IISConstr]
        return result

    mission_values = {
        mission.id: round(mission_vars[mission.id].X, 8)
        for mission in missions if mission_vars[mission.id].X > 1e-7
    }
    selected_missions = []
    for mission_id, count in mission_values.items():
        mission = mission_by_id[mission_id]
        service = services[mission.service_id]
        selected_missions.append({
            "mission_id": mission.id,
            "service_id": mission.service_id,
            "vehicle_count": count,
            "mode": mission.mode,
            "vehicle_source": mission.vehicle_source,
            "route": list(service.route),
            "origin": mission.origin,
            "destination": mission.destination,
            "departure_slot": mission.departure,
            "arrival_slot": mission.arrival,
            "unit_cost": mission.cost,
            "total_cost": round(mission.cost * count, 8),
            "segments": [
                {
                    "segment_index": segment.index,
                    "edge_id": segment.edge_id,
                    "origin": segment.origin,
                    "destination": segment.destination,
                    "departure_slot": segment.departure,
                    "arrival_slot": segment.arrival,
                }
                for segment in service.segments
            ],
        })
    itinerary_values = []
    for (demand_id, itinerary_id), variable in demand_vars.items():
        if variable.X <= 1e-7:
            continue
        itinerary = itinerary_by_id[itinerary_id]
        record = demand_by_id[demand_id]
        itinerary_values.append({
            "demand_id": demand_id,
            "itinerary_id": itinerary_id,
            "tons": round(variable.X, 8),
            "product": record["product"],
            "origin": record["origin"],
            "destination": record["destination"],
            "release_slot": int(record["release_slot"]),
            "service_clock_slot": int(record.get("service_clock_slot", record["release_slot"])),
            "ride_ids": [ride.id for ride in itinerary.rides],
            "service_ids": [ride.service_id for ride in itinerary.rides],
            "departure": itinerary.rides[0].departure,
            "arrival": itinerary.arrival,
            "transfers": itinerary.transfers,
            "inventory_slots": itinerary.holding_slots,
            "holding_slots": itinerary.holding_slots,
            "delay_slots": itinerary.delay_slots,
            "variable_cost_per_ton": itinerary.variable_cost_per_ton,
            "admission_slot": itinerary_admission_slot.get(itinerary_id),
            "inventory_occupancy": [
                {"node_id": node_id, "slot": slot}
                for node_id, slot in itinerary.storage_occupancy
            ],
            "handling_operations": [
                {"node_id": node_id, "slot": slot, "operations": operations}
                for node_id, slot, operations in itinerary.handling_operations
            ],
            "legs": [
                {
                    "ride_id": ride.id,
                    "service_id": ride.service_id,
                    "origin": ride.origin,
                    "destination": ride.destination,
                    "departure_slot": ride.departure,
                    "arrival_slot": ride.arrival,
                    "traversed_nodes": list(ride.traversed_nodes),
                    "covered_segments": list(ride.covered_segments),
                    "segments": [
                        {
                            "segment_index": segment.index,
                            "edge_id": segment.edge_id,
                            "origin": segment.origin,
                            "destination": segment.destination,
                            "departure_slot": segment.departure,
                            "arrival_slot": segment.arrival,
                        }
                        for segment in services[ride.service_id].segments
                        if segment.index in ride.covered_segments
                    ],
                }
                for ride in itinerary.rides
            ],
        })
    resource_values = {
        _resource_name(*resource): round(expression.getValue(), 8)
        for resource, expression in resource_flow_expr.items()
        if expression.getValue() > 1e-7
    }
    demand_resource_values = {
        f"{demand_id}|{service_id}|{segment_index}": round(expression.getValue(), 8)
        for (demand_id, service_id, segment_index), expression in demand_resource_flow_expr.items()
        if expression.getValue() > 1e-7
    }
    service_rates = {}
    for product in service_tons:
        total = service_tons_expr[product].getValue()
        ontime = ontime_expr[product].getValue()
        shortfall = service_shortfall_vars[product].X
        service_rates[product] = {
            "total_tons": total,
            "on_time_tons": ontime,
            "on_time_rate": ontime / total if total else 1.0,
            "required_rate": float(config["products"][product]["minimum_on_time_rate"]),
            "shortfall_tons": shortfall,
            "shortfall_rate": shortfall / total if total else 0.0,
            "shortfall_penalty_per_ton": float(
                config["products"][product]["service_shortfall_penalty_per_ton"]
            ),
        }
    insert_decision = None
    if pending_insert_id is not None and admission_reject_var is not None:
        record = demand_by_id[pending_insert_id]
        requested_slot = int(record["release_slot"])
        selected_slot = next(
            (slot for slot, variable in admission_vars.items() if variable.X > 0.5), None
        )
        rejected = admission_reject_var.X > 0.5
        insert_decision = {
            "demand_id": pending_insert_id,
            "requested_slot": requested_slot,
            "requested_hour": requested_slot * int(config["time"]["slot_hours"]),
            "status": (
                "rejected_within_observation_horizon" if rejected
                else ("accepted_immediately" if selected_slot == requested_slot else "accepted_deferred")
            ),
            "admission_slot": selected_slot,
            "admission_hour": (
                selected_slot * int(config["time"]["slot_hours"])
                if selected_slot is not None else None
            ),
            "defer_slots": (
                selected_slot - requested_slot if selected_slot is not None else None
            ),
            "defer_hours": (
                (selected_slot - requested_slot) * int(config["time"]["slot_hours"])
                if selected_slot is not None else None
            ),
            "service_clock_slot": requested_slot,
            "service_clock_reset": False,
            "requested_tons": float(record[demand_field]),
        }
    elif event.get("type") == "urgent_insert":
        fixed_record = next(
            (record for record in active_demand if record["id"] == event.get("demand_id")), None
        )
        if fixed_record is not None and fixed_record.get("admission_status") is not None:
            requested_slot = int(fixed_record.get("service_clock_slot", event.get("slot", 0)))
            selected_slot = int(fixed_record["release_slot"])
            insert_decision = {
                "demand_id": fixed_record["id"],
                "requested_slot": requested_slot,
                "requested_hour": requested_slot * int(config["time"]["slot_hours"]),
                "status": fixed_record["admission_status"],
                "admission_slot": selected_slot,
                "admission_hour": selected_slot * int(config["time"]["slot_hours"]),
                "defer_slots": selected_slot - requested_slot,
                "defer_hours": (selected_slot - requested_slot) * int(config["time"]["slot_hours"]),
                "service_clock_slot": requested_slot,
                "service_clock_reset": False,
                "requested_tons": float(fixed_record[demand_field]),
            }

    vehicle_inventory_values = {
        f"{node_id}#{slot}": round(variable.X, 8)
        for (node_id, slot), variable in vehicle_vars.items()
    }
    node_timeline: dict[str, list[dict[str, Any]]] = {}
    for node_id, node in node_by_id.items():
        timeline = []
        for slot in range(horizon + 1):
            handling_tons = (
                round(handling_expr[(node_id, slot)].getValue(), 8)
                if slot < horizon else 0.0
            )
            inventory_tons = (
                round(storage_expr[(node_id, slot)].getValue(), 8)
                if slot < horizon else 0.0
            )
            handling_capacity = (
                float(node["handling_capacity"][slot]) if slot < horizon else None
            )
            timeline.append({
                "slot": slot,
                "hour": slot * int(config["time"]["slot_hours"]),
                "own_vehicles": vehicle_inventory_values[f"{node_id}#{slot}"],
                "handling_tons": handling_tons,
                "handling_capacity_tons": handling_capacity,
                "handling_utilization": (
                    handling_tons / handling_capacity
                    if handling_capacity not in (None, 0.0) else None
                ),
                "inventory_tons": inventory_tons,
                "inventory_cost": round(inventory_tons * inventory_holding_cost, 8),
                "released_tons": 0.0,
                "cargo_departure_tons": 0.0,
                "cargo_arrival_tons": 0.0,
                "delivered_tons": 0.0,
                "own_vehicle_departures": 0.0,
                "own_vehicle_arrivals": 0.0,
                "external_vehicle_departures": 0.0,
                "external_vehicle_arrivals": 0.0,
                "vehicle_segment_departures": [],
                "vehicle_segment_arrivals": [],
                "mission_departures": [],
                "mission_arrivals": [],
                "cargo_departures": [],
                "cargo_arrivals": [],
                "deliveries": [],
                "demand_releases": [],
            })
        node_timeline[node_id] = timeline

    for record in active_demand:
        released = float(record[demand_field])
        if record["id"] == pending_insert_id and admission_reject_var is not None:
            if admission_reject_var.X > 0.5:
                continue
        if released <= 1e-9:
            continue
        slot = int(record["release_slot"])
        if slot > horizon:
            continue
        state = node_timeline[record["origin"]][slot]
        state["released_tons"] = round(state["released_tons"] + released, 8)
        state["demand_releases"].append({
            "demand_id": record["id"],
            "product": record["product"],
            "destination": record["destination"],
            "tons": round(released, 8),
        })

    for mission in selected_missions:
        for segment in mission["segments"]:
            node_timeline[segment["origin"]][segment["departure_slot"]][
                "vehicle_segment_departures"
            ].append({
                "mission_id": mission["mission_id"],
                "segment_index": segment["segment_index"],
                "destination": segment["destination"],
                "vehicle_source": mission["vehicle_source"],
                "vehicle_count": mission["vehicle_count"],
            })
            node_timeline[segment["destination"]][segment["arrival_slot"]][
                "vehicle_segment_arrivals"
            ].append({
                "mission_id": mission["mission_id"],
                "segment_index": segment["segment_index"],
                "origin": segment["origin"],
                "vehicle_source": mission["vehicle_source"],
                "vehicle_count": mission["vehicle_count"],
            })
        departure_state = node_timeline[mission["origin"]][mission["departure_slot"]]
        departure_state["mission_departures"].append({
            "mission_id": mission["mission_id"],
            "route": mission["route"],
            "vehicle_source": mission["vehicle_source"],
            "mode": mission["mode"],
            "vehicle_count": mission["vehicle_count"],
        })
        if mission["vehicle_source"] == "own":
            departure_state["own_vehicle_departures"] = round(
                departure_state["own_vehicle_departures"] + mission["vehicle_count"], 8
            )
            arrival_state = node_timeline[mission["destination"]][mission["arrival_slot"]]
            arrival_state["own_vehicle_arrivals"] = round(
                arrival_state["own_vehicle_arrivals"] + mission["vehicle_count"], 8
            )
            arrival_state["mission_arrivals"].append({
                "mission_id": mission["mission_id"],
                "route": mission["route"],
                "vehicle_count": mission["vehicle_count"],
            })
        else:
            departure_state["external_vehicle_departures"] = round(
                departure_state["external_vehicle_departures"] + mission["vehicle_count"], 8
            )
            arrival_state = node_timeline[mission["destination"]][mission["arrival_slot"]]
            arrival_state["external_vehicle_arrivals"] = round(
                arrival_state["external_vehicle_arrivals"] + mission["vehicle_count"], 8
            )
            arrival_state["mission_arrivals"].append({
                "mission_id": mission["mission_id"],
                "route": mission["route"],
                "vehicle_source": mission["vehicle_source"],
                "vehicle_count": mission["vehicle_count"],
            })

    for itinerary in itinerary_values:
        tons = float(itinerary["tons"])
        for leg in itinerary["legs"]:
            departure_state = node_timeline[leg["origin"]][leg["departure_slot"]]
            arrival_state = node_timeline[leg["destination"]][leg["arrival_slot"]]
            departure_state["cargo_departure_tons"] = round(
                departure_state["cargo_departure_tons"] + tons, 8
            )
            arrival_state["cargo_arrival_tons"] = round(
                arrival_state["cargo_arrival_tons"] + tons, 8
            )
            departure_state["cargo_departures"].append({
                "demand_id": itinerary["demand_id"],
                "itinerary_id": itinerary["itinerary_id"],
                "service_id": leg["service_id"],
                "destination": leg["destination"],
                "tons": tons,
            })
            arrival_state["cargo_arrivals"].append({
                "demand_id": itinerary["demand_id"],
                "itinerary_id": itinerary["itinerary_id"],
                "service_id": leg["service_id"],
                "origin": leg["origin"],
                "tons": tons,
            })
        delivery_state = node_timeline[itinerary["destination"]][itinerary["arrival"]]
        delivery_state["delivered_tons"] = round(delivery_state["delivered_tons"] + tons, 8)
        delivery_state["deliveries"].append({
            "demand_id": itinerary["demand_id"],
            "itinerary_id": itinerary["itinerary_id"],
            "product": itinerary["product"],
            "tons": tons,
            "delay_slots": itinerary["delay_slots"],
        })

    plan_snapshot = {
        "schema_version": 1,
        "slot_hours": int(config["time"]["slot_hours"]),
        "observation_slots": horizon,
        "storage_policy": "capacity_assumed_sufficient_no_upper_bound",
        "solver": {
            "status": status,
            "runtime_seconds": model.Runtime,
            "mip_gap": (
                None if pending_insert_id is not None
                else (model.MIPGap if math.isfinite(model.MIPGap) else None)
            ),
        },
        "objective": operating_cost_expr.getValue(),
        "objective_components": {
            "transport": transport_expr.getValue(),
            "cargo_handling": cargo_handling_expr.getValue(),
            "inventory_holding": inventory_holding_expr.getValue(),
            "transfer": transfer_expr.getValue(),
            "delay": delay_expr.getValue(),
            "service_shortfall": service_shortfall_expr.getValue(),
            "change": change_expr.getValue(),
        },
        "service_rates": copy.deepcopy(service_rates),
        "insert_decision": copy.deepcopy(insert_decision),
        "selected_missions": selected_missions,
        "cargo_itineraries": copy.deepcopy(itinerary_values),
        "nodes": [
            {"node_id": node_id, "timeline": node_timeline[node_id]}
            for node_id in sorted(node_timeline)
        ],
    }

    result.update({
        "objective": operating_cost_expr.getValue(),
        "best_bound": None if pending_insert_id is not None else model.ObjBound,
        "mip_gap": (
            None if pending_insert_id is not None
            else (model.MIPGap if math.isfinite(model.MIPGap) else None)
        ),
        "objective_components": {
            "transport": transport_expr.getValue(),
            "cargo_handling": cargo_handling_expr.getValue(),
            "inventory_holding": inventory_holding_expr.getValue(),
            "transfer": transfer_expr.getValue(),
            "delay": delay_expr.getValue(),
            "service_shortfall": service_shortfall_expr.getValue(),
            "change": change_expr.getValue(),
        },
        "missions": mission_values,
        "itineraries": itinerary_values,
        "resource_flow": resource_values,
        "demand_resource_flow": demand_resource_values,
        "service_rates": service_rates,
        "insert_decision": insert_decision,
        "vehicle_inventory": vehicle_inventory_values,
        "plan_snapshot": plan_snapshot,
        "change_metrics": {
            "changed_future_mission_tasks": sum(variable.X for variable in trip_delta_vars),
            "rerouted_previously_planned_tons": 0.5 * sum(
                variable.X for variable in cargo_delta_vars
            ),
            "mission_change_rate": (
                sum(variable.X for variable in trip_delta_vars) / trip_denominator
            ),
            "cargo_reroute_rate": (
                0.5 * sum(variable.X for variable in cargo_delta_vars) / cargo_denominator
            ),
        },
        "max_node_handling_utilization": max(
            (
                (
                    handling_expr[(node_id, slot)].getValue()
                    / float(node["handling_capacity"][slot])
                    if float(node["handling_capacity"][slot]) > 0.0
                    else (0.0 if handling_expr[(node_id, slot)].getValue() <= 1e-9 else math.inf)
                )
                for node_id, node in node_by_id.items() for slot in range(horizon)
            ),
            default=0.0,
        ),
    })
    return result


def solve_case(
    case: dict[str, Any], config: dict[str, Any], verification: bool = False,
    output_log_dir: str | Path | None = None,
    stop_after_slot: int | None = None,
    static_solver: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    log_dir = Path(output_log_dir) if output_log_dir is not None else None
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
    runtime_case = copy.deepcopy(case)
    model_context: dict[str, Any] = {}
    initial_information = build_information_case(runtime_case, 0)
    selected_static_solver = static_solver or solve_static
    baseline = selected_static_solver(
        initial_information, config, "planning_tons", include_event=False, verification=verification,
        output_log=str(log_dir / f"{case['case_id']}_baseline.log") if log_dir else None,
        model_context=model_context,
    )
    if not baseline.get("has_solution"):
        return {"case_id": case["case_id"], "status": "baseline_failed", "baseline": baseline}

    slot_hours = int(config["time"]["slot_hours"])
    baseline_snapshot = baseline.pop("plan_snapshot")
    baseline_snapshot.update({
        "snapshot_id": "plan_000_baseline",
        "decision_slot": 0,
        "decision_hour": 0,
        "decision_type": "baseline",
        "trigger_reasons": ["day_start_plan"],
        "plan_before_snapshot_id": None,
        "known_information": _known_information_snapshot(
            initial_information, "planning_tons", 0, slot_hours
        ),
    })
    plan_snapshots: list[dict[str, Any]] = [baseline_snapshot]

    current_plan = baseline
    rolling_steps: list[dict[str, Any]] = []
    cumulative_change_cost = 0.0
    horizon = int(config["time"]["observation_slots"])
    rolling_step = int(config["time"]["rolling_interval_slots"])
    regular_arrivals = [int(slot) for slot in config["time"]["regular_arrival_slots"]]
    last_regular_arrival = max(regular_arrivals)
    event = runtime_case["event"]
    event_slot = int(event["slot"]) if event["type"] != "none" and event.get("slot") is not None else None
    scheduled_event_slot = event_slot
    realized_event: dict[str, Any] | None = None
    insert_decision_record: dict[str, Any] | None = None
    diagnostic_stopped_at_slot: int | None = None
    decision_slots = set(range(rolling_step, horizon, rolling_step))
    if event_slot is not None:
        decision_slots.add(event_slot)
    if event["type"] == "vehicle_breakdown":
        decision_slots.update(int(slot) for slot in config["events"]["vehicle_breakdown_slots"])

    for slot in sorted(decision_slots):
        completion_slot = max(
            (int(item["arrival"]) for item in current_plan.get("itineraries", [])),
            default=0,
        )
        future_event_pending = event_slot is not None and event_slot > slot
        if slot > last_regular_arrival and completion_slot <= slot and not future_event_pending:
            break

        if event["type"] == "vehicle_breakdown" and realized_event is None and slot == event_slot:
            resolved = _resolve_breakdown_event(runtime_case, current_plan, slot)
            if resolved is None:
                future_candidates = [
                    int(candidate) for candidate in config["events"]["vehicle_breakdown_slots"]
                    if int(candidate) > slot and any(
                        float(current_plan.get("vehicle_inventory", {}).get(
                            f"{node['id']}#{int(candidate)}", 0.0
                        )) >= int(event.get("vehicle_count") or 0)
                        for node in runtime_case["nodes"]
                    )
                ]
                if not future_candidates:
                    return {
                        "case_id": runtime_case["case_id"],
                        "category": runtime_case["category"],
                        "status": "breakdown_event_has_no_available_own_vehicle",
                        "baseline": baseline,
                        "rolling_steps": rolling_steps,
                        "plan_snapshots": plan_snapshots,
                        "scheduled_event_slot": scheduled_event_slot,
                        "cumulative_change_cost": cumulative_change_cost,
                    }
                event_slot = min(future_candidates)
                runtime_case["event"]["slot"] = event_slot
                event = runtime_case["event"]
            else:
                runtime_case["event"] = resolved
                event = runtime_case["event"]
                realized_event = copy.deepcopy(resolved)

        if event["type"] == "urgent_cancel" and realized_event is None and slot == event_slot:
            resolved = _resolve_cancel_event(runtime_case, current_plan, slot)
            if resolved is None:
                return {
                    "case_id": runtime_case["case_id"],
                    "category": runtime_case["category"],
                    "status": "cancel_event_has_insufficient_unshipped_cargo",
                    "baseline": baseline,
                    "rolling_steps": rolling_steps,
                    "plan_snapshots": plan_snapshots,
                    "scheduled_event_slot": scheduled_event_slot,
                    "cumulative_change_cost": cumulative_change_cost,
                }
            cancelled_by_id = {
                item["demand_id"]: float(item["cancel_tons"])
                for item in resolved.get("demand_adjustments", [])
            }
            for record in runtime_case["demand"]:
                record["actual_tons"] = round(
                    max(0.0, float(record["actual_tons"]) - cancelled_by_id.get(record["id"], 0.0)),
                    8,
                )
            runtime_case["event"] = resolved
            event = runtime_case["event"]
            realized_event = copy.deepcopy(resolved)

        reasons = trigger_reasons_at_slot(runtime_case, config, slot, current_plan)
        if not reasons:
            continue
        information_case = build_information_case(runtime_case, slot)
        include_known_event = (
            event["type"] != "none" and event.get("slot") is not None
            and int(event["slot"]) <= slot
        )
        all_information_known = slot >= last_regular_arrival and (
            event_slot is None or event_slot <= slot
        )
        planning_case = runtime_case if all_information_known else information_case
        demand_field = "actual_tons" if all_information_known else "planning_tons"
        decision_type = "event" if event_slot == slot else "periodic"
        if event_slot == slot and slot % rolling_step == 0:
            decision_type = "periodic_and_event"
        next_plan = selected_static_solver(
            planning_case, config, demand_field, reference=current_plan,
            change_slot=slot, include_event=include_known_event,
            verification=verification,
            output_log=str(log_dir / f"{case['case_id']}_slot{slot}_{decision_type}.log") if log_dir else None,
            model_context=model_context,
        )
        step_record = {
            "slot": slot,
            "hour": slot * int(config["time"]["slot_hours"]),
            "decision_type": decision_type,
            "reasons": reasons,
            "status": next_plan.get("status"),
            "objective": next_plan.get("objective"), "mip_gap": next_plan.get("mip_gap"),
            "runtime_seconds": next_plan.get("runtime_seconds"),
            "objective_components": copy.deepcopy(next_plan.get("objective_components", {})),
            "service_rates": copy.deepcopy(next_plan.get("service_rates", {})),
            "insert_decision": copy.deepcopy(next_plan.get("insert_decision")),
            "change_metrics": copy.deepcopy(next_plan.get("change_metrics", {})),
            "solver_method": next_plan.get("solver_method", "joint_milp"),
            "decomposition_trace": copy.deepcopy(next_plan.get("decomposition_trace")),
            "incurred_change_cost": float(
                next_plan.get("objective_components", {}).get("change", 0.0)
            ),
            "plan_before_snapshot_id": plan_snapshots[-1]["snapshot_id"],
            "plan_after_snapshot_id": None,
        }
        rolling_steps.append(step_record)
        if not next_plan.get("has_solution"):
            return {
                "case_id": case["case_id"], "category": case["category"],
                "status": f"rolling_failed_at_slot_{slot}", "baseline": baseline,
                "rolling_steps": rolling_steps, "failed_plan": next_plan,
                "plan_snapshots": plan_snapshots,
                "scheduled_event_slot": scheduled_event_slot,
                "realized_event": realized_event,
                "cumulative_change_cost": cumulative_change_cost,
            }
        if event["type"] == "urgent_insert" and event_slot == slot:
            decision = next_plan.get("insert_decision")
            if decision is None:
                return {
                    "case_id": case["case_id"], "category": case["category"],
                    "status": f"insert_admission_decision_missing_at_slot_{slot}",
                    "baseline": baseline, "rolling_steps": rolling_steps,
                    "plan_snapshots": plan_snapshots,
                    "failed_plan": next_plan,
                }
            insert_decision_record = copy.deepcopy(decision)
            demand_id = decision["demand_id"]
            inserted_record = next(
                record for record in runtime_case["demand"] if record["id"] == demand_id
            )
            inserted_record["service_clock_slot"] = int(decision["requested_slot"])
            inserted_record["admission_status"] = str(decision["status"])
            if decision["admission_slot"] is None:
                inserted_record["admission_status"] = "rejected"
            else:
                admission_slot = int(decision["admission_slot"])
                inserted_record["release_slot"] = admission_slot
                inserted_record["candidate_key"] = f"{demand_id}_ADM{admission_slot}"
            event.update({
                "requested_slot": int(decision["requested_slot"]),
                "admission_slot": decision["admission_slot"],
                "admission_status": decision["status"],
                "service_clock_reset": False,
            })
            runtime_case["event"] = event
            realized_event = copy.deepcopy(event)
        cumulative_change_cost += step_record["incurred_change_cost"]
        step_record["cumulative_change_cost"] = cumulative_change_cost
        plan_snapshot = next_plan.pop("plan_snapshot")
        snapshot_id = f"plan_{len(plan_snapshots):03d}_slot_{slot}"
        plan_snapshot.update({
            "snapshot_id": snapshot_id,
            "decision_slot": slot,
            "decision_hour": slot * slot_hours,
            "decision_type": decision_type,
            "trigger_reasons": copy.deepcopy(reasons),
            "plan_before_snapshot_id": step_record["plan_before_snapshot_id"],
            "known_information": _known_information_snapshot(
                planning_case, demand_field, slot, slot_hours
            ),
        })
        plan_snapshots.append(plan_snapshot)
        step_record["plan_after_snapshot_id"] = snapshot_id
        current_plan = next_plan
        if insert_decision_record is not None:
            current_plan["insert_decision"] = copy.deepcopy(insert_decision_record)
        if stop_after_slot is not None and slot >= stop_after_slot:
            diagnostic_stopped_at_slot = slot
            break
    actual = current_plan
    final_completion_slot = max(
        (int(item["arrival"]) for item in actual.get("itineraries", [])),
        default=0,
    )
    final_components = actual.get("objective_components", {})
    episode_components = {
        "transport": float(final_components.get("transport", 0.0)),
        "cargo_handling": float(final_components.get("cargo_handling", 0.0)),
        "inventory_holding": float(final_components.get("inventory_holding", 0.0)),
        "transfer": float(final_components.get("transfer", 0.0)),
        "delay": float(final_components.get("delay", 0.0)),
        "service_shortfall": float(final_components.get("service_shortfall", 0.0)),
        "cumulative_change": cumulative_change_cost,
    }
    return {
        "result_schema_version": int(config.get("result_schema_version", 1)),
        "model_protocol_version": int(config.get("model_protocol_version", 1)),
        "case_id": case["case_id"],
        "category": case["category"],
        "status": (
            f"diagnostic_complete_through_slot_{diagnostic_stopped_at_slot}"
            if diagnostic_stopped_at_slot is not None
            else ("complete" if actual.get("has_solution") else "actual_failed")
        ),
        "trigger_slot": rolling_steps[0]["slot"] if rolling_steps else 0,
        "trigger_reasons": rolling_steps[0]["reasons"] if rolling_steps else ["initial_plan_only"],
        "event_slot": event_slot,
        "event_hour": event_slot * int(config["time"]["slot_hours"]) if event_slot is not None else None,
        "completion_slot": final_completion_slot,
        "completion_hour": final_completion_slot * int(config["time"]["slot_hours"]),
        "rolling_steps": rolling_steps,
        "plan_snapshots": plan_snapshots,
        "baseline": baseline,
        "actual": actual,
        "scheduled_event_slot": scheduled_event_slot,
        "realized_event": realized_event,
        "insert_decision": insert_decision_record,
        "episode_objective": sum(episode_components.values()),
        "episode_objective_components": episode_components,
        "cumulative_change_cost": cumulative_change_cost,
        "diagnostic_stopped_at_slot": diagnostic_stopped_at_slot,
        "model_scope_note": (
            "Three-hour internal clock; periodic replanning every six hours plus one possible off-cycle event. "
            "Only revealed demand and occurred events are known, and executed missions/cargo flows are fixed. "
            "Storage capacity is assumed sufficient; retained inventory remains costed by ton-slot."
        ),
    }
