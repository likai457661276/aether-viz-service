"""Sandbox artifact value objects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SandboxArtifacts:
    run_id: str
    run_dir: Path
    html_path: Path
    report_path: Path
    repair_path: Path
