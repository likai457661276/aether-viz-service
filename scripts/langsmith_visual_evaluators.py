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


def animation_visible_change_evaluator(run, example):
    viewports = _outputs(run).get("viewports", [])
    passed = bool(viewports) and all(
        item.get("behavior", {}).get("animation_visible_change") for item in viewports
    )
    return {"score": 1 if passed else 0, "comment": "播放后主视觉发生变化" if passed else "播放后未检测到主视觉变化"}


def pause_stability_evaluator(run, example):
    viewports = _outputs(run).get("viewports", [])
    passed = bool(viewports) and all(item.get("behavior", {}).get("pause_stable") for item in viewports)
    return {"score": 1 if passed else 0, "comment": "暂停后画面稳定" if passed else "暂停后画面仍变化"}


def reset_consistency_evaluator(run, example):
    viewports = _outputs(run).get("viewports", [])
    passed = bool(viewports) and all(item.get("behavior", {}).get("reset_consistent") for item in viewports)
    return {"score": 1 if passed else 0, "comment": "重置恢复初始视觉" if passed else "重置未恢复初始视觉"}


def parameter_visual_sync_evaluator(run, example):
    viewports = _outputs(run).get("viewports", [])
    passed = bool(viewports) and all(item.get("behavior", {}).get("parameter_visual_sync") for item in viewports)
    return {"score": 1 if passed else 0, "comment": "参数与主视觉同步" if passed else "参数变化未驱动主视觉"}


def node_count_stability_evaluator(run, example):
    viewports = _outputs(run).get("viewports", [])
    passed = bool(viewports) and all(item.get("behavior", {}).get("node_count_stable") for item in viewports)
    return {"score": 1 if passed else 0, "comment": "重复播放节点数稳定" if passed else "重复播放导致节点数漂移"}


def gsap_fallback_evaluator(run, example):
    fallback = _outputs(run).get("gsap_fallback", {})
    passed = bool(fallback.get("runtime_ready")) and bool(
        fallback.get("behavior", {}).get("animation_visible_change")
    )
    return {"score": 1 if passed else 0, "comment": "GSAP 不可用时动画可运行" if passed else "GSAP fallback 不可运行"}
