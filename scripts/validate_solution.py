from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from freight_opt.config import load_config  # noqa: E402
from freight_opt.io import load_case, write_json  # noqa: E402
from freight_opt.validator import validate_case_solution  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case")
    parser.add_argument("solution")
    parser.add_argument("--output")
    args = parser.parse_args()
    case = load_case(args.case)
    solution = load_case(args.solution)
    report = validate_case_solution(case, load_config(ROOT / "config" / "base_config.yaml"), solution)
    if args.output:
        write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
