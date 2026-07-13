#!/usr/bin/env python3
"""Offline browser quality checks for generated AetherViz HTML."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

VIEWPORTS = ((959, 900), (960, 540), (1280, 720), (912, 1180), (390, 844))

METRICS_JS = r"""
() => {
  const stage = document.querySelector('#aetherviz-stage');
  if (!stage) return {error: 'missing_stage'};
  const stageRect = stage.getBoundingClientRect();
  const viewportArea = innerWidth * innerHeight;
  const visible = (rect) => rect.width > 0 && rect.height > 0 &&
    rect.right > 0 && rect.bottom > 0 && rect.left < innerWidth && rect.top < innerHeight;
  const overflowElements = [...document.querySelectorAll('body *')].filter((el) => {
    const r = el.getBoundingClientRect();
    return visible(r) && (r.left < -1 || r.top < -1 || r.right > innerWidth + 1 || r.bottom > innerHeight + 1);
  });
  const scrollContainers = [...document.querySelectorAll('body *')].filter((el) => {
    const s = getComputedStyle(el);
    return /(auto|scroll)/.test(s.overflow + s.overflowX + s.overflowY) &&
      (el.scrollHeight > el.clientHeight + 2 || el.scrollWidth > el.clientWidth + 2);
  });
  const labels = [...stage.querySelectorAll('svg text')].map((el) => el.getBoundingClientRect()).filter(visible);
  let labelOverlaps = 0;
  for (let i = 0; i < labels.length; i++) for (let j = i + 1; j < labels.length; j++) {
    const a = labels[i], b = labels[j];
    if (Math.min(a.right,b.right)-Math.max(a.left,b.left) > 2 && Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top) > 2) labelOverlaps++;
  }
  const maxLabelPx = labels.reduce((n, r) => Math.max(n, r.height), 0);
  const maxStrokePx = [...stage.querySelectorAll('svg [stroke],svg line,svg path,svg circle,svg rect')].reduce((n, el) => {
    const width = parseFloat(getComputedStyle(el).strokeWidth) || 0;
    const ctm = el.getScreenCTM && el.getScreenCTM();
    const scale = ctm ? Math.sqrt(Math.abs(ctm.a * ctm.d - ctm.b * ctm.c)) : 1;
    return Math.max(n, getComputedStyle(el).vectorEffect === 'non-scaling-stroke' ? width : width * scale);
  }, 0);
  const topLevelSlots = ['.av-header', '#aetherviz-stage', '.av-status', '.av-inspector']
    .map((selector) => document.querySelector(selector)).filter(Boolean);
  let slotOverlapCount = 0;
  for (let i = 0; i < topLevelSlots.length; i++) for (let j = i + 1; j < topLevelSlots.length; j++) {
    const a = topLevelSlots[i].getBoundingClientRect(), b = topLevelSlots[j].getBoundingClientRect();
    if (Math.min(a.right,b.right)-Math.max(a.left,b.left) > 2 && Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top) > 2) slotOverlapCount++;
  }
  const ranges = [...document.querySelectorAll('#aetherviz-app-shell input[type="range"]')];
  const invalidRanges = ranges.filter((el) => {
    const r = el.getBoundingClientRect();
    const owner = el.closest('.av-primary-controls,.av-secondary-controls');
    if (!owner) return true;
    const o = owner.getBoundingClientRect();
    const contained = r.left >= o.left - 1 && r.right <= o.right + 1 && r.top >= o.top - 1 && r.bottom <= o.bottom + 1;
    return !contained || r.height < 44 || r.height > 64;
  });
  return {
    stage_area_ratio: viewportArea ? stageRect.width * stageRect.height / viewportArea : 0,
    stage_clipped: stageRect.left < -1 || stageRect.top < -1 || stageRect.right > innerWidth + 1 || stageRect.bottom > innerHeight + 1,
    overflow_element_count: overflowElements.length,
    scroll_container_count: scrollContainers.length,
    label_overlap_count: labelOverlaps,
    max_label_height_px: maxLabelPx,
    max_stroke_width_px: maxStrokePx,
    slot_overlap_count: slotOverlapCount,
    invalid_range_count: invalidRanges.length,
    range_heights_px: ranges.map((el) => el.getBoundingClientRect().height),
    runtime_ready: window.__AETHERVIZ_RUNTIME_READY__ === true,
    runtime_error: String(window.__AETHERVIZ_RUNTIME_ERROR__ || '')
  };
}
"""

RUNTIME_SNAPSHOT_JS = r"""
() => {
  const stage = document.querySelector('#aetherviz-stage');
  const runtime = window.AetherVizRuntime;
  const nodes = stage ? [...stage.querySelectorAll('*')] : [];
  const visual = nodes.map((el) => [
    el.tagName, el.id, el.getAttribute('transform'), el.getAttribute('d'),
    el.getAttribute('cx'), el.getAttribute('cy'), el.getAttribute('x'), el.getAttribute('y'),
    el.getAttribute('fill'), el.getAttribute('stroke'), el.textContent
  ].join('|')).join('\n');
  const canvas = stage && stage.querySelector('canvas');
  let canvasSample = '';
  try { if (canvas) canvasSample = canvas.toDataURL().slice(-256); } catch (_) {}
  let state = {};
  try { state = runtime && runtime.getState ? runtime.getState() : {}; } catch (error) { state = {error: String(error)}; }
  const controls = [...document.querySelectorAll('#aetherviz-app-shell input,select')]
    .map((el) => [el.id || el.getAttribute('data-var') || el.name, el.value, el.checked].join('|'));
  return {node_count: nodes.length, visual_signature: visual + canvasSample, state, controls};
}
"""


def _runtime_behavior(page) -> dict:
    initial = page.evaluate(RUNTIME_SNAPSHOT_JS)
    has_runtime = page.evaluate("() => Boolean(window.AetherVizRuntime)")
    if not has_runtime:
        return {"runtime_present": False}
    page.evaluate("() => window.AetherVizRuntime.play()")
    page.wait_for_timeout(350)
    playing = page.evaluate(RUNTIME_SNAPSHOT_JS)
    page.evaluate("() => window.AetherVizRuntime.pause()")
    page.wait_for_timeout(40)
    paused_start = page.evaluate(RUNTIME_SNAPSHOT_JS)
    page.wait_for_timeout(180)
    paused = page.evaluate(RUNTIME_SNAPSHOT_JS)
    page.evaluate("() => window.AetherVizRuntime.reset()")
    page.wait_for_timeout(80)
    reset = page.evaluate(RUNTIME_SNAPSHOT_JS)
    for _ in range(2):
        page.evaluate("() => { window.AetherVizRuntime.reset(); window.AetherVizRuntime.play(); }")
        page.wait_for_timeout(80)
        page.evaluate("() => window.AetherVizRuntime.pause()")
    repeated = page.evaluate(RUNTIME_SNAPSHOT_JS)
    before_parameter = reset
    parameter_changed = page.evaluate(
        """() => {
          const input = document.querySelector('#aetherviz-app-shell input[type="range"]');
          if (!input) return false;
          const min = Number(input.min || 0), max = Number(input.max || 100);
          input.value = String(Number(input.value) === max ? min : max);
          input.dispatchEvent(new Event('input', {bubbles: true}));
          input.dispatchEvent(new Event('change', {bubbles: true}));
          return true;
        }"""
    )
    page.wait_for_timeout(80)
    after_parameter = page.evaluate(RUNTIME_SNAPSHOT_JS)
    page.evaluate("() => window.AetherVizRuntime.reset()")
    page.wait_for_timeout(80)
    parameter_reset = page.evaluate(RUNTIME_SNAPSHOT_JS)
    page.evaluate(
        """() => {
          const runtime=window.AetherVizRuntime;
          if (typeof runtime.setSpeed === 'function') runtime.setSpeed(20);
          runtime.play();
        }"""
    )
    page.wait_for_timeout(800)
    completed = page.evaluate(RUNTIME_SNAPSHOT_JS)
    completed_state = completed["state"] if isinstance(completed["state"], dict) else {}
    completed_progress = completed_state.get("progress")
    completion_reached = isinstance(completed_progress, (int, float)) and completed_progress >= 0.98
    page.evaluate(
        """() => {
          const runtime=window.AetherVizRuntime;
          if (typeof runtime.setSpeed === 'function') runtime.setSpeed(1);
          runtime.play();
        }"""
    )
    page.wait_for_timeout(80)
    replaying = page.evaluate(RUNTIME_SNAPSHOT_JS)
    return {
        "runtime_present": True,
        "animation_visible_change": playing["visual_signature"] != initial["visual_signature"],
        "pause_stable": paused["visual_signature"] == paused_start["visual_signature"],
        "reset_consistent": reset["visual_signature"] == initial["visual_signature"],
        "node_count_stable": repeated["node_count"] == reset["node_count"],
        "parameter_control_present": parameter_changed,
        "parameter_visual_sync": not parameter_changed
        or after_parameter["visual_signature"] != before_parameter["visual_signature"],
        "parameter_reset_consistent": not parameter_changed
        or (
            parameter_reset["visual_signature"] == initial["visual_signature"]
            and parameter_reset["state"] == initial["state"]
            and parameter_reset["controls"] == initial["controls"]
        ),
        "completion_visible_change": not completion_reached
        or completed["visual_signature"] != initial["visual_signature"],
        "completion_state_stable": not completion_reached
        or completed_state.get("isPlaying") is not True,
        "replay_after_completion": not completion_reached
        or replaying["visual_signature"] != completed["visual_signature"],
        "snapshots": {"initial": initial, "playing": playing, "paused": paused, "reset": reset},
    }


def evaluate_html(html_path: Path, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, height in VIEWPORTS:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(html_path.resolve().as_uri(), wait_until="load")
            page.wait_for_timeout(500)
            metrics = page.evaluate(METRICS_JS)
            metrics["behavior"] = _runtime_behavior(page)
            screenshot = output_dir / f"{html_path.stem}-{width}x{height}.png"
            page.screenshot(path=str(screenshot), full_page=False)
            metrics.update({"width": width, "height": height, "screenshot": str(screenshot)})
            results.append(metrics)
            page.close()
        fallback_page = browser.new_page(viewport={"width": VIEWPORTS[0][0], "height": VIEWPORTS[0][1]})
        fallback_page.route("**/*gsap*", lambda route: route.abort())
        fallback_page.goto(html_path.resolve().as_uri(), wait_until="load")
        fallback_page.wait_for_timeout(500)
        fallback_metrics = fallback_page.evaluate(METRICS_JS)
        fallback_metrics["behavior"] = _runtime_behavior(fallback_page)
        fallback_page.close()
        browser.close()
    passed = all(
        not item.get("error")
        and not item["stage_clipped"]
        and item["stage_area_ratio"] >= (0.18 if item["width"] >= 900 else 0.12)
        and item["max_label_height_px"] <= 48
        and item["max_stroke_width_px"] <= 12
        and item["slot_overlap_count"] == 0
        and item["invalid_range_count"] == 0
        and not item["runtime_error"]
        and item["runtime_ready"]
        and item["behavior"].get("animation_visible_change", False)
        and item["behavior"].get("pause_stable", False)
        and item["behavior"].get("reset_consistent", False)
        and item["behavior"].get("node_count_stable", False)
        and item["behavior"].get("parameter_visual_sync", False)
        and item["behavior"].get("parameter_reset_consistent", False)
        and item["behavior"].get("completion_visible_change", False)
        and item["behavior"].get("completion_state_stable", False)
        and item["behavior"].get("replay_after_completion", False)
        for item in results
    ) and fallback_metrics.get("runtime_ready") and fallback_metrics["behavior"].get("animation_visible_change", False)
    return {
        "html": str(html_path),
        "passed": passed,
        "viewports": results,
        "gsap_fallback": fallback_metrics,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("html", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path(".visual-regression"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = evaluate_html(args.html, args.output_dir)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
