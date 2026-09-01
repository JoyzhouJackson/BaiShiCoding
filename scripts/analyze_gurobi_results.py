from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from freight_opt.io import load_case, write_json  # noqa: E402


def mean_ci95(values: list[float]) -> dict:
    """Return a transparent normal-approximation interval for descriptive reporting."""
    if not values:
        return {"n": 0, "mean": None, "ci95_low": None, "ci95_high": None}
    mean = statistics.mean(values)
    if len(values) == 1:
        return {"n": 1, "mean": mean, "ci95_low": None, "ci95_high": None}
    half_width = 1.96 * statistics.stdev(values) / math.sqrt(len(values))
    return {
        "n": len(values),
        "mean": mean,
        "ci95_low": mean - half_width,
        "ci95_high": mean + half_width,
    }


def flatten_solution(path: Path) -> dict:
    solution = load_case(path)
    validation_path = path.with_name(f"{path.stem}_validation.json")
    validation = load_case(validation_path) if validation_path.exists() else {"status": "missing"}
    baseline = solution.get("baseline", {})
    actual = solution.get("actual", {})
    rolling_steps = solution.get("rolling_steps", [])
    phase_records = [("baseline", baseline)] + [
        (f"slot{step.get('slot')}", step) for step in rolling_steps
    ]
    runtime = sum(float(record.get("runtime_seconds") or 0.0) for _, record in phase_records)
    components = solution.get("episode_objective_components", {})
    service_rates = actual.get("service_rates", {})
    insert_decision = solution.get("insert_decision") or {}
    row = {
        "case_id": solution.get("case_id"),
        "category": solution.get("category"),
        "case_status": solution.get("status"),
        "validation_status": validation.get("status"),
        "baseline_status": baseline.get("status"),
        "actual_status": actual.get("status"),
        "objective": solution.get("episode_objective"),
        "final_plan_objective": actual.get("objective"),
        "best_bound": actual.get("best_bound"),
        "mip_gap": actual.get("mip_gap"),
        "runtime_seconds": runtime,
        "transport_cost": components.get("transport"),
        "cargo_handling_cost": components.get("cargo_handling"),
        "inventory_holding_cost": components.get("inventory_holding"),
        "transfer_cost": components.get("transfer"),
        "delay_cost": components.get("delay"),
        "cargo_cost": sum(
            float(components.get(name) or 0.0)
            for name in ("cargo_handling", "inventory_holding", "transfer", "delay")
        ),
        "service_shortfall_cost": components.get("service_shortfall"),
        "change_cost": components.get("cumulative_change"),
        "changed_future_mission_tasks": sum(
            float(step.get("change_metrics", {}).get("changed_future_mission_tasks") or 0.0)
            for step in rolling_steps
        ),
        "rerouted_previously_planned_tons": sum(
            float(step.get("change_metrics", {}).get("rerouted_previously_planned_tons") or 0.0)
            for step in rolling_steps
        ),
        "urgent_on_time_rate": service_rates.get("urgent", {}).get("on_time_rate"),
        "standard_on_time_rate": service_rates.get("standard", {}).get("on_time_rate"),
        "economy_on_time_rate": service_rates.get("economy", {}).get("on_time_rate"),
        "trigger_slot": solution.get("trigger_slot"),
        "insert_status": insert_decision.get("status"),
        "insert_requested_hour": insert_decision.get("requested_hour"),
        "insert_admission_hour": insert_decision.get("admission_hour"),
        "insert_defer_hours": insert_decision.get("defer_hours"),
        "failed_phase": (
            solution.get("status", "").removeprefix("rolling_failed_at_")
            if str(solution.get("status", "")).startswith("rolling_failed_at_")
            else ("baseline" if solution.get("status") == "baseline_failed" else None)
        ),
        "phase_statuses": "|".join(f"{name}:{record.get('status')}" for name, record in phase_records),
    }
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-set", default="gurobi_v6_12")
    args = parser.parse_args()
    result_dir = ROOT / "results" / args.result_set / "test"
    paths = [
        path for path in sorted(result_dir.glob("test_*.json"))
        if not path.name.endswith("_validation.json") and path.name not in {"summary.json", "analysis.json"}
    ]
    rows = [flatten_solution(path) for path in paths]
    result_dir.mkdir(parents=True, exist_ok=True)
    csv_path = result_dir / "case_metrics.csv"
    if rows:
        with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    by_category: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_category[str(row["category"])].append(row)
    category_statistics = {}
    for category, category_rows in sorted(by_category.items()):
        validated = [
            row for row in category_rows
            if row["case_status"] == "complete" and row["validation_status"] == "pass"
        ]
        category_statistics[category] = {
            "count": len(category_rows),
            "validated_complete_count": len(validated),
            "objective": mean_ci95([float(row["objective"]) for row in validated if row["objective"] is not None]),
            "runtime_seconds": mean_ci95([float(row["runtime_seconds"]) for row in category_rows]),
            "final_mip_gap": mean_ci95([float(row["mip_gap"]) for row in validated if row["mip_gap"] is not None]),
        }
    analysis = {
        "result_set": args.result_set,
        "completed_case_records": len(rows),
        "case_status_counts": dict(Counter(str(row["case_status"]) for row in rows)),
        "validation_status_counts": dict(Counter(str(row["validation_status"]) for row in rows)),
        "actual_status_counts": dict(Counter(str(row["actual_status"]) for row in rows)),
        "urgent_insert_decision_counts": dict(Counter(
            str(row["insert_status"]) for row in rows if row["insert_status"] is not None
        )),
        "category_statistics": category_statistics,
        "ci_note": (
            "Each category has only three active demonstration cases. The normal-approximation "
            "interval is descriptive only and must not be presented as a significance or population claim."
        ),
    }
    write_json(result_dir / "analysis.json", analysis)
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
