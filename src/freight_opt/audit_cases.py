from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

import networkx as nx

from .config import load_config, project_paths


def _load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def audit_draft(root: Path | None = None, data_dir: Path | None = None) -> dict[str, Any]:
    paths = project_paths(root)
    config = load_config(paths.config)
    draft = Path(data_dir) if data_dir is not None else paths.draft_data
    errors: list[str] = []
    warnings: list[str] = []

    test_files = sorted((draft / "test").rglob("*.json"))
    validation_files = sorted((draft / "validation").rglob("*.json"))
    verification_files = sorted((draft / "verification").glob("*.json"))
    expected_test = len(config["datasets"]["categories"]) * config["datasets"]["test_cases_per_category"]
    expected_validation = len(config["datasets"]["categories"]) * config["datasets"]["validation_cases_per_category"]
    if len(test_files) != expected_test:
        errors.append(f"Expected {expected_test} test cases, found {len(test_files)}")
    if len(validation_files) != expected_validation:
        errors.append(f"Expected {expected_validation} validation cases, found {len(validation_files)}")
    if len(verification_files) != config["datasets"]["verification_cases"]:
        errors.append("Verification case count mismatch")

    categories = Counter()
    release_forecast = defaultdict(float)
    release_actual = defaultdict(float)
    product_forecast = defaultdict(float)
    event_tons = defaultdict(list)
    node_signatures: set[str] = set()
    edge_signatures: set[str] = set()
    schedule_signatures: set[str] = set()
    forecast_errors: list[float] = []
    batch_errors: list[float] = []
    post_event_batch_errors: list[float] = []
    ordinary_load_ratios: list[float] = []
    peak_load_ratios: list[float] = []

    for path in [*validation_files, *test_files]:
        case = _load(path)
        categories[(case["split"], case["category"])] += 1
        if len(case["nodes"]) != config["network"]["main_nodes"]:
            errors.append(f"{case['case_id']}: wrong node count")
        handling_low, handling_high = config["node"]["handling_capacity_range"]
        storage_low, storage_high = config["node"]["storage_capacity_range"]
        own_low, own_high = config["vehicle"]["initial_count_range"]
        external_low, external_high = config["node"]["external_vehicle_limit_range"]
        for node in case["nodes"]:
            if any(not (handling_low <= value <= handling_high) for value in node["handling_capacity"]):
                errors.append(f"{case['case_id']}: node {node['id']} handling capacity out of range")
            if not (storage_low <= node["storage_capacity"] <= storage_high):
                errors.append(f"{case['case_id']}: node {node['id']} storage capacity out of range")
            if not (own_low <= node["initial_own_vehicles"] <= own_high):
                errors.append(f"{case['case_id']}: node {node['id']} initial vehicles out of range")
            if any(not (external_low <= value <= external_high) for value in node["external_vehicle_limit"]):
                errors.append(f"{case['case_id']}: node {node['id']} external limit out of range")

        graph = nx.DiGraph()
        for edge in case["edges"]:
            graph.add_edge(
                edge["origin"], edge["destination"],
                travel_slots=edge["travel_slots"],
            )
            allowed_travel_slots = {
                int(item[2]) * int(config["network"].get("travel_slot_multiplier", 1))
                for item in config["network"]["undirected_pairs"]
            }
            if edge["travel_slots"] not in allowed_travel_slots:
                errors.append(f"{case['case_id']}: invalid travel slots")
        if not nx.is_strongly_connected(graph):
            errors.append(f"{case['case_id']}: graph is not strongly connected")

        node_signatures.add(json.dumps(case["nodes"], sort_keys=True))
        edge_signatures.add(json.dumps(case["edges"], sort_keys=True))
        schedule_signatures.add(json.dumps(case["scheduled_trips"], sort_keys=True))

        event = case["event"]
        if case["category"] == "normal" and event["type"] != "none":
            errors.append(f"{case['case_id']}: normal case has an event")
        if case["category"] != "normal" and event["type"] != case["category"]:
            errors.append(f"{case['case_id']}: event/category mismatch")
        if event["type"] in ("urgent_insert", "urgent_cancel"):
            event_tons[event["type"]].append(float(event["tons"]))
        if event["type"] == "urgent_insert" and event["product"] != "urgent":
            errors.append(f"{case['case_id']}: inserted demand is not urgent")
        if event["type"] == "vehicle_breakdown" and event["vehicle_count"] != 1:
            errors.append(f"{case['case_id']}: breakdown count is not 1")
        if event["type"] == "vehicle_breakdown":
            if event.get("node") is not None:
                errors.append(f"{case['case_id']}: breakdown node must be resolved from the runtime vehicle state")
            if event.get("selection_policy") != "runtime_available_own_vehicle":
                errors.append(f"{case['case_id']}: wrong breakdown vehicle selection policy")
        if event["type"] == "urgent_cancel":
            low, high = config["demand"]["urgent_cancel_tons_range"]
            if not (low - 0.02 <= float(event["tons"]) <= high + 0.02):
                errors.append(f"{case['case_id']}: cancellation tons outside configured range")
            if event.get("demand_adjustments"):
                errors.append(f"{case['case_id']}: cancellation targets must be resolved at runtime")
            if event.get("selection_policy") != "runtime_unshipped_cargo":
                errors.append(f"{case['case_id']}: wrong cancellation selection policy")
        if event["type"] != "none":
            configured_slots = {
                "urgent_insert": config["events"]["urgent_insert_slots"],
                "urgent_cancel": config["events"]["urgent_cancel_slots"],
                "vehicle_breakdown": config["events"]["vehicle_breakdown_slots"],
            }[event["type"]]
            if int(event["slot"]) not in [int(slot) for slot in configured_slots]:
                errors.append(f"{case['case_id']}: event outside configured off-cycle slots")
            if int(event["slot"]) % int(config["time"]["rolling_interval_slots"]) == 0:
                errors.append(f"{case['case_id']}: event coincides with periodic replan")

        trip_count_by_slot = Counter(
            trip["departure_slot"] for trip in case["scheduled_trips"]
        )
        schedule_by_edge_day: dict[tuple[str, int], list[int]] = defaultdict(list)
        slots_per_day = int(config["time"]["slots_per_day"])
        for trip in case["scheduled_trips"]:
            schedule_by_edge_day[(trip["edge_id"], trip["departure_slot"] // slots_per_day)].append(
                trip["departure_slot"] % slots_per_day
            )
        schedule_days = (config["time"]["observation_slots"] + slots_per_day - 1) // slots_per_day
        for edge in case["edges"]:
            daily_patterns = [
                sorted(schedule_by_edge_day[(edge["id"], day)])
                for day in range(schedule_days)
            ]
            if any(not pattern for pattern in daily_patterns):
                errors.append(f"{case['case_id']}: edge {edge['id']} lacks service on a day")
            if any(pattern != daily_patterns[0] for pattern in daily_patterns[1:]):
                errors.append(f"{case['case_id']}: edge {edge['id']} daily schedule does not repeat")
        forecast_by_slot = defaultdict(float)
        for demand in case["demand"]:
            forecast_by_slot[demand["release_slot"]] += float(demand["forecast_tons"])
        release_slots = [int(slot) for slot in config["time"]["regular_arrival_slots"]]
        for slot in release_slots:
            capacity = trip_count_by_slot[slot] * config["vehicle"]["capacity_equivalent_tons"]
            if capacity <= 0:
                errors.append(f"{case['case_id']}: no scheduled capacity in arrival slot {slot}")
                continue
            ratio = forecast_by_slot[slot] / capacity
            if slot == release_slots[-1]:
                peak_load_ratios.append(ratio)
            else:
                ordinary_load_ratios.append(ratio)
            slot_records = [
                record for record in case["demand"]
                if int(record["release_slot"]) == slot and not record["id"].startswith("EMG_INSERT")
            ]
            slot_forecast = sum(float(record["forecast_tons"]) for record in slot_records)
            slot_actual = sum(float(record["actual_tons"]) for record in slot_records)
            if slot_forecast > 1e-9:
                observed_error = (slot_actual - slot_forecast) / slot_forecast
                post_event_batch_errors.append(observed_error)
                if case["category"] != "urgent_cancel":
                    batch_errors.append(observed_error)

        for demand in case["demand"]:
            if not demand["id"].startswith("EMG_INSERT") and int(demand["release_slot"]) not in release_slots:
                errors.append(f"{case['case_id']}: demand outside arrival window")
            if demand["forecast_tons"] < 0 or demand["actual_tons"] < 0:
                errors.append(f"{case['case_id']}: negative demand")
            if demand["product"] == "urgent" and demand["forecast_tons"] > 1e-9:
                shortest = nx.shortest_path_length(
                    graph, demand["origin"], demand["destination"], weight="travel_slots"
                )
                if shortest > config["products"]["urgent"]["deadline_slots"]:
                    errors.append(f"{case['case_id']}: urgent demand on physically late OD")
            if demand["id"].startswith("EMG_INSERT"):
                continue
            release_forecast[demand["release_slot"]] += demand["forecast_tons"]
            release_actual[demand["release_slot"]] += demand["actual_tons"]
            product_forecast[demand["product"]] += demand["forecast_tons"]
            if demand["forecast_tons"] > 1e-9:
                forecast_errors.append(abs(demand["actual_tons"] - demand["forecast_tons"]) / demand["forecast_tons"])

    if len(node_signatures) != 1:
        errors.append("Main node parameters are not fixed across validation/test cases")
    if len(edge_signatures) != 1:
        errors.append("Main edge topology is not fixed across validation/test cases")
    if len(schedule_signatures) != 1:
        errors.append("Normal schedule is not fixed across validation/test cases")

    total_product = sum(product_forecast.values())
    product_shares = {
        key: value / total_product if total_product else 0.0
        for key, value in sorted(product_forecast.items())
    }
    test_counts = {
        category: categories[("test", category)]
        for category in config["datasets"]["categories"]
    }
    validation_counts = {
        category: categories[("validation", category)]
        for category in config["datasets"]["categories"]
    }
    if any(count != config["datasets"]["test_cases_per_category"] for count in test_counts.values()):
        errors.append("Test categories are not balanced")
    if any(count != config["datasets"]["validation_cases_per_category"] for count in validation_counts.values()):
        errors.append("Validation categories are not balanced")

    ordinary_low, ordinary_high = config["demand"]["ordinary_load_ratio_range"]
    peak_low, peak_high = config["demand"]["peak_load_ratio_range"]
    if ordinary_load_ratios and (
        min(ordinary_load_ratios) < ordinary_low - 0.0001
        or max(ordinary_load_ratios) > ordinary_high + 0.0001
    ):
        errors.append("At least one ordinary-slot forecast load ratio is outside its configured range")
    if peak_load_ratios and (
        min(peak_load_ratios) < peak_low - 0.0001
        or max(peak_load_ratios) > peak_high + 0.0001
    ):
        errors.append("At least one peak-slot forecast load ratio is outside its configured range")

    report = {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "verification": len(verification_files),
            "validation": len(validation_files),
            "test": len(test_files),
            "validation_by_category": validation_counts,
            "test_by_category": test_counts,
        },
        "fixed_main_environment": {
            "unique_node_parameter_sets": len(node_signatures),
            "unique_edge_sets": len(edge_signatures),
            "unique_schedules": len(schedule_signatures),
        },
        "demand": {
            "forecast_product_shares": product_shares,
            "mean_absolute_record_error_ratio": mean(forecast_errors) if forecast_errors else 0.0,
            "generated_batch_forecast_error_range_excluding_cancellation": {
                "min": min(batch_errors) if batch_errors else None,
                "max": max(batch_errors) if batch_errors else None,
            },
            "post_event_batch_difference_range": {
                "min": min(post_event_batch_errors) if post_event_batch_errors else None,
                "max": max(post_event_batch_errors) if post_event_batch_errors else None,
            },
            "total_forecast_by_release_slot": dict(sorted(release_forecast.items())),
            "total_actual_by_release_slot": dict(sorted(release_actual.items())),
            "ordinary_slot_load_ratio_range": {
                "min": min(ordinary_load_ratios) if ordinary_load_ratios else None,
                "max": max(ordinary_load_ratios) if ordinary_load_ratios else None,
            },
            "peak_slot_load_ratio_range": {
                "min": min(peak_load_ratios) if peak_load_ratios else None,
                "max": max(peak_load_ratios) if peak_load_ratios else None,
            },
        },
        "event_tons": {
            event_type: {
                "min": min(values), "mean": mean(values), "max": max(values)
            }
            for event_type, values in sorted(event_tons.items())
            if values
        },
        "approved_fixed_assumptions": {
            "balanced_change_penalty_ratio": config["cost"]["balanced_change_penalty_ratio"],
            "main_network_topology": config["network"]["undirected_pairs"],
        },
    }
    return report


def write_audit(
    root: Path | None = None,
    data_dir: Path | None = None,
    output: Path | None = None,
) -> Path:
    paths = project_paths(root)
    report = audit_draft(paths.root, data_dir=data_dir)
    output = Path(output) if output is not None else paths.draft_data / "audit_report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return output
