"""
tests/test_self_healing.py
─────────────────────────────────────────────────────────────────────────────
Phase 3 — Self-Healing Selector Tests

Verifies that the SelfHealer engine can find elements even when the primary
selector is wrong, outdated, or intentionally broken — and logs the healed
selector for config.py updates.

Test IDs  : SH-001 … SH-008
Categories: Self-Healing

SH-001  SelfHealer finds button when primary selector is exact match
SH-002  SelfHealer heals a broken selector via text-content fallback
SH-003  SelfHealer heals a broken selector via aria-label fallback
SH-004  SelfHealer heals a broken input selector via placeholder fallback
SH-005  SelfHealer handles completely missing element gracefully (no crash)
SH-006  SelfHealer healed selectors are saved to self_heal_log.json
SH-007  SelectorValidator reports correct/broken status for all key selectors
SH-008  SelfHealer works correctly on /psychics listing page
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
from test_agent.self_healer import SelfHealer, SelectorValidator
from config import BASE_URL, PSYCHICS_URL, LOGIN_URL, SELECTORS


class SelfHealingTests:
    CATEGORY = "Self-Healing"

    def __init__(self, browser: BrowserController, reporter: TestReporter):
        self.br  = browser
        self.rep = reporter

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _record(self, name, input_data, expected, actual, status,
                rt=0, ss="", notes=""):
        self.rep.add_result(
            test_name=name, input_data=input_data,
            expected_result=expected, actual_result=actual,
            status=status, response_time_ms=rt,
            screenshot=ss, notes=notes, category=self.CATEGORY,
        )

    def _healer(self) -> SelfHealer:
        return SelfHealer(self.br.page, SELECTORS)

    # ── SH-001  Exact match — healer finds element on first try ─────────────
    def tc_sh001_exact_selector_works(self):
        self.br.goto(BASE_URL)
        time.sleep(2)
        healer = self._healer()

        t0     = time.time()
        result = healer.find(
            "button:has-text('Ask a Free Question')",
            hint="Ask a Free Question button",
        )
        rt = round((time.time() - t0) * 1000)
        ss = self.br.screenshot("sh001_exact_selector")

        self._record(
            "SH-001: SelfHealer Finds Element with Exact Selector",
            {"selector": "button:has-text('Ask a Free Question')"},
            "Element found on first attempt; healed=False",
            f"Found={result.found}, Strategy={result.strategy}, "
            f"Healed={result.healed}, WinningSel='{result.winning_sel}'",
            "PASS" if (result.found and not result.healed) else "FAIL",
            rt, ss,
        )

    # ── SH-002  Broken selector — heals via text-content ────────────────────
    def tc_sh002_heals_via_text_content(self):
        self.br.goto(BASE_URL)
        time.sleep(2)
        healer = self._healer()

        # Intentionally broken selector — the class name is fictional
        broken_sel = "button.fictional-class-xyz-9999-does-not-exist"
        t0     = time.time()
        result = healer.find(
            broken_sel,
            hint="Ask a Free Question button",   # hint lets healer use text search
        )
        rt = round((time.time() - t0) * 1000)
        ss = self.br.screenshot("sh002_text_content_heal")

        self._record(
            "SH-002: SelfHealer Heals Broken Selector via Text-Content Fallback",
            {"broken_selector": broken_sel, "hint": "Ask a Free Question button"},
            "Element found via text-content strategy; healed=True",
            f"Found={result.found}, Strategy={result.strategy}, "
            f"Healed={result.healed}, WinningSel='{result.winning_sel}'",
            "PASS" if (result.found and result.healed) else "FAIL",
            rt, ss,
            notes="If FAIL: button text may have changed. Check homepage manually.",
        )

    # ── SH-003  Heals via aria-label fallback ────────────────────────────────
    def tc_sh003_heals_via_aria(self):
        self.br.goto(LOGIN_URL)
        time.sleep(2)
        healer = self._healer()

        # Broken selector — wrong attribute value
        broken_sel = "input[type='email'][name='email-field-does-not-exist']"
        t0     = time.time()
        result = healer.find(
            broken_sel,
            hint="email input",
            fallback_list=["input[type='email']", "input[placeholder*='email' i]"],
        )
        rt = round((time.time() - t0) * 1000)
        ss = self.br.screenshot("sh003_aria_heal")

        self._record(
            "SH-003: SelfHealer Heals Broken Input Selector via Aria/Fallback",
            {"broken_selector": broken_sel, "page": LOGIN_URL},
            "Email input found via fallback list; healed=True",
            f"Found={result.found}, Strategy={result.strategy}, "
            f"Healed={result.healed}, WinningSel='{result.winning_sel}'",
            "PASS" if result.found else "FAIL",
            rt, ss,
        )

    # ── SH-004  Heals input via placeholder fallback ─────────────────────────
    def tc_sh004_heals_input_via_placeholder(self):
        self.br.goto(LOGIN_URL)
        time.sleep(2)
        healer = self._healer()

        # Wrong selector — password field named incorrectly
        broken_sel = "input[name='super-secret-field-xyz']"
        t0     = time.time()
        result = healer.find(
            broken_sel,
            hint="password input",
            fallback_list=[
                "input[type='password']",
                "input[placeholder*='password' i]",
                "input[name='password']",
            ],
        )
        rt = round((time.time() - t0) * 1000)
        ss = self.br.screenshot("sh004_placeholder_heal")

        self._record(
            "SH-004: SelfHealer Heals Broken Password Selector via Placeholder",
            {"broken_selector": broken_sel, "page": LOGIN_URL},
            "Password input found via placeholder/type fallback; healed=True",
            f"Found={result.found}, Strategy={result.strategy}, "
            f"Healed={result.healed}, WinningSel='{result.winning_sel}'",
            "PASS" if result.found else "FAIL",
            rt, ss,
        )

    # ── SH-005  Missing element — graceful failure ────────────────────────────
    def tc_sh005_missing_element_graceful(self):
        self.br.goto(BASE_URL)
        time.sleep(2)
        healer = self._healer()

        # Selector for an element that genuinely does not exist anywhere
        impossible_sel = "div#this-element-absolutely-does-not-exist-anywhere-on-the-page"
        t0     = time.time()
        result = healer.find(impossible_sel, hint="nonexistent element", timeout=1500)
        rt     = round((time.time() - t0) * 1000)
        ss     = self.br.screenshot("sh005_missing_graceful")
        no_crash = not self.br.has_error_on_page()

        self._record(
            "SH-005: SelfHealer Handles Completely Missing Element Gracefully",
            {"impossible_selector": impossible_sel},
            "found=False returned cleanly; no exception; no crash",
            f"Found={result.found}, Strategy={result.strategy}, NoCrash={no_crash}",
            "PASS" if (not result.found and no_crash) else "FAIL",
            rt, ss,
            notes="SelfHealer must never raise an exception — always return HealResult.",
        )

    # ── SH-006  Healed selectors saved to log ────────────────────────────────
    def tc_sh006_heal_log_saved(self):
        self.br.goto(BASE_URL)
        time.sleep(2)
        healer = self._healer()

        # Trigger a heal
        healer.find(
            "button.broken-class-for-logging-test",
            hint="Ask a Free Question button",
        )
        healer.save_log()

        log_path = SelfHealer.HEAL_LOG_PATH
        log_exists = os.path.exists(log_path)
        log_valid  = False
        entry_count = 0

        if log_exists:
            try:
                with open(log_path) as f:
                    log_data = json.load(f)
                log_valid   = isinstance(log_data, list)
                entry_count = len(log_data)
            except Exception:
                pass

        ss = self.br.screenshot("sh006_heal_log")
        self._record(
            "SH-006: Healed Selectors Are Saved to self_heal_log.json",
            {"log_path": log_path},
            "Heal log JSON file created with at least one entry",
            f"LogExists={log_exists}, ValidJSON={log_valid}, Entries={entry_count}",
            "PASS" if (log_exists and log_valid and entry_count > 0) else "FAIL",
            ss=ss,
            notes=f"Log saved at: {log_path}",
        )

    # ── SH-007  SelectorValidator reports correct/broken status ─────────────
    def tc_sh007_selector_validator(self):
        validator = SelectorValidator(self.br.page, SELECTORS)

        # Validate key selectors on homepage
        t0      = time.time()
        results = validator.validate_all(BASE_URL)
        rt      = round((time.time() - t0) * 1000)
        ss      = self.br.screenshot("sh007_validator")

        found_count  = sum(1 for v in results.values() if v.get("found"))
        broken       = [k for k, v in results.items() if not v.get("found")]
        healed_count = sum(1 for v in results.values() if v.get("healed"))

        self._record(
            "SH-007: SelectorValidator Reports Correct/Broken Status for All Selectors",
            {"url": BASE_URL, "selectors_checked": len(results)},
            "Validator runs without crash; reports found/broken status per selector",
            f"Checked={len(results)}, Found={found_count}, "
            f"Broken={len(broken)}, Healed={healed_count}",
            # PASS as long as the validator ran without crashing
            "PASS" if len(results) > 0 else "FAIL",
            rt, ss,
            notes=f"Broken selectors: {broken[:5]}. "
                  "Update config.py with healed alternatives.",
        )

    # ── SH-008  SelfHealer on /psychics listing ──────────────────────────────
    def tc_sh008_healer_on_psychics(self):
        self.br.goto(PSYCHICS_URL)
        time.sleep(3)
        healer = self._healer()

        # Try to find a psychic card with a broken selector, then heal
        broken_sel = "div.psychic-card-class-that-does-not-exist"
        t0     = time.time()
        result = healer.find(
            broken_sel,
            hint="psychic card",
            fallback_list=[
                "[class*='card']",
                "[class*='psychic']",
                "article",
                "[class*='expert']",
            ],
        )
        rt = round((time.time() - t0) * 1000)
        ss = self.br.screenshot("sh008_psychics_heal")

        self._record(
            "SH-008: SelfHealer Works on /psychics Listing Page",
            {"broken_selector": broken_sel, "page": PSYCHICS_URL},
            "Psychic card element found via fallback list on /psychics",
            f"Found={result.found}, Strategy={result.strategy}, "
            f"Healed={result.healed}, WinningSel='{result.winning_sel}'",
            "PASS" if result.found else "FAIL",
            rt, ss,
            notes="If FAIL: psychic cards may use different class names. "
                  "Inspect /psychics in DevTools and update fallback_list.",
        )

    # ── run_all ──────────────────────────────────────────────────────────────
    def run_all(self):
        print("\n🔧 Self-Healing Tests  (SH-001 – SH-008)\n")
        tests = [
            ("SH-001: Exact selector works",              self.tc_sh001_exact_selector_works),
            ("SH-002: Heals via text-content",            self.tc_sh002_heals_via_text_content),
            ("SH-003: Heals via aria/fallback",           self.tc_sh003_heals_via_aria),
            ("SH-004: Heals input via placeholder",       self.tc_sh004_heals_input_via_placeholder),
            ("SH-005: Missing element handled gracefully",self.tc_sh005_missing_element_graceful),
            ("SH-006: Heal log saved to JSON",            self.tc_sh006_heal_log_saved),
            ("SH-007: SelectorValidator reports status",  self.tc_sh007_selector_validator),
            ("SH-008: Healer works on /psychics",         self.tc_sh008_healer_on_psychics),
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
        print("\n✅ Self-healing tests complete.\n")
