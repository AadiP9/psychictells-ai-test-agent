"""
test_executor_click.py
─────────────────────────────────────────────────────────────────────────────
Unit tests for TestExecutor._step_click()

Tests verified:
  - Native click fires
  - dispatch_event fallback fires when URL doesn't change after native click
  - New-tab detection: executor switches self.page to the new tab
  - PASS result returned in all valid cases

FIX vs original:
  FakePage was missing .context (needed by _step_click for new-tab detection)
  and .wait_for_url (called when checking for same-tab navigation).
  The original test also asserted page.wait_for_timeout_calls == [500], but
  the executor uses time.sleep() not page.wait_for_timeout() — that assertion
  was wrong. Replaced with a check that time.sleep was called with 0.5.
─────────────────────────────────────────────────────────────────────────────
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.executor import TestExecutor
from agent.models import TestStep


# ── Fakes ─────────────────────────────────────────────────────────────────────

class FakeLocator:
    def __init__(self, page):
        self.page = page
        self.first = self

    def wait_for(self, **kwargs):
        return None

    def scroll_into_view_if_needed(self):
        return None

    def click(self):
        self.page.clicks += 1

    def dispatch_event(self, event_name):
        self.page.dispatch_events += 1

    def count(self):
        return 1

    def is_visible(self):
        return True


class FakeContext:
    """Minimal browser context fake — tracks open pages."""
    def __init__(self, pages):
        self._pages = list(pages)

    @property
    def pages(self):
        return list(self._pages)


class FakePage:
    def __init__(self):
        self.url             = "https://example.com/start"
        self.clicks          = 0
        self.dispatch_events = 0
        self._wait_for_url_calls: list = []
        # Provide a context with only this page open (no new tabs)
        self.context = FakeContext([self])

    def locator(self, selector):
        return FakeLocator(self)

    def wait_for_url(self, predicate, timeout=2000):
        """
        Simulates Playwright's wait_for_url. Records the call.
        Like the real thing, it raises a timeout when the predicate is not
        satisfied (i.e. the URL did not change), so the executor's
        dispatch_event fallback path is exercised.
        """
        self._wait_for_url_calls.append({"timeout": timeout})
        if not predicate(self.url):
            raise TimeoutError("wait_for_url timed out: URL did not change")

    def wait_for_load_state(self, state, timeout=None):
        pass


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_step_click_fires_native_click_and_falls_back_to_dispatch_event():
    """
    When the URL doesn't change after a native click (same-page click like a
    filter button or modal toggle), _step_click should:
      1. Fire the native click (page.clicks == 1)
      2. Call wait_for_url to check for same-tab navigation
      3. Fall back to dispatch_event when wait_for_url times out / URL stays same
      4. Return PASS

    time.sleep calls are intercepted so the test runs fast.
    """
    page     = FakePage()
    executor = TestExecutor(page, timeout=1000)
    step     = TestStep(action="click", selector="button")

    sleep_calls = []

    def fake_sleep(s):
        sleep_calls.append(s)

    with patch("agent.executor.time.sleep", side_effect=fake_sleep):
        result = executor._step_click(step)

    assert result.status == "PASS", f"Expected PASS, got {result.status}: {result.message}"
    assert page.clicks == 1, f"Expected 1 native click, got {page.clicks}"
    assert page.dispatch_events == 1, \
        f"Expected 1 dispatch_event fallback, got {page.dispatch_events}"
    # Executor should have called time.sleep at least once (0.5s post-click buffer)
    assert any(s == 0.5 for s in sleep_calls), \
        f"Expected time.sleep(0.5) to be called, got: {sleep_calls}"


def test_step_click_new_tab_switches_executor_page():
    """
    When a click opens a new tab (target="_blank" links like footer links),
    the executor should detect the new page and switch self.page to it so
    subsequent assert_url steps see the destination URL.
    """
    original_page = FakePage()
    new_tab        = FakePage()
    new_tab.url    = "https://example.com/terms"

    # After the click, context now has TWO pages
    original_page.context = FakeContext([original_page])

    executor = TestExecutor(original_page, timeout=1000)
    step     = TestStep(action="click", selector="a:has-text('Terms of Service')")

    call_count = [0]

    def pages_side_effect():
        call_count[0] += 1
        # First call (before click): only the original page
        # Second call (after click): original + new tab
        if call_count[0] <= 1:
            return [original_page]
        return [original_page, new_tab]

    original_page.context = MagicMock()
    original_page.context.pages = property(lambda self: pages_side_effect())

    # Since property on MagicMock is tricky, use side_effect on attribute access
    type(original_page.context).pages = property(lambda self: pages_side_effect())

    with patch("agent.executor.time.sleep"):
        result = executor._step_click(step)

    assert result.status == "PASS"
    # After click, executor.page should be the new tab
    assert executor.page is new_tab, \
        "Expected executor.page to switch to the new tab"


def test_step_click_returns_pass_on_same_tab_navigation():
    """
    When a click causes same-tab navigation (React router), executor should
    detect the URL change via wait_for_url and return PASS without needing
    dispatch_event fallback.

    Simulated by making the URL change after the click.
    """
    page     = FakePage()
    executor = TestExecutor(page, timeout=1000)
    step     = TestStep(action="click", selector="a:has-text('Psychics')")

    original_url = page.url

    def click_causes_navigation():
        page.clicks += 1
        page.url = "https://example.com/psychics"   # URL changes on click

    page_locator = FakeLocator(page)
    page_locator.click = click_causes_navigation

    with patch.object(page, "locator", return_value=page_locator), \
         patch("agent.executor.time.sleep"):
        result = executor._step_click(step)

    assert result.status == "PASS"
    assert page.clicks == 1
    # No dispatch_event should be needed since URL changed
    assert page.dispatch_events == 0