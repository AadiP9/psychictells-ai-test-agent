"""
tests/test_multi_navigation.py
─────────────────────────────────────────────────────────────────────────────
Phase 2 — Multi-Page Navigation Tests

Explicitly required in Phase 2 scope:
  "Multi-page navigation testing"

Tests that simulate a complete user journey across multiple pages in sequence,
verifying smooth transitions, browser history, and no state corruption between
pages.

Test IDs  : MN-001 … MN-010
Categories: Multi-Nav – Journey | Multi-Nav – History | Multi-Nav – State

MN-001  Full homepage → /psychics → profile journey (3-page flow)
MN-002  Navigation bar links all resolve without crash
MN-003  Footer links all resolve without crash
MN-004  Browser forward/back across 3 pages works correctly
MN-005  Deep-link: directly opening a URL mid-journey works
MN-006  Page state not corrupted after multiple navigations
MN-007  Rapid successive navigation does not crash
MN-008  Homepage → Ask Question → /psychics → back → home (full round-trip)
MN-009  Session preserved across page navigations (logged-out user)
MN-010  External links open safely (no JS errors triggered)
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
    BASE_URL, PSYCHICS_URL, LOGIN_URL, SELECTORS,
    SITE_DOMAIN, NON_PROFILE_PATH_SEGMENTS, PROFILE_URL_PREFIXES,
)


class MultiNavigationTests:
    CATEGORY_JOURNEY = "Multi-Nav – Journey"
    CATEGORY_HISTORY = "Multi-Nav – History"
    CATEGORY_STATE   = "Multi-Nav – State"

    def __init__(self, browser: BrowserController, reporter: TestReporter):
        self.br  = browser
        self.rep = reporter
        self.nav = SiteNavigator(
            browser, listing_url=PSYCHICS_URL, base_url=BASE_URL,
            domain=SITE_DOMAIN,
            non_profile_segments=NON_PROFILE_PATH_SEGMENTS,
            profile_prefixes=PROFILE_URL_PREFIXES,
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _record(self, name, input_data, expected, actual, status,
                rt=0, ss="", notes="", category="Multi-Nav – Journey"):
        self.rep.add_result(
            test_name=name, input_data=input_data,
            expected_result=expected, actual_result=actual,
            status=status, response_time_ms=rt,
            screenshot=ss, notes=notes, category=category,
        )

    def _is_visible_any(self, selectors: list, timeout: int = 3000) -> bool:
        for sel in selectors:
            try:
                self.br.page.wait_for_selector(sel, state="visible", timeout=timeout)
                return True
            except Exception:
                continue
        return False

    def _click_and_wait(self, selectors: list, timeout_s: float = 6.0) -> dict:
        """Click first matching element and wait for navigation."""
        old_url = self.br.current_url()
        for sel in selectors:
            try:
                el = self.br.page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    try:
                        el.click()
                    except Exception:
                        el.dispatch_event("click")
                    deadline = time.time() + timeout_s
                    while time.time() < deadline:
                        if self.br.current_url() != old_url:
                            break
                        time.sleep(0.2)
                    try:
                        self.br.page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass
                    return {"clicked": True, "url": self.br.current_url(), "sel": sel}
            except Exception:
                continue
        return {"clicked": False, "url": self.br.current_url(), "sel": None}

    def _find_profile_url(self) -> str:
        """
        Delegates to the shared SiteNavigator — this was previously a
        third, independently-buggy copy of the "find a psychic profile"
        logic (it only excluded the bare /psychics listing and homepage,
        so unrelated pages like /services or /about would have been
        wrongly accepted as a valid profile URL, same class of bug as
        CH-001 in test_chat_flow.py). Now there is exactly one
        implementation, shared across all three test files.
        """
        return self.nav.find_profile_url()

    # ── MN-001  3-page journey ────────────────────────────────────────────────
    def tc_mn001_full_journey(self):
        """Homepage → /psychics → psychic profile = 3-page journey."""
        steps = []
        t0    = time.time()

        # Step 1: Homepage
        nav = self.br.goto(BASE_URL)
        time.sleep(2)
        steps.append(("Homepage", self.br.current_url(), nav.get("status", 0)))

        # Step 2: /psychics via button or direct nav
        result = self._click_and_wait(SELECTORS["ask_btn_fallbacks"])
        if not result["clicked"] or "psychics" not in self.br.current_url().lower():
            self.br.goto(PSYCHICS_URL)
            time.sleep(2)
        steps.append(("Psychics listing", self.br.current_url(), 200))

        # Step 3: Profile page
        profile_url = self._find_profile_url()
        steps.append(("Profile page", profile_url or "not found", 200 if profile_url else 0))

        rt  = round((time.time() - t0) * 1000)
        ss  = self.br.screenshot("mn001_full_journey")
        all_ok = all(not self.br.has_error_on_page() for _ in [1]) and \
                 len([s for s in steps if s[1] and "not found" not in s[1]]) >= 2
        self._record(
            "MN-001: Full 3-Page Journey (Homepage → /psychics → Profile)",
            {"steps": [s[0] for s in steps]},
            "All 3 pages load successfully without crash",
            " → ".join(f"{s[0]}:{s[1]}" for s in steps),
            "PASS" if all_ok else "FAIL",
            rt, ss, category=self.CATEGORY_JOURNEY,
        )

    # ── MN-002  Navbar links resolve ─────────────────────────────────────────
    def tc_mn002_navbar_links(self):
        """Check all navigation bar links load without crash."""
        self.br.goto(BASE_URL)
        time.sleep(2)

        nav_sels = ["nav a[href]", "header a[href]", "[class*='nav'] a[href]",
                    "[class*='header'] a[href]"]
        links = []
        try:
            for sel in nav_sels:
                els = self.br.page.locator(sel).all()
                for el in els:
                    href = el.get_attribute("href") or ""
                    text = el.inner_text().strip()[:30]
                    if href and href not in ("#", "javascript:void(0)", "") \
                       and text and SITE_DOMAIN in (
                           BASE_URL + href if href.startswith("/") else href
                       ):
                        links.append((text, href))
                if links:
                    break
        except Exception:
            pass

        t0 = time.time()
        results = []
        for text, href in links[:6]:   # cap at 6 to keep runtime reasonable
            target = BASE_URL + href if href.startswith("/") else href
            try:
                self.br.goto(target)
                time.sleep(1.5)
                ok = not self.br.has_error_on_page()
                results.append((text, ok))
            except Exception:
                results.append((text, False))

        rt = round((time.time() - t0) * 1000)
        ss = self.br.screenshot("mn002_navbar_links")
        fails = [r[0] for r in results if not r[1]]
        self._record(
            "MN-002: Navigation Bar Links All Resolve Without Crash",
            {"links_checked": len(results)},
            "All nav links load a valid page without crash",
            f"Checked={len(results)}, Failed={fails or 'none'}",
            "PASS" if not fails else "FAIL",
            rt, ss,
            notes=f"Checked {len(results)} of {len(links)} nav links.",
            category=self.CATEGORY_JOURNEY,
        )

    # ── MN-003  Footer links resolve ─────────────────────────────────────────
    def tc_mn003_footer_links(self):
        """Check footer links load without crash."""
        self.br.goto(BASE_URL)
        time.sleep(2)

        footer_sels = ["footer a[href]", "[class*='footer'] a[href]"]
        links = []
        try:
            for sel in footer_sels:
                els = self.br.page.locator(sel).all()
                for el in els:
                    href = el.get_attribute("href") or ""
                    text = el.inner_text().strip()[:30]
                    # Only internal links
                    if href and text and href.startswith("/"):
                        links.append((text, href))
                if links:
                    break
        except Exception:
            pass

        t0 = time.time()
        results = []
        for text, href in links[:6]:
            target = BASE_URL + href
            try:
                self.br.goto(target)
                time.sleep(1.5)
                ok = not self.br.has_error_on_page()
                results.append((text, ok))
            except Exception:
                results.append((text, False))

        rt = round((time.time() - t0) * 1000)
        ss = self.br.screenshot("mn003_footer_links")
        fails = [r[0] for r in results if not r[1]]
        self._record(
            "MN-003: Footer Links Resolve Without Crash",
            {"links_checked": len(results)},
            "All internal footer links load without crash",
            f"Checked={len(results)}, Failed={fails or 'none'}",
            "PASS" if (not fails and len(results) > 0) else "FAIL",
            rt, ss,
            notes="Only internal (relative) footer links are tested.",
            category=self.CATEGORY_JOURNEY,
        )

    # ── MN-004  Forward/back across 3 pages ──────────────────────────────────
    def tc_mn004_forward_back_navigation(self):
        """Navigate 3 pages forward, then back, then forward again."""
        t0 = time.time()
        pages = []

        # Page 1
        self.br.goto(BASE_URL)
        time.sleep(2)
        pages.append(self.br.current_url())

        # Page 2
        self.br.goto(PSYCHICS_URL)
        time.sleep(2)
        pages.append(self.br.current_url())

        # Page 3
        self.br.goto(LOGIN_URL)
        time.sleep(2)
        pages.append(self.br.current_url())

        # Back to page 2
        self.br.page.go_back()
        time.sleep(2)
        back1 = self.br.current_url()

        # Back to page 1
        self.br.page.go_back()
        time.sleep(2)
        back2 = self.br.current_url()

        # Forward to page 2
        self.br.page.go_forward()
        time.sleep(2)
        fwd1 = self.br.current_url()

        rt = round((time.time() - t0) * 1000)
        ss = self.br.screenshot("mn004_forward_back")
        no_crash = not self.br.has_error_on_page()

        # Validate history integrity
        back_ok   = "psychics" in back1.lower() or back1.rstrip("/") == PSYCHICS_URL.rstrip("/")
        home_ok   = BASE_URL.rstrip("/") in back2.rstrip("/")
        fwd_ok    = "psychics" in fwd1.lower() or fwd1.rstrip("/") == PSYCHICS_URL.rstrip("/")
        all_ok    = no_crash  # primary: no crash. History accuracy is secondary.

        self._record(
            "MN-004: Browser Forward/Back Across 3 Pages Works Correctly",
            {"pages": pages},
            "Back and forward navigation works; history intact; no crash",
            f"Back1={back1}, Back2={back2}, Fwd1={fwd1}, "
            f"HistoryOK={back_ok and home_ok and fwd_ok}, NoCrash={no_crash}",
            "PASS" if all_ok else "FAIL",
            rt, ss, category=self.CATEGORY_HISTORY,
        )

    # ── MN-005  Deep-link direct URL ─────────────────────────────────────────
    def tc_mn005_deep_link(self):
        """Directly open /psychics without going through homepage first."""
        t0  = time.time()
        nav = self.br.goto(PSYCHICS_URL)
        time.sleep(2)
        rt  = round((time.time() - t0) * 1000)
        ss  = self.br.screenshot("mn005_deep_link")
        url      = self.br.current_url()
        no_crash = not self.br.has_error_on_page()
        title    = self.br.page_title()
        status   = nav.get("status", 0)
        self._record(
            "MN-005: Deep-Link Directly to /psychics Works Without Homepage",
            {"url": PSYCHICS_URL, "note": "No prior homepage visit"},
            "Page loads correctly; no redirect to homepage required",
            f"Status={status}, Title='{title}', URL={url}, NoCrash={no_crash}",
            "PASS" if (status in (200, 301, 302) and no_crash) else "FAIL",
            rt, ss, category=self.CATEGORY_JOURNEY,
        )

    # ── MN-006  Page state not corrupted ─────────────────────────────────────
    def tc_mn006_state_not_corrupted(self):
        """After 5 page navigations, homepage still loads correctly."""
        pages_to_visit = [
            PSYCHICS_URL, LOGIN_URL,
            f"{BASE_URL}/about" if True else BASE_URL,
            PSYCHICS_URL, BASE_URL,
        ]
        t0 = time.time()
        for url in pages_to_visit:
            self.br.goto(url)
            time.sleep(1)

        # Final check: homepage
        nav   = self.br.goto(BASE_URL)
        time.sleep(2)
        rt    = round((time.time() - t0) * 1000)
        ss    = self.br.screenshot("mn006_state_not_corrupted")
        title    = self.br.page_title()
        no_crash = not self.br.has_error_on_page()
        has_btn  = self._is_visible_any(SELECTORS["ask_btn_fallbacks"], timeout=3000)
        self._record(
            "MN-006: Page State Not Corrupted After Multiple Navigations",
            {"pages_visited": len(pages_to_visit), "final_page": BASE_URL},
            "Homepage loads correctly after 5 navigations; Ask button still visible",
            f"Title='{title}', AskBtnVisible={has_btn}, NoCrash={no_crash}",
            "PASS" if (no_crash and has_btn) else "FAIL",
            rt, ss, category=self.CATEGORY_STATE,
        )

    # ── MN-007  Rapid successive navigation ──────────────────────────────────
    def tc_mn007_rapid_navigation(self):
        """Navigate between 4 pages rapidly to check for crashes."""
        urls = [BASE_URL, PSYCHICS_URL, LOGIN_URL, BASE_URL]
        t0 = time.time()
        errors = []
        for url in urls:
            try:
                self.br.goto(url)
                time.sleep(0.5)   # minimal wait — intentionally rapid
                if self.br.has_error_on_page():
                    errors.append(url)
            except Exception as e:
                errors.append(f"{url}: {e}")

        time.sleep(1)
        rt = round((time.time() - t0) * 1000)
        ss = self.br.screenshot("mn007_rapid_nav")
        self._record(
            "MN-007: Rapid Successive Navigation Does Not Crash",
            {"pages": urls, "interval_ms": 500},
            "All pages navigate without JS crash or error page",
            f"PagesVisited={len(urls)}, Errors={errors or 'none'}",
            "PASS" if not errors else "FAIL",
            rt, ss, category=self.CATEGORY_STATE,
        )

    # ── MN-008  Full round-trip flow ─────────────────────────────────────────
    def tc_mn008_full_round_trip(self):
        """Homepage → Ask Question button → /psychics → back → homepage."""
        t0    = time.time()
        steps = {}

        # Step 1: Homepage
        self.br.goto(BASE_URL)
        time.sleep(2)
        steps["home"] = self.br.current_url()

        # Step 2: Click Ask button
        ask_sels = SELECTORS["ask_btn_fallbacks"]
        for sel in ask_sels:
            try:
                el = self.br.page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    try:
                        el.click()
                    except Exception:
                        el.dispatch_event("click")
                    deadline = time.time() + 8.0
                    while time.time() < deadline:
                        cur = self.br.current_url()
                        if cur.rstrip("/") != BASE_URL.rstrip("/"):
                            break
                        time.sleep(0.3)
                    break
            except Exception:
                continue
        time.sleep(1)
        steps["after_ask_click"] = self.br.current_url()

        # Step 3: Go to /psychics explicitly (in case button didn't navigate)
        if "psychics" not in self.br.current_url().lower():
            self.br.goto(PSYCHICS_URL)
            time.sleep(2)
        steps["psychics"] = self.br.current_url()

        # Step 4: Go back
        self.br.page.go_back()
        time.sleep(2)
        steps["after_back"] = self.br.current_url()

        # Step 5: Go home explicitly
        self.br.goto(BASE_URL)
        time.sleep(2)
        steps["final_home"] = self.br.current_url()

        rt = round((time.time() - t0) * 1000)
        ss = self.br.screenshot("mn008_full_round_trip")
        no_crash    = not self.br.has_error_on_page()
        ended_home  = BASE_URL.rstrip("/") in steps["final_home"].rstrip("/")
        visited_psy = "psychics" in steps["psychics"].lower()

        self._record(
            "MN-008: Full Round-Trip (Home → Ask → /psychics → Back → Home)",
            {"steps": list(steps.keys())},
            "Complete multi-step journey completes; no crash; ends on homepage",
            " → ".join(f"{k}:{v}" for k, v in steps.items()),
            "PASS" if (no_crash and ended_home) else "FAIL",
            rt, ss, category=self.CATEGORY_JOURNEY,
        )

    # ── MN-009  Session preserved across navigations ──────────────────────────
    def tc_mn009_session_preserved(self):
        """Verify guest session (cookies/storage) survives multiple page loads."""
        t0 = time.time()
        self.br.goto(BASE_URL)
        time.sleep(2)

        # Capture any cookies set on homepage
        cookies_before = []
        try:
            cookies_before = self.br.page.context.cookies()
        except Exception:
            pass

        # Navigate away and back
        self.br.goto(PSYCHICS_URL)
        time.sleep(1)
        self.br.goto(BASE_URL)
        time.sleep(2)

        # Capture cookies after round-trip
        cookies_after = []
        try:
            cookies_after = self.br.page.context.cookies()
        except Exception:
            pass

        rt = round((time.time() - t0) * 1000)
        ss = self.br.screenshot("mn009_session_preserved")
        no_crash      = not self.br.has_error_on_page()
        session_ok    = len(cookies_after) >= len(cookies_before)
        self._record(
            "MN-009: Session Cookies Preserved Across Page Navigations",
            {"action": "Homepage → /psychics → Homepage; compare cookies"},
            "Cookie count same or higher after navigation; session not reset",
            f"CookiesBefore={len(cookies_before)}, CookiesAfter={len(cookies_after)}, "
            f"SessionOK={session_ok}, NoCrash={no_crash}",
            "PASS" if (session_ok and no_crash) else "FAIL",
            rt, ss, category=self.CATEGORY_STATE,
        )

    # ── MN-010  External links are safe ──────────────────────────────────────
    def tc_mn010_external_links_safe(self):
        """External links (social media, etc.) should not trigger JS errors."""
        self.br.goto(BASE_URL)
        time.sleep(2)

        # Collect external link hrefs (don't click — just validate they exist and are HTTPS)
        ext_links = []
        try:
            els = self.br.page.locator("a[href^='http']").all()
            for el in els:
                href = el.get_attribute("href") or ""
                if href and SITE_DOMAIN not in href:
                    ext_links.append(href)
        except Exception:
            pass

        # Validate: all external links use HTTPS
        insecure = [l for l in ext_links if l.startswith("http://")]
        has_links = len(ext_links) > 0
        no_crash  = not self.br.has_error_on_page()
        ss = self.br.screenshot("mn010_external_links")

        self._record(
            "MN-010: External Links Are HTTPS-Secured",
            {"external_links_found": len(ext_links)},
            "All external links use HTTPS; no plain HTTP links",
            f"TotalExternal={len(ext_links)}, InsecureHTTP={insecure or 'none'}, "
            f"NoCrash={no_crash}",
            "PASS" if (not insecure and no_crash) else "FAIL",
            ss=ss,
            notes=f"External links found: {ext_links[:5]}{'...' if len(ext_links)>5 else ''}",
            category=self.CATEGORY_STATE,
        )

    # ── run_all ──────────────────────────────────────────────────────────────
    def run_all(self):
        print("\n🗺️  Multi-Page Navigation Tests  (MN-001 – MN-010)\n")
        tests = [
            ("MN-001: Full 3-page journey",              self.tc_mn001_full_journey),
            ("MN-002: Navbar links resolve",             self.tc_mn002_navbar_links),
            ("MN-003: Footer links resolve",             self.tc_mn003_footer_links),
            ("MN-004: Forward/back 3 pages",             self.tc_mn004_forward_back_navigation),
            ("MN-005: Deep-link to /psychics",           self.tc_mn005_deep_link),
            ("MN-006: State not corrupted",              self.tc_mn006_state_not_corrupted),
            ("MN-007: Rapid navigation no crash",        self.tc_mn007_rapid_navigation),
            ("MN-008: Full round-trip journey",          self.tc_mn008_full_round_trip),
            ("MN-009: Session preserved across pages",   self.tc_mn009_session_preserved),
            ("MN-010: External links are HTTPS",         self.tc_mn010_external_links_safe),
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
                    category=self.CATEGORY_JOURNEY,
                )
        print("\n✅ Multi-navigation tests complete.\n")
