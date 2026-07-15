from __future__ import annotations

from pathlib import Path

from evals.targets.css_edit import evaluate_css_edit


def _write(path: Path, *, target_css: str, sibling_css: str = "", script: str = "") -> None:
    path.write_text(
        f"""<!doctype html><html><head><style>
body{{margin:0;background:white}} #target{{{target_css}}} #sibling{{{sibling_css}}}
</style></head><body><main data-role="main-visual">
<button id="action" type="button">执行</button><div id="target">目标</div><div id="sibling">旁区</div>
</main><script>document.querySelector('#action').addEventListener('click',()=>{{}});{script}</script></body></html>""",
        encoding="utf-8",
    )


def test_css_edit_browser_gate_accepts_target_only_computed_style_change(tmp_path: Path) -> None:
    before = tmp_path / "before.html"
    after = tmp_path / "after.html"
    _write(before, target_css="display:block;color:red")
    _write(after, target_css="display:grid;color:red")

    report = evaluate_css_edit(
        before,
        after,
        selector="#target",
        expected_styles={"display": "grid"},
        interaction_selector="#action",
        output_dir=tmp_path / "report",
    )

    assert report["passed"], report
    assert report["outside_target_unchanged"] is True
    assert report["new_browser_errors"] == []


def test_css_edit_browser_gate_rejects_outside_change_and_new_runtime_error(tmp_path: Path) -> None:
    before = tmp_path / "before.html"
    after = tmp_path / "after.html"
    _write(before, target_css="display:block;color:red")
    _write(
        after,
        target_css="display:grid;color:red",
        sibling_css="margin-left:80px",
        script="setTimeout(()=>{throw new Error('new failure')},0);",
    )

    report = evaluate_css_edit(
        before,
        after,
        selector="#target",
        expected_styles={"display": "grid"},
        output_dir=tmp_path / "report",
    )

    assert report["passed"] is False
    assert report["outside_target_unchanged"] is False
    assert any("new failure" in error for error in report["new_browser_errors"])
