from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import dataclass, replace
from itertools import count
from typing import Any


@dataclass(frozen=True)
class Segment:
    edge_id: str
    origin: str
    destination: str
    departure: int
    arrival: int
    index: int


@dataclass(frozen=True)
class Service:
    id: str
    route: tuple[str, ...]
    departure: int
    arrival: int
    segments: tuple[Segment, ...]


@dataclass(frozen=True)
class Mission:
    id: str
    service_id: str
    mode: str
    vehicle_source: str
    origin: str
    destination: str
    departure: int
    arrival: int
    cost: float
    template_id: str | None
    upper_bound: int


@dataclass(frozen=True)
class Ride:
    id: str
    service_id: str
    origin: str
    destination: str
    departure: int
    arrival: int
    covered_segments: tuple[int, ...]
    traversed_nodes: tuple[str, ...]


@dataclass(frozen=True)
class Itinerary:
    id: str
    demand_id: str
    rides: tuple[Ride, ...]
    arrival: int
    transfers: int
    holding_slots: int
    delay_slots: int
    variable_cost_per_ton: float
    resource_keys: tuple[tuple[str, int], ...]
    handling_operations: tuple[tuple[str, int, int], ...]
    storage_occupancy: tuple[tuple[str, int], ...]


def _service_id(route: tuple[str, ...], departure: int) -> str:
    return f"S_{'-'.join(route)}_T{departure}"


def _route_segments(
    route: tuple[str, ...], departure: int, edge_by_pair: dict[tuple[str, str], dict[str, Any]]
) -> tuple[Segment, ...]:
    segments: list[Segment] = []
    clock = departure
    for index, (origin, destination) in enumerate(zip(route, route[1:])):
        edge = edge_by_pair[(origin, destination)]
        arrival = clock + int(edge["travel_slots"])
        segments.append(Segment(edge["id"], origin, destination, clock, arrival, index))
        clock = arrival
    return tuple(segments)


def build_services_and_missions(
    case: dict[str, Any], config: dict[str, Any]
) -> tuple[dict[str, Service], list[Mission]]:
    horizon = int(config["time"]["observation_slots"])
    edge_by_id = {edge["id"]: edge for edge in case["edges"]}
    edge_by_pair = {(edge["origin"], edge["destination"]): edge for edge in case["edges"]}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in case["edges"]:
        outgoing[edge["origin"]].append(edge["destination"])

    routes: set[tuple[str, ...]] = set()
    for edge in case["edges"]:
        routes.add((edge["origin"], edge["destination"]))
    if int(config["network"]["max_string_stops"]) >= 1:
        for first in case["edges"]:
            for destination in outgoing[first["destination"]]:
                if destination != first["origin"]:
                    routes.add((first["origin"], first["destination"], destination))

    services: dict[str, Service] = {}
    for route in sorted(routes):
        for departure in range(horizon):
            segments = _route_segments(route, departure, edge_by_pair)
            arrival = segments[-1].arrival
            if arrival <= horizon:
                service_id = _service_id(route, departure)
                services[service_id] = Service(service_id, route, departure, arrival, segments)

    total_own = sum(int(node["initial_own_vehicles"]) for node in case["nodes"])
    node_by_id = {node["id"]: node for node in case["nodes"]}
    missions: list[Mission] = []

    for service in services.values():
        added_cost = sum(float(edge_by_id[segment.edge_id]["added_cost"]) for segment in service.segments)
        outsourced_cost = sum(float(edge_by_id[segment.edge_id]["outsourced_cost"]) for segment in service.segments)
        missions.append(Mission(
            id=f"ADD_{service.id}", service_id=service.id, mode="added_own",
            vehicle_source="own", origin=service.route[0], destination=service.route[-1],
            departure=service.departure, arrival=service.arrival, cost=added_cost,
            template_id=None, upper_bound=max(1, total_own),
        ))
        ext_limit = int(node_by_id[service.route[0]]["external_vehicle_limit"][service.departure])
        missions.append(Mission(
            id=f"EXT_{service.id}", service_id=service.id, mode="outsourced",
            vehicle_source="external", origin=service.route[0], destination=service.route[-1],
            departure=service.departure, arrival=service.arrival, cost=outsourced_cost,
            template_id=None, upper_bound=ext_limit,
        ))

    for trip in case["scheduled_trips"]:
        base_edge = edge_by_id[trip["edge_id"]]
        origin = base_edge["origin"]
        destination = base_edge["destination"]
        departure = int(trip["departure_slot"])
        candidate_routes = [(origin, destination)]
        if int(config["network"]["max_string_stops"]) >= 1:
            candidate_routes.extend(
                (origin, middle, destination)
                for middle in outgoing[origin]
                if middle not in (origin, destination) and (middle, destination) in edge_by_pair
            )
        for variant, route in enumerate(candidate_routes):
            service_id = _service_id(tuple(route), departure)
            if service_id not in services:
                continue
            service = services[service_id]
            normal_cost = sum(float(edge_by_id[segment.edge_id]["normal_cost"]) for segment in service.segments)
            missions.append(Mission(
                id=f"NOR_{trip['id']}_V{variant}", service_id=service_id,
                mode="normal", vehicle_source="own", origin=origin,
                destination=destination, departure=departure, arrival=service.arrival,
                cost=normal_cost, template_id=trip["id"], upper_bound=1,
            ))
    return services, missions


def build_rides(services: dict[str, Service]) -> dict[str, list[Ride]]:
    rides_by_origin: dict[str, list[Ride]] = defaultdict(list)
    for service in services.values():
        route = service.route
        for board_index in range(len(route) - 1):
            for alight_index in range(board_index + 1, len(route)):
                first_segment = service.segments[board_index]
                last_segment = service.segments[alight_index - 1]
                ride = Ride(
                    id=f"R_{service.id}_{board_index}_{alight_index}",
                    service_id=service.id,
                    origin=route[board_index],
                    destination=route[alight_index],
                    departure=first_segment.departure,
                    arrival=last_segment.arrival,
                    covered_segments=tuple(range(board_index, alight_index)),
                    traversed_nodes=route[board_index + 1:alight_index + 1],
                )
                rides_by_origin[ride.origin].append(ride)
    for rides in rides_by_origin.values():
        rides.sort(key=lambda ride: (ride.departure, ride.arrival, ride.service_id, ride.destination))
    return rides_by_origin


def _wait_is_legal(
    product: str, start: int, departure: int, allow_overnight: bool, slots_per_day: int
) -> bool:
    if departure <= start:
        return True
    if not allow_overnight:
        return start // slots_per_day == departure // slots_per_day
    return True


def _shift_itinerary(
    itinerary: Itinerary,
    demand: dict[str, Any],
    services: dict[str, Service],
    delta: int,
    config: dict[str, Any],
) -> Itinerary | None:
    if delta <= 0:
        return itinerary
    shifted_rides: list[Ride] = []
    for ride in itinerary.rides:
        original_service = services[ride.service_id]
        shifted_id = _service_id(original_service.route, original_service.departure + delta)
        shifted_service = services.get(shifted_id)
        if shifted_service is None:
            return None
        board_index = min(ride.covered_segments)
        alight_index = max(ride.covered_segments) + 1
        first_segment = shifted_service.segments[board_index]
        last_segment = shifted_service.segments[alight_index - 1]
        shifted_rides.append(Ride(
            id=f"R_{shifted_id}_{board_index}_{alight_index}",
            service_id=shifted_id,
            origin=ride.origin,
            destination=ride.destination,
            departure=first_segment.departure,
            arrival=last_segment.arrival,
            covered_segments=ride.covered_segments,
            traversed_nodes=ride.traversed_nodes,
        ))

    release = int(demand["release_slot"])
    service_clock = int(demand.get("service_clock_slot", release))
    horizon = int(config["time"]["observation_slots"])
    deadline = int(config["products"][demand["product"]]["deadline_slots"])
    storage: list[tuple[str, int]] = []
    operations: list[tuple[str, int, int]] = []
    resources: list[tuple[str, int]] = []
    current_node = demand["origin"]
    current_time = release
    for ride in shifted_rides:
        storage.extend((current_node, slot) for slot in range(current_time, ride.departure))
        operations.append((ride.origin, min(ride.departure, horizon - 1), 1))
        operations.append((ride.destination, min(ride.arrival, horizon - 1), 1))
        resources.extend((ride.service_id, index) for index in ride.covered_segments)
        current_node = ride.destination
        current_time = ride.arrival
    transfers = len(shifted_rides) - 1
    delay_slots = max(0, shifted_rides[-1].arrival - service_clock - deadline)
    variable_cost = (
        float(config["cost"]["inventory_holding_per_ton_slot"]) * len(storage)
        + float(config["cost"]["handling_per_ton_operation"]) * (2 + 2 * transfers)
        + float(config["cost"]["transfer_extra_per_ton"]) * transfers
        + float(config["products"][demand["product"]]["delay_cost_per_ton_slot"]) * delay_slots
    )
    return Itinerary(
        id=itinerary.id,
        demand_id=itinerary.demand_id,
        rides=tuple(shifted_rides),
        arrival=shifted_rides[-1].arrival,
        transfers=transfers,
        holding_slots=len(storage),
        delay_slots=delay_slots,
        variable_cost_per_ton=variable_cost,
        resource_keys=tuple(resources),
        handling_operations=tuple(operations),
        storage_occupancy=tuple(storage),
    )


def generate_itineraries(
    demand: dict[str, Any],
    config: dict[str, Any],
    services: dict[str, Service],
    rides_by_origin: dict[str, list[Ride]],
    max_itineraries: int = 36,
) -> list[Itinerary]:
    product = demand["product"]
    product_cfg = config["products"][product]
    release = int(demand["release_slot"])
    service_clock = int(demand.get("service_clock_slot", release))
    candidate_key = str(demand.get("candidate_key", demand["id"]))
    deadline = int(product_cfg["deadline_slots"])
    max_boardings = int(product_cfg["max_transfers"]) + 1
    allow_overnight = bool(product_cfg["allow_overnight_hold"])
    horizon = int(config["time"]["observation_slots"])
    holding_cost = float(config["cost"]["inventory_holding_per_ton_slot"])
    handling_cost = float(config["cost"]["handling_per_ton_operation"])
    transfer_extra = float(config["cost"]["transfer_extra_per_ton"])
    delay_cost = float(product_cfg["delay_cost_per_ton_slot"])
    slots_per_day = int(config["time"]["slots_per_day"])

    delayed_budget = 6 if max_itineraries >= 8 else 0
    cheapest_budget = max_itineraries - delayed_budget

    mission_cost_per_service: dict[str, float] = {}
    for service_id, service in services.items():
        travel = service.arrival - service.departure
        mission_cost_per_service[service_id] = float(config["time"]["slot_hours"]) * travel

    serial = count()
    queue: list[tuple[float, int, str, int, int, frozenset[str], tuple[Ride, ...], int]] = []
    heapq.heappush(queue, (0.0, next(serial), demand["origin"], release, 0,
                           frozenset([demand["origin"]]), tuple(), 0))
    results: list[Itinerary] = []
    seen_results: set[tuple[str, ...]] = set()
    expanded_best: dict[tuple[str, int, int, frozenset[str]], list[float]] = defaultdict(list)

    while queue and len(results) < cheapest_budget:
        score, _, node, clock, boardings, visited, chosen, holding_slots = heapq.heappop(queue)
        if node == demand["destination"] and chosen:
            signature = tuple(ride.id for ride in chosen)
            if signature in seen_results:
                continue
            seen_results.add(signature)
            transfers = len(chosen) - 1
            arrival = chosen[-1].arrival
            delay_slots = max(0, arrival - service_clock - deadline)
            operations: list[tuple[str, int, int]] = []
            storage: list[tuple[str, int]] = []
            current_node = demand["origin"]
            current_time = release
            resources: list[tuple[str, int]] = []
            for ride in chosen:
                for slot in range(current_time, ride.departure):
                    storage.append((current_node, slot))
                operations.append((ride.origin, min(ride.departure, horizon - 1), 1))
                operations.append((ride.destination, min(ride.arrival, horizon - 1), 1))
                resources.extend((ride.service_id, index) for index in ride.covered_segments)
                current_node = ride.destination
                current_time = ride.arrival
            variable_cost = (
                holding_cost * holding_slots
                + handling_cost * (2 + 2 * transfers)
                + transfer_extra * transfers
                + delay_cost * delay_slots
            )
            results.append(Itinerary(
                id=f"IT_{candidate_key}_{len(results):03d}", demand_id=demand["id"],
                rides=chosen, arrival=arrival, transfers=transfers,
                holding_slots=holding_slots, delay_slots=delay_slots,
                variable_cost_per_ton=variable_cost,
                resource_keys=tuple(resources), handling_operations=tuple(operations),
                storage_occupancy=tuple(storage),
            ))
            continue
        if boardings >= max_boardings:
            continue

        state_key = (node, clock, boardings, visited)
        prior_scores = expanded_best[state_key]
        if len(prior_scores) >= 4 and score >= max(prior_scores):
            continue
        prior_scores.append(score)
        prior_scores.sort()
        del prior_scores[4:]

        for ride in rides_by_origin.get(node, []):
            if ride.departure < clock or ride.arrival > horizon:
                continue
            if ride.destination in visited or any(n in visited for n in ride.traversed_nodes):
                continue
            if not _wait_is_legal(product, clock, ride.departure, allow_overnight, slots_per_day):
                continue
            wait = ride.departure - clock
            new_holding = holding_slots + wait
            new_boardings = boardings + 1
            transfers = max(0, new_boardings - 1)
            provisional_delay = (
                max(0, ride.arrival - service_clock - deadline)
                if ride.destination == demand["destination"] else 0
            )
            increment = (
                mission_cost_per_service[ride.service_id]
                + holding_cost * wait
                + handling_cost * 2
                + (transfer_extra if new_boardings > 1 else 0.0)
                + delay_cost * provisional_delay
            )
            heapq.heappush(queue, (
                score + increment, next(serial), ride.destination, ride.arrival,
                new_boardings, visited.union(ride.traversed_nodes),
                (*chosen, ride), new_holding,
            ))
    # Create delayed recovery choices by time-shifting two good route patterns.
    # Added/outsourced services exist in every slot, so this avoids three extra
    # graph searches per demand and keeps candidate generation fast.
    if delayed_budget and results:
        seen = {tuple(ride.id for ride in itinerary.rides) for itinerary in results}
        for fraction in (0.33, 0.55, 0.75):
            threshold = int(round(release + (horizon - release) * fraction))
            for source in results[:2]:
                delta = max(0, threshold - source.rides[0].departure)
                shifted = _shift_itinerary(source, demand, services, delta, config)
                if shifted is None:
                    continue
                signature = tuple(ride.id for ride in shifted.rides)
                if signature in seen:
                    continue
                seen.add(signature)
                results.append(replace(
                    shifted,
                    id=f"IT_{candidate_key}_{len(results):03d}",
                ))
                if len(results) >= max_itineraries:
                    return results
    return results
