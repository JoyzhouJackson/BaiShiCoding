from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from freight_opt.config import load_config, project_paths  # noqa: E402
from freight_opt.io import load_case, write_json  # noqa: E402
from freight_opt.optimization import solve_case  # noqa: E402
from freight_opt.validator import validate_case_solution, validate_expected_behavior  # noqa: E402


def main() -> None:
    config = load_config(ROOT / "config" / "base_config.yaml")
    input_dir = project_paths(ROOT).frozen_data / "verification"
    output_dir = ROOT / "results" / "verification"
    cases = []
    for case_path in sorted(input_dir.glob("*.json")):
        case = load_case(case_path)
        solution = solve_case(case, config, verification=True)
        validation = validate_case_solution(case, config, solution) if solution.get("status") == "complete" else {
            "status": "fail", "errors": [solution.get("status", "unknown")]
        }
        behavior = validate_expected_behavior(case, solution) if solution.get("status") == "complete" else {
            "status": "fail", "errors": [solution.get("status", "unknown")]
        }
        validation["expected_behavior"] = behavior
        if behavior["status"] != "pass":
            validation["status"] = "fail"
        write_json(output_dir / f"{case['case_id']}.json", solution)
        write_json(output_dir / f"{case['case_id']}_validation.json", validation)
        cases.append({
            "case_id": case["case_id"],
            "solution_status": solution.get("status"),
            "baseline_status": solution.get("baseline", {}).get("status"),
            "actual_status": solution.get("actual", {}).get("status"),
            "validation_status": validation.get("status"),
            "objective": solution.get("episode_objective"),
            "runtime_seconds": (
                solution.get("baseline", {}).get("runtime_seconds", 0.0)
                + sum(
                    float(step.get("runtime_seconds") or 0.0)
                    for step in solution.get("rolling_steps", [])
                )
            ),
        })
        print(cases[-1], flush=True)
    write_json(output_dir / "summary.json", {
        "status": "pass" if all(item["validation_status"] == "pass" for item in cases) else "fail",
        "cases": cases,
    })


if __name__ == "__main__":
    main()
