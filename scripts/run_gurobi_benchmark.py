from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from freight_opt.config import load_config, project_paths  # noqa: E402
from freight_opt.io import load_case, write_json  # noqa: E402
from freight_opt.optimization import solve_case  # noqa: E402
from freight_opt.decomposition import solve_case_benders_cg  # noqa: E402
from freight_opt.validator import validate_case_solution  # noqa: E402


def summarize(output_dir: Path) -> dict:
    records = []
    for path in sorted(output_dir.glob("test_*.json")):
        if path.name.endswith("_validation.json") or path.name == "summary.json":
            continue
        solution = load_case(path)
        actual = solution.get("actual", {})
        baseline = solution.get("baseline", {})
        validation_path = path.with_name(f"{path.stem}_validation.json")
        validation = load_case(validation_path) if validation_path.exists() else {"status": "missing"}
        insert_decision = solution.get("insert_decision") or {}
        records.append({
            "case_id": solution.get("case_id"),
            "category": solution.get("category"),
            "status": solution.get("status"),
            "validation": validation.get("status"),
            "baseline_status": baseline.get("status"),
            "actual_status": actual.get("status"),
            "objective": solution.get("episode_objective"),
            "plan_objective": actual.get("objective"),
            "cumulative_change_cost": solution.get("cumulative_change_cost"),
            "mip_gap": actual.get("mip_gap"),
            "runtime_seconds": float(baseline.get("runtime_seconds", 0.0)) + sum(
                float(step.get("runtime_seconds") or 0.0)
                for step in solution.get("rolling_steps", [])
            ),
            "trigger_slot": solution.get("trigger_slot"),
            "insert_status": insert_decision.get("status"),
            "insert_admission_hour": insert_decision.get("admission_hour"),
        })
    by_category = defaultdict(list)
    for record in records:
        by_category[record["category"]].append(record)
    category_summary = {}
    for category, values in sorted(by_category.items()):
        objectives = [item["objective"] for item in values if item["objective"] is not None]
        runtimes = [item["runtime_seconds"] for item in values]
        category_summary[category] = {
            "count": len(values),
            "mean_objective": statistics.mean(objectives) if objectives else None,
            "median_objective": statistics.median(objectives) if objectives else None,
            "mean_runtime_seconds": statistics.mean(runtimes) if runtimes else None,
        }
    return {
        "completed_files": len(records),
        "status_counts": dict(Counter(item["status"] for item in records)),
        "actual_solver_status_counts": dict(Counter(item["actual_status"] for item in records)),
        "validation_counts": dict(Counter(item["validation"] for item in records)),
        "trigger_slot_counts": dict(Counter(str(item["trigger_slot"]) for item in records)),
        "urgent_insert_decision_counts": dict(Counter(
            str(item["insert_status"]) for item in records if item["insert_status"] is not None
        )),
        "by_category": category_summary,
        "cases": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--category")
    parser.add_argument("--case-id", action="append", help="Solve only the named case; may be repeated.")
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--time-limit", type=int)
    parser.add_argument("--threads", type=int)
    parser.add_argument("--method", choices=["milp", "benders-cg"], default="milp")
    parser.add_argument("--stop-after-slot", type=int, help="Diagnostic only: stop after this replan slot.")
    parser.add_argument("--no-summary", action="store_true")
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Rebuild summary.json from completed result files without solving cases.",
    )
    parser.add_argument(
        "--result-set",
        default="gurobi_v6_12",
        help="Result directory name under results/ (for example gurobi_supplemental).",
    )
    args = parser.parse_args()

    config = copy.deepcopy(load_config(ROOT / "config" / "base_config.yaml"))
    if args.method == "benders-cg":
        with (ROOT / "config" / "benders_cg_config.yaml").open("r", encoding="utf-8") as stream:
            config["decomposition"] = yaml.safe_load(stream)
    if args.time_limit:
        config["solver"]["formal_time_limit_seconds"] = args.time_limit
    if args.threads:
        config["solver"]["threads_per_worker"] = args.threads
    input_dir = project_paths(ROOT).frozen_data / "test"
    output_dir = ROOT / "results" / args.result_set / "test"
    log_dir = ROOT / "results" / args.result_set / "logs"
    if args.summary_only:
        summary = summarize(output_dir)
        write_json(output_dir / "summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        return
    paths = sorted(input_dir.rglob("*.json"))
    if args.category:
        paths = [path for path in paths if path.parent.name == args.category]
    if args.case_id:
        requested = set(args.case_id)
        paths = [path for path in paths if path.stem in requested]
        missing = requested.difference(path.stem for path in paths)
        if missing:
            parser.error(f"Unknown case id(s): {', '.join(sorted(missing))}")
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        parser.error("--shard-count must be positive and --shard-index must be in [0, shard-count).")
    paths = [path for index, path in enumerate(paths) if index % args.shard_count == args.shard_index]
    if args.max_cases:
        paths = paths[:args.max_cases]

    for index, case_path in enumerate(paths, start=1):
        case = load_case(case_path)
        output_path = output_dir / f"{case['case_id']}.json"
        validation_path = output_dir / f"{case['case_id']}_validation.json"
        if output_path.exists() and validation_path.exists() and not args.force:
            existing = load_case(output_path)
            existing_validation = load_case(validation_path)
            if (
                int(existing.get("result_schema_version", 0))
                == int(config.get("result_schema_version", 1))
                and existing.get("status") == "complete"
                and existing_validation.get("status") == "pass"
            ):
                print(f"[{index}/{len(paths)}] skip {case['case_id']}", flush=True)
                continue
        started = time.perf_counter()
        print(f"[{index}/{len(paths)}] solve {case['case_id']}", flush=True)
        solver = solve_case if args.method == "milp" else solve_case_benders_cg
        solution = solver(
            case, config, output_log_dir=log_dir,
            stop_after_slot=args.stop_after_slot,
        )
        write_json(output_path, solution)
        if solution.get("status") == "complete":
            validation = validate_case_solution(case, config, solution)
        else:
            validation = {"case_id": case["case_id"], "status": "fail", "errors": [solution.get("status")]}
        write_json(validation_path, validation)
        if not args.no_summary:
            write_json(output_dir / "summary.json", summarize(output_dir))
        print(
            f"[{index}/{len(paths)}] {case['case_id']} status={solution.get('status')} "
            f"validation={validation.get('status')} wall={time.perf_counter() - started:.1f}s",
            flush=True,
        )
    if not args.no_summary:
        summary = summarize(output_dir)
        write_json(output_dir / "summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
