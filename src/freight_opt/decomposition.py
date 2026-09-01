from __future__ import annotations

import copy
import math
import time
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import Any

import gurobipy as gp
from gurobipy import GRB

from .candidates import (
    Itinerary,
    Mission,
    build_rides,
    build_services_and_missions,
    generate_itineraries,
)
from .optimization import STATUS_NAMES, _event_breakdown, solve_case, solve_static


TOL = 1e-7


@dataclass
class PreparedProblem:
    case: dict[str, Any]
    config: dict[str, Any]
    demand_field: str
    active_demand: list[dict[str, Any]]
    demand_by_id: dict[str, dict[str, Any]]
    services: dict[str, Any]
    missions: list[Mission]
    mission_by_id: dict[str, Mission]
    pools: dict[str, list[Itinerary]]
    itinerary_by_id: dict[str, Itinerary]
    reference: dict[str, Any] | None
    change_slot: int | None
    include_event: bool
    trip_change_unit: float
    trip_denominator: float
    cargo_change_unit: float
    cargo_denominator: float
    cargo_scale: dict[str, float]
    cargo_baseline: dict[tuple[str, str], float]
    cargo_missing_constant: float


def _remaining(deadline: float) -> float:
    return max(0.01, deadline - time.perf_counter())


def _prepare(
    case: dict[str, Any], config: dict[str, Any], demand_field: str,
    reference: dict[str, Any] | None, change_slot: int | None,
    include_event: bool, model_context: dict[str, Any] | None,
) -> PreparedProblem | dict[str, Any]:
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
                "decomposition_itinerary_cache": {},
            })
    cache = (
        model_context.setdefault("decomposition_itinerary_cache", {})
        if model_context is not None else {}
    )

    active = [
        record for record in case["demand"]
        if float(record[demand_field]) > 1e-9
        and record.get("admission_status") != "rejected"
    ]
    pools: dict[str, list[Itinerary]] = {}
    itinerary_by_id: dict[str, Itinerary] = {}
    for record in active:
        key = (
            record["id"], record["origin"], record["destination"], record["product"],
            int(record["release_slot"]),
            int(record.get("service_clock_slot", record["release_slot"])),
            str(record.get("candidate_key", record["id"])),
        )
        if key not in cache:
            cache[key] = generate_itineraries(record, config, services, rides_by_origin)
        itineraries = cache[key]
        if not itineraries:
            return {
                "case_id": case["case_id"], "status": "candidate_infeasible",
                "message": f"No legal itinerary for {record['id']}", "has_solution": False,
            }
        pools[record["id"]] = itineraries
        itinerary_by_id.update((item.id, item) for item in itineraries)

    used_services = {
        key[0] for values in pools.values() for item in values for key in item.resource_keys
    }
    missions = [
        mission for mission in all_missions
        if mission.service_id in used_services or len(services[mission.service_id].route) == 2
    ]

    capacity = float(config["vehicle"]["capacity_equivalent_tons"])
    trip_change_unit = 0.0
    trip_denominator = 1.0
    cargo_change_unit = 0.0
    cargo_denominator = 1.0
    cargo_scale: dict[str, float] = {}
    cargo_baseline: dict[tuple[str, str], float] = {}
    cargo_missing_constant = 0.0
    if reference is not None and change_slot is not None:
        future_missions = [mission for mission in missions if mission.departure >= change_slot]
        baseline_trip_total = sum(
            float(reference.get("missions", {}).get(mission.id, 0.0))
            for mission in future_missions
        )
        demand_vehicle_equivalent = sum(float(r[demand_field]) for r in active) / capacity
        trip_denominator = max(1.0, baseline_trip_total + demand_vehicle_equivalent)
        reference_cost = max(1.0, float(reference["objective"]))
        rho = float(config["cost"]["balanced_change_penalty_ratio"])
        trip_change_unit = (
            rho * reference_cost * float(config["cost"]["trip_change_weight"])
            / trip_denominator
        )

        items_by_demand: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in reference.get("itineraries", []):
            items_by_demand[item["demand_id"]].append(item)
        common_future = 0.0
        for record in active:
            demand_id = record["id"]
            reference_items = items_by_demand.get(demand_id, [])
            reference_future = [
                item for item in reference_items if int(item["arrival"]) > change_slot
            ]
            reference_future_total = sum(float(item["tons"]) for item in reference_future)
            completed = sum(
                float(item["tons"]) for item in reference_items
                if int(item["arrival"]) <= change_slot
            )
            current_future_total = max(0.0, float(record[demand_field]) - completed)
            overlap = min(reference_future_total, current_future_total)
            if overlap <= 1e-9:
                continue
            common_future += overlap
            cargo_scale[demand_id] = overlap / current_future_total
            reference_scale = overlap / reference_future_total
            for item in reference_future:
                cargo_baseline[(demand_id, item["itinerary_id"])] = (
                    float(item["tons"]) * reference_scale
                )
        cargo_denominator = max(1.0, common_future)
        cargo_change_unit = (
            rho * reference_cost * float(config["cost"]["cargo_change_weight"])
            * 0.5 / cargo_denominator
        )
        current_keys = {
            (demand_id, item.id) for demand_id, values in pools.items() for item in values
            if item.arrival > change_slot
        }
        cargo_missing_constant = cargo_change_unit * sum(
            baseline for key, baseline in cargo_baseline.items() if key not in current_keys
        )

    return PreparedProblem(
        case=case, config=config, demand_field=demand_field,
        active_demand=active, demand_by_id={r["id"]: r for r in active},
        services=services, missions=missions,
        mission_by_id={m.id: m for m in missions}, pools=pools,
        itinerary_by_id=itinerary_by_id, reference=reference,
        change_slot=change_slot, include_event=include_event,
        trip_change_unit=trip_change_unit, trip_denominator=trip_denominator,
        cargo_change_unit=cargo_change_unit, cargo_denominator=cargo_denominator,
        cargo_scale=cargo_scale, cargo_baseline=cargo_baseline,
        cargo_missing_constant=cargo_missing_constant,
    )


def _build_master(problem: PreparedProblem, verification: bool) -> tuple[Any, ...]:
    config = problem.config
    model = gp.Model(f"benders_master_{problem.case['case_id']}")
    model.Params.OutputFlag = 0
    model.Params.Seed = int(config["solver"]["random_seed"] % 2_000_000_000)
    model.Params.Threads = int(config["solver"].get("threads_per_worker", 0))
    model.Params.MIPGap = 0.0 if verification else float(config["solver"]["target_mip_gap"])
    model.Params.MIPFocus = 1
    model.Params.Heuristics = 0.2

    y: dict[str, gp.Var] = {}
    by_service: dict[str, list[Mission]] = defaultdict(list)
    for mission in problem.missions:
        y[mission.id] = model.addVar(
            lb=0, ub=mission.upper_bound,
            vtype=GRB.BINARY if mission.mode == "normal" else GRB.INTEGER,
            name=f"y[{mission.id}]",
        )
        y[mission.id].Start = float(
            problem.reference.get("missions", {}).get(mission.id, 0.0)
            if problem.reference is not None else 0.0
        )
        by_service[mission.service_id].append(mission)

    templates: dict[str, list[Mission]] = defaultdict(list)
    for mission in problem.missions:
        if mission.template_id:
            templates[mission.template_id].append(mission)
    for template_id, variants in templates.items():
        model.addConstr(
            gp.quicksum(y[m.id] for m in variants) <= 1,
            name=f"normal_choice[{template_id}]",
        )

    nodes = {node["id"]: node for node in problem.case["nodes"]}
    horizon = int(config["time"]["observation_slots"])
    total_own = sum(int(node["initial_own_vehicles"]) for node in nodes.values())
    own = [mission for mission in problem.missions if mission.vehicle_source == "own"]
    breakdown = _event_breakdown(problem.case, problem.include_event)
    v: dict[tuple[str, int], gp.Var] = {}
    for node_id, node in nodes.items():
        for slot in range(horizon + 1):
            v[(node_id, slot)] = model.addVar(
                lb=0, ub=total_own, vtype=GRB.INTEGER, name=f"v[{node_id},{slot}]"
            )
            if problem.reference is not None:
                v[(node_id, slot)].Start = float(
                    problem.reference.get("vehicle_inventory", {}).get(
                        f"{node_id}#{slot}", node["initial_own_vehicles"]
                    )
                )
            else:
                cumulative_loss = sum(
                    loss for (loss_node, loss_slot), loss in breakdown.items()
                    if loss_node == node_id and loss_slot < slot
                )
                v[(node_id, slot)].Start = max(
                    0, int(node["initial_own_vehicles"]) - cumulative_loss
                )
        model.addConstr(v[(node_id, 0)] == int(node["initial_own_vehicles"]))
    for node_id in nodes:
        for slot in range(horizon):
            departures = gp.quicksum(
                y[m.id] for m in own if m.origin == node_id and m.departure == slot
            )
            arrivals = gp.quicksum(
                y[m.id] for m in own if m.destination == node_id and m.arrival == slot + 1
            )
            loss = breakdown.get((node_id, slot), 0)
            model.addConstr(
                v[(node_id, slot + 1)] == v[(node_id, slot)] - loss - departures + arrivals,
                name=f"vehicle_balance[{node_id},{slot}]",
            )
            if loss:
                model.addConstr(v[(node_id, slot)] >= loss)
    for node_id, node in nodes.items():
        for slot in range(horizon):
            model.addConstr(
                gp.quicksum(
                    y[m.id] for m in problem.missions
                    if m.vehicle_source == "external" and m.origin == node_id
                    and m.departure == slot
                ) <= int(node["external_vehicle_limit"][slot]),
                name=f"external_limit[{node_id},{slot}]",
            )

    # Valid Benders-master strengthening. Every ton whose OD pair crosses a
    # physical node cut must use at least one vehicle segment crossing that cut.
    # These constraints are projections of cargo flow conservation; they remove
    # disconnected cheap schedules early without choosing a cargo itinerary.
    capacity = float(config["vehicle"]["capacity_equivalent_tons"])
    node_ids = sorted(nodes)
    for size in range(1, len(node_ids)):
        for members in combinations(node_ids, size):
            inside = frozenset(members)
            required = sum(
                float(record[problem.demand_field])
                for record in problem.active_demand
                if record["origin"] in inside and record["destination"] not in inside
            )
            if required <= TOL:
                continue
            crossing_terms = []
            for mission in problem.missions:
                service = problem.services[mission.service_id]
                crossings = sum(
                    segment.origin in inside and segment.destination not in inside
                    for segment in service.segments
                )
                if crossings:
                    crossing_terms.append(crossings * y[mission.id])
            model.addConstr(
                capacity * gp.quicksum(crossing_terms) >= required,
                name=f"cargo_cut_relaxation[{','.join(members)}]",
            )

    minimum_ton_segments = sum(
        float(record[problem.demand_field])
        * min(len(item.resource_keys) for item in problem.pools[record["id"]])
        for record in problem.active_demand
    )
    supplied_segment_capacity = capacity * gp.quicksum(
        len(problem.services[mission.service_id].segments) * y[mission.id]
        for mission in problem.missions
    )
    model.addConstr(
        supplied_segment_capacity >= minimum_ton_segments,
        name="minimum_total_ton_segment_capacity",
    )

    if problem.reference is not None and problem.change_slot is not None:
        for mission in problem.missions:
            if mission.departure < problem.change_slot:
                model.addConstr(
                    y[mission.id] == float(
                        problem.reference.get("missions", {}).get(mission.id, 0.0)
                    ),
                    name=f"executed_mission_fixed[{mission.id}]",
                )

    trip_deltas: list[gp.Var] = []
    if problem.reference is not None and problem.change_slot is not None:
        for mission in problem.missions:
            if mission.departure < problem.change_slot:
                continue
            delta = model.addVar(lb=0.0, name=f"trip_delta[{mission.id}]")
            baseline = float(problem.reference.get("missions", {}).get(mission.id, 0.0))
            delta.Start = 0.0
            model.addConstr(delta >= y[mission.id] - baseline)
            model.addConstr(delta >= baseline - y[mission.id])
            trip_deltas.append(delta)

    theta = model.addVar(lb=0.0, name="theta_cargo")
    theta.Start = 0.0
    vehicle_cost = gp.quicksum(m.cost * y[m.id] for m in problem.missions)
    trip_change = problem.trip_change_unit * gp.quicksum(trip_deltas)
    model.setObjective(vehicle_cost + trip_change + theta, GRB.MINIMIZE)
    model.update()
    return model, y, v, theta, vehicle_cost, trip_change


def _initial_columns(problem: PreparedProblem) -> dict[str, set[str]]:
    reference_ids: dict[str, set[str]] = defaultdict(set)
    if problem.reference is not None:
        for item in problem.reference.get("itineraries", []):
            if float(item.get("tons", 0.0)) > TOL:
                reference_ids[item["demand_id"]].add(item["itinerary_id"])
    active: dict[str, set[str]] = {}
    for demand_id, pool in problem.pools.items():
        cheapest = min(pool, key=lambda p: (p.variable_cost_per_ton, p.arrival, p.id))
        fastest = min(pool, key=lambda p: (p.arrival, p.variable_cost_per_ton, p.id))
        delayed = max(pool, key=lambda p: (p.arrival, p.id))
        selected = {cheapest.id, fastest.id, delayed.id}
        selected.update(
            itinerary_id for (did, itinerary_id), value in problem.cargo_baseline.items()
            if did == demand_id and value > TOL and itinerary_id in problem.itinerary_by_id
        )
        selected.update(
            itinerary_id for itinerary_id in reference_ids.get(demand_id, set())
            if itinerary_id in problem.itinerary_by_id
        )
        active[demand_id] = selected
    return active


def _route_cost(problem: PreparedProblem, demand_id: str, item: Itinerary) -> float:
    cost = float(item.variable_cost_per_ton)
    if problem.change_slot is None or item.arrival <= problem.change_slot:
        return cost
    baseline = problem.cargo_baseline.get((demand_id, item.id), 0.0)
    if baseline <= TOL:
        cost += problem.cargo_change_unit * problem.cargo_scale.get(demand_id, 0.0)
    return cost


def _solve_rmp(
    problem: PreparedProblem, ybar: dict[str, float], active: dict[str, set[str]],
    phase: str, deadline: float,
) -> dict[str, Any]:
    model = gp.Model(f"cg_{phase}_{problem.case['case_id']}")
    model.Params.OutputFlag = 0
    model.Params.Threads = 1
    model.Params.Method = 1
    model.Params.TimeLimit = _remaining(deadline)

    x: dict[tuple[str, str], gp.Var] = {}
    artificial: dict[str, gp.Var] = {}
    for record in problem.active_demand:
        demand_id = record["id"]
        for itinerary_id in active[demand_id]:
            x[(demand_id, itinerary_id)] = model.addVar(lb=0.0, name=f"x[{itinerary_id}]")
        artificial[demand_id] = model.addVar(
            lb=0.0, ub=GRB.INFINITY if phase == "feasibility" else 0.0,
            name=f"artificial[{demand_id}]",
        )

    demand_constr: dict[str, gp.Constr] = {}
    for record in problem.active_demand:
        demand_id = record["id"]
        demand_constr[demand_id] = model.addConstr(
            gp.quicksum(
                x[(demand_id, itinerary_id)] for itinerary_id in active[demand_id]
            ) + artificial[demand_id] == float(record[problem.demand_field]),
            name=f"demand[{demand_id}]",
        )

    resource_expr: dict[tuple[str, int], gp.LinExpr] = defaultdict(gp.LinExpr)
    handling_expr: dict[tuple[str, int], gp.LinExpr] = defaultdict(gp.LinExpr)
    demand_resource_expr: dict[tuple[str, str, int], gp.LinExpr] = defaultdict(gp.LinExpr)
    ontime_expr: dict[str, gp.LinExpr] = defaultdict(gp.LinExpr)
    totals: dict[str, float] = defaultdict(float)
    for record in problem.active_demand:
        demand_id = record["id"]
        totals[record["product"]] += float(record[problem.demand_field])
        for itinerary_id in active[demand_id]:
            item = problem.itinerary_by_id[itinerary_id]
            var = x[(demand_id, itinerary_id)]
            for resource in item.resource_keys:
                resource_expr[resource] += var
                demand_resource_expr[(demand_id, resource[0], resource[1])] += var
            for node_id, slot, operations in item.handling_operations:
                handling_expr[(node_id, slot)] += operations * var
            if item.delay_slots == 0:
                ontime_expr[record["product"]] += var

    capacity = float(problem.config["vehicle"]["capacity_equivalent_tons"])
    missions_by_service: dict[str, list[Mission]] = defaultdict(list)
    for mission in problem.missions:
        missions_by_service[mission.service_id].append(mission)
    capacity_constr: dict[tuple[str, int], gp.Constr] = {}
    capacity_artificial: dict[tuple[str, int], gp.Var] = {}
    for service in problem.services.values():
        supplied = capacity * sum(
            ybar.get(mission.id, 0.0) for mission in missions_by_service[service.id]
        )
        for segment in service.segments:
            key = (service.id, segment.index)
            if phase == "feasibility":
                capacity_artificial[key] = model.addVar(
                    lb=0.0, name=f"capacity_artificial[{service.id},{segment.index}]"
                )
            capacity_constr[key] = model.addConstr(
                resource_expr[key]
                <= supplied + (capacity_artificial[key] if phase == "feasibility" else 0.0),
                name=f"capacity[{service.id},{segment.index}]",
            )

    handling_constr: dict[tuple[str, int], gp.Constr] = {}
    handling_artificial: dict[tuple[str, int], gp.Var] = {}
    horizon = int(problem.config["time"]["observation_slots"])
    for node in problem.case["nodes"]:
        for slot in range(horizon):
            key = (node["id"], slot)
            if phase == "feasibility":
                handling_artificial[key] = model.addVar(
                    lb=0.0, name=f"handling_artificial[{node['id']},{slot}]"
                )
            handling_constr[key] = model.addConstr(
                handling_expr[key]
                <= float(node["handling_capacity"][slot])
                + (handling_artificial[key] if phase == "feasibility" else 0.0),
                name=f"handling[{node['id']},{slot}]",
            )

    service_vars: dict[str, gp.Var] = {}
    service_constr: dict[str, gp.Constr] = {}
    for product, total in totals.items():
        service_vars[product] = model.addVar(lb=0.0, ub=total, name=f"shortfall[{product}]")
        service_constr[product] = model.addConstr(
            ontime_expr[product] + service_vars[product]
            >= float(problem.config["products"][product]["minimum_on_time_rate"]) * total,
            name=f"service[{product}]",
        )

    past_constr: dict[tuple[str, str, int], gp.Constr] = {}
    if problem.reference is not None and problem.change_slot is not None:
        reference_flow = problem.reference.get("demand_resource_flow", {})
        keys = {
            key for key in demand_resource_expr
            if problem.services[key[1]].segments[key[2]].departure < problem.change_slot
        }
        keys.update(
            (parts[0], parts[1], int(parts[2]))
            for name in reference_flow for parts in [name.split("|")]
            if parts[0] in problem.demand_by_id and parts[1] in problem.services
            and problem.services[parts[1]].segments[int(parts[2])].departure < problem.change_slot
        )
        for key in sorted(keys):
            name = f"{key[0]}|{key[1]}|{key[2]}"
            past_constr[key] = model.addConstr(
                demand_resource_expr[key] == float(reference_flow.get(name, 0.0)),
                name=f"past[{name}]",
            )

    cargo_delta: list[gp.Var] = []
    cargo_constant = problem.cargo_missing_constant
    if phase == "cost" and problem.reference is not None and problem.change_slot is not None:
        for (demand_id, itinerary_id), baseline in problem.cargo_baseline.items():
            item = problem.itinerary_by_id.get(itinerary_id)
            if item is None or item.arrival <= problem.change_slot:
                continue
            var = x.get((demand_id, itinerary_id))
            if var is None:
                cargo_constant += problem.cargo_change_unit * baseline
                continue
            delta = model.addVar(lb=0.0, name=f"cargo_delta[{demand_id},{itinerary_id}]")
            current = problem.cargo_scale.get(demand_id, 0.0) * var
            model.addConstr(delta >= current - baseline)
            model.addConstr(delta >= baseline - current)
            cargo_delta.append(delta)

    if phase == "feasibility":
        # Scale transport overload by vehicle capacity so all Phase-I terms are
        # comparable violation quantities. These variables exist only to obtain
        # a valid feasibility cut and must be zero before the cost phase starts.
        objective = (
            gp.quicksum(artificial.values())
            + gp.quicksum(capacity_artificial.values()) / capacity
            + gp.quicksum(handling_artificial.values())
        )
    else:
        route_cost = gp.quicksum(
            _route_cost(problem, demand_id, problem.itinerary_by_id[itinerary_id]) * var
            for (demand_id, itinerary_id), var in x.items()
        )
        shortfall_cost = gp.quicksum(
            float(problem.config["products"][product]["service_shortfall_penalty_per_ton"])
            * var for product, var in service_vars.items()
        )
        objective = (
            route_cost + shortfall_cost
            + problem.cargo_change_unit * gp.quicksum(cargo_delta) + cargo_constant
        )
    model.setObjective(objective, GRB.MINIMIZE)
    model.optimize()
    if model.SolCount <= 0:
        return {"status": STATUS_NAMES.get(model.Status, str(model.Status)), "has_solution": False}

    dual_demand = {key: constr.Pi for key, constr in demand_constr.items()}
    dual_capacity = {key: constr.Pi for key, constr in capacity_constr.items()}
    dual_handling = {key: constr.Pi for key, constr in handling_constr.items()}
    dual_service = {key: constr.Pi for key, constr in service_constr.items()}
    dual_past = {key: constr.Pi for key, constr in past_constr.items()}
    negative: list[tuple[float, str, str]] = []
    minimum_rc = math.inf
    for record in problem.active_demand:
        demand_id = record["id"]
        product = record["product"]
        for item in problem.pools[demand_id]:
            if item.id in active[demand_id]:
                continue
            cost = 0.0 if phase == "feasibility" else _route_cost(problem, demand_id, item)
            rc = cost - dual_demand[demand_id]
            rc -= sum(dual_capacity[key] for key in item.resource_keys)
            rc -= sum(
                operations * dual_handling[(node_id, slot)]
                for node_id, slot, operations in item.handling_operations
            )
            if item.delay_slots == 0:
                rc -= dual_service.get(product, 0.0)
            for resource in item.resource_keys:
                key = (demand_id, resource[0], resource[1])
                rc -= dual_past.get(key, 0.0)
            minimum_rc = min(minimum_rc, rc)
            if rc < -1e-7:
                negative.append((rc, demand_id, item.id))

    beta: dict[str, float] = {}
    for mission in problem.missions:
        service = problem.services[mission.service_id]
        value = capacity * sum(
            dual_capacity[(service.id, segment.index)] for segment in service.segments
        )
        if abs(value) > 1e-10:
            beta[mission.id] = value
    unmet_artificial = sum(var.X for var in artificial.values())
    capacity_violation = sum(var.X for var in capacity_artificial.values())
    handling_violation = sum(var.X for var in handling_artificial.values())
    artificial_total = (
        unmet_artificial + capacity_violation / capacity + handling_violation
    )
    nonzero_duals = {
        "demand": {key: value for key, value in dual_demand.items() if abs(value) > 1e-10},
        "capacity": {
            f"{key[0]}#{key[1]}": value
            for key, value in dual_capacity.items() if abs(value) > 1e-10
        },
        "handling": {
            f"{key[0]}#{key[1]}": value
            for key, value in dual_handling.items() if abs(value) > 1e-10
        },
        "service": {key: value for key, value in dual_service.items() if abs(value) > 1e-10},
        "executed_flow": {
            f"{key[0]}|{key[1]}|{key[2]}": value
            for key, value in dual_past.items() if abs(value) > 1e-10
        },
    }
    return {
        "status": STATUS_NAMES.get(model.Status, str(model.Status)),
        "has_solution": True,
        "objective": float(model.ObjVal),
        "artificial_total": artificial_total,
        "artificial_components": {
            "unmet_tons": unmet_artificial,
            "capacity_overload_tons": capacity_violation,
            "handling_overload_tons": handling_violation,
        },
        "negative": sorted(negative),
        "minimum_reduced_cost": None if math.isinf(minimum_rc) else minimum_rc,
        "beta": beta,
        "duals_nonzero": nonzero_duals,
        "runtime_seconds": model.Runtime,
        "variables": model.NumVars,
        "constraints": model.NumConstrs,
    }


def _column_generation(
    problem: PreparedProblem, ybar: dict[str, float], active: dict[str, set[str]],
    phase: str, deadline: float,
) -> dict[str, Any]:
    settings = problem.config.get("decomposition", {})
    max_iterations = int(settings.get("max_column_generation_iterations", 100))
    batch_size = int(settings.get("columns_per_iteration", 250))
    iterations = []
    final: dict[str, Any] | None = None
    for iteration in range(1, max_iterations + 1):
        if _remaining(deadline) <= 0.05:
            return {"status": "time_limit", "converged": False, "iterations": iterations}
        result = _solve_rmp(problem, ybar, active, phase, deadline)
        if not result.get("has_solution"):
            return {"status": result["status"], "converged": False, "iterations": iterations}
        additions = result.pop("negative")[:batch_size]
        iteration_record = {
            "iteration": iteration,
            "phase": phase,
            "rmp_status": result["status"],
            "rmp_objective": result["objective"],
            "artificial_tons": result["artificial_total"],
            "artificial_components": result["artificial_components"],
            "minimum_reduced_cost": result["minimum_reduced_cost"],
            "active_columns_before": sum(len(value) for value in active.values()),
            "priced_negative_columns": len(additions),
            "added_columns": [
                {"demand_id": demand_id, "itinerary_id": itinerary_id, "reduced_cost": rc}
                for rc, demand_id, itinerary_id in additions
            ],
            "duals_nonzero": result["duals_nonzero"],
            "runtime_seconds": result["runtime_seconds"],
            "rmp_variables": result["variables"],
            "rmp_constraints": result["constraints"],
        }
        for _, demand_id, itinerary_id in additions:
            active[demand_id].add(itinerary_id)
        iteration_record["active_columns_after"] = sum(len(value) for value in active.values())
        iterations.append(iteration_record)
        final = result
        if not additions:
            return {
                "status": "optimal", "converged": True, "iterations": iterations,
                "objective": result["objective"],
                "artificial_total": result["artificial_total"], "beta": result["beta"],
            }
    return {
        "status": "iteration_limit", "converged": False, "iterations": iterations,
        "objective": None if final is None else final["objective"],
    }


def _core_decomposition(
    case: dict[str, Any], config: dict[str, Any], demand_field: str, *,
    reference: dict[str, Any] | None, change_slot: int | None,
    include_event: bool, verification: bool, output_log: str | None,
    model_context: dict[str, Any] | None, deadline: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    prepared = _prepare(
        case, config, demand_field, reference, change_slot, include_event, model_context
    )
    if isinstance(prepared, dict):
        return prepared
    problem = prepared
    preprocessing_seconds = time.perf_counter() - started
    # Match the existing MILP protocol: its 300-second Gurobi limit starts only
    # after candidate generation/model construction.  End-to-end wall time is
    # still reported separately and therefore remains visible in comparisons.
    optimization_limit = (
        float(config["solver"]["formal_time_limit_seconds"])
        if not verification else float(
            config.get("decomposition", {}).get("verification_time_limit_seconds", 1800)
        )
    )
    overall_deadline = time.perf_counter() + optimization_limit
    configured_reserve = float(
        config.get("decomposition", {}).get("recovery_time_reserve_seconds", 60)
    )
    recovery_reserve = min(configured_reserve, 0.20 * optimization_limit)
    deadline = overall_deadline - recovery_reserve
    master, y, _, theta, vehicle_cost, trip_change = _build_master(problem, verification)
    active = _initial_columns(problem)
    initial_column_ids = {key: sorted(value) for key, value in active.items()}
    max_benders = int(config.get("decomposition", {}).get("max_benders_iterations", 100))
    target_gap = 0.0 if verification else float(config["solver"]["target_mip_gap"])
    best_upper = math.inf
    best_y: dict[str, float] | None = None
    lower_bound = -math.inf
    benders_iterations: list[dict[str, Any]] = []
    cut_signatures: set[tuple[Any, ...]] = set()
    termination = "iteration_limit"

    for iteration in range(1, max_benders + 1):
        if _remaining(deadline) <= 0.05:
            termination = "time_limit"
            break
        master.Params.TimeLimit = _remaining(deadline)
        master.optimize()
        if master.SolCount <= 0:
            termination = STATUS_NAMES.get(master.Status, str(master.Status))
            break
        ybar = {key: round(var.X) for key, var in y.items()}
        master_bound = float(master.ObjBound)
        lower_bound = max(lower_bound, master_bound)
        record: dict[str, Any] = {
            "iteration": iteration,
            "master_status": STATUS_NAMES.get(master.Status, str(master.Status)),
            "master_incumbent": float(master.ObjVal),
            "master_bound": master_bound,
            "theta": float(theta.X),
            "vehicle_cost": float(vehicle_cost.getValue()),
            "vehicle_change_cost": float(trip_change.getValue()),
            "mission_proposal_nonzero": {
                key: value for key, value in ybar.items() if value > TOL
            },
            "master_runtime_seconds": master.Runtime,
        }

        phase1 = _column_generation(problem, ybar, active, "feasibility", deadline)
        record["feasibility_column_generation"] = phase1
        if not phase1.get("converged"):
            record["outcome"] = "inner_not_converged"
            benders_iterations.append(record)
            termination = f"inner_{phase1.get('status')}"
            break
        if float(phase1["artificial_total"]) > 1e-6:
            beta = phase1["beta"]
            value = float(phase1["objective"])
            alpha = value - sum(beta.get(key, 0.0) * ybar[key] for key in ybar)
            signature = (
                "F", round(alpha, 8),
                tuple(sorted((key, round(val, 8)) for key, val in beta.items())),
            )
            if signature in cut_signatures:
                record["outcome"] = "duplicate_feasibility_cut"
                benders_iterations.append(record)
                termination = "stalled_duplicate_cut"
                break
            cut_signatures.add(signature)
            master.addConstr(
                alpha + gp.quicksum(beta.get(key, 0.0) * y[key] for key in y) <= 0.0,
                name=f"feasibility_cut[{iteration}]",
            )
            record.update({
                "outcome": "feasibility_cut",
                "cut": {"type": "feasibility", "alpha": alpha, "beta_nonzero": beta},
            })
            benders_iterations.append(record)
            continue

        phase2 = _column_generation(problem, ybar, active, "cost", deadline)
        record["cost_column_generation"] = phase2
        if not phase2.get("converged"):
            record["outcome"] = "inner_not_converged"
            benders_iterations.append(record)
            termination = f"inner_{phase2.get('status')}"
            break
        qbar = float(phase2["objective"])
        beta = phase2["beta"]
        alpha = qbar - sum(beta.get(key, 0.0) * ybar[key] for key in ybar)
        total = float(vehicle_cost.getValue()) + float(trip_change.getValue()) + qbar
        if total < best_upper - 1e-7:
            best_upper = total
            best_y = copy.deepcopy(ybar)
        signature = (
            "O", round(alpha, 8),
            tuple(sorted((key, round(val, 8)) for key, val in beta.items())),
        )
        cut_added = signature not in cut_signatures
        if cut_added:
            cut_signatures.add(signature)
            master.addConstr(
                theta >= alpha + gp.quicksum(beta.get(key, 0.0) * y[key] for key in y),
                name=f"optimality_cut[{iteration}]",
            )
        gap = (
            max(0.0, best_upper - lower_bound) / max(1.0, abs(best_upper))
            if math.isfinite(best_upper) and math.isfinite(lower_bound) else math.inf
        )
        record.update({
            "outcome": "optimality_cut" if cut_added else "duplicate_optimality_cut",
            "subproblem_cost": qbar,
            "candidate_upper_bound": total,
            "global_upper_bound": best_upper,
            "global_lower_bound": lower_bound,
            "relative_gap": gap,
            "cut": {"type": "optimality", "alpha": alpha, "beta_nonzero": beta},
        })
        benders_iterations.append(record)
        if gap <= target_gap + 1e-10:
            termination = "gap_reached"
            break
        if not cut_added:
            termination = "stalled_duplicate_cut"
            break

    trace = {
        "algorithm": "integer_benders_with_finite_pool_column_generation",
        "comparison_scope": "same_candidate_itinerary_universe_as_v6_milp",
        "candidate_universe_columns": sum(len(value) for value in problem.pools.values()),
        "preprocessing_seconds": preprocessing_seconds,
        "optimization_time_limit_seconds": optimization_limit,
        "recovery_time_reserve_seconds": recovery_reserve,
        "time_limit_scope": "after_candidate_generation_matching_v6_milp_gurobi_limit",
        "initial_columns": sum(len(value) for value in initial_column_ids.values()),
        "initial_column_ids_by_demand": initial_column_ids,
        "final_active_column_ids_by_demand": {
            key: sorted(value) for key, value in active.items()
        },
        "benders_iterations": benders_iterations,
        "benders_iteration_count": len(benders_iterations),
        "feasibility_cut_count": sum(
            item.get("outcome") == "feasibility_cut" for item in benders_iterations
        ),
        "optimality_cut_count": sum(
            item.get("outcome") == "optimality_cut" for item in benders_iterations
        ),
        "best_upper_bound": None if not math.isfinite(best_upper) else best_upper,
        "best_lower_bound": None if not math.isfinite(lower_bound) else lower_bound,
        "termination_reason": termination,
        "wall_seconds_before_recovery": time.perf_counter() - started,
        "all_zero_duals_omitted_from_log": True,
    }
    if best_y is None:
        return {
            "case_id": case["case_id"], "status": termination,
            "has_solution": False, "runtime_seconds": time.perf_counter() - started,
            "decomposition_trace": trace,
        }

    recovery_config = copy.deepcopy(config)
    if not verification:
        recovery_config["solver"]["formal_time_limit_seconds"] = max(
            1, int(_remaining(overall_deadline))
        )
    result = solve_static(
        case, recovery_config, demand_field, reference=reference,
        change_slot=change_slot, include_event=include_event,
        verification=verification, output_log=output_log,
        model_context=model_context, fixed_missions=best_y,
    )
    trace["recovery_status"] = result.get("status")
    trace["recovery_runtime_seconds"] = result.get("runtime_seconds")
    trace["total_wall_seconds"] = time.perf_counter() - started
    trace["recovered_objective"] = result.get("objective")
    trace["bound_consistency_error"] = (
        None if result.get("objective") is None
        else float(result["objective"]) - best_upper
    )
    result["decomposition_trace"] = trace
    result["solver_method"] = "benders_column_generation"
    result["runtime_seconds"] = time.perf_counter() - started
    result["best_bound"] = trace["best_lower_bound"]
    if result.get("objective") is not None and trace["best_lower_bound"] is not None:
        result["mip_gap"] = max(
            0.0, float(result["objective"]) - float(trace["best_lower_bound"])
        ) / max(1.0, abs(float(result["objective"])))
    if "plan_snapshot" in result:
        result["plan_snapshot"]["solver"].update({
            "method": "benders_column_generation",
            "benders_iterations": len(benders_iterations),
            "benders_termination": termination,
            "best_bound": trace["best_lower_bound"],
        })
    return result


def solve_static_benders_cg(
    case: dict[str, Any], config: dict[str, Any], demand_field: str, *,
    reference: dict[str, Any] | None = None, change_slot: int | None = None,
    include_event: bool = False, verification: bool = False,
    output_log: str | None = None, model_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    total_limit = (
        float(config["solver"]["formal_time_limit_seconds"])
        if not verification else float(config.get("decomposition", {}).get("verification_time_limit_seconds", 1800))
    )
    deadline = started + total_limit
    event = case.get("event", {})
    pending_id = None
    if include_event and event.get("type") == "urgent_insert":
        candidate_id = event.get("demand_id")
        record = next((r for r in case["demand"] if r["id"] == candidate_id), None)
        if (
            record is not None and float(record[demand_field]) > TOL
            and record.get("admission_status") is None
        ):
            pending_id = candidate_id
    if pending_id is None:
        return _core_decomposition(
            case, config, demand_field, reference=reference, change_slot=change_slot,
            include_event=include_event, verification=verification, output_log=output_log,
            model_context=model_context, deadline=deadline,
        )

    original = next(record for record in case["demand"] if record["id"] == pending_id)
    requested = int(original["release_slot"])
    admission_attempts = []
    horizon = int(config["time"]["observation_slots"])
    for admission_slot in range(requested, horizon):
        option_case = copy.deepcopy(case)
        option = next(record for record in option_case["demand"] if record["id"] == pending_id)
        option["service_clock_slot"] = requested
        option["release_slot"] = admission_slot
        option["candidate_key"] = f"{pending_id}_ADM{admission_slot}"
        option["admission_status"] = (
            "accepted_immediately" if admission_slot == requested else "accepted_deferred"
        )
        result = _core_decomposition(
            option_case, config, demand_field, reference=reference, change_slot=change_slot,
            include_event=include_event, verification=verification, output_log=output_log,
            model_context=model_context, deadline=deadline,
        )
        admission_attempts.append({
            "admission_slot": admission_slot, "status": result.get("status"),
            "has_solution": result.get("has_solution", False),
        })
        if result.get("has_solution"):
            result["insert_decision"] = {
                "demand_id": pending_id, "requested_slot": requested,
                "requested_hour": requested * int(config["time"]["slot_hours"]),
                "status": option["admission_status"], "admission_slot": admission_slot,
                "admission_hour": admission_slot * int(config["time"]["slot_hours"]),
                "defer_slots": admission_slot - requested,
                "defer_hours": (admission_slot - requested) * int(config["time"]["slot_hours"]),
                "service_clock_slot": requested, "service_clock_reset": False,
                "requested_tons": float(option[demand_field]),
            }
            result["decomposition_trace"]["urgent_insert_outer_admission_attempts"] = admission_attempts
            if "plan_snapshot" in result:
                result["plan_snapshot"]["insert_decision"] = copy.deepcopy(result["insert_decision"])
            return result
        if result.get("status") not in {"infeasible", "candidate_infeasible"}:
            result.setdefault("decomposition_trace", {})[
                "urgent_insert_outer_admission_attempts"
            ] = admission_attempts
            return result

    rejected_case = copy.deepcopy(case)
    rejected = next(record for record in rejected_case["demand"] if record["id"] == pending_id)
    rejected["service_clock_slot"] = requested
    rejected["admission_status"] = "rejected"
    result = _core_decomposition(
        rejected_case, config, demand_field, reference=reference, change_slot=change_slot,
        include_event=include_event, verification=verification, output_log=output_log,
        model_context=model_context, deadline=deadline,
    )
    decision = {
        "demand_id": pending_id, "requested_slot": requested,
        "requested_hour": requested * int(config["time"]["slot_hours"]),
        "status": "rejected_within_observation_horizon", "admission_slot": None,
        "admission_hour": None, "defer_slots": None, "defer_hours": None,
        "service_clock_slot": requested, "service_clock_reset": False,
        "requested_tons": float(original[demand_field]),
    }
    result["insert_decision"] = decision
    result.setdefault("decomposition_trace", {})[
        "urgent_insert_outer_admission_attempts"
    ] = admission_attempts
    if "plan_snapshot" in result:
        result["plan_snapshot"]["insert_decision"] = copy.deepcopy(decision)
    return result


def solve_case_benders_cg(
    case: dict[str, Any], config: dict[str, Any], verification: bool = False,
    output_log_dir: str | None = None, stop_after_slot: int | None = None,
) -> dict[str, Any]:
    result = solve_case(
        case, config, verification=verification, output_log_dir=output_log_dir,
        stop_after_slot=stop_after_slot, static_solver=solve_static_benders_cg,
    )
    result["solver_method"] = "benders_column_generation"
    result["comparison_protocol"] = {
        "model_protocol_version": int(config.get("model_protocol_version", 6)),
        "same_frozen_cases_as_milp": True,
        "same_candidate_itinerary_universe_as_milp": True,
        "only_solver_decomposition_changed": True,
    }
    return result
