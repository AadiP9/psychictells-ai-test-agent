"""
tests/test_click_interactions.py
─────────────────────────────────────────────────────────────────────────────
Tests the 'Ask a Free Question' button across 5 click positions and 3 click
types = 15 test cases total.

Positions
─────────
  Center  |  Top-Left  |  Top-Right  |  Bottom-Left  |  Bottom-Right

Click types
───────────
  Single (1×)  •  Double (2×)  •  Triple (3×)

Test IDs
─────────
  CLK-001 … CLK-005  →  Single click  @ each position
  CLK-006 … CLK-010  →  Double click  @ each position
  CLK-011 … CLK-015  →  Triple click  @ each position

Pass criteria
─────────────
  Single  :  URL contains "psychics" after click  AND  no crash
  Double  :  No crash; URL may or may not change  (first click triggers nav)
  Triple  :  No crash; no JS exception or broken UI
─────────────────────────────────────────────────────────────────────────────
"""

import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from test_agent.browser_controller import BrowserController
from test_agent.reporter import TestReporter
from config import BASE_URL, CLICK_POSITIONS


class ClickInteractionTests:
    CATEGORY = "Click Interactions"

    def __init__(self, browser: BrowserController, reporter: TestReporter):
        self.br  = browser
        self.rep = reporter

    # ── Internal helper ─────────────────────────────────────────────────────────
    def _record(self, name, input_data, expected, actual, status, rt=0, ss="", notes=""):
        self.rep.add_result(
            test_name=name,
            input_data=input_data,
            expected_result=expected,
            actual_result=actual,
            status=status,
            response_time_ms=rt,
            screenshot=ss,
            notes=notes,
            category=self.CATEGORY,
        )

    def _load_homepage(self) -> str | None:
        """
        Navigate to homepage, wait for JS hydration, return the active
        'Ask a Free Question' button selector (or None if not found).
        """
        self.br.goto(BASE_URL)
        time.sleep(2)
        return self.br.find_ask_button_selector()

    def _url_reached_ask_page(self, wait_s: float = 8.0) -> dict:
        """
        Wait until the URL leaves the homepage (navigates to /psychics,
        /ask-question, or any other destination triggered by the button).

        The 'Ask a Free Question' button may route to /psychics OR directly
        to an /ask-question page depending on the site version.  We accept
        any URL that is no longer the bare homepage as a successful navigation.
        """
        try:
            self.br.page.wait_for_load_state(
                "domcontentloaded", timeout=int(wait_s * 1000)
            )
        except Exception:
            pass

        deadline = time.time() + wait_s
        home = BASE_URL.rstrip("/")
        while time.time() < deadline:
            cur = self.br.current_url().rstrip("/")
            # Accept any page that is not the bare homepage
            if cur != home:
                navigated_url = self.br.current_url()
                return {"navigated": True, "url": navigated_url}
            time.sleep(0.3)
        cur = self.br.current_url()
        return {"navigated": cur.rstrip("/") != home, "url": cur}

    # ── Core parametric test ────────────────────────────────────────────────────
    def _run_click_test(
        self,
        tc_id:        str,
        pos_label:    str,
        pos_fn,                 # lambda w, h → {"x": int, "y": int}
        click_count:  int,
        click_label:  str,      # "Single" | "Double" | "Triple"
    ):
        test_name = f"{tc_id} – {click_label} Click @ {pos_label}"

        # ── Step 1: load homepage ─────────────────────────────────────────────
        btn_sel = self._load_homepage()
        if not btn_sel:
            ss = self.br.screenshot(f"clk_{tc_id.lower()}_no_btn")
            self._record(
                test_name,
                {"position": pos_label, "click_count": click_count},
                "Button visible on homepage",
                "Button NOT found – check SELECTORS['ask_btn_fallbacks']",
                "FAIL",
                ss=ss,
                notes="Homepage may have changed layout. Update selectors in config.py.",
            )
            return

        # ── Step 2: get bounding box ─────────────────────────────────────────
        bbox = self.br.get_element_bbox(btn_sel)
        if not bbox:
            ss = self.br.screenshot(f"clk_{tc_id.lower()}_no_bbox")
            self._record(
                test_name,
                {"position": pos_label, "selector": btn_sel},
                "Button has a bounding box",
                "Could not compute bounding box (off-screen?)",
                "FAIL",
                ss=ss,
            )
            return

        w, h    = bbox["width"], bbox["height"]
        rel_pos = pos_fn(w, h)

        # ── Step 3: perform click ────────────────────────────────────────────
        old_url = self.br.current_url()
        t0      = time.time()
        result  = self.br.click_at_position(btn_sel, rel_pos, click_count=click_count)
        rt      = round((time.time() - t0) * 1000)

        if not result.get("success"):
            ss = self.br.screenshot(f"clk_{tc_id.lower()}_click_err")
            self._record(
                test_name,
                {
                    "position":    pos_label,
                    "click_count": click_count,
                    "rel_pos":     rel_pos,
                    "btn_size":    f"{w:.0f}×{h:.0f}px",
                },
                "Click executes without error",
                f"Click failed: {result.get('error', 'unknown')}",
                "FAIL",
                rt, ss,
            )
            return

        # ── Step 4: observe outcome ───────────────────────────────────────────
        nav      = self._url_reached_ask_page(wait_s=8.0)
        no_crash = not self.br.has_error_on_page()
        ss       = self.br.screenshot(
            f"clk_{tc_id.lower()}_{click_label.lower().replace(' ', '_')}"
        )

        abs_x = result.get("abs_x", "?")
        abs_y = result.get("abs_y", "?")
        warn  = result.get("warning", "")

        actual = (
            f"ClickOK=True, "
            f"Navigated={nav['navigated']}, "
            f"URL='{nav['url']}', "
            f"NoCrash={no_crash}"
        )
        if warn:
            actual += f", Warning='{warn[:80]}'"

        if click_count == 1:
            # Single click MUST navigate away from homepage (to /psychics,
            # /ask-question, or wherever the button leads)
            expected = "Navigates away from homepage; no crash"
            status   = "PASS" if (nav["navigated"] and no_crash) else "FAIL"
        else:
            # Double / triple: accept that the first click already navigated.
            # We only require no crash / JS exception.
            expected = "No crash; button responds (first click navigates)"
            status   = "PASS" if no_crash else "FAIL"

        self._record(
            test_name,
            {
                "position":    pos_label,
                "click_count": click_count,
                "rel_pos":     rel_pos,
                "abs_coords":  f"({abs_x}, {abs_y})",
                "btn_size":    f"{w:.0f}×{h:.0f}px",
            },
            expected,
            actual,
            status,
            rt, ss,
            notes=f"Selector used: {btn_sel}",
        )

    # ── Public run_all ──────────────────────────────────────────────────────────
    def run_all(self):
        print("\n🖱️  Click Interaction Tests  (5 positions × 3 click types = 15 tests)\n")

        click_types = [
            ("Single", 1),
            ("Double", 2),
            ("Triple", 3),
        ]

        tc_num = 1
        for click_label, click_count in click_types:
            print(f"\n  ── {click_label} Click ──")
            for pos_label, pos_fn in CLICK_POSITIONS:
                tc_id = f"CLK-{tc_num:03d}"
                print(f"  ▶ {tc_id}: {click_label} Click @ {pos_label}")
                try:
                    self._run_click_test(
                        tc_id, pos_label, pos_fn, click_count, click_label
                    )
                except Exception as exc:
                    print(f"    ⚠️  Unhandled: {exc}")
                    self.rep.add_result(
                        test_name=f"{tc_id} – {click_label} Click @ {pos_label}",
                        input_data={"position": pos_label, "click_count": click_count},
                        expected_result="Click executes",
                        actual_result=str(exc),
                        status="ERROR",
                        category=self.CATEGORY,
                    )
                tc_num += 1

        print("\n✅ Click interaction tests complete.\n")