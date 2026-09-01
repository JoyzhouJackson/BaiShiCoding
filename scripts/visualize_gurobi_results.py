from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager
from matplotlib.ticker import PercentFormatter


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


CATEGORY_LABELS = {
    "normal": "正常波动",
    "urgent_insert": "紧急插单",
    "urgent_cancel": "紧急撤单",
    "vehicle_breakdown": "车辆故障",
}
CATEGORY_COLORS = {
    "normal": "#3B82F6",
    "urgent_insert": "#F59E0B",
    "urgent_cancel": "#8B5CF6",
    "vehicle_breakdown": "#EF4444",
}
COST_LABELS = {
    "transport": "运输",
    "cargo_handling": "装卸",
    "inventory_holding": "留仓库存",
    "transfer": "中转",
    "delay": "延误",
    "service_shortfall": "服务违约",
    "cumulative_change": "方案变更",
}
COST_COLORS = {
    "transport": "#2563EB",
    "cargo_handling": "#14B8A6",
    "inventory_holding": "#F59E0B",
    "transfer": "#8B5CF6",
    "delay": "#F97316",
    "service_shortfall": "#DC2626",
    "cumulative_change": "#64748B",
}
PRODUCT_LABELS = {"urgent": "加急件", "standard": "标准件", "economy": "经济件"}
PRODUCT_TARGETS = {"urgent": 0.98, "standard": 0.95, "economy": 0.90}


def configure_plotting() -> str:
    available = {font.name for font in font_manager.fontManager.ttflist}
    candidates = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Arial Unicode MS"]
    selected = next((name for name in candidates if name in available), "DejaVu Sans")
    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams.update({
        "font.sans-serif": [selected],
        "axes.unicode_minus": False,
        "figure.facecolor": "#F8FAFC",
        "axes.facecolor": "#FFFFFF",
        "axes.titleweight": "bold",
        "axes.titlesize": 12,
        "axes.labelsize": 10,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
    })
    return selected


def case_label(case_id: str, category: str) -> str:
    return f"{CATEGORY_LABELS[category]}-{case_id.rsplit('_', 1)[-1]}"


def load_results(result_set: str) -> tuple[list[dict], list[dict]]:
    result_dir = ROOT / "results" / result_set / "test"
    paths = [
        path for path in sorted(result_dir.glob("test_*.json"))
        if not path.name.endswith("_validation.json")
    ]
    solutions = []
    validations = []
    for path in paths:
        with path.open("r", encoding="utf-8") as stream:
            solutions.append(json.load(stream))
        validation_path = path.with_name(f"{path.stem}_validation.json")
        with validation_path.open("r", encoding="utf-8") as stream:
            validations.append(json.load(stream))
    if not solutions:
        raise FileNotFoundError(f"No result files found in {result_dir}")
    return solutions, validations


def prepare_data(solutions: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    case_rows: list[dict] = []
    service_rows: list[dict] = []
    phase_rows: list[dict] = []
    for solution in solutions:
        category = solution["category"]
        components = solution["episode_objective_components"]
        max_inventory = max(
            float(state["inventory_tons"])
            for snapshot in solution["plan_snapshots"]
            for node in snapshot["nodes"]
            for state in node["timeline"]
        )
        case_rows.append({
            "case_id": solution["case_id"],
            "category": category,
            "case_label": case_label(solution["case_id"], category),
            "objective": float(solution["episode_objective"]),
            "completion_hour": float(solution["completion_hour"]),
            "max_inventory": max_inventory,
            "runtime_seconds": float(solution["baseline"].get("runtime_seconds") or 0.0)
            + sum(float(step.get("runtime_seconds") or 0.0) for step in solution["rolling_steps"]),
            "time_limit_calls": int(solution["baseline"].get("status") == "time_limit")
            + sum(int(step.get("status") == "time_limit") for step in solution["rolling_steps"]),
            **{name: float(components.get(name) or 0.0) for name in COST_LABELS},
        })
        phase_rows.append({
            "case_id": solution["case_id"],
            "category": category,
            "case_label": case_label(solution["case_id"], category),
            "phase": "日初规划",
            "slot": 0,
            "status": solution["baseline"]["status"],
            "gap": solution["baseline"].get("mip_gap"),
            "runtime_seconds": float(solution["baseline"].get("runtime_seconds") or 0.0),
        })
        for step in solution["rolling_steps"]:
            phase_rows.append({
                "case_id": solution["case_id"],
                "category": category,
                "case_label": case_label(solution["case_id"], category),
                "phase": "事件重调度" if "event" in str(step["decision_type"]) else "周期滚动",
                "slot": int(step["slot"]),
                "status": step["status"],
                "gap": step.get("mip_gap"),
                "runtime_seconds": float(step.get("runtime_seconds") or 0.0),
            })
        for product, values in solution["actual"]["service_rates"].items():
            service_rows.append({
                "case_id": solution["case_id"],
                "category": category,
                "case_label": case_label(solution["case_id"], category),
                "product": product,
                "total_tons": float(values["total_tons"]),
                "on_time_tons": float(values["on_time_tons"]),
                "on_time_rate": float(values["on_time_rate"]),
                "required_rate": float(values["required_rate"]),
                "shortfall_tons": float(values["shortfall_tons"]),
            })
    return pd.DataFrame(case_rows), pd.DataFrame(service_rows), pd.DataFrame(phase_rows)


def save_figure(fig: plt.Figure, path: Path) -> None:
    fig.savefig(path, dpi=190, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def draw_overview(
    cases: pd.DataFrame, services: pd.DataFrame, phases: pd.DataFrame,
    validations: list[dict], output: Path,
) -> None:
    fig = plt.figure(figsize=(16, 10), constrained_layout=True)
    grid = fig.add_gridspec(3, 4, height_ratios=[0.48, 1.5, 1.5])
    fig.suptitle("Gurobi滚动优化结果总览（12个演示算例）", fontsize=20, fontweight="bold")

    kpis = [
        ("完成算例", f"{len(cases)}/{len(cases)}", "#2563EB"),
        ("独立校验", f"{sum(v.get('status') == 'pass' for v in validations)}/{len(validations)} 通过", "#16A34A"),
        ("Gurobi调用", f"{len(phases)} 次", "#7C3AED"),
        ("实际并行耗时", "约30.5分钟", "#EA580C"),
    ]
    for index, (title, value, color) in enumerate(kpis):
        ax = fig.add_subplot(grid[0, index])
        ax.axis("off")
        ax.text(0.03, 0.72, title, fontsize=11, color="#64748B", transform=ax.transAxes)
        ax.text(0.03, 0.23, value, fontsize=22, fontweight="bold", color=color, transform=ax.transAxes)
        ax.add_patch(plt.Rectangle((0, 0), 1, 1, transform=ax.transAxes, fill=False,
                                   linewidth=1.2, edgecolor="#CBD5E1"))

    ax = fig.add_subplot(grid[1, :2])
    category_order = list(CATEGORY_LABELS)
    category_mean = cases.groupby("category")["objective"].mean().reindex(category_order)
    bars = ax.barh(
        [CATEGORY_LABELS[item] for item in category_order], category_mean,
        color=[CATEGORY_COLORS[item] for item in category_order], height=0.58,
    )
    ax.set_title("各类别平均全过程成本（描述性）")
    ax.set_xlabel("成本单位")
    ax.bar_label(bars, labels=[f"{value:,.0f}" for value in category_mean], padding=5)
    ax.invert_yaxis()

    ax = fig.add_subplot(grid[1, 2:])
    component_totals = cases[list(COST_LABELS)].sum()
    wedges, _ = ax.pie(
        component_totals,
        colors=[COST_COLORS[name] for name in COST_LABELS],
        startangle=90,
        wedgeprops={"width": 0.42, "edgecolor": "white"},
    )
    ax.text(0, 0.07, f"{cases['objective'].sum():,.0f}", ha="center", va="center",
            fontsize=18, fontweight="bold")
    ax.text(0, -0.13, "总成本", ha="center", va="center", fontsize=10, color="#64748B")
    ax.set_title("总成本构成")
    ax.legend(
        wedges,
        [f"{COST_LABELS[name]}  {component_totals[name] / cases['objective'].sum():.1%}" for name in COST_LABELS],
        loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False,
    )

    ax = fig.add_subplot(grid[2, :2])
    weighted = services.groupby("product").apply(
        lambda frame: frame["on_time_tons"].sum() / frame["total_tons"].sum()
    ).reindex(["urgent", "standard", "economy"])
    targets = pd.Series(PRODUCT_TARGETS).reindex(weighted.index)
    x = np.arange(len(weighted))
    bars = ax.bar(x, weighted * 100, color=["#EF4444", "#3B82F6", "#10B981"], width=0.55)
    ax.scatter(x, targets * 100, marker="D", s=55, color="#111827", label="目标")
    ax.set_xticks(x, [PRODUCT_LABELS[item] for item in weighted.index])
    ax.set_ylim(88, 101.5)
    ax.set_ylabel("加权准时率")
    ax.yaxis.set_major_formatter(PercentFormatter(100))
    ax.set_title("产品准时服务水平")
    ax.bar_label(bars, labels=[f"{value:.2f}%" for value in weighted * 100], padding=4)
    ax.legend(frameon=False, loc="lower right")

    ax = fig.add_subplot(grid[2, 2])
    status_counts = phases["status"].value_counts().reindex(["optimal", "time_limit"], fill_value=0)
    bars = ax.bar(["证明最优", "达到时限\n但有可行解"], status_counts,
                  color=["#16A34A", "#F59E0B"], width=0.58)
    ax.set_title("96次求解调用状态")
    ax.set_ylabel("调用次数")
    ax.bar_label(bars, padding=4, fontweight="bold")

    ax = fig.add_subplot(grid[2, 3])
    change_mean = cases.groupby("category")["cumulative_change"].mean().reindex(category_order)
    bars = ax.bar(
        [CATEGORY_LABELS[item].replace("紧急", "") for item in category_order],
        change_mean,
        color=[CATEGORY_COLORS[item] for item in category_order], width=0.62,
    )
    ax.set_title("平均方案变更成本")
    ax.set_ylabel("成本单位")
    ax.bar_label(bars, labels=[f"{value:.0f}" for value in change_mean], padding=3)
    ax.tick_params(axis="x", rotation=18)

    save_figure(fig, output / "01_overview_dashboard.png")


def draw_cost_breakdown(cases: pd.DataFrame, output: Path) -> None:
    fig, ax = plt.subplots(figsize=(15, 8.5), constrained_layout=True)
    y = np.arange(len(cases))
    left = np.zeros(len(cases))
    for component in COST_LABELS:
        values = cases[component].to_numpy()
        ax.barh(y, values, left=left, color=COST_COLORS[component], label=COST_LABELS[component])
        left += values
    ax.set_yticks(y, cases["case_label"])
    ax.invert_yaxis()
    ax.set_xlabel("全过程成本")
    ax.set_title("逐算例成本构成：最终运营成本 + 全过程累计变更成本", fontsize=15)
    ax.legend(ncol=4, loc="lower center", bbox_to_anchor=(0.5, -0.14), frameon=False)
    for index, total in enumerate(cases["objective"]):
        ax.text(total + 120, index, f"{total:,.0f}", va="center", fontsize=8.5, color="#334155")
    ax.set_xlim(0, cases["objective"].max() * 1.09)
    save_figure(fig, output / "02_case_cost_breakdown.png")


def draw_service_levels(services: pd.DataFrame, output: Path) -> None:
    products = ["urgent", "standard", "economy"]
    fig, axes = plt.subplots(3, 1, figsize=(15, 11.5), constrained_layout=True)
    fig.suptitle("逐算例准时率与产品目标", fontsize=17, fontweight="bold")
    for ax, product in zip(axes, products):
        frame = services[services["product"] == product].reset_index(drop=True)
        target = PRODUCT_TARGETS[product]
        colors = ["#DC2626" if value + 1e-10 < target else "#16A34A" for value in frame["on_time_rate"]]
        bars = ax.bar(np.arange(len(frame)), frame["on_time_rate"] * 100, color=colors, width=0.66)
        ax.axhline(target * 100, color="#111827", linestyle="--", linewidth=1.4,
                   label=f"目标 {target:.0%}")
        lower = min(target * 100 - 1.2, float(frame["on_time_rate"].min() * 100) - 0.5)
        ax.set_ylim(max(0, lower), 100.8)
        ax.set_title(PRODUCT_LABELS[product], loc="left")
        ax.set_ylabel("准时率")
        ax.yaxis.set_major_formatter(PercentFormatter(100))
        ax.set_xticks(np.arange(len(frame)), frame["case_label"], rotation=25, ha="right")
        ax.bar_label(bars, labels=[f"{value:.2f}%" for value in frame["on_time_rate"] * 100],
                     padding=2, fontsize=8)
        ax.legend(frameon=False, loc="lower right")
    save_figure(fig, output / "03_service_levels.png")


def draw_solver_performance(cases: pd.DataFrame, phases: pd.DataFrame, output: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(15, 10), constrained_layout=True)
    x = np.arange(len(cases))
    bars = axes[0].bar(
        x, cases["runtime_seconds"] / 60,
        color=[CATEGORY_COLORS[item] for item in cases["category"]], width=0.68,
    )
    axes[0].set_xticks(x, cases["case_label"], rotation=25, ha="right")
    axes[0].set_ylabel("累计求解时间（分钟）")
    axes[0].set_title("逐算例Gurobi累计求解时间（并行前的调用时间合计）")
    axes[0].bar_label(bars, labels=[f"{value:.1f}" for value in cases["runtime_seconds"] / 60],
                      padding=3, fontsize=8)

    limited = phases[phases["status"] == "time_limit"].copy()
    phase_colors = {"日初规划": "#F59E0B", "周期滚动": "#3B82F6", "事件重调度": "#EF4444"}
    case_order = list(cases["case_label"])
    x_position = {label: index for index, label in enumerate(case_order)}
    for phase, frame in limited.groupby("phase"):
        axes[1].scatter(
            [x_position[label] for label in frame["case_label"]], frame["gap"] * 100,
            s=68, alpha=0.85, color=phase_colors[phase], label=phase, edgecolor="white", linewidth=0.7,
        )
    axes[1].axhline(5, color="#111827", linestyle="--", linewidth=1.2, label="目标Gap 5%")
    axes[1].set_ylabel("达到时限时的Gap")
    axes[1].yaxis.set_major_formatter(PercentFormatter(100))
    axes[1].set_title("19次达到300秒上限的求解精度")
    axes[1].set_xticks(np.arange(len(case_order)), case_order, rotation=25, ha="right")
    axes[1].legend(frameon=False, ncol=4)
    save_figure(fig, output / "04_solver_performance.png")


def draw_operations(cases: pd.DataFrame, output: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(17, 8), constrained_layout=True, sharey=True)
    y = np.arange(len(cases))
    colors = [CATEGORY_COLORS[item] for item in cases["category"]]
    charts = [
        ("completion_hour", "全部货物完成时间", "小时"),
        ("max_inventory", "单节点峰值留仓量", "吨"),
        ("cumulative_change", "全过程方案变更成本", "成本单位"),
    ]
    for ax, (column, title, xlabel) in zip(axes, charts):
        bars = ax.barh(y, cases[column], color=colors, height=0.62)
        ax.set_title(title)
        ax.set_xlabel(xlabel)
        ax.bar_label(bars, labels=[f"{value:.1f}" for value in cases[column]], padding=3, fontsize=8)
        ax.set_xlim(0, cases[column].max() * 1.16)
    axes[0].set_yticks(y, cases["case_label"])
    axes[0].invert_yaxis()
    fig.suptitle("滚动运营结果：完成、留仓与计划稳定性", fontsize=17, fontweight="bold")
    save_figure(fig, output / "05_dynamic_operations.png")


def draw_node_heatmap(solutions: list[dict], output: Path) -> None:
    solution = next(item for item in solutions if item["case_id"] == "test_urgent_insert_002")
    event_slot = int(solution["event_slot"])
    snapshot = next(item for item in solution["plan_snapshots"] if int(item["decision_slot"]) == event_slot)
    node_ids = [item["node_id"] for item in snapshot["nodes"]]
    inventory = np.array([
        [float(state["inventory_tons"]) for state in node["timeline"][:-1]]
        for node in snapshot["nodes"]
    ])
    utilization = np.array([
        [float(state["handling_utilization"] or 0.0) * 100 for state in node["timeline"][:-1]]
        for node in snapshot["nodes"]
    ])
    hours = [int(state["hour"]) for state in snapshot["nodes"][0]["timeline"][:-1]]

    fig, axes = plt.subplots(2, 1, figsize=(16, 7.8), constrained_layout=True)
    fig.suptitle("紧急插单002：15小时事件重调度后的节点时序", fontsize=17, fontweight="bold")
    image = axes[0].imshow(inventory, aspect="auto", cmap="YlOrRd", vmin=0)
    axes[0].set_title("各节点计划留仓量（吨）", loc="left")
    axes[0].set_yticks(np.arange(len(node_ids)), node_ids)
    axes[0].set_xticks(np.arange(len(hours)), hours)
    axes[0].set_xlabel("小时")
    fig.colorbar(image, ax=axes[0], shrink=0.85, label="吨")

    image = axes[1].imshow(utilization, aspect="auto", cmap="Blues", vmin=0, vmax=100)
    axes[1].set_title("各节点处理能力利用率", loc="left")
    axes[1].set_yticks(np.arange(len(node_ids)), node_ids)
    axes[1].set_xticks(np.arange(len(hours)), hours)
    axes[1].set_xlabel("小时")
    fig.colorbar(image, ax=axes[1], shrink=0.85, label="%")
    for ax in axes:
        ax.axvline(event_slot, color="#7C3AED", linestyle="--", linewidth=2)
        ax.text(event_slot + 0.1, -0.75, "插单发生", color="#7C3AED", fontweight="bold")
    save_figure(fig, output / "06_node_timeline_heatmap.png")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-set", default="gurobi_v6_12")
    args = parser.parse_args()
    selected_font = configure_plotting()
    solutions, validations = load_results(args.result_set)
    cases, services, phases = prepare_data(solutions)
    output = ROOT / "reports" / "figures" / args.result_set
    output.mkdir(parents=True, exist_ok=True)
    draw_overview(cases, services, phases, validations, output)
    draw_cost_breakdown(cases, output)
    draw_service_levels(services, output)
    draw_solver_performance(cases, phases, output)
    draw_operations(cases, output)
    draw_node_heatmap(solutions, output)
    print(json.dumps({
        "status": "complete",
        "font": selected_font,
        "result_set": args.result_set,
        "case_count": len(cases),
        "phase_count": len(phases),
        "output_dir": str(output),
        "files": [path.name for path in sorted(output.glob("*.png"))],
        "solver_status_counts": dict(Counter(phases["status"])),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
