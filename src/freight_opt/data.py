from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class NodeData:
    id: str
    handling_capacity: list[float]
    storage_capacity: float
    initial_own_vehicles: int
    external_vehicle_limit: list[int]


@dataclass(frozen=True)
class EdgeData:
    id: str
    origin: str
    destination: str
    travel_slots: int
    normal_cost: float
    added_cost: float
    outsourced_cost: float


@dataclass(frozen=True)
class ScheduledTrip:
    id: str
    edge_id: str
    departure_slot: int


@dataclass(frozen=True)
class DemandRecord:
    id: str
    origin: str
    destination: str
    product: str
    release_slot: int
    forecast_tons: float
    actual_tons: float


@dataclass(frozen=True)
class EventData:
    type: str
    slot: int | None = None
    origin: str | None = None
    destination: str | None = None
    product: str | None = None
    tons: float | None = None
    node: str | None = None
    vehicle_count: int | None = None
    demand_id: str | None = None
    demand_adjustments: list[dict[str, Any]] | None = None
    selection_policy: str | None = None


@dataclass(frozen=True)
class CaseData:
    schema_version: int
    case_id: str
    split: str
    category: str
    seed: int
    nodes: list[NodeData]
    edges: list[EdgeData]
    scheduled_trips: list[ScheduledTrip]
    demand: list[DemandRecord]
    event: EventData
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
