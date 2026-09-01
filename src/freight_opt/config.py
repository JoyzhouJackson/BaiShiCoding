from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    config: Path
    draft_data: Path
    frozen_data: Path


def project_paths(root: Path | None = None) -> ProjectPaths:
    resolved_root = (root or Path(__file__).resolve().parents[2]).resolve()
    return ProjectPaths(
        root=resolved_root,
        config=resolved_root / "config" / "base_config.yaml",
        draft_data=resolved_root / "data" / "draft",
        frozen_data=resolved_root / "data" / "frozen",
    )


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or project_paths().config
    with config_path.open("r", encoding="utf-8") as stream:
        return yaml.safe_load(stream)
