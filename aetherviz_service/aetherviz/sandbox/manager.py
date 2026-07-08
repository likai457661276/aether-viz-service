"""Per-run sandbox manager."""

from __future__ import annotations

import uuid
from pathlib import Path

from aetherviz_service.aetherviz.sandbox.artifacts import SandboxArtifacts
from aetherviz_service.config import settings


class SandboxPathError(ValueError):
    pass


class SandboxManager:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or settings.aetherviz_agent_sandbox_root).expanduser()
        self._validate_root()
        self.root.mkdir(parents=True, exist_ok=True)

    def create_run(self) -> SandboxArtifacts:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        run_dir = self.root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        return SandboxArtifacts(
            run_id=run_id,
            run_dir=run_dir,
            html_path=run_dir / "index.html",
            report_path=run_dir / "validation-report.json",
            repair_path=run_dir / "repair-draft.html",
        )

    def write_html(self, artifacts: SandboxArtifacts, html: str, *, repaired: bool = False) -> Path:
        path = artifacts.repair_path if repaired else artifacts.html_path
        path.write_text(html, encoding="utf-8")
        return path

    def _validate_root(self) -> None:
        resolved = self.root.resolve()
        cwd = Path.cwd().resolve()
        home = Path.home().resolve()
        if resolved == home or resolved == Path("/"):
            raise SandboxPathError("沙箱目录不能指向用户主目录或系统根目录")
        if resolved == cwd:
            raise SandboxPathError("沙箱目录不能指向仓库根目录")
