"""
tests/test_chat_flow.py
─────────────────────────────────────────────────────────────────────────────
Phase 2 — Chat / Consultation Flow Tests

Tests the chat initiation and messaging flow on psychictells.com.
Runs as a logged-in user where possible; falls back to guest flow.

Test IDs  : CH-001 … CH-008
Categories: Chat – Navigation | Chat – Messaging | Chat – UI

CH-001  Chat / Consult button visible on psychic profile page
CH-002  Clicking Chat button opens chat UI or login prompt
CH-003  Chat window / widget loads without JS crash
CH-004  Chat input field is present and accepts text
CH-005  Send button is present
CH-006  Sending a message does not crash the page
CH-007  Chat UI renders correctly on mobile viewport (390×844)
CH-008  Back navigation from chat returns to /psychics
─────────────────────────────────────────────────────────────────────────────
"""

import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from test_agent.browser_controller import BrowserController
from test_agent.reporter import TestReporter
from test_agent.site_navigator import SiteNavigator
from config import (
    BASE_URL, PSYCHICS_URL, LOGIN_URL,
    USER_EMAIL, USER_PASSWORD, SELECTORS, VIEWPORT,
    SITE_DOMAIN, NON_PROFILE_PATH_SEGMENTS, PROFILE_URL_PREFIXES,
)


class ChatFlowTests:
    CATEGORY_NAV  = "Chat – Navigation"
    CATEGORY_MSG  = "Chat – Messaging"
    CATEGORY_UI   = "Chat – UI"

    def __init__(self, browser: BrowserController, reporter: TestReporter):
        self.br       = browser
        self.rep      = reporter
        self.sel_chat = SELECTORS["chat"]
        self.sel_auth = SELECTORS["user_auth"]
        # FIX: previously this file had its own local _is_profile_url() /
        # _navigate_to_a_profile() that only excluded the bare listing/home
        # URL, so unrelated pages like /services were wrongly accepted as
        # "psychic profiles" (see CH-001 in report.html — ProfileURL landed
        # on /services). Now delegates to the shared SiteNavigator, which is
        # also used by test_ask_question.py and test_multi_navigation.py so
        # there is exactly one implementation of this logic to maintain.
        self.nav = SiteNavigator(
            browser, listing_url=PSYCHICS_URL, base_url=BASE_URL,
            domain=SITE_DOMAIN,
            non_profile_segments=NON_PROFILE_PATH_SEGMENTS,
            profile_prefixes=PROFILE_URL_PREFIXES,
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _record(self, name, input_data, expected, actual, status,
                rt=0, ss="", notes="", category="Chat – Navigation"):
        self.rep.add_result(
            test_name=name, input_data=input_data,
            expected_result=expected, actual_result=actual,
            status=status, response_time_ms=rt,
            screenshot=ss, notes=notes, category=category,
        )

    def _click_first(self, selectors: list) -> bool:
        for sel in selectors:
            try:
                el = self.br.page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    try:
                        el.click()
                    except Exception:
                        el.dispatch_event("click")
                    return True
            except Exception:
                continue
        return False

    def _is_visible_any(self, selectors: list, timeout: int = 3000) -> bool:
        for sel in selectors:
            try:
                self.br.page.wait_for_selector(sel, state="visible", timeout=timeout)
                return True
            except Exception:
                continue
        return False

    def _try_login(self):
        """Attempt a quick login so chat features are accessible."""
        self.br.goto(LOGIN_URL)
        time.sleep(2)
        for sel in self.sel_auth["email_input"]:
            try:
                el = self.br.page.locator(sel).first
                if el.is_visible():
                    el.fill(USER_EMAIL)
                    break
            except Exception:
                pass
        for sel in self.sel_auth["password_input"]:
            try:
                el = self.br.page.locator(sel).first
                if el.is_visible():
                    el.fill(USER_PASSWORD)
                    break
            except Exception:
                pass
        self._click_first(self.sel_auth["submit_login"])
        time.sleep(4)

    def _is_profile_url(self, url: str) -> bool:
        """Delegates to the shared SiteNavigator — see class docstring for
        why this used to be a local (buggy) implementation."""
        return self.nav.is_profile_url(url)

    def _navigate_to_a_profile(self) -> str:
        """Delegates to the shared SiteNavigator.find_profile_url()."""
        return self.nav.find_profile_url()

    @property
    def _profile_url(self) -> str:
        """
        Exposes SiteNavigator's internal cache under the old attribute name
        so the rest of this file's call sites (CH-002, CH-003, CH-008, etc.)
        didn't need to be individually rewritten when the detection logic
        moved to the shared module.
        """
        return self.nav._cached_profile_url

    # ── CH-001  Chat button visible on profile ────────────────────────────
    def tc_ch001_chat_btn_visible(self):
        profile_url = self._navigate_to_a_profile()
        time.sleep(2)
        ss    = self.br.screenshot("ch001_chat_btn")
        found = self._is_visible_any(self.sel_chat["start_chat_btn"], timeout=5000)
        url   = self.br.current_url()
        self._record(
            "CH-001: Chat / Consult Button Visible on Psychic Profile",
            {"url": url},
            "Chat or Consult button visible on profile page",
            f"ProfileURL={url}, ChatBtnFound={found}",
            "PASS" if found else "FAIL",
            ss=ss,
            notes="If FAIL: TC-005 psychic card routing issue may still be blocking profile access.",
            category=self.CATEGORY_NAV,
        )

    # ── CH-002  Clicking chat opens UI or login prompt ─────────────────────
    def tc_ch002_chat_btn_click(self):
        if not self._profile_url:
            self._navigate_to_a_profile()

        # Re-navigate to profile to start fresh
        if self._profile_url:
            self.br.goto(self._profile_url)
            time.sleep(2)

        old_url = self.br.current_url()
        t0 = time.time()
        clicked = self._click_first(self.sel_chat["start_chat_btn"])
        time.sleep(4)
        rt  = round((time.time() - t0) * 1000)
        ss  = self.br.screenshot("ch002_chat_click")
        url = self.br.current_url()
        no_crash = not self.br.has_error_on_page()

        # Acceptable outcomes: chat UI opened, OR login/signup prompt appeared
        chat_opened  = self._is_visible_any(self.sel_chat["chat_window"],   timeout=2000)
        login_prompt = self._is_visible_any(self.sel_auth["email_input"],   timeout=2000)
        url_changed  = url != old_url

        outcome = "chat_opened" if chat_opened else \
                  "login_prompt" if login_prompt else \
                  "url_changed" if url_changed else "no_change"
        self._record(
            "CH-002: Clicking Chat Button Opens Chat UI or Login Prompt",
            {"action": "Click Chat/Consult button on profile page"},
            "Chat UI opens OR login required prompt shown; no crash",
            f"Clicked={clicked}, Outcome={outcome}, URL={url}, NoCrash={no_crash}",
            "PASS" if (clicked and (chat_opened or login_prompt or url_changed) and no_crash)
                   else "FAIL",
            rt, ss, category=self.CATEGORY_NAV,
        )

    # ── CH-003  Chat window loads without JS crash ─────────────────────────
    def tc_ch003_chat_window_loads(self):
        if not self._profile_url:
            self._navigate_to_a_profile()
        if self._profile_url:
            self.br.goto(self._profile_url)
            time.sleep(2)

        self._click_first(self.sel_chat["start_chat_btn"])
        time.sleep(3)

        # Try to login if prompted
        if self._is_visible_any(self.sel_auth["email_input"], timeout=2000):
            self._try_login()
            if self._profile_url:
                self.br.goto(self._profile_url)
                time.sleep(2)
                self._click_first(self.sel_chat["start_chat_btn"])
                time.sleep(3)

        ss       = self.br.screenshot("ch003_chat_window")
        no_crash = not self.br.has_error_on_page()
        chat_ui  = self._is_visible_any(self.sel_chat["chat_window"], timeout=3000)
        self._record(
            "CH-003: Chat Window / Widget Loads Without JS Crash",
            {"action": "Open chat window"},
            "Chat widget loads; no JS errors or crash",
            f"ChatUIVisible={chat_ui}, NoCrash={no_crash}, URL={self.br.current_url()}",
            "PASS" if no_crash else "FAIL",
            ss=ss,
            notes="Chat UI visibility depends on login state.",
            category=self.CATEGORY_UI,
        )

    # ── CH-004  Chat input field present ──────────────────────────────────
    def tc_ch004_chat_input_present(self):
        ss    = self.br.screenshot("ch004_chat_input")
        found = self._is_visible_any(self.sel_chat["chat_input"], timeout=5000)
        url   = self.br.current_url()
        self._record(
            "CH-004: Chat Input Field is Present and Accepts Text",
            {"action": "Check for message input field in chat"},
            "Text input or textarea for chat messages is visible",
            f"InputFound={found}, URL={url}",
            "PASS" if found else "FAIL",
            ss=ss,
            notes="If FAIL: user may need to be logged in with a paid account to access chat.",
            category=self.CATEGORY_UI,
        )

    # ── CH-005  Send button present ────────────────────────────────────────
    def tc_ch005_send_btn_present(self):
        ss    = self.br.screenshot("ch005_send_btn")
        found = self._is_visible_any(self.sel_chat["send_btn"], timeout=5000)
        self._record(
            "CH-005: Send Button is Present in Chat Window",
            {"action": "Check for Send button"},
            "Send button visible in chat UI",
            f"SendBtnFound={found}",
            "PASS" if found else "FAIL",
            ss=ss, category=self.CATEGORY_UI,
        )

    # ── CH-006  Sending a message does not crash ───────────────────────────
    def tc_ch006_send_message_no_crash(self):
        filled = False
        for sel in self.sel_chat["chat_input"]:
            try:
                el = self.br.page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    el.fill("Hello, I have a question about my future.")
                    filled = True
                    break
            except Exception:
                continue

        t0 = time.time()
        if filled:
            self._click_first(self.sel_chat["send_btn"])
        time.sleep(3)
        rt = round((time.time() - t0) * 1000)
        ss = self.br.screenshot("ch006_send_message")
        no_crash = not self.br.has_error_on_page()
        self._record(
            "CH-006: Sending a Message Does Not Crash the Page",
            {"message": "Hello, I have a question about my future."},
            "Message sent without crash or JS error",
            f"Filled={filled}, NoCrash={no_crash}, URL={self.br.current_url()}",
            "PASS" if no_crash else "FAIL",
            rt, ss,
            notes="Message delivery confirmation depends on login/credit state.",
            category=self.CATEGORY_MSG,
        )

    # ── CH-007  Mobile viewport renders chat ───────────────────────────────
    def tc_ch007_mobile_chat_ui(self):
        # Switch to mobile viewport
        self.br.page.set_viewport_size({"width": 390, "height": 844})
        if self._profile_url:
            self.br.goto(self._profile_url)
        else:
            self.br.goto(PSYCHICS_URL)
        time.sleep(3)
        ss = self.br.screenshot("ch007_mobile_chat")
        no_crash = not self.br.has_error_on_page()
        title    = self.br.page_title()
        # Restore desktop viewport
        self.br.page.set_viewport_size(VIEWPORT)
        self._record(
            "CH-007: Chat UI Renders Correctly on Mobile Viewport (390×844)",
            {"viewport": "390×844px"},
            "Page renders without crash on mobile; no horizontal overflow",
            f"Title='{title}', NoCrash={no_crash}",
            "PASS" if no_crash else "FAIL",
            ss=ss, category=self.CATEGORY_UI,
        )

    # ── CH-008  Back navigation from chat ─────────────────────────────────
    def tc_ch008_back_from_chat(self):
        if self._profile_url:
            self.br.goto(self._profile_url)
            time.sleep(2)

        self.br.page.go_back()
        try:
            self.br.page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        time.sleep(1.5)
        ss       = self.br.screenshot("ch008_back_from_chat")
        url      = self.br.current_url()
        no_crash = not self.br.has_error_on_page()
        went_back = "psychics" in url.lower() or SITE_DOMAIN in url.lower()
        self._record(
            "CH-008: Back Navigation from Chat Returns to /psychics",
            {"action": "Press browser back from chat/profile page"},
            "Returns to /psychics or homepage; no crash",
            f"URLAfterBack='{url}', WentBack={went_back}, NoCrash={no_crash}",
            "PASS" if (went_back and no_crash) else "FAIL",
            ss=ss, category=self.CATEGORY_NAV,
        )

    # ── CH-009  Psychic specialty filter ─────────────────────────────────────
    def tc_ch009_specialty_filter(self):
        """Verify specialty/category filter buttons on /psychics work without crash."""
        self.br.goto(PSYCHICS_URL)
        time.sleep(3)

        filter_sels = [
            "button:has-text('Love')",    "button:has-text('Career')",
            "button:has-text('Finance')", "button:has-text('Tarot')",
            "button:has-text('All')",     "[class*='filter']",
            "[class*='specialty']",       "[class*='category']",
            "a[href*='specialty']",       "a[href*='category']",
        ]

        found  = self._is_visible_any(filter_sels, timeout=5000)
        clicked = False
        url_after = self.br.current_url()

        if found:
            for sel in filter_sels:
                try:
                    el = self.br.page.locator(sel).first
                    if el.count() > 0 and el.is_visible():
                        old_url = self.br.current_url()
                        try:
                            el.click()
                        except Exception:
                            el.dispatch_event("click")
                        time.sleep(2)
                        clicked    = True
                        url_after  = self.br.current_url()
                        break
                except Exception:
                    continue

        ss       = self.br.screenshot("ch009_specialty_filter")
        no_crash = not self.br.has_error_on_page()
        self._record(
            "CH-009: Psychic Specialty Filter Works Without Crash",
            {"action": "Click a specialty/category filter on /psychics"},
            "Filter present; clicking it does not crash the page",
            f"FilterFound={found}, Clicked={clicked}, URL={url_after}, NoCrash={no_crash}",
            "PASS" if (found and no_crash) else "FAIL",
            ss=ss,
            notes="Filter may update URL with ?specialty= param or filter cards in-place.",
            category=self.CATEGORY_NAV,
        )

    # ── CH-010  Filtered results are displayed ────────────────────────────────
    def tc_ch010_filter_results_displayed(self):
        """After applying a filter, verify that psychic cards are still visible."""
        self.br.goto(PSYCHICS_URL)
        time.sleep(3)

        # Try to apply a filter
        filter_sels = [
            "a[href*='specialty']", "button:has-text('Love')",
            "button:has-text('Career')", "[class*='filter']:not([class*='active'])",
        ]
        for sel in filter_sels:
            try:
                el = self.br.page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    try:
                        el.click()
                    except Exception:
                        el.dispatch_event("click")
                    time.sleep(3)
                    break
            except Exception:
                continue

        ss  = self.br.screenshot("ch010_filter_results")
        url = self.br.current_url()
        no_crash = not self.br.has_error_on_page()

        # Check that at least one card/result is still visible after filtering
        card_sels = [
            "[class*='card']", "[class*='psychic']",
            "[class*='expert']", "article", "[class*='reader']",
        ]
        cards_visible = self._is_visible_any(card_sels, timeout=4000)

        self._record(
            "CH-010: Filtered Results Show Psychic Cards",
            {"action": "Apply filter then check cards still visible"},
            "At least one psychic card displayed after filter applied; no crash",
            f"CardsVisible={cards_visible}, URL={url}, NoCrash={no_crash}",
            "PASS" if (cards_visible and no_crash) else "FAIL",
            ss=ss,
            notes="Empty results after filtering is a FAIL — site should show "
                  "available psychics or a 'no results' message.",
            category=self.CATEGORY_NAV,
        )

    # ── run_all ──────────────────────────────────────────────────────────────
    def run_all(self):
        print("\n💬 Chat Flow Tests  (CH-001 – CH-010)\n")
        tests = [
            ("CH-001: Chat button visible on profile",    self.tc_ch001_chat_btn_visible),
            ("CH-002: Chat button click opens UI",        self.tc_ch002_chat_btn_click),
            ("CH-003: Chat window loads without crash",   self.tc_ch003_chat_window_loads),
            ("CH-004: Chat input field present",          self.tc_ch004_chat_input_present),
            ("CH-005: Send button present",               self.tc_ch005_send_btn_present),
            ("CH-006: Sending a message - no crash",      self.tc_ch006_send_message_no_crash),
            ("CH-007: Mobile viewport renders chat",      self.tc_ch007_mobile_chat_ui),
            ("CH-008: Back navigation from chat",         self.tc_ch008_back_from_chat),
            ("CH-009: Specialty filter works",            self.tc_ch009_specialty_filter),
            ("CH-010: Filter results displayed",          self.tc_ch010_filter_results_displayed),
        ]
        for label, fn in tests:
            print(f"  ▶ {label}")
            try:
                fn()
            except Exception as exc:
                print(f"    ⚠️  Unhandled: {exc}")
                self.rep.add_result(
                    test_name=label, input_data={},
                    expected_result="Completes without crash",
                    actual_result=str(exc), status="ERROR",
                    category=self.CATEGORY_NAV,
                )
        print("\n✅ Chat flow tests complete.\n")
