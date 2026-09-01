from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from freight_opt.io import load_case, write_json  # noqa: E402


def _traces(solution: dict[str, Any]) -> list[dict[str, Any]]:
    values = []
    baseline = solution.get("baseline", {}).get("decomposition_trace")
    if baseline:
        values.append(baseline)
    for step in solution.get("rolling_steps", []):
        if step.get("decomposition_trace"):
            values.append(step["decomposition_trace"])
    return values


def _runtime(solution: dict[str, Any]) -> float:
    return float(solution.get("baseline", {}).get("runtime_seconds", 0.0)) + sum(
        float(step.get("runtime_seconds") or 0.0)
        for step in solution.get("rolling_steps", [])
    )


def main() -> None:
    milp_dir = ROOT / "results" / "gurobi_v6_12" / "test"
    decomposition_dir = ROOT / "results" / "benders_cg_v6_12" / "test"
    output_dir = ROOT / "results" / "milp_vs_benders_cg_v6_12"
    rows = []
    for benders_path in sorted(decomposition_dir.glob("test_*.json")):
        if benders_path.name.endswith("_validation.json") or benders_path.name == "summary.json":
            continue
        milp_path = milp_dir / benders_path.name
        if not milp_path.exists():
            continue
        milp = load_case(milp_path)
        benders = load_case(benders_path)
        traces = _traces(benders)
        milp_objective = milp.get("episode_objective")
        benders_objective = benders.get("episode_objective")
        rows.append({
            "case_id": benders.get("case_id"),
            "category": benders.get("category"),
            "milp_status": milp.get("status"),
            "benders_cg_status": benders.get("status"),
            "milp_objective": milp_objective,
            "benders_cg_objective": benders_objective,
            "absolute_objective_delta": (
                None if milp_objective is None or benders_objective is None
                else float(benders_objective) - float(milp_objective)
            ),
            "relative_objective_delta": (
                None if milp_objective in (None, 0) or benders_objective is None
                else (float(benders_objective) - float(milp_objective))
                / abs(float(milp_objective))
            ),
            "milp_runtime_seconds": _runtime(milp),
            "benders_cg_runtime_seconds": _runtime(benders),
            "benders_iterations": sum(int(t.get("benders_iteration_count", 0)) for t in traces),
            "feasibility_cuts": sum(int(t.get("feasibility_cut_count", 0)) for t in traces),
            "optimality_cuts": sum(int(t.get("optimality_cut_count", 0)) for t in traces),
            "column_generation_iterations": sum(
                len(phase.get("iterations", []))
                for trace in traces for iteration in trace.get("benders_iterations", [])
                for phase in (
                    iteration.get("feasibility_column_generation", {}),
                    iteration.get("cost_column_generation", {}),
                )
            ),
            "milp_validation": (
                load_case(milp_path.with_name(f"{milp_path.stem}_validation.json")).get("status")
                if milp_path.with_name(f"{milp_path.stem}_validation.json").exists() else "missing"
            ),
            "benders_cg_validation": (
                load_case(benders_path.with_name(f"{benders_path.stem}_validation.json")).get("status")
                if benders_path.with_name(f"{benders_path.stem}_validation.json").exists() else "missing"
            ),
        })
    deltas = [row["relative_objective_delta"] for row in rows if row["relative_objective_delta"] is not None]
    summary = {
        "protocol": "V6 fixed twelve-case paired comparison",
        "paired_case_count": len(rows),
        "all_inputs_and_business_constraints_identical": True,
        "pricing_universe": "same finite candidate itinerary universe as MILP",
        "mean_relative_objective_delta": statistics.mean(deltas) if deltas else None,
        "median_relative_objective_delta": statistics.median(deltas) if deltas else None,
        "cases": rows,
    }
    write_json(output_dir / "comparison.json", summary)
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "comparison.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        if rows:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
