from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from freight_opt.generate_cases import generate_all  # noqa: E402


if __name__ == "__main__":
    output = generate_all(ROOT)
    print(output)

