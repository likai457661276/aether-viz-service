#!/usr/bin/env python3
"""Offline browser gate for comparing a focused CSS edit with its source HTML."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

DEFAULT_VIEWPORT = {"width": 960, "height": 720}

TARGET_SNAPSHOT_JS = r"""
({selector, properties}) => {
  const targets = [...document.querySelectorAll(selector)];
  const target = targets[0] || null;
  const style = target ? getComputedStyle(target) : null;
  const rect = target ? target.getBoundingClientRect() : null;
  const mainVisual = document.querySelector('[data-role="main-visual"],#aetherviz-stage,svg,canvas');
  const mainRect = mainVisual ? mainVisual.getBoundingClientRect() : null;
  const visible = (element, bounds) => Boolean(element && bounds && bounds.width > 0 && bounds.height > 0 &&
    style && style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) > 0 &&
    bounds.right > 0 && bounds.bottom > 0 && bounds.left < innerWidth && bounds.top < innerHeight);
  return {
    target_count: targets.length,
    target_visible: visible(target, rect),
    target_rect: rect ? {x: rect.x, y: rect.y, width: rect.width, height: rect.height} : null,
    computed_styles: Object.fromEntries(properties.map((name) => [name, style ? style.getPropertyValue(name).trim() : ''])),
    main_visual_present: Boolean(mainVisual),
    main_visual_visible: mainRect ? mainRect.width > 0 && mainRect.height > 0 : false,
    runtime_ready: window.__AETHERVIZ_RUNTIME_READY__ === true,
    runtime_error: String(window.__AETHERVIZ_RUNTIME_ERROR__ || '')
  };
}
"""


def _capture_page(
    browser: Any,
    html_path: Path,
    *,
    selector: str,
    properties: tuple[str, ...],
    screenshot_path: Path,
    interaction_selector: str | None,
) -> dict[str, Any]:
    page = browser.new_page(viewport=DEFAULT_VIEWPORT)
    page_errors: list[str] = []
    console_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "console",
        lambda message: console_errors.append(message.text) if message.type == "error" else None,
    )
    page.goto(html_path.resolve().as_uri(), wait_until="load")
    page.wait_for_timeout(150)
    interaction_ok = True
    if interaction_selector:
        try:
            page.locator(interaction_selector).first.click(timeout=1_000)
            page.wait_for_timeout(50)
        except PlaywrightError as error:
            interaction_ok = False
            page_errors.append(f"interaction_failed:{error}")
    snapshot = page.evaluate(
        TARGET_SNAPSHOT_JS,
        {"selector": selector, "properties": list(properties)},
    )
    target = page.locator(selector)
    screenshot = page.screenshot(
        path=str(screenshot_path),
        full_page=False,
        animations="disabled",
        mask=[target] if snapshot["target_count"] else [],
    )
    page.close()
    return {
        **snapshot,
        "page_errors": page_errors,
        "console_errors": console_errors,
        "interaction_ok": interaction_ok,
        "masked_screenshot": str(screenshot_path),
        "masked_screenshot_sha256": hashlib.sha256(screenshot).hexdigest(),
    }


def evaluate_css_edit(
    before_path: Path,
    after_path: Path,
    *,
    selector: str,
    expected_styles: dict[str, str],
    output_dir: Path,
    interaction_selector: str | None = None,
    allow_outside_target_changes: bool = False,
) -> dict[str, Any]:
    """Compare browser semantics while masking the intended target in screenshots."""
    output_dir.mkdir(parents=True, exist_ok=True)
    properties = tuple(sorted(expected_styles))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        before = _capture_page(
            browser,
            before_path,
            selector=selector,
            properties=properties,
            screenshot_path=output_dir / "before-masked.png",
            interaction_selector=interaction_selector,
        )
        after = _capture_page(
            browser,
            after_path,
            selector=selector,
            properties=properties,
            screenshot_path=output_dir / "after-masked.png",
            interaction_selector=interaction_selector,
        )
        browser.close()

    before_errors = set((*before["page_errors"], *before["console_errors"]))
    after_errors = set((*after["page_errors"], *after["console_errors"]))
    new_errors = sorted(after_errors - before_errors)
    style_mismatches = {
        name: {"expected": expected, "actual": after["computed_styles"].get(name, "")}
        for name, expected in expected_styles.items()
        if after["computed_styles"].get(name, "") != expected
    }
    outside_target_unchanged = (
        before["masked_screenshot_sha256"] == after["masked_screenshot_sha256"]
    )
    passed = (
        before["target_count"] > 0
        and after["target_count"] == before["target_count"]
        and after["target_visible"]
        and after["main_visual_present"]
        and after["main_visual_visible"]
        and not after["runtime_error"]
        and not new_errors
        and after["interaction_ok"]
        and not style_mismatches
        and (allow_outside_target_changes or outside_target_unchanged)
    )
    return {
        "passed": passed,
        "selector": selector,
        "expected_styles": expected_styles,
        "style_mismatches": style_mismatches,
        "new_browser_errors": new_errors,
        "outside_target_unchanged": outside_target_unchanged,
        "allow_outside_target_changes": allow_outside_target_changes,
        "before": before,
        "after": after,
    }


def _expected_styles(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        name, separator, expected = value.partition("=")
        if not separator or not name.strip():
            raise ValueError(f"invalid expected style: {value}")
        result[name.strip()] = expected.strip()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--selector", required=True)
    parser.add_argument("--expected-style", action="append", default=[])
    parser.add_argument("--interaction-selector")
    parser.add_argument("--allow-outside-target-changes", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path(".css-edit-regression"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = evaluate_css_edit(
        args.before,
        args.after,
        selector=args.selector,
        expected_styles=_expected_styles(args.expected_style),
        output_dir=args.output_dir,
        interaction_selector=args.interaction_selector,
        allow_outside_target_changes=args.allow_outside_target_changes,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
