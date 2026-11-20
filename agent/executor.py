"""
agent/executor.py
─────────────────────────────────────────────────────────────────────────────
Executor — Phase 3 of the agent pipeline.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page, TimeoutError as PWTimeout

from agent.models import StepResult, TestCase, TestResult, TestStep

log = logging.getLogger("executor")

SCREENSHOTS_DIR = "screenshots/agent"
Path(SCREENSHOTS_DIR).mkdir(parents=True, exist_ok=True)


class TestExecutor:

    def __init__(self, page: Page, timeout: int = 15000, screenshots_dir: str = SCREENSHOTS_DIR):
        self.page            = page
        self.timeout         = timeout
        self._assert_timeout = min(timeout, 10000)
        self.ss_dir          = screenshots_dir
        Path(self.ss_dir).mkdir(parents=True, exist_ok=True)
        self._counter        = 0

    # ── Public ────────────────────────────────────────────────────────────────

    def run_all(self, test_cases: list[TestCase]) -> list[TestResult]:
        results = []
        total   = len(test_cases)

        for i, tc in enumerate(test_cases, 1):
            priority_badge = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(tc.priority, "⚪")
            log.info(f"  [{i:>2}/{total}] {priority_badge}  {tc.id} — {tc.name}")

            result = self._run_one(tc)
            results.append(result)

            icon = "✅" if result.status == "PASS" else "❌"
            log.info(f"         {icon}  {result.status}  ({result.duration_ms:.0f}ms)")
            if result.status != "PASS" and result.error:
                log.info(f"            ↳  {result.error[:120]}")

        return results

    # ── Run one test ──────────────────────────────────────────────────────────

    def _run_one(self, tc: TestCase) -> TestResult:
        t_start      = time.time()
        step_results : list[StepResult] = []
        final_status = "PASS"
        actual_msg   = tc.expected_outcome
        error_msg    = ""
        screenshot   = ""

        for step in tc.steps:
            sr = self._execute_step(step)
            step_results.append(sr)

            if sr.status in ("FAIL", "ERROR"):
                final_status = sr.status
                actual_msg   = sr.message
                error_msg    = sr.message
                screenshot   = self._screenshot(tc.id)
                break

        duration_ms = (time.time() - t_start) * 1000

        return TestResult(
            test_case      = tc,
            status         = final_status,
            actual_outcome = actual_msg,
            duration_ms    = duration_ms,
            step_results   = step_results,
            screenshot     = screenshot,
            error          = error_msg,
        )

    # ── Step dispatcher ───────────────────────────────────────────────────────

    def _execute_step(self, step: TestStep) -> StepResult:
        action = step.action.lower().strip()
        try:
            if action == "goto":
                return self._step_goto(step)
            elif action == "fill":
                return self._step_fill(step)
            elif action == "click":
                return self._step_click(step)
            elif action == "select":
                return self._step_select(step)
            elif action == "wait":
                return self._step_wait(step)
            elif action == "wait_visible":
                return self._step_wait_visible(step)
            elif action == "assert_visible":
                return self._step_assert_visible(step)
            elif action == "assert_not_visible":
                return self._step_assert_not_visible(step)
            elif action == "assert_text":
                return self._step_assert_text(step)
            elif action == "assert_url":
                return self._step_assert_url(step)
            elif action == "screenshot":
                self._screenshot("mid_test")
                return StepResult(step=step, status="PASS", message="Screenshot captured")
            else:
                return StepResult(step=step, status="SKIP",
                                  message=f"Unknown action '{action}' — skipped")
        except PWTimeout as e:
            return StepResult(step=step, status="FAIL",
                              message=f"Timeout waiting for '{step.selector}': {str(e)[:120]}")
        except Exception as e:
            return StepResult(step=step, status="ERROR",
                              message=f"{type(e).__name__}: {str(e)[:200]}")

    # ── Step handlers ─────────────────────────────────────────────────────────

    def _step_goto(self, step: TestStep) -> StepResult:
        url = step.url or step.value
        if not url:
            return StepResult(step=step, status="ERROR", message="goto: no URL provided")
        self.page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)
        try:
            self.page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        time.sleep(0.3)
        return StepResult(step=step, status="PASS", message=f"Navigated to {url}")

    def _step_fill(self, step: TestStep) -> StepResult:
        if not step.selector:
            return StepResult(step=step, status="ERROR", message="fill: no selector")
        loc = self.page.locator(step.selector).first
        loc.wait_for(state="visible", timeout=self._assert_timeout)
        loc.fill(step.value)
        return StepResult(step=step, status="PASS",
                          message=f"Filled '{step.selector}' with value")

    def _step_click(self, step: TestStep) -> StepResult:
        """Click an element and handle both same-page and new-tab navigation.

        FIX for footer links (Terms of Service, Money-Back Policy):
        These are <a href> links that may open in a new tab (target="_blank").
        When that happens, the current page URL never changes, so wait_for_url
        times out silently and assert_url fails.

        Solution: after clicking, check if a new page/tab opened in the context.
        If it did, switch to it so subsequent assert_url steps see the new URL.
        If navigation happened in the same tab, use wait_for_url as before.
        """
        if not step.selector:
            return StepResult(step=step, status="ERROR", message="click: no selector")

        loc = self.page.locator(step.selector).first
        loc.wait_for(state="visible", timeout=self._assert_timeout)
        loc.scroll_into_view_if_needed()

        old_url     = self.page.url
        context     = self.page.context
        pages_before = set(p for p in context.pages)

        loc.click()

        # Give React / the browser a moment to decide what to do
        time.sleep(0.5)

        # Case 1: a new tab opened (target="_blank" links like footer links)
        pages_after = set(p for p in context.pages)
        new_pages   = pages_after - pages_before
        if new_pages:
            new_page = list(new_pages)[0]
            try:
                new_page.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:
                pass
            # Bring the new tab into focus so subsequent steps run against it
            self.page = new_page
            return StepResult(step=step, status="PASS",
                              message=f"Clicked '{step.selector}' → new tab: {new_page.url}")

        # Case 2: same-tab navigation (React router, normal href)
        try:
            self.page.wait_for_url(lambda url: url != old_url, timeout=2000)
        except Exception:
            # No navigation — plain UI click (toggle, modal, filter button)
            try:
                if self.page.url == old_url:
                    loc.dispatch_event("click")
                    self.page.wait_for_url(lambda url: url != old_url, timeout=1000)
            except Exception:
                pass

        time.sleep(0.3)
        return StepResult(step=step, status="PASS", message=f"Clicked '{step.selector}'")

    def _step_select(self, step: TestStep) -> StepResult:
        if not step.selector:
            return StepResult(step=step, status="ERROR", message="select: no selector")
        loc = self.page.locator(step.selector).first
        loc.wait_for(state="visible", timeout=self._assert_timeout)
        loc.select_option(label=step.value)
        return StepResult(step=step, status="PASS",
                          message=f"Selected '{step.value}' in '{step.selector}'")

    def _step_wait(self, step: TestStep) -> StepResult:
        ms = int(step.value) if step.value and step.value.isdigit() else 1000
        ms = min(ms, 5000)
        time.sleep(ms / 1000)
        return StepResult(step=step, status="PASS", message=f"Waited {ms}ms")

    def _step_wait_visible(self, step: TestStep) -> StepResult:
        if not step.selector:
            return StepResult(step=step, status="ERROR", message="wait_visible: no selector")
        self.page.locator(step.selector).first.wait_for(
            state="visible", timeout=self._assert_timeout
        )
        return StepResult(step=step, status="PASS",
                          message=f"Element visible: '{step.selector}'")

    def _step_assert_visible(self, step: TestStep) -> StepResult:
        if not step.selector:
            return StepResult(step=step, status="ERROR", message="assert_visible: no selector")
        try:
            self.page.locator(step.selector).first.wait_for(
                state="visible", timeout=self._assert_timeout
            )
            return StepResult(step=step, status="PASS",
                              message=f"✓ Visible: '{step.selector}'")
        except (PWTimeout, Exception):
            count = self.page.locator(step.selector).count()
            return StepResult(
                step=step, status="FAIL",
                message=f"✗ Not visible: '{step.selector}' (found {count} matching elements)",
            )

    def _step_assert_not_visible(self, step: TestStep) -> StepResult:
        if not step.selector:
            return StepResult(step=step, status="ERROR", message="assert_not_visible: no selector")
        try:
            self.page.locator(step.selector).first.wait_for(state="hidden", timeout=3000)
            return StepResult(step=step, status="PASS",
                              message=f"✓ Not visible (as expected): '{step.selector}'")
        except Exception:
            return StepResult(
                step=step, status="FAIL",
                message=f"✗ Unexpectedly visible: '{step.selector}'",
            )

    def _step_assert_text(self, step: TestStep) -> StepResult:
        if not step.selector:
            return StepResult(step=step, status="ERROR", message="assert_text: no selector")
        try:
            loc = self.page.locator(step.selector).first
            loc.wait_for(state="visible", timeout=self._assert_timeout)
            actual = loc.inner_text()
            if step.value.lower() in actual.lower():
                return StepResult(step=step, status="PASS",
                                  message=f"✓ Text found: '{step.value}'")
            return StepResult(
                step=step, status="FAIL",
                message=f"✗ Expected '{step.value}' in text, got: '{actual[:100]}'",
            )
        except (PWTimeout, Exception) as e:
            return StepResult(step=step, status="FAIL",
                              message=f"✗ Element not found: {str(e)[:100]}")

    def _step_assert_url(self, step: TestStep) -> StepResult:
        current = self.page.url
        if step.value.lower() in current.lower():
            return StepResult(step=step, status="PASS",
                              message=f"✓ URL contains '{step.value}'")
        return StepResult(
            step=step, status="FAIL",
            message=f"✗ URL '{current}' does not contain '{step.value}'",
        )

    # ── Screenshot ────────────────────────────────────────────────────────────

    def _screenshot(self, label: str) -> str:
        self._counter += 1
        safe_label = label.replace("/", "_").replace(" ", "_")
        path = os.path.join(self.ss_dir, f"{self._counter:03d}_{safe_label}.png")
        try:
            self.page.screenshot(path=path, full_page=True)
            return path
        except Exception as e:
            log.warning(f"Screenshot failed: {e}")
            return ""