"""Deterministic one-metric LangSmith evaluators for visual regression outputs."""


def _outputs(run):
    return run.outputs if hasattr(run, "outputs") else (run.get("outputs", {}) or {})


def visual_pass_evaluator(run, example):
    output = _outputs(run)
    passed = bool(output.get("passed"))
    return {"score": 1 if passed else 0, "comment": "全部视口通过" if passed else "至少一个视口未通过"}


def stage_visibility_evaluator(run, example):
    viewports = _outputs(run).get("viewports", [])
    passed = bool(viewports) and all(not item.get("stage_clipped") for item in viewports)
    return {"score": 1 if passed else 0, "comment": f"检查 {len(viewports)} 个视口的舞台边界"}


def svg_scale_evaluator(run, example):
    viewports = _outputs(run).get("viewports", [])
    expected = example.outputs if hasattr(example, "outputs") else (example.get("outputs", {}) or {})
    stroke_limit = float(expected.get("max_stroke_width_px", 12))
    label_limit = float(expected.get("max_label_height_px", 48))
    passed = bool(viewports) and all(
        item.get("max_stroke_width_px", 0) <= stroke_limit
        and item.get("max_label_height_px", 0) <= label_limit
        for item in viewports
    )
    return {"score": 1 if passed else 0, "comment": f"描边≤{stroke_limit}px，标签≤{label_limit}px"}
