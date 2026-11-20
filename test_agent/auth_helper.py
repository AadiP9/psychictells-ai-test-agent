"""
auth_helper.py
─────────────────────────────────────────────────────────────────────────────
Shared Authentication Helper — Single Source of Truth

BUGS THIS FILE FIXES:

1. UA-002 / UA-010 (test_user_auth.py) — the "user not found" detection used
   a hardcoded list of only 6 exact phrases. Real error text on the site
   didn't match any of them, so a legitimate "account doesn't exist" case
   was reported as a hard FAIL instead of the intended SKIP with a clear
   diagnostic message.

2. EP-002 (test_expert_panel.py) — login failures burned the full 20-second
   timeout with no visibility into WHY the login failed. The error-selector
   list was too narrow to catch the site's actual error UI, so genuinely
   invalid/expired credentials looked identical to "detection bug" in the
   report — a human reading the report couldn't tell which one it was.

This module provides ONE robust login helper used by test_user_auth.py,
test_expert_panel.py, and test_chat_flow.py, with:
  - A much broader error-phrase and error-selector list
  - Captures and reports the ACTUAL error text shown on the page
  - Distinguishes "credentials rejected" (environment/data issue → SKIP)
    from "we can't tell what happened" (possible selector/agent bug → FAIL)
  - Multi-strategy success detection: URL change, dashboard UI, storage token
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ── Broad error detection ──────────────────────────────────────────────────────

# Phrases indicating the account genuinely doesn't exist / isn't registered.
# Kept separate from generic error phrases so callers can distinguish
# "no such account" (→ SKIP, needs account setup) from other login errors.
ACCOUNT_NOT_FOUND_PHRASES = [
    "user not found", "no account", "doesn't exist", "does not exist",
    "not registered", "account not found", "no user found",
    "couldn't find an account", "could not find an account",
    "email not found", "no account exists", "unregistered",
    "account doesn't exist", "we don't recognize", "not found with this email",
]

# Broader set of generic auth-failure phrases (wrong password, locked, etc).
GENERIC_AUTH_ERROR_PHRASES = [
    "invalid", "incorrect", "wrong password", "failed", "error",
    "unauthorized", "denied", "locked", "expired", "try again",
    "doesn't match", "does not match", "authentication failed",
    "login failed", "unable to sign in", "unable to log in",
] + ACCOUNT_NOT_FOUND_PHRASES

# CSS selectors commonly used for inline error / toast / alert UI across
# React, Vue, and plain HTML sites. Broader than a single project's list.
ERROR_UI_SELECTORS = [
    "[class*='error']", "[class*='invalid']", "[class*='alert']",
    "[class*='toast']", "[class*='snackbar']", "[class*='notification']",
    "[role='alert']", ".alert", ".error", ".invalid-feedback",
    "p:has-text('Invalid')", "p:has-text('incorrect')",
    "p:has-text('failed')", "div:has-text('Invalid email or password')",
]

SUCCESS_UI_SELECTORS = [
    "[class*='avatar']", "[class*='profile']", "[class*='account']",
    "[class*='dashboard']", "[class*='welcome']",
    "a[href*='account']", "a[href*='profile']", "a[href*='dashboard']",
    "button:has-text('Logout')", "button:has-text('Sign Out')",
    "button:has-text('Log Out')",
]


@dataclass
class AuthResult:
    """Outcome of a login attempt with enough detail to classify PASS/FAIL/SKIP."""
    success:            bool
    url:                str
    error_detected:     bool   = False
    error_text:         str    = ""
    account_not_found:  bool   = False
    timed_out:          bool   = False
    duration_ms:        int    = 0


class AuthHelper:
    """
    Shared login helper. Wraps a BrowserController and a Playwright page to
    perform a login attempt with robust, multi-strategy success/failure
    detection.
    """

    def __init__(self, browser):
        self.br = browser

    # ── Public API ─────────────────────────────────────────────────────────

    def fill_first(self, selectors: list, value: str) -> bool:
        """Fill the first visible matching field. Reusable across all auth forms."""
        for sel in selectors:
            try:
                el = self.br.page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    el.fill(value)
                    return True
            except Exception:
                continue
        return False

    def click_first(self, selectors: list) -> bool:
        """Click the first visible matching element, with dispatch_event fallback
        for React/Next.js elements that don't respond to native clicks."""
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

    def is_visible_any(self, selectors: list, timeout: int = 3000) -> bool:
        for sel in selectors:
            try:
                self.br.page.wait_for_selector(sel, state="visible", timeout=timeout)
                return True
            except Exception:
                continue
        return False

    def attempt_login(
        self,
        login_url: str,
        email: str,
        password: str,
        email_selectors: list,
        password_selectors: list,
        submit_selectors: list,
        extra_success_selectors: list = None,
        max_wait_s: float = 15.0,
    ) -> AuthResult:
        """
        Perform a full login attempt and classify the outcome.

        This is the SINGLE authoritative login flow used by user auth,
        expert panel, and chat-flow login-prompt handling. It:
          1. Navigates to login_url
          2. Fills email + password
          3. Clicks submit
          4. Polls (up to max_wait_s) for the FIRST of:
             - URL change away from the login page   → success
             - Success UI element appears             → success
             - Auth token appears in local/session storage → success
             - Error UI element appears                → captures error text,
               classifies as account_not_found or generic error, returns
               immediately (does NOT wait out the full timeout)
          5. If nothing matched by max_wait_s, returns timed_out=True

        Returning quickly on a detected error (instead of waiting the full
        timeout) is the key fix for the EP-002 23-second-blind-wait problem.
        """
        t0 = time.time()
        self.br.goto(login_url)
        time.sleep(2)

        self.fill_first(email_selectors, email)
        self.fill_first(password_selectors, password)
        self.click_first(submit_selectors)

        success_selectors = SUCCESS_UI_SELECTORS + (extra_success_selectors or [])
        start_url = self.br.current_url()
        deadline  = time.time() + max_wait_s

        while time.time() < deadline:
            cur = self.br.current_url()

            # ── Success: URL left the login page ───────────────────────────
            if cur != start_url and "login" not in cur.lower():
                try:
                    self.br.page.wait_for_load_state("domcontentloaded", timeout=4000)
                except Exception:
                    pass
                return AuthResult(
                    success=True, url=self.br.current_url(),
                    duration_ms=round((time.time() - t0) * 1000),
                )

            # ── Success: dashboard/account UI visible ──────────────────────
            if self.is_visible_any(success_selectors, timeout=250):
                return AuthResult(
                    success=True, url=cur,
                    duration_ms=round((time.time() - t0) * 1000),
                )

            # ── Success: auth token in storage (SPA pattern) ────────────────
            if self._has_auth_token():
                return AuthResult(
                    success=True, url=cur,
                    duration_ms=round((time.time() - t0) * 1000),
                )

            # ── Error detected — classify and return immediately ────────────
            error_text = self._read_error_text()
            if error_text:
                text_lower = error_text.lower()
                not_found  = any(p in text_lower for p in ACCOUNT_NOT_FOUND_PHRASES)
                return AuthResult(
                    success=False, url=cur,
                    error_detected=True, error_text=error_text,
                    account_not_found=not_found,
                    duration_ms=round((time.time() - t0) * 1000),
                )

            time.sleep(0.4)

        # Timed out — no success or error signal detected within max_wait_s
        return AuthResult(
            success=False, url=self.br.current_url(),
            timed_out=True,
            duration_ms=round((time.time() - t0) * 1000),
        )

    # ── Internal ───────────────────────────────────────────────────────────

    def _read_error_text(self) -> str:
        """
        Check ERROR_UI_SELECTORS for a visible match and return its text.
        Also does a broad page-content scan for GENERIC_AUTH_ERROR_PHRASES
        as a fallback for sites that don't use a recognizable error element.
        """
        for sel in ERROR_UI_SELECTORS:
            try:
                el = self.br.page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    text = (el.inner_text() or "").strip()
                    if text:
                        return text[:200]
            except Exception:
                continue

        # Fallback: scan visible page text for known error phrases.
        # Slower, so only used after the selector scan finds nothing.
        try:
            body_text = self.br.page.inner_text("body").lower()
            for phrase in GENERIC_AUTH_ERROR_PHRASES:
                if phrase in body_text:
                    return f"(matched phrase: '{phrase}')"
        except Exception:
            pass

        return ""

    def _has_auth_token(self) -> bool:
        try:
            return bool(self.br.page.evaluate("""
                () => {
                    try {
                        const keys = Object.keys(localStorage).concat(
                                     Object.keys(sessionStorage));
                        return keys.some(k =>
                            k.toLowerCase().includes('token') ||
                            k.toLowerCase().includes('auth') ||
                            k.toLowerCase().includes('user') ||
                            k.toLowerCase().includes('session')
                        );
                    } catch(e) { return false; }
                }
            """))
        except Exception:
            return False
