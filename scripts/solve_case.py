from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from freight_opt.config import load_config  # noqa: E402
from freight_opt.io import load_case, write_json  # noqa: E402
from freight_opt.optimization import solve_case  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case")
    parser.add_argument("--output")
    parser.add_argument("--verification", action="store_true")
    parser.add_argument("--time-limit", type=int)
    parser.add_argument("--log-dir")
    args = parser.parse_args()
    case = load_case(args.case)
    config = copy.deepcopy(load_config(ROOT / "config" / "base_config.yaml"))
    if args.time_limit:
        config["solver"]["formal_time_limit_seconds"] = args.time_limit
    result = solve_case(
        case, config, args.verification,
        output_log_dir=args.log_dir,
    )
    output = args.output or str(ROOT / "results" / "single" / f"{case['case_id']}.json")
    print(write_json(output, result))


if __name__ == "__main__":
    main()
