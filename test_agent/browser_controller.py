import logging
"""
browser_controller.py
Thin Playwright wrapper: navigation, form interaction, screenshots,
targeted click operations (by position + click count).
"""

import os
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    HEADLESS, SLOW_MO, TIMEOUT, VIEWPORT,
    SCREENSHOTS_DIR, BASE_URL,
)


class BrowserController:
    """Wraps a Playwright browser session with helper utilities."""

    def __init__(self):
        self._pw                      = None
        self.browser: Browser         = None
        self.context: BrowserContext  = None
        self.page: Page               = None
        Path(SCREENSHOTS_DIR).mkdir(parents=True, exist_ok=True)

    # ── Lifecycle ───────────────────────────────────────────────────────────────
    def start(self):
        self._pw     = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO)
        self.context = self.browser.new_context(viewport=VIEWPORT)
        self.page    = self.context.new_page()
        self.page.set_default_timeout(TIMEOUT)
        return self

    def stop(self):
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass

    def __enter__(self):  return self.start()
    def __exit__(self, *_): self.stop()

    # ── Navigation ──────────────────────────────────────────────────────────────
    def goto(self, url: str, wait_until: str = "domcontentloaded") -> dict:
        """Navigate to URL; return timing + status info."""
        t0 = time.time()
        try:
            resp       = self.page.goto(url, wait_until=wait_until)
            elapsed_ms = round((time.time() - t0) * 1000)
            return {
                "ok":         resp.ok if resp else False,
                "status":     resp.status if resp else 0,
                "elapsed_ms": elapsed_ms,
                "url":        self.page.url,
            }
        except Exception as exc:
            return {"ok": False, "status": 0, "elapsed_ms": 0,
                    "error": str(exc), "url": url}

    def click(self, selector: str, timeout: int | None = None):
        self.page.click(selector, timeout=timeout or TIMEOUT)

    def click_text(self, text: str):
        self.page.get_by_text(text, exact=False).first.click()

    def fill(self, selector: str, value: str):
        self.page.fill(selector, value)

    def select_option(self, selector: str, value: str):
        try:
            self.page.select_option(selector, label=value)
        except Exception:
            try:
                self.page.select_option(selector, value=value)
            except Exception:
                pass  # dropdown may not exist — caller handles

    # ── Click at position (core new capability) ─────────────────────────────────
    def get_element_bbox(self, selector: str) -> dict | None:
        """Return element bounding box {x, y, width, height} or None."""
        try:
            el   = self.page.locator(selector).first
            el.scroll_into_view_if_needed()
            time.sleep(0.2)
            return el.bounding_box()
        except Exception:
            return None

    def click_at_position(
        self,
        selector: str,
        rel_pos:     dict,
        click_count: int = 1,
    ) -> dict:
        """
        Click an element at a position relative to its top-left corner.

        Args:
            selector:    CSS / Playwright selector
            rel_pos:     {"x": px_from_left, "y": px_from_top}
            click_count: 1 = single, 2 = double, 3 = triple

        Returns dict with: success, abs_x, abs_y, bbox, warning (if any).
        """
        try:
            el = self.page.locator(selector).first
            el.scroll_into_view_if_needed()
            time.sleep(0.3)  # let scroll settle

            bbox = el.bounding_box()
            if not bbox:
                return {"success": False, "error": "Element has no bounding box"}

            abs_x = bbox["x"] + rel_pos["x"]
            abs_y = bbox["y"] + rel_pos["y"]

            warning    = None
            url_before = self.page.url

            # ── Step 1: raw mouse click at absolute screen coordinates ─────────
            # Fires a real pointer event. Works for plain links; may miss React
            # onClick handlers on rounded-corner buttons.
            try:
                self.page.mouse.click(abs_x, abs_y, click_count=click_count)
            except Exception as clk_exc:
                err_msg = str(clk_exc).lower()
                is_nav_exc = any(k in err_msg for k in (
                    "navigation", "frame was detached", "target closed",
                    "execution context was destroyed",
                ))
                if is_nav_exc or click_count > 1:
                    warning = str(clk_exc)
                else:
                    raise

            # ── Step 2: JS dispatch_event fallback (single clicks only) ────────
            # On React/Next.js sites the raw mouse click fires at coordinates but
            # the JS onClick handler may not receive it — particularly at rounded
            # corners where a wrapper element intercepts the pointer event.
            # If the URL has not changed within 2 s, fire dispatch_event("click")
            # directly on the element, bypassing coordinate hit-testing entirely
            # and guaranteeing React's synthetic event system receives the click.
            if click_count == 1:
                deadline = time.time() + 2.0
                while time.time() < deadline:
                    if self.page.url != url_before:
                        break
                    time.sleep(0.15)

                if self.page.url == url_before:
                    try:
                        el = self.page.locator(selector).first
                        el.dispatch_event("click")
                        warning = (warning or "") + " [JS fallback click used]"
                    except Exception as fb_exc:
                        warning = (warning or "") + f" [JS fallback failed: {fb_exc}]"

            return {
                "success": True,
                "abs_x":   round(abs_x),
                "abs_y":   round(abs_y),
                "bbox":    {k: round(v) for k, v in bbox.items()},
                "rel_pos": rel_pos,
                "warning": warning,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def find_ask_button_selector(self) -> str | None:
        """Find and return an active 'Ask a Free Question' button selector."""
        from config import SELECTORS
        for sel in SELECTORS["ask_btn_fallbacks"]:
            try:
                loc = self.page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    return sel
            except Exception:
                continue

        # Last resort: text scan
        try:
            buttons = self.page.query_selector_all("button, a")
            for btn in buttons:
                txt = btn.inner_text().strip().lower()
                if "ask" in txt and btn.is_visible():
                    # Build a selector by index is tricky; return None here
                    # and let the caller use the fallback list.
                    break
        except Exception:
            pass
        return None

    # ── Assertions ──────────────────────────────────────────────────────────────
    def is_visible(self, selector: str, timeout: int = 3000) -> bool:
        try:
            self.page.wait_for_selector(selector, state="visible", timeout=timeout)
            return True
        except Exception:
            return False

    def get_text(self, selector: str) -> str:
        try:
            return self.page.inner_text(selector)
        except Exception:
            return ""

    def page_title(self) -> str:
        return self.page.title()

    def current_url(self) -> str:
        return self.page.url

    def has_error_on_page(self) -> bool:
        """Detect JS console errors or crash pages via the page title."""
        try:
            title = self.page.title().lower()
            return any(k in title for k in ["error", "500", "404", "not found", "oops"])
        except Exception:
            return True

    def wait_for_url_change(self, old_url: str, timeout_s: float = 5.0) -> str:
        """Block until URL changes from old_url; return new URL."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            cur = self.current_url()
            if cur != old_url:
                return cur
            time.sleep(0.3)
        return self.current_url()

    # ── Screenshots ─────────────────────────────────────────────────────────────
    def screenshot(self, name: str) -> str:
        clean = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        ts    = int(time.time())
        path  = os.path.join(SCREENSHOTS_DIR, f"{clean}_{ts}.png")
        try:
            self.page.screenshot(path=path, full_page=True)
        except Exception:
            path = ""
        return path

    # ── Form helpers ─────────────────────────────────────────────────────────────
    def find_and_fill_textarea(self, text: str) -> bool:
        """
        Robust question-field detection and fill.
        """

        candidates = [
            "textarea",
            "textarea[name]",
            "textarea[placeholder]",

            "input[type='text']",
            "input[type='search']",
            "input[name]",
            "input[placeholder]",

            "input[name*='question' i]",
            "input[placeholder*='question' i]",

            "[contenteditable='true']",
        ]

        for sel in candidates:
            try:
                el = self.page.locator(sel).first

                if el.count() > 0 and el.is_visible():
                    el.scroll_into_view_if_needed()

                    try:
                        el.click()
                    except:
                        pass

                    el.fill(text)

                    value = el.input_value()

                    if value and value.strip():
                        print(
                            f" Filled field using selector: {sel}"
                        )
                        return True

            except Exception as e:
                logging.debug(f" Fill failed for {sel}: {e}")
                continue

        logging.debug(" Could not find fillable question field")
        return False

    def find_and_click_submit(self) -> bool:
        """Robust submit button detection and click."""
        candidates = [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Submit')",
            "button:has-text('Send')",
            "button:has-text('Ask')",
            "button:has-text('Question')",
            "button:has-text('Continue')",
        ]
        for sel in candidates:
            try:
                btn = self.page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn.scroll_into_view_if_needed()
                    btn.click(force=True)
                    return True
            except Exception:
                continue
        return False

    def wait_for_response(self, timeout_ms: int = 15000) -> dict:
        """Poll for success/error state or URL change after form submit."""
        start_url = self.current_url()

        success_sels = [
            "text=thank you",
            "text=submitted",
            "text=received",
            "text=success",
            "[class*='success']",
            "[class*='thank']",
        ]
        error_sels = [
            "[class*='error']",
            "[class*='invalid']",
            ".invalid-feedback",
            ".error",
        ]

        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            for sel in success_sels:
                try:
                    if self.page.locator(sel).count() > 0:
                        return {"type": "success", "selector": sel}
                except Exception:
                    pass

            for sel in error_sels:
                try:
                    if self.page.locator(sel).count() > 0:
                        return {"type": "validation_error", "selector": sel}
                except Exception:
                    pass

            if self.current_url() != start_url:
                return {"type": "redirect", "url": self.current_url()}

            time.sleep(0.5)

        return {"type": "unknown", "url": self.current_url()}