from __future__ import annotations

import copy
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from freight_opt.config import load_config, project_paths  # noqa: E402
from freight_opt.decomposition import solve_case_benders_cg  # noqa: E402
from freight_opt.io import load_case, write_json  # noqa: E402
from freight_opt.validator import validate_case_solution, validate_expected_behavior  # noqa: E402


def main() -> None:
    config = copy.deepcopy(load_config(ROOT / "config" / "base_config.yaml"))
    with (ROOT / "config" / "benders_cg_config.yaml").open("r", encoding="utf-8") as stream:
        config["decomposition"] = yaml.safe_load(stream)
    input_dir = project_paths(ROOT).frozen_data / "verification"
    output_dir = ROOT / "results" / "benders_cg_verification"
    cases = []
    for case_path in sorted(input_dir.glob("*.json")):
        case = load_case(case_path)
        solution = solve_case_benders_cg(case, config, verification=True)
        if solution.get("status") == "complete":
            validation = validate_case_solution(case, config, solution)
            behavior = validate_expected_behavior(case, solution)
        else:
            validation = {"status": "fail", "errors": [solution.get("status", "unknown")]}
            behavior = {"status": "fail", "errors": [solution.get("status", "unknown")]}
        validation["expected_behavior"] = behavior
        if behavior["status"] != "pass":
            validation["status"] = "fail"
        write_json(output_dir / f"{case['case_id']}.json", solution)
        write_json(output_dir / f"{case['case_id']}_validation.json", validation)
        record = {
            "case_id": case["case_id"],
            "solution_status": solution.get("status"),
            "validation_status": validation.get("status"),
            "objective": solution.get("episode_objective"),
            "baseline_benders_iterations": solution.get("baseline", {}).get(
                "decomposition_trace", {}
            ).get("benders_iteration_count"),
            "actual_benders_iterations": solution.get("actual", {}).get(
                "decomposition_trace", {}
            ).get("benders_iteration_count"),
        }
        cases.append(record)
        print(record, flush=True)
    write_json(output_dir / "summary.json", {
        "status": "pass" if all(item["validation_status"] == "pass" for item in cases) else "fail",
        "method": "benders_column_generation",
        "cases": cases,
    })


if __name__ == "__main__":
    main()
