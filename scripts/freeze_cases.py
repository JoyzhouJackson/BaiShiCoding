from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from freight_opt.audit_cases import audit_draft  # noqa: E402
from freight_opt.config import load_config, project_paths  # noqa: E402
from freight_opt.io import write_json  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> None:
    paths = project_paths(ROOT)
    config = load_config(paths.config)
    audit = audit_draft(ROOT, data_dir=paths.draft_data)
    if audit["status"] != "pass":
        raise RuntimeError(f"Draft audit failed: {audit['errors']}")
    if paths.frozen_data.exists():
        raise FileExistsError(
            f"{paths.frozen_data} already exists. Archive it explicitly before creating a new frozen set."
        )
    shutil.copytree(paths.draft_data, paths.frozen_data)

    active_per_category = int(config["datasets"]["active_test_cases_per_category"])
    active_index_path = ROOT / config["datasets"]["active_test_index"]
    active_categories = {}
    for category in config["datasets"]["categories"]:
        candidates = sorted((paths.frozen_data / "test" / category).glob("*.json"))
        active_categories[category] = [path.stem for path in candidates[:active_per_category]]
    write_json(active_index_path, {
        "schema_version": 1,
        "name": "v6_twelve_case_demonstration_set",
        "purpose": "Demonstrate solution feasibility and compare methods; not for significance claims.",
        "selection_policy": (
            "For each category, sort the five frozen cases by case_id and select the first three "
            "without using solver outcomes."
        ),
        "cases_per_category": active_per_category,
        "categories": active_categories,
    })

    manifest_path = paths.frozen_data / "manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()
    files = sorted(
        path for path in paths.frozen_data.rglob("*.json")
        if path.name not in {"manifest.json", "freeze_record.json"}
    )
    manifest = {
        "schema_version": int(config["schema_version"]),
        "status": config["status"],
        "generator": "src.freight_opt.generate_cases.generate_all",
        "master_seed": config["master_seed"],
        "file_count": len(files),
        "files": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in files
        ],
    }
    write_json(manifest_path, manifest)
    record = {
        "status": "frozen_user_approved_v6_model_protocol",
        "approved_items": [
            "four_verification_cases",
            "twenty_case_frozen_master_pool_five_per_category",
            "twelve_case_active_demonstration_set_three_per_category",
            "three_hour_internal_clock_and_six_hour_periodic_replanning",
            "regular_arrivals_at_hours_0_6_12_only",
            "one_off_cycle_discrete_event_at_most_per_case",
            "batch_forecast_error_plus_or_minus_twenty_percent",
            "gurobi_300_seconds_five_percent_gap_three_threads",
            "six_parallel_workers_with_dynamic_case_queue",
            "soft_service_level_with_product_specific_shortfall_penalty",
            "higher_service_shortfall_penalties_1000_500_250",
            "delayed_itinerary_candidates_within_fixed_candidate_budget",
            "overnight_inventory_holding_allowed_with_delay_cost",
            "storage_capacity_assumed_sufficient_and_nonbinding",
            "inventory_holding_cost_2_5_per_ton_per_three_hour_slot",
            "lexicographic_urgent_insert_admission_decision",
            "urgent_insert_service_clock_starts_at_request",
            "breakdown_resolved_from_runtime_available_own_vehicle",
            "cancellation_resolved_from_runtime_unshipped_cargo",
            "cumulative_vehicle_mission_and_cargo_reroute_change_cost",
            "divisible_equivalent_tons_across_multiple_itineraries",
            "scheduled_trips_are_optional_joint_decisions",
            "complete_plan_snapshot_after_every_rolling_decision",
            "node_by_slot_animation_decision_records",
        ],
        "master_seed": config["master_seed"],
        "manifest_sha256": sha256(manifest_path),
        "config_sha256_at_freeze": sha256(paths.config),
        "active_test_index": config["datasets"]["active_test_index"],
        "active_test_index_sha256": sha256(active_index_path),
        "archived_previous_dataset": "data/archive/v5_dynamic_6x3_frozen_20260831",
        "note": (
            "The 20 frozen cases are the master pool. All methods use the same fixed 12-case active "
            "demonstration set; learning methods must not train or tune on it."
        ),
    }
    write_json(paths.frozen_data / "freeze_record.json", record)
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
