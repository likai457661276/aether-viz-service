#!/usr/bin/env python3
"""Offline browser quality checks for generated AetherViz HTML."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

VIEWPORTS = ((960, 540), (1280, 720), (390, 844))

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
  return {
    stage_area_ratio: viewportArea ? stageRect.width * stageRect.height / viewportArea : 0,
    stage_clipped: stageRect.left < -1 || stageRect.top < -1 || stageRect.right > innerWidth + 1 || stageRect.bottom > innerHeight + 1,
    overflow_element_count: overflowElements.length,
    scroll_container_count: scrollContainers.length,
    label_overlap_count: labelOverlaps,
    max_label_height_px: maxLabelPx,
    max_stroke_width_px: maxStrokePx,
    runtime_ready: window.__AETHERVIZ_RUNTIME_READY__ === true,
    runtime_error: String(window.__AETHERVIZ_RUNTIME_ERROR__ || '')
  };
}
"""


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
            screenshot = output_dir / f"{html_path.stem}-{width}x{height}.png"
            page.screenshot(path=str(screenshot), full_page=False)
            metrics.update({"width": width, "height": height, "screenshot": str(screenshot)})
            results.append(metrics)
            page.close()
        browser.close()
    passed = all(
        not item.get("error")
        and not item["stage_clipped"]
        and item["stage_area_ratio"] >= (0.18 if item["width"] >= 900 else 0.12)
        and item["max_label_height_px"] <= 48
        and item["max_stroke_width_px"] <= 12
        and not item["runtime_error"]
        for item in results
    )
    return {"html": str(html_path), "passed": passed, "viewports": results}


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
