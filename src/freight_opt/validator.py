from __future__ import annotations

import copy
from collections import defaultdict
from typing import Any

from .candidates import build_rides, build_services_and_missions, generate_itineraries
from .optimization import build_information_case


TOL = 1e-5


def _resource_name(service_id: str, segment_index: int) -> str:
    return f"{service_id}#{segment_index}"


def validate_static(
    case: dict[str, Any], config: dict[str, Any], result: dict[str, Any], *, include_event: bool
) -> dict[str, Any]:
    errors: list[str] = []
    if not result.get("has_solution"):
        return {"status": "fail", "errors": [f"No solution: {result.get('status')}"]}
    demand_field = result["demand_field"]
    services, missions = build_services_and_missions(case, config)
    rides_by_origin = build_rides(services)
    mission_by_id = {mission.id: mission for mission in missions}
    mission_values = defaultdict(float, result.get("missions", {}))

    for mission_id, value in mission_values.items():
        if mission_id not in mission_by_id:
            errors.append(f"Unknown mission {mission_id}")
        elif value < -TOL or value > mission_by_id[mission_id].upper_bound + TOL:
            errors.append(f"Mission bound violation {mission_id}")

    template_use: dict[str, float] = defaultdict(float)
    for mission in missions:
        if mission.template_id:
            template_use[mission.template_id] += mission_values[mission.id]
    for template, value in template_use.items():
        if value > 1.0 + TOL:
            errors.append(f"Normal template {template} selects {value}")

    horizon = int(config["time"]["observation_slots"])
    node_by_id = {node["id"]: node for node in case["nodes"]}
    inventory = {
        (key.split("#")[0], int(key.split("#")[1])): float(value)
        for key, value in result["vehicle_inventory"].items()
    }
    breakdown: dict[tuple[str, int], int] = {}
    if include_event and case["event"]["type"] == "vehicle_breakdown":
        breakdown[(case["event"]["node"], int(case["event"]["slot"]))] = int(case["event"]["vehicle_count"])
    for node_id, node in node_by_id.items():
        if abs(inventory[(node_id, 0)] - int(node["initial_own_vehicles"])) > TOL:
            errors.append(f"Initial vehicle mismatch at {node_id}")
        for slot in range(horizon):
            departures = sum(
                mission_values[mission.id] for mission in missions
                if mission.vehicle_source == "own" and mission.origin == node_id and mission.departure == slot
            )
            arrivals = sum(
                mission_values[mission.id] for mission in missions
                if mission.vehicle_source == "own" and mission.destination == node_id and mission.arrival == slot + 1
            )
            expected = inventory[(node_id, slot)] - breakdown.get((node_id, slot), 0) - departures + arrivals
            if abs(inventory[(node_id, slot + 1)] - expected) > TOL or expected < -TOL:
                errors.append(f"Vehicle balance violation at {node_id}, slot {slot}")
            external = sum(
                mission_values[mission.id] for mission in missions
                if mission.vehicle_source == "external" and mission.origin == node_id and mission.departure == slot
            )
            if external > int(node["external_vehicle_limit"][slot]) + TOL:
                errors.append(f"External vehicle cap violation at {node_id}, slot {slot}")

    active_demand = {
        record["id"]: record for record in case["demand"]
        if float(record[demand_field]) > 1e-9
        and record.get("admission_status") != "rejected"
    }
    itinerary_lookup = {}
    for record in active_demand.values():
        for itinerary in generate_itineraries(record, config, services, rides_by_origin):
            itinerary_lookup[itinerary.id] = itinerary

    allocation: dict[str, float] = defaultdict(float)
    resource_flow: dict[tuple[str, int], float] = defaultdict(float)
    handling: dict[tuple[str, int], float] = defaultdict(float)
    storage: dict[tuple[str, int], float] = defaultdict(float)
    ontime: dict[str, float] = defaultdict(float)
    cargo_handling_cost = 0.0
    inventory_holding_cost = 0.0
    transfer_cost = 0.0
    delay_cost = 0.0
    for item in result["itineraries"]:
        demand_id = item["demand_id"]
        itinerary_id = item["itinerary_id"]
        tons = float(item["tons"])
        if demand_id not in active_demand:
            errors.append(f"Unknown active demand {demand_id}")
            continue
        itinerary = itinerary_lookup.get(itinerary_id)
        if itinerary is None:
            errors.append(f"Unknown itinerary {itinerary_id}")
            continue
        allocation[demand_id] += tons
        cargo_handling_cost += tons * float(config["cost"]["handling_per_ton_operation"]) * (
            2 + 2 * itinerary.transfers
        )
        inventory_holding_cost += tons * float(
            config["cost"]["inventory_holding_per_ton_slot"]
        ) * itinerary.holding_slots
        transfer_cost += tons * float(config["cost"]["transfer_extra_per_ton"]) * itinerary.transfers
        delay_cost += tons * float(
            config["products"][active_demand[demand_id]["product"]]["delay_cost_per_ton_slot"]
        ) * itinerary.delay_slots
        if itinerary.delay_slots == 0:
            ontime[active_demand[demand_id]["product"]] += tons
        for resource in itinerary.resource_keys:
            resource_flow[resource] += tons
        for node_id, slot, operations in itinerary.handling_operations:
            handling[(node_id, slot)] += operations * tons
        for node_id, slot in itinerary.storage_occupancy:
            storage[(node_id, slot)] += tons

    for demand_id, record in active_demand.items():
        if abs(allocation[demand_id] - float(record[demand_field])) > TOL:
            errors.append(f"Demand allocation mismatch {demand_id}")

    capacity = float(config["vehicle"]["capacity_equivalent_tons"])
    for resource, flow in resource_flow.items():
        supplied = capacity * sum(
            mission_values[mission.id] for mission in missions if mission.service_id == resource[0]
        )
        if flow > supplied + TOL:
            errors.append(f"Capacity violation {_resource_name(*resource)}: {flow}>{supplied}")
    for (node_id, slot), value in handling.items():
        if value > float(node_by_id[node_id]["handling_capacity"][slot]) + TOL:
            errors.append(f"Handling violation {node_id}, slot {slot}")
    totals: dict[str, float] = defaultdict(float)
    for record in active_demand.values():
        totals[record["product"]] += float(record[demand_field])
    service_shortfall_cost = 0.0
    reported_service = result.get("service_rates", {})
    for product, total in totals.items():
        required = float(config["products"][product]["minimum_on_time_rate"])
        expected_shortfall = max(0.0, required * total - ontime[product])
        reported_shortfall = float(reported_service.get(product, {}).get("shortfall_tons", 0.0))
        if abs(expected_shortfall - reported_shortfall) > 1e-4:
            errors.append(f"Service shortfall mismatch {product}")
        service_shortfall_cost += expected_shortfall * float(
            config["products"][product]["service_shortfall_penalty_per_ton"]
        )

    transport_cost = sum(mission.cost * mission_values[mission.id] for mission in missions)
    components = result["objective_components"]
    if abs(transport_cost - float(components["transport"])) > 1e-4:
        errors.append("Transport cost mismatch")
    expected_cargo_components = {
        "cargo_handling": cargo_handling_cost,
        "inventory_holding": inventory_holding_cost,
        "transfer": transfer_cost,
        "delay": delay_cost,
    }
    for name, expected in expected_cargo_components.items():
        if abs(expected - float(components[name])) > 1e-4:
            errors.append(f"{name} cost mismatch")
    if abs(service_shortfall_cost - float(components["service_shortfall"])) > 1e-4:
        errors.append("Service shortfall cost mismatch")
    component_total = sum(float(value) for value in components.values())
    if abs(component_total - float(result["objective"])) > 1e-4:
        errors.append("Objective component mismatch")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "checks": {
            "normal_trip_exclusivity": True,
            "own_vehicle_balance": True,
            "external_vehicle_caps": True,
            "full_cargo_allocation": True,
            "trip_capacity": True,
            "node_handling_capacity": True,
            "storage_capacity_assumed_sufficient": True,
            "itinerary_legality": True,
            "product_service_shortfall_accounting": True,
            "objective_recalculation": True,
        },
    }


def _validate_plan_snapshots(
    case: dict[str, Any], config: dict[str, Any], solution: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    snapshots = solution.get("plan_snapshots", [])
    if not snapshots:
        return ["Missing plan_snapshots for rolling animation"]
    snapshot_by_id = {item.get("snapshot_id"): item for item in snapshots}
    if None in snapshot_by_id or len(snapshot_by_id) != len(snapshots):
        errors.append("Plan snapshot IDs are missing or duplicated")
    horizon = int(config["time"]["observation_slots"])
    expected_nodes = {node["id"] for node in case["nodes"]}
    for snapshot in snapshots:
        snapshot_id = snapshot.get("snapshot_id", "unknown")
        if snapshot.get("storage_policy") != "capacity_assumed_sufficient_no_upper_bound":
            errors.append(f"{snapshot_id}: wrong storage policy")
        nodes = {item.get("node_id"): item for item in snapshot.get("nodes", [])}
        if set(nodes) != expected_nodes:
            errors.append(f"{snapshot_id}: incomplete node set")
            continue
        expected_inventory: dict[tuple[str, int], float] = defaultdict(float)
        expected_handling: dict[tuple[str, int], float] = defaultdict(float)
        for itinerary in snapshot.get("cargo_itineraries", []):
            tons = float(itinerary["tons"])
            for occupancy in itinerary.get("inventory_occupancy", []):
                expected_inventory[(occupancy["node_id"], int(occupancy["slot"]))] += tons
            for operation in itinerary.get("handling_operations", []):
                expected_handling[(operation["node_id"], int(operation["slot"]))] += (
                    tons * int(operation["operations"])
                )
        for node_id, node_snapshot in nodes.items():
            timeline = node_snapshot.get("timeline", [])
            if len(timeline) != horizon + 1:
                errors.append(f"{snapshot_id}: node {node_id} timeline is incomplete")
                continue
            for slot, state in enumerate(timeline):
                if int(state.get("slot", -1)) != slot:
                    errors.append(f"{snapshot_id}: node {node_id} slot order mismatch")
                    break
                if abs(float(state.get("inventory_tons", 0.0)) - expected_inventory[(node_id, slot)]) > TOL:
                    errors.append(f"{snapshot_id}: node {node_id} inventory mismatch at slot {slot}")
                if abs(float(state.get("handling_tons", 0.0)) - expected_handling[(node_id, slot)]) > TOL:
                    errors.append(f"{snapshot_id}: node {node_id} handling mismatch at slot {slot}")
    prior_id = snapshots[0].get("snapshot_id")
    for step in solution.get("rolling_steps", []):
        if step.get("plan_before_snapshot_id") != prior_id:
            errors.append(f"Rolling slot {step.get('slot')}: before-snapshot link mismatch")
        after_id = step.get("plan_after_snapshot_id")
        if after_id not in snapshot_by_id:
            errors.append(f"Rolling slot {step.get('slot')}: after-snapshot missing")
        else:
            prior_id = after_id
    return errors


def validate_case_solution(
    case: dict[str, Any], config: dict[str, Any], solution: dict[str, Any]
) -> dict[str, Any]:
    baseline_case = build_information_case(case, 0)
    baseline = validate_static(baseline_case, config, solution["baseline"], include_event=False)
    realized_case = copy.deepcopy(case)
    if solution.get("realized_event") is not None:
        realized_case["event"] = copy.deepcopy(solution["realized_event"])
        if realized_case["event"]["type"] == "urgent_cancel":
            cancelled_by_id = {
                item["demand_id"]: float(item["cancel_tons"])
                for item in realized_case["event"].get("demand_adjustments", [])
            }
            for record in realized_case["demand"]:
                record["actual_tons"] = round(
                    max(
                        0.0,
                        float(record["actual_tons"])
                        - cancelled_by_id.get(record["id"], 0.0),
                    ),
                    8,
                )
        elif realized_case["event"]["type"] == "urgent_insert":
            decision = solution.get("insert_decision")
            if decision is not None:
                for record in realized_case["demand"]:
                    if record["id"] != decision["demand_id"]:
                        continue
                    record["service_clock_slot"] = int(decision["requested_slot"])
                    if decision["admission_slot"] is None:
                        record["admission_status"] = "rejected"
                    else:
                        admission_slot = int(decision["admission_slot"])
                        record["release_slot"] = admission_slot
                        record["candidate_key"] = f"{record['id']}_ADM{admission_slot}"
                        record["admission_status"] = str(decision["status"])
    actual = validate_static(realized_case, config, solution["actual"], include_event=True)
    fixed_errors: list[str] = []
    trigger = int(solution["trigger_slot"])
    _, missions = build_services_and_missions(case, config)
    baseline_missions = defaultdict(float, solution["baseline"].get("missions", {}))
    actual_missions = defaultdict(float, solution["actual"].get("missions", {}))
    for mission in missions:
        if mission.departure < trigger and abs(baseline_missions[mission.id] - actual_missions[mission.id]) > TOL:
            fixed_errors.append(f"Executed mission changed: {mission.id}")
    snapshot_errors = _validate_plan_snapshots(case, config, solution)
    return {
        "case_id": case["case_id"],
        "status": (
            "pass"
            if baseline["status"] == actual["status"] == "pass"
            and not fixed_errors and not snapshot_errors
            else "fail"
        ),
        "baseline": baseline,
        "actual": actual,
        "executed_decision_errors": fixed_errors,
        "plan_snapshot_errors": snapshot_errors,
    }


def validate_expected_behavior(case: dict[str, Any], solution: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    code = case["category"]
    actual = solution.get("actual", {})
    missions = actual.get("missions", {})
    itineraries = actual.get("itineraries", [])
    modes = {mission_id.split("_", 1)[0] for mission_id in missions}
    if code == "V01":
        if "NOR_SCH_A_B_0_V0" not in missions or modes.intersection({"ADD", "EXT"}):
            errors.append("V01 did not use only the scheduled direct trip")
        if any(item["transfers"] or item.get("inventory_slots", item.get("holding_slots", 0)) for item in itineraries):
            errors.append("V01 cargo was transferred or held")
    elif code == "V02":
        if not any(item["transfers"] == 1 and item["service_ids"] == ["S_A-B_T0", "S_B-C_T2"] for item in itineraries):
            errors.append("V02 did not use the intended A-B-C transfer")
    elif code == "V03":
        if not any(item["service_ids"] == ["S_A-B-C_T0"] and item["transfers"] == 0 for item in itineraries):
            errors.append("V03 did not demonstrate a zero-transfer string ride")
    elif code == "V04":
        inserted = [item for item in itineraries if item["demand_id"] == "EMG_INSERT_T1_A_C"]
        if not inserted or any(item["delay_slots"] > 0 for item in inserted):
            errors.append("V04 inserted urgent cargo was not recovered on time")
        if not any(step.get("decision_type") == "event" and step.get("slot") == 1 for step in solution.get("rolling_steps", [])):
            errors.append("V04 did not perform the off-cycle event replan at hour 3")
    return {"status": "pass" if not errors else "fail", "errors": errors}
