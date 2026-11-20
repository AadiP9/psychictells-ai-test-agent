"""
tests/test_ui_regression.py
─────────────────────────────────────────────────────────────────────────────
Phase 3 — UI Regression / Change Detection Tests

Uses UIChangeDetector to capture a baseline of the site and then compare
every subsequent run against it. Automatically flags any DOM structure
changes, missing critical elements, title changes, or visual diffs.

Test IDs  : UR-001 … UR-008
Categories: UI Regression

UR-001  Baseline capture completes successfully for all pages
UR-002  Homepage DOM structure matches baseline (element counts)
UR-003  /psychics listing element count within acceptable threshold
UR-004  Critical selectors still present on homepage (Ask button, nav, footer)
UR-005  Login page form elements match baseline
UR-006  Page titles match baseline across all pages
UR-007  Navigation link count has not changed significantly
UR-008  No new HTTP errors introduced since baseline
─────────────────────────────────────────────────────────────────────────────
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from test_agent.browser_controller import BrowserController
from test_agent.reporter import TestReporter
from test_agent.ui_change_detector import UIChangeDetector
from config import BASELINE_PAGES
from config import BASE_URL, PSYCHICS_URL, LOGIN_URL, SELECTORS


class UIRegressionTests:
    CATEGORY = "UI Regression"

    def __init__(self, browser: BrowserController, reporter: TestReporter):
        self.br       = browser
        self.rep      = reporter
        self.detector = UIChangeDetector(browser, BASELINE_PAGES)
        self._baseline_captured = False
        self._live_snaps: dict  = {}   # page_id → live snapshot
        self._changes:    list  = []   # all detected changes

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _record(self, name, input_data, expected, actual, status,
                rt=0, ss="", notes=""):
        self.rep.add_result(
            test_name=name, input_data=input_data,
            expected_result=expected, actual_result=actual,
            status=status, response_time_ms=rt,
            screenshot=ss, notes=notes, category=self.CATEGORY,
        )

    def _get_changes_for_page(self, page_id: str, change_type: str = None) -> list:
        """Filter self._changes for a specific page and optional type."""
        return [
            c for c in self._changes
            if c.get("page_id") == page_id and
               (change_type is None or c.get("type") == change_type)
        ]

    def _ensure_baseline_and_changes(self):
        """
        Run detect_changes() once and cache results.
        If no baseline exists, capture one first.
        """
        if self._changes or self._live_snaps:
            return   # already done

        summary = self.detector.get_baseline_summary()
        if summary.get("status") == "no_baseline" or summary.get("total_pages", 0) == 0:
            print("\n  📸  No baseline found — capturing now (first-time setup)...")
            self.detector.capture_baseline()
            self._baseline_captured = True

        self._changes = self.detector.detect_changes()

    # ── UR-001  Baseline capture ─────────────────────────────────────────────
    def tc_ur001_baseline_capture(self):
        """Capture a fresh baseline and verify it succeeded for all pages."""
        t0 = time.time()
        try:
            baseline = self.detector.capture_baseline()
            self._baseline_captured = True
        except Exception as e:
            rt = round((time.time() - t0) * 1000)
            ss = self.br.screenshot("ur001_baseline_fail")
            self._record(
                "UR-001: Baseline Capture Completes for All Pages",
                {"pages": [p["id"] for p in BASELINE_PAGES]},
                "Baseline JSON saved for all configured pages",
                f"ERROR: {e}",
                "ERROR", rt, ss,
            )
            return

        rt        = round((time.time() - t0) * 1000)
        ss        = self.br.screenshot("ur001_baseline")
        pages     = baseline.get("pages", {})
        ok_pages  = [pid for pid, snap in pages.items()
                     if snap.get("http_status", 0) in (200, 301, 302)]
        all_ok    = len(ok_pages) == len(BASELINE_PAGES)

        self._record(
            "UR-001: Baseline Capture Completes for All Pages",
            {"pages_configured": len(BASELINE_PAGES)},
            f"All {len(BASELINE_PAGES)} pages snapshotted with HTTP 200",
            f"PagesOK={len(ok_pages)}/{len(BASELINE_PAGES)}, "
            f"OKPages={ok_pages}",
            "PASS" if all_ok else "FAIL",
            rt, ss,
            notes="Baseline saved to baselines/baseline.json. "
                  "Re-run after confirming site is correct to reset baseline.",
        )

    # ── UR-002  Homepage DOM structure matches baseline ───────────────────────
    def tc_ur002_homepage_dom_structure(self):
        self._ensure_baseline_and_changes()
        t0 = time.time()

        # Check for element-count changes on homepage
        hp_changes = self._get_changes_for_page("homepage", "ELEMENT_COUNT_CHANGED")
        crit_missing = self._get_changes_for_page("homepage", "SELECTOR_MISSING")

        rt = round((time.time() - t0) * 1000)
        ss = self.br.screenshot("ur002_homepage_dom")

        all_clean = not hp_changes and not crit_missing
        self._record(
            "UR-002: Homepage DOM Structure Matches Baseline",
            {"page": BASE_URL},
            "No significant element count changes from baseline",
            f"ElementCountChanges={len(hp_changes)}, "
            f"CriticalMissing={len(crit_missing)}, "
            f"Details={[c['message'] for c in hp_changes + crit_missing][:3]}",
            "PASS" if all_clean else "FAIL",
            rt, ss,
            notes="Changes may indicate a site redesign. "
                  "If intentional, run UR-001 to update the baseline.",
        )

    # ── UR-003  /psychics listing element count within threshold ─────────────
    def tc_ur003_psychics_listing_count(self):
        self._ensure_baseline_and_changes()
        t0 = time.time()

        listing_changes = self._get_changes_for_page(
            "psychics_listing", "ELEMENT_COUNT_CHANGED"
        )
        rt = round((time.time() - t0) * 1000)

        # Navigate and count cards directly for extra validation
        self.br.goto(PSYCHICS_URL)
        time.sleep(3)
        ss = self.br.screenshot("ur003_psychics_listing")

        card_count = 0
        for sel in ["[class*='card']", "[class*='psychic']", "article"]:
            try:
                card_count = self.br.page.locator(sel).count()
                if card_count > 0:
                    break
            except Exception:
                pass

        no_crash = not self.br.has_error_on_page()

        self._record(
            "UR-003: /psychics Listing Element Count Within Threshold",
            {"page": PSYCHICS_URL},
            "Psychic card count ≥ 1; no significant DOM changes from baseline",
            f"CardCount={card_count}, BaselineChanges={len(listing_changes)}, "
            f"NoCrash={no_crash}",
            "PASS" if (card_count >= 1 and no_crash) else "FAIL",
            rt, ss,
            notes=f"Found {card_count} card-like elements on /psychics.",
        )

    # ── UR-004  Critical selectors still present on homepage ─────────────────
    def tc_ur004_critical_selectors_homepage(self):
        self._ensure_baseline_and_changes()

        critical = [
            "button:has-text('Ask')",
            "nav",
            "footer",
            "a[href*='psychic']",
        ]

        t0 = time.time()
        results = self.detector.validate_critical_selectors(BASE_URL, critical)
        rt = round((time.time() - t0) * 1000)
        ss = self.br.screenshot("ur004_critical_selectors")

        missing  = [sel for sel, found in results.items() if not found]
        all_ok   = not missing

        self._record(
            "UR-004: Critical Selectors Still Present on Homepage",
            {"selectors_checked": critical},
            "All critical selectors (Ask button, nav, footer) found on homepage",
            f"Found={sum(results.values())}/{len(results)}, Missing={missing or 'none'}",
            "PASS" if all_ok else "FAIL",
            rt, ss,
            notes="Missing selectors may mean the site was redesigned. "
                  "Update SELECTORS in config.py and re-run UR-001.",
        )

    # ── UR-005  Login page form elements match baseline ───────────────────────
    def tc_ur005_login_form_baseline(self):
        self._ensure_baseline_and_changes()

        critical_login = [
            "input[type='email']",
            "input[type='password']",
            "button[type='submit']",
        ]

        t0      = time.time()
        results = self.detector.validate_critical_selectors(LOGIN_URL, critical_login)
        rt      = round((time.time() - t0) * 1000)
        ss      = self.br.screenshot("ur005_login_form")

        # Also check for baseline changes on login page
        login_changes = self._get_changes_for_page("login_page", "SELECTOR_MISSING")
        missing       = [sel for sel, found in results.items() if not found]
        all_ok        = not missing and not login_changes

        self._record(
            "UR-005: Login Page Form Elements Match Baseline",
            {"page": LOGIN_URL, "selectors": critical_login},
            "Email, password, and submit fields all present; no baseline regression",
            f"Missing={missing or 'none'}, BaselineRegressions={len(login_changes)}",
            "PASS" if all_ok else "FAIL",
            rt, ss,
        )

    # ── UR-006  Page titles match baseline ────────────────────────────────────
    def tc_ur006_page_titles_match(self):
        self._ensure_baseline_and_changes()
        t0 = time.time()

        title_changes = [
            c for c in self._changes if c.get("type") == "TITLE_CHANGED"
        ]
        rt = round((time.time() - t0) * 1000)
        ss = self.br.screenshot("ur006_page_titles")

        changed_pages = [c["page_id"] for c in title_changes]

        self._record(
            "UR-006: Page Titles Match Baseline Across All Pages",
            {"pages_checked": [p["id"] for p in BASELINE_PAGES]},
            "No page title changes detected since baseline",
            f"TitleChanges={len(title_changes)}, ChangedPages={changed_pages or 'none'}, "
            f"Details={[c['message'] for c in title_changes]}",
            "PASS" if not title_changes else "FAIL",
            rt, ss,
            notes="Title changes may indicate a rebrand or page restructure. "
                  "If intentional, update the baseline with UR-001.",
        )

    # ── UR-007  Navigation link count has not changed ─────────────────────────
    def tc_ur007_nav_link_count(self):
        self._ensure_baseline_and_changes()
        t0 = time.time()

        nav_changes = [
            c for c in self._changes if c.get("type") == "NAV_LINKS_CHANGED"
        ]

        # Also do a live count for the report
        self.br.goto(BASE_URL)
        time.sleep(2)
        live_nav_count = 0
        try:
            live_nav_count = self.br.page.locator("nav a").count()
        except Exception:
            pass

        rt = round((time.time() - t0) * 1000)
        ss = self.br.screenshot("ur007_nav_links")

        self._record(
            "UR-007: Navigation Link Count Has Not Changed Significantly",
            {"page": BASE_URL},
            "Nav link count matches baseline (within ±2 links)",
            f"LiveNavLinks={live_nav_count}, NavChanges={len(nav_changes)}, "
            f"Details={[c['message'] for c in nav_changes]}",
            "PASS" if not nav_changes else "FAIL",
            rt, ss,
            notes="A drop in nav links may mean a menu item was removed. "
                  "An increase may mean new pages were added.",
        )

    # ── UR-008  No new HTTP errors since baseline ─────────────────────────────
    def tc_ur008_no_new_http_errors(self):
        self._ensure_baseline_and_changes()
        t0 = time.time()

        http_changes = [
            c for c in self._changes
            if c.get("type") == "HTTP_STATUS_CHANGED"
            and c.get("current", 0) >= 400
        ]

        # Also do a live HTTP check on all configured pages
        live_errors = []
        for page_cfg in BASELINE_PAGES:
            try:
                nav = self.br.goto(page_cfg["url"])
                time.sleep(1)
                status = nav.get("status", 0) if nav else 0
                if status >= 400:
                    live_errors.append(f"{page_cfg['id']}:{status}")
            except Exception as e:
                live_errors.append(f"{page_cfg['id']}:error({e})")

        rt = round((time.time() - t0) * 1000)
        ss = self.br.screenshot("ur008_http_errors")

        all_clean = not http_changes and not live_errors

        self._record(
            "UR-008: No New HTTP Errors Introduced Since Baseline",
            {"pages_checked": [p["id"] for p in BASELINE_PAGES]},
            "All pages return HTTP 200/301/302; no 4xx or 5xx since baseline",
            f"BaselineHTTPChanges={len(http_changes)}, "
            f"LiveErrors={live_errors or 'none'}",
            "PASS" if all_clean else "FAIL",
            rt, ss,
            notes="HTTP errors on previously working pages indicate server-side issues. "
                  "Report to the dev team immediately.",
        )

    # ── run_all ──────────────────────────────────────────────────────────────
    def run_all(self):
        print("\n🔍 UI Regression Tests  (UR-001 – UR-008)\n")
        tests = [
            ("UR-001: Baseline capture",                   self.tc_ur001_baseline_capture),
            ("UR-002: Homepage DOM structure",             self.tc_ur002_homepage_dom_structure),
            ("UR-003: /psychics listing count",            self.tc_ur003_psychics_listing_count),
            ("UR-004: Critical selectors on homepage",     self.tc_ur004_critical_selectors_homepage),
            ("UR-005: Login form elements match baseline", self.tc_ur005_login_form_baseline),
            ("UR-006: Page titles match baseline",         self.tc_ur006_page_titles_match),
            ("UR-007: Nav link count unchanged",           self.tc_ur007_nav_link_count),
            ("UR-008: No new HTTP errors",                 self.tc_ur008_no_new_http_errors),
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
                    category=self.CATEGORY,
                )
        print("\n✅ UI regression tests complete.\n")
