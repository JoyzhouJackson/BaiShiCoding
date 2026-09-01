import argparse
from pathlib import Path
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from freight_opt.audit_cases import write_audit  # noqa: E402


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    input_dir = args.input if args.input is None or args.input.is_absolute() else ROOT / args.input
    output_path = args.output if args.output is None or args.output.is_absolute() else ROOT / args.output
    output = write_audit(ROOT, data_dir=input_dir, output=output_path)
    print(output)
    with output.open("r", encoding="utf-8") as stream:
        print(json.dumps(json.load(stream), ensure_ascii=False, indent=2))
