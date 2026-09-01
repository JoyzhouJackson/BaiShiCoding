from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULT_SET = "gurobi_v6_12"
sys.path.insert(0, str(ROOT / "src"))

from freight_opt.config import load_config  # noqa: E402


def run_checked(arguments: list[str]) -> None:
    print(f"\n>>> {' '.join(arguments)}", flush=True)
    subprocess.run(arguments, cwd=ROOT, check=True, env={**os.environ, "PYTHONUTF8": "1"})


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def verify_frozen_integrity() -> None:
    frozen = ROOT / "data" / "frozen"
    record_path = frozen / "freeze_record.json"
    manifest_path = frozen / "manifest.json"
    with record_path.open("r", encoding="utf-8") as stream:
        record = json.load(stream)
    with manifest_path.open("r", encoding="utf-8") as stream:
        manifest = json.load(stream)
    if sha256(ROOT / "config" / "base_config.yaml") != record["config_sha256_at_freeze"]:
        raise RuntimeError("base_config.yaml 已在冻结后改变，请先重新审核并冻结算例。")
    if sha256(manifest_path) != record["manifest_sha256"]:
        raise RuntimeError("冻结数据 manifest 已改变。")
    active_index_path = ROOT / record["active_test_index"]
    if (
        not active_index_path.exists()
        or sha256(active_index_path) != record["active_test_index_sha256"]
    ):
        raise RuntimeError("V6正式测试算例清单缺失或已改变。")
    for item in manifest["files"]:
        path = ROOT / item["path"]
        if not path.exists() or sha256(path) != item["sha256"]:
            raise RuntimeError(f"冻结文件缺失或哈希不一致: {item['path']}")


def _case_result_exists(case_id: str, result_set: str = RESULT_SET) -> bool:
    output_dir = ROOT / "results" / result_set / "test"
    output_path = output_dir / f"{case_id}.json"
    validation_path = output_dir / f"{case_id}_validation.json"
    if not output_path.exists() or not validation_path.exists():
        return False
    try:
        with output_path.open("r", encoding="utf-8") as stream:
            result = json.load(stream)
        with validation_path.open("r", encoding="utf-8") as stream:
            validation = json.load(stream)
        return (
            int(result.get("result_schema_version", 0)) == 6
            and result.get("status") == "complete"
            and validation.get("status") == "pass"
        )
    except (OSError, ValueError, TypeError):
        return False


def load_active_test_cases(config: dict) -> list[Path]:
    index_path = ROOT / config["datasets"]["active_test_index"]
    with index_path.open("r", encoding="utf-8") as stream:
        index = json.load(stream)
    expected_categories = list(config["datasets"]["categories"])
    per_category = int(config["datasets"]["active_test_cases_per_category"])
    case_paths: list[Path] = []
    seen: set[str] = set()
    for category in expected_categories:
        case_ids = index.get("categories", {}).get(category, [])
        if len(case_ids) != per_category:
            raise RuntimeError(f"类别 {category} 的正式算例应为 {per_category} 个。")
        for case_id in case_ids:
            if case_id in seen:
                raise RuntimeError(f"正式算例清单存在重复ID: {case_id}")
            seen.add(case_id)
            path = ROOT / "data" / "frozen" / "test" / category / f"{case_id}.json"
            if not path.exists():
                raise RuntimeError(f"正式算例不存在: {path}")
            with path.open("r", encoding="utf-8") as stream:
                case = json.load(stream)
            if case.get("case_id") != case_id or case.get("category") != category:
                raise RuntimeError(f"正式算例ID或类别不一致: {path}")
            case_paths.append(path)
    return case_paths


def run_dynamic_case_queue(
    test_cases: list[Path], *, workers: int, threads: int, time_limit: int,
    result_set: str = RESULT_SET, method: str = "milp",
) -> None:
    """Keep a bounded pool busy without assigning cases to fixed shards.

    Every subprocess owns one case, one result file and case-specific log files.
    A fast case immediately frees a slot for the next pending case, which avoids
    the tail-idle problem of static round-robin shards.
    """
    pending = [path for path in test_cases if not _case_result_exists(path.stem, result_set)]
    skipped = len(test_cases) - len(pending)
    print(
        f">>> 动态队列：待运行 {len(pending)} 个，已完成跳过 {skipped} 个，"
        f"最多同时运行 {workers} 个。",
        flush=True,
    )
    active: dict[subprocess.Popen, str] = {}
    failures: list[tuple[str, int]] = []
    launched = 0
    completed = skipped

    def launch(case_path: Path) -> None:
        nonlocal launched
        case_id = case_path.stem
        command = [
            sys.executable,
            str(ROOT / "scripts" / "run_gurobi_benchmark.py"),
            "--case-id", case_id,
            "--threads", str(threads),
            "--time-limit", str(time_limit),
            "--result-set", result_set,
            "--method", method,
            "--no-summary",
        ]
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        active[process] = case_id
        launched += 1
        print(
            f">>> [{launched}/{len(pending)}] 启动 {case_id}；当前并行 {len(active)}/{workers}",
            flush=True,
        )

    try:
        while pending or active:
            while pending and len(active) < workers:
                launch(pending.pop(0))

            finished = [process for process in active if process.poll() is not None]
            if not finished:
                time.sleep(0.25)
                continue
            for process in finished:
                case_id = active.pop(process)
                completed += 1
                if process.returncode != 0:
                    failures.append((case_id, int(process.returncode)))
                print(
                    f">>> 完成进度 {completed}/{len(test_cases)}：{case_id} "
                    f"(exit={process.returncode})；当前并行 {len(active)}/{workers}",
                    flush=True,
                )
    except KeyboardInterrupt:
        print("\n收到中断，正在停止活动算例；已完整写入的结果会保留。", flush=True)
        for process in active:
            if process.poll() is None:
                process.terminate()
        for process in active:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        raise

    if failures:
        raise RuntimeError(f"以下算例进程异常退出: {failures}")


def main(
    method: str = "milp", result_set: str = RESULT_SET,
    verification_script: str = "run_verification.py",
) -> None:
    config = load_config(ROOT / "config" / "base_config.yaml")
    verify_frozen_integrity()
    workers = int(config["solver"]["parallel_workers"])
    threads = int(config["solver"]["threads_per_worker"])
    time_limit = int(config["solver"]["formal_time_limit_seconds"])
    test_cases = load_active_test_cases(config)
    expected = len(config["datasets"]["categories"]) * int(
        config["datasets"]["active_test_cases_per_category"]
    )
    if len(test_cases) != expected:
        raise RuntimeError(f"V6正式测试集应有 {expected} 个算例，实际找到 {len(test_cases)} 个。")

    print("=" * 72)
    print(f"快运网络滚动优化：一键实验（{method}）")
    print(f"测试算例: {expected}；并行进程: {workers}；每进程线程: {threads}")
    print(f"单次 Gurobi 上限: {time_limit} 秒；目标 Gap: {config['solver']['target_mip_gap']:.1%}")
    print("已有完整结果会自动跳过，可在中断后再次点击运行续跑。")
    print("=" * 72, flush=True)

    run_checked([sys.executable, str(ROOT / "scripts" / verification_script)])
    verification_dir = "verification" if method == "milp" else "benders_cg_verification"
    verification_summary = ROOT / "results" / verification_dir / "summary.json"
    with verification_summary.open("r", encoding="utf-8") as stream:
        verification = json.load(stream)
    if verification.get("status") != "pass":
        raise RuntimeError("4个小型验证算例没有全部通过，正式测试已停止。请查看 results/verification。")

    run_dynamic_case_queue(
        test_cases, workers=workers, threads=threads, time_limit=time_limit,
        result_set=result_set, method=method,
    )

    run_checked([
        sys.executable,
        str(ROOT / "scripts" / "run_gurobi_benchmark.py"),
        "--summary-only",
        "--result-set", result_set,
    ])
    run_checked([
        sys.executable,
        str(ROOT / "scripts" / "analyze_gurobi_results.py"),
        "--result-set", result_set,
    ])
    print(f"\n全部完成。请查看 results/{result_set}/test/summary.json、analysis.json 和 case_metrics.csv。")


if __name__ == "__main__":
    main()
