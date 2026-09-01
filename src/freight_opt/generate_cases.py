from __future__ import annotations

import hashlib
import json
import math
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

import networkx as nx
import numpy as np

from .config import load_config, project_paths
from .data import CaseData, DemandRecord, EdgeData, EventData, NodeData, ScheduledTrip


def _stable_seed(master_seed: int, *parts: str) -> int:
    payload = "|".join([str(master_seed), *parts]).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % (2**32)


def _round(value: float) -> float:
    return round(float(value), 2)


def build_main_network(config: dict[str, Any]) -> tuple[list[NodeData], list[EdgeData], list[ScheduledTrip]]:
    seed = _stable_seed(config["master_seed"], "main_network")
    rng = np.random.default_rng(seed)
    time_cfg = config["time"]
    node_cfg = config["node"]
    vehicle_cfg = config["vehicle"]
    cost_cfg = config["cost"]
    schedule_cfg = config["schedule"]
    node_ids = config["network"]["main_node_ids"]

    nodes: list[NodeData] = []
    for node_id in node_ids:
        base_handling = float(rng.integers(
            int(node_cfg["handling_capacity_range"][0]),
            int(node_cfg["handling_capacity_range"][1]) + 1,
        ))
        handling = [
            _round(float(np.clip(
                base_handling * float(rng.uniform(0.90, 1.10)),
                node_cfg["handling_capacity_range"][0],
                node_cfg["handling_capacity_range"][1],
            )))
            for _ in range(time_cfg["observation_slots"])
        ]
        storage = float(rng.integers(
            int(node_cfg["storage_capacity_range"][0]),
            int(node_cfg["storage_capacity_range"][1]) + 1,
        ))
        vehicles = int(rng.integers(
            int(vehicle_cfg["initial_count_range"][0]),
            int(vehicle_cfg["initial_count_range"][1]) + 1,
        ))
        external_limits = [
            int(rng.integers(
                int(node_cfg["external_vehicle_limit_range"][0]),
                int(node_cfg["external_vehicle_limit_range"][1]) + 1,
            ))
            for _ in range(time_cfg["observation_slots"])
        ]
        nodes.append(NodeData(node_id, handling, storage, vehicles, external_limits))

    edges: list[EdgeData] = []
    travel_multiplier = int(config["network"].get("travel_slot_multiplier", 1))
    for left, right, base_travel_slots in config["network"]["undirected_pairs"]:
        travel_slots = int(base_travel_slots) * travel_multiplier
        for origin, destination in ((left, right), (right, left)):
            edge_id = f"{origin}_{destination}"
            edges.append(EdgeData(
                id=edge_id,
                origin=origin,
                destination=destination,
                travel_slots=int(travel_slots),
                normal_cost=_round(cost_cfg["normal_own_per_travel_slot"] * travel_slots),
                added_cost=_round(cost_cfg["added_own_per_travel_slot"] * travel_slots),
                outsourced_cost=_round(cost_cfg["outsourced_per_travel_slot"] * travel_slots),
            ))

    schedule_seed = _stable_seed(config["master_seed"], "main_schedule")
    schedule_rng = np.random.default_rng(schedule_seed)
    scheduled_trips: list[ScheduledTrip] = []
    low, high = schedule_cfg["trips_per_directed_edge_per_day_range"]
    for edge in edges:
        trips_per_day = int(schedule_rng.integers(low, high + 1))
        slots_per_day = int(time_cfg["slots_per_day"])
        rolling_step = int(time_cfg["rolling_interval_slots"])
        first_day_slots = sorted(schedule_rng.choice(
            np.arange(0, slots_per_day, rolling_step), size=trips_per_day, replace=False
        ).tolist())
        schedule_days = math.ceil(time_cfg["observation_slots"] / slots_per_day)
        for day in range(schedule_days):
            for sequence, slot in enumerate(first_day_slots):
                departure_slot = int(slot + slots_per_day * day)
                if departure_slot >= time_cfg["observation_slots"]:
                    continue
                scheduled_trips.append(ScheduledTrip(
                    id=f"SCH_{edge.id}_D{day + 1}_{sequence + 1}",
                    edge_id=edge.id,
                    departure_slot=departure_slot,
                ))

    return nodes, edges, scheduled_trips


def _graph(edges: Iterable[EdgeData]) -> nx.DiGraph:
    graph = nx.DiGraph()
    for edge in edges:
        graph.add_edge(edge.origin, edge.destination, weight=edge.travel_slots)
    return graph


def _slot_capacity(schedule: list[ScheduledTrip], capacity: float, slot: int) -> float:
    return sum(1 for trip in schedule if trip.departure_slot == slot) * capacity


def generate_demand(
    config: dict[str, Any],
    nodes: list[NodeData],
    edges: list[EdgeData],
    scheduled_trips: list[ScheduledTrip],
    rng: np.random.Generator,
) -> list[DemandRecord]:
    graph = _graph(edges)
    node_ids = [node.id for node in nodes]
    products = config["products"]
    product_names = list(products)
    product_shares = np.array([products[name]["share"] for name in product_names], dtype=float)
    product_shares /= product_shares.sum()
    vehicle_capacity = config["vehicle"]["capacity_equivalent_tons"]
    demand_records: list[DemandRecord] = []

    od_pairs: list[tuple[str, str, float]] = []
    for origin in node_ids:
        for destination in node_ids:
            if origin == destination:
                continue
            distance = nx.shortest_path_length(graph, origin, destination, weight="weight")
            weight = float(rng.gamma(shape=1.8, scale=1.0)) / max(1.0, float(distance))
            od_pairs.append((origin, destination, weight))

    od_weights = np.array([item[2] for item in od_pairs], dtype=float)
    od_weights /= od_weights.sum()

    release_slots = [int(slot) for slot in config["time"]["regular_arrival_slots"]]
    error_low, error_high = [float(value) for value in config["demand"]["batch_total_error_range"]]
    batch_errors = {slot: float(rng.uniform(error_low, error_high)) for slot in release_slots}
    future_slots = release_slots[1:]
    minimum_error = float(config["demand"]["minimum_material_future_error"])
    if future_slots and all(abs(batch_errors[slot]) < minimum_error for slot in future_slots):
        forced_slot = future_slots[int(rng.integers(0, len(future_slots)))]
        sign = -1.0 if rng.random() < 0.5 else 1.0
        batch_errors[forced_slot] = sign * float(rng.uniform(minimum_error, max(minimum_error, error_high)))

    for release_slot in release_slots:
        slot_start = len(demand_records)
        base_capacity = _slot_capacity(scheduled_trips, vehicle_capacity, release_slot)
        if release_slot == release_slots[-1]:
            load_low, load_high = config["demand"]["peak_load_ratio_range"]
        else:
            load_low, load_high = config["demand"]["ordinary_load_ratio_range"]
        target_total = base_capacity * float(rng.uniform(load_low, load_high))
        target_total = max(target_total, vehicle_capacity * 2.0)

        record_index = 0
        for product, product_share in zip(product_names, product_shares):
            product_start = len(demand_records)
            eligible_weights = np.array([
                od_weight
                if (
                    product != "urgent"
                    or nx.shortest_path_length(
                        graph, origin, destination, weight="weight"
                    ) <= int(products[product]["deadline_slots"])
                )
                else 0.0
                for (origin, destination, _), od_weight in zip(od_pairs, od_weights)
            ], dtype=float)
            eligible_weights *= rng.uniform(0.85, 1.15, size=len(eligible_weights))
            eligible_weights /= eligible_weights.sum()
            product_target = target_total * float(product_share)
            for (origin, destination, _), od_weight in zip(od_pairs, eligible_weights):
                if od_weight <= 0:
                    continue
                forecast = product_target * float(od_weight)
                record_index += 1
                demand_records.append(DemandRecord(
                    id=f"DEM_T{release_slot}_{origin}_{destination}_{product}_{record_index:03d}",
                    origin=origin,
                    destination=destination,
                    product=product,
                    release_slot=release_slot,
                    forecast_tons=_round(forecast),
                    actual_tons=0.0,
                ))
            product_records = demand_records[product_start:]
            residual = _round(_round(product_target) - sum(record.forecast_tons for record in product_records))
            if abs(residual) > 0:
                largest_index = max(
                    range(len(product_records)),
                    key=lambda idx: product_records[idx].forecast_tons,
                )
                product_records[largest_index] = replace(
                    product_records[largest_index],
                    forecast_tons=_round(product_records[largest_index].forecast_tons + residual),
                )
                demand_records[product_start:] = product_records
        slot_records = demand_records[slot_start:]
        residual = _round(_round(target_total) - sum(record.forecast_tons for record in slot_records))
        if abs(residual) > 0:
            largest_index = max(
                range(len(slot_records)),
                key=lambda idx: slot_records[idx].forecast_tons,
            )
            slot_records[largest_index] = replace(
                slot_records[largest_index],
                forecast_tons=_round(slot_records[largest_index].forecast_tons + residual),
            )
            demand_records[slot_start:] = slot_records

        slot_records = demand_records[slot_start:]
        actual_total = _round(target_total * (1.0 + batch_errors[release_slot]))
        perturbation = float(config["demand"]["od_product_share_perturbation"])
        perturbed = np.array([
            max(0.0, record.forecast_tons * float(rng.uniform(1.0 - perturbation, 1.0 + perturbation)))
            for record in slot_records
        ])
        if perturbed.sum() <= 1e-9:
            raise RuntimeError("Forecast allocation unexpectedly has zero mass")
        actual_values = actual_total * perturbed / perturbed.sum()
        slot_records = [
            replace(record, actual_tons=_round(value))
            for record, value in zip(slot_records, actual_values)
        ]
        actual_residual = _round(actual_total - sum(record.actual_tons for record in slot_records))
        if abs(actual_residual) > 0:
            largest_index = max(range(len(slot_records)), key=lambda idx: slot_records[idx].actual_tons)
            slot_records[largest_index] = replace(
                slot_records[largest_index],
                actual_tons=_round(slot_records[largest_index].actual_tons + actual_residual),
            )
        demand_records[slot_start:] = slot_records
    return demand_records


def apply_event(
    config: dict[str, Any],
    category: str,
    nodes: list[NodeData],
    edges: list[EdgeData],
    demand: list[DemandRecord],
    rng: np.random.Generator,
    event_slot: int | None = None,
) -> tuple[list[DemandRecord], EventData]:
    if category == "normal":
        return demand, EventData(type="none")

    node_ids = [node.id for node in nodes]
    graph = _graph(edges)

    if category == "urgent_insert":
        if event_slot is None:
            raise ValueError("urgent_insert requires an event slot")
        urgent_deadline = int(config["products"]["urgent"]["deadline_slots"])
        eligible_pairs = [
            (origin, destination)
            for origin in node_ids for destination in node_ids
            if origin != destination
            and nx.shortest_path_length(graph, origin, destination, weight="weight") <= urgent_deadline
        ]
        origin, destination = eligible_pairs[int(rng.integers(0, len(eligible_pairs)))]
        low, high = config["demand"]["urgent_insert_tons_range"]
        tons = _round(rng.uniform(low, high))
        inserted = DemandRecord(
            id=f"EMG_INSERT_T{event_slot}_{origin}_{destination}",
            origin=origin,
            destination=destination,
            product="urgent",
            release_slot=event_slot,
            forecast_tons=0.0,
            actual_tons=tons,
        )
        return [*demand, inserted], EventData(
            type="urgent_insert", slot=event_slot, origin=origin,
            destination=destination, product="urgent", tons=tons,
            demand_id=inserted.id,
        )

    if category == "urgent_cancel":
        if event_slot is None:
            raise ValueError("urgent_cancel requires an event slot")
        low, high = config["demand"]["urgent_cancel_tons_range"]
        tons = _round(float(rng.uniform(low, high)))
        return demand, EventData(
            type="urgent_cancel", slot=event_slot, tons=tons,
            selection_policy="runtime_unshipped_cargo",
        )

    if category == "vehicle_breakdown":
        if event_slot is None:
            raise ValueError("vehicle_breakdown requires an event slot")
        return demand, EventData(
            type="vehicle_breakdown", slot=event_slot,
            vehicle_count=config["vehicle"]["breakdown_count"],
            selection_policy="runtime_available_own_vehicle",
        )

    raise ValueError(f"Unsupported category: {category}")


def make_case(config: dict[str, Any], split: str, category: str, index: int) -> CaseData:
    nodes, edges, scheduled_trips = build_main_network(config)
    seed = _stable_seed(config["master_seed"], split, category, f"{index:03d}")
    rng = np.random.default_rng(seed)
    demand = generate_demand(config, nodes, edges, scheduled_trips, rng)
    event_slot = None
    if category != "normal":
        candidate_slots = [int(slot) for slot in config["events"][f"{category}_slots"]]
        order_rng = np.random.default_rng(_stable_seed(config["master_seed"], split, category, "event_slot_order"))
        shuffled_slots = order_rng.permutation(candidate_slots).tolist()
        event_slot = int(shuffled_slots[(index - 1) % len(shuffled_slots)])
    demand, event = apply_event(config, category, nodes, edges, demand, rng, event_slot=event_slot)
    return CaseData(
        schema_version=int(config["schema_version"]),
        case_id=f"{split}_{category}_{index:03d}",
        split=split,
        category=category,
        seed=seed,
        nodes=nodes,
        edges=edges,
        scheduled_trips=scheduled_trips,
        demand=demand,
        event=event,
        metadata={
            "batch_total_error_range": config["demand"]["batch_total_error_range"],
            "od_product_share_perturbation": config["demand"]["od_product_share_perturbation"],
            "slot_hours": config["time"]["slot_hours"],
            "rolling_interval_hours": config["time"]["rolling_interval_hours"],
            "change_penalty_ratio_candidate": config["cost"]["balanced_change_penalty_ratio"],
            "status": config["status"],
        },
    )


def _verification_network() -> tuple[list[NodeData], list[EdgeData]]:
    observation_slots = 24
    nodes = [
        NodeData("A", [80.0] * observation_slots, 60.0, 2, [2] * observation_slots),
        NodeData("B", [80.0] * observation_slots, 60.0, 2, [2] * observation_slots),
        NodeData("C", [80.0] * observation_slots, 60.0, 2, [2] * observation_slots),
    ]
    edges = []
    for origin, destination, slots in (
        ("A", "B", 2), ("B", "A", 2),
        ("B", "C", 2), ("C", "B", 2),
        ("A", "C", 4), ("C", "A", 4),
    ):
        edges.append(EdgeData(
            id=f"{origin}_{destination}", origin=origin, destination=destination,
            travel_slots=slots, normal_cost=50.0 * slots,
            added_cost=60.0 * slots, outsourced_cost=90.0 * slots,
        ))
    return nodes, edges


def make_verification_case(config: dict[str, Any], index: int) -> CaseData:
    nodes, edges = _verification_network()
    case_id = f"verify_V{index:02d}"
    seed = _stable_seed(config["master_seed"], case_id)
    scheduled: list[ScheduledTrip] = []
    demand: list[DemandRecord] = []
    event = EventData(type="none")
    expected = ""

    if index == 1:
        scheduled = [ScheduledTrip("SCH_A_B_0", "A_B", 0)]
        demand = [DemandRecord("D1", "A", "B", "urgent", 0, 5.0, 5.0)]
        expected = "Use the scheduled direct trip; no transfer, hold, added or outsourced trip."
    elif index == 2:
        edges = [replace(
            edge,
            added_cost=1000.0 * edge.travel_slots,
            outsourced_cost=1500.0 * edge.travel_slots,
        ) for edge in edges]
        scheduled = [ScheduledTrip("SCH_A_B_0", "A_B", 0), ScheduledTrip("SCH_B_C_2", "B_C", 2)]
        demand = [DemandRecord("D1", "A", "C", "standard", 0, 8.0, 8.0)]
        expected = "Use one transfer through B because no A-C scheduled trip is available."
    elif index == 3:
        edges = [
            replace(edge, normal_cost=300.0) if edge.id == "A_C" else edge
            for edge in edges
        ]
        scheduled = [ScheduledTrip("SCH_A_C_0", "A_C", 0)]
        demand = [DemandRecord("D1", "A", "C", "urgent", 0, 8.0, 8.0)]
        expected = "A-B-C string service may be selected; staying onboard at B is not a transfer."
    elif index == 4:
        scheduled = [ScheduledTrip("SCH_A_B_0", "A_B", 0)]
        demand = [DemandRecord("D1", "A", "B", "standard", 0, 5.0, 5.0)]
        inserted = DemandRecord("EMG_INSERT_T1_A_C", "A", "C", "urgent", 1, 0.0, 8.0)
        demand.append(inserted)
        event = EventData(type="urgent_insert", slot=1, origin="A", destination="C", product="urgent", tons=8.0, demand_id=inserted.id)
        expected = "An off-cycle insertion at hour 3 triggers one additional replan and on-time recovery."
    else:
        raise ValueError(index)

    return CaseData(
        schema_version=int(config["schema_version"]),
        case_id=case_id,
        split="verification",
        category=f"V{index:02d}",
        seed=seed,
        nodes=nodes,
        edges=edges,
        scheduled_trips=scheduled,
        demand=demand,
        event=event,
        metadata={"expected_behavior": expected, "status": config["status"]},
    )


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate_all(root: Path | None = None) -> Path:
    paths = project_paths(root)
    config = load_config(paths.config)
    output = paths.draft_data
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    nodes, edges, scheduled = build_main_network(config)
    _write_json(output / "main_network.json", {
        "schema_version": int(config["schema_version"]),
        "status": config["status"],
        "nodes": [node.__dict__ for node in nodes],
        "edges": [edge.__dict__ for edge in edges],
        "scheduled_trips": [trip.__dict__ for trip in scheduled],
    })

    for index in range(1, config["datasets"]["verification_cases"] + 1):
        case = make_verification_case(config, index)
        _write_json(output / "verification" / f"{case.case_id}.json", case.to_dict())

    for split, count_per_category in (
        ("validation", config["datasets"]["validation_cases_per_category"]),
        ("test", config["datasets"]["test_cases_per_category"]),
    ):
        for category in config["datasets"]["categories"]:
            for index in range(1, count_per_category + 1):
                case = make_case(config, split, category, index)
                _write_json(output / split / category / f"{case.case_id}.json", case.to_dict())

    files = sorted(path for path in output.rglob("*.json") if path.name != "manifest.json")
    manifest = {
        "schema_version": int(config["schema_version"]),
        "status": config["status"],
        "generator": "src.freight_opt.generate_cases.generate_all",
        "master_seed": config["master_seed"],
        "file_count": len(files),
        "files": [
            {
                "path": path.relative_to(paths.root).as_posix(),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in files
        ],
    }
    _write_json(output / "manifest.json", manifest)
    return output
