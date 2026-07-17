from __future__ import annotations

from pathlib import Path

import pytest

from aetherviz_service.aetherviz.contracts.layout import assemble_layout_contract
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan
from evals.targets.visual import evaluate_playback_progress

FIXTURE = Path("evals/datasets/html_contract/playback_progress.html")


@pytest.mark.parametrize("use_gsap_stub", [False, True])
def test_play_button_advances_state_with_native_and_gsap_paths(
    tmp_path: Path, use_gsap_stub: bool
) -> None:
    business = FIXTURE.read_text(encoding="utf-8")
    assembled = assemble_layout_contract(
        business, normalize_plan({}, "动画播放进度回归")
    )
    html_path = tmp_path / "playback-progress.html"
    html_path.write_text(assembled, encoding="utf-8")

    report = evaluate_playback_progress(html_path, wait_ms=500, use_gsap_stub=use_gsap_stub)

    assert report["passed"], report
    assert report["numeric_progress"]["sides"][1] > 6
