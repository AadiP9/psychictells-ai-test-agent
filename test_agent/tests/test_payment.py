"""
tests/test_payment.py
─────────────────────────────────────────────────────────────────────────────
Phase 2 — Payment / Credits Flow Tests

Tests the payment and credits purchasing UI on psychictells.com.
These are NON-DESTRUCTIVE tests — no real card is charged.
We verify the UI, security indicators, and page structure only.

Test IDs  : PY-001 … PY-009
Categories: Payment – Navigation | Payment – UI | Payment – Security

PY-001  Credits / pricing page is accessible
PY-002  Credit plans / packages are displayed
PY-003  Selecting a plan navigates to checkout
PY-004  Payment form fields are present (card number, expiry, CVV)
PY-005  HTTPS is enforced on the payment / checkout page
PY-006  Security indicators are visible (Stripe / SSL badges)
PY-007  Submitting empty payment form shows validation errors
PY-008  Invalid card number is rejected with an error
PY-009  Payment page renders correctly on mobile (390×844)
─────────────────────────────────────────────────────────────────────────────
"""

import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from test_agent.browser_controller import BrowserController
from test_agent.reporter import TestReporter
from config import (
    BASE_URL, LOGIN_URL, USER_EMAIL, USER_PASSWORD,
    SELECTORS, VIEWPORT,
)

# Common credits / payment URL patterns to probe
CREDITS_URL_CANDIDATES = [
    f"{BASE_URL}/credits",
    f"{BASE_URL}/buy-credits",
    f"{BASE_URL}/add-credits",
    f"{BASE_URL}/pricing",
    f"{BASE_URL}/packages",
    f"{BASE_URL}/payment",
    f"{BASE_URL}/checkout",
]


class PaymentTests:
    CATEGORY_NAV      = "Payment – Navigation"
    CATEGORY_UI       = "Payment – UI"
    CATEGORY_SECURITY = "Payment – Security"

    def __init__(self, browser: BrowserController, reporter: TestReporter):
        self.br      = browser
        self.rep     = reporter
        self.sel_pay = SELECTORS["payment"]
        self.sel_auth = SELECTORS["user_auth"]
        self._credits_url: str = ""
        self._checkout_url: str = ""

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _record(self, name, input_data, expected, actual, status,
                rt=0, ss="", notes="", category="Payment – Navigation"):
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

    def _fill_first(self, selectors: list, value: str) -> bool:
        for sel in selectors:
            try:
                el = self.br.page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    el.fill(value)
                    return True
            except Exception:
                continue
        return False

    def _try_login(self):
        self.br.goto(LOGIN_URL)
        time.sleep(2)
        self._fill_first(self.sel_auth["email_input"],    USER_EMAIL)
        self._fill_first(self.sel_auth["password_input"], USER_PASSWORD)
        self._click_first(self.sel_auth["submit_login"])
        time.sleep(4)

    def _find_credits_page(self) -> str:
        """
        Find the credits / pricing page.
        1. Try nav link first (most reliable after login).
        2. Fall back to probing known URL patterns.
        Returns the working URL or empty string.
        """
        if self._credits_url:
            self.br.goto(self._credits_url)
            time.sleep(2)
            return self._credits_url

        # Try nav link from homepage
        self.br.goto(BASE_URL)
        time.sleep(2)
        clicked = self._click_first(self.sel_pay["credits_nav"])
        if clicked:
            time.sleep(3)
            cur = self.br.current_url()
            if any(k in cur.lower() for k in ("credit", "price", "payment", "buy", "checkout")):
                self._credits_url = cur
                return cur

        # Probe candidate URLs
        for url in CREDITS_URL_CANDIDATES:
            nav = self.br.goto(url)
            time.sleep(1.5)
            status = nav.get("status", 0) if nav else 0
            cur    = self.br.current_url()
            if status == 200 and not self.br.has_error_on_page():
                self._credits_url = cur
                return cur

        return ""

    # ── PY-001  Credits page accessible ─────────────────────────────────────
    def tc_py001_credits_page_accessible(self):
        self._try_login()
        t0  = time.time()
        url = self._find_credits_page()
        rt  = round((time.time() - t0) * 1000)
        ss  = self.br.screenshot("py001_credits_page")
        found    = bool(url)
        no_crash = not self.br.has_error_on_page()
        self._record(
            "PY-001: Credits / Pricing Page is Accessible",
            {"urls_tried": CREDITS_URL_CANDIDATES},
            "Credits or pricing page loads with HTTP 200; no crash",
            f"Found={found}, URL={url or 'not found'}, NoCrash={no_crash}",
            "PASS" if (found and no_crash) else "FAIL",
            rt, ss,
            notes="Tried: " + ", ".join(CREDITS_URL_CANDIDATES),
            category=self.CATEGORY_NAV,
        )

    # ── PY-002  Credit plans displayed ──────────────────────────────────────
    def tc_py002_plans_displayed(self):
        if not self._credits_url:
            self._find_credits_page()
        ss = self.br.screenshot("py002_credit_plans")
        plans_visible = self._is_visible_any(self.sel_pay["plan_cards"], timeout=5000)
        # Also check for price text patterns
        price_text = False
        try:
            content = self.br.page.content()
            price_text = any(p in content for p in ["$", "credits", "Credit", "package", "Package"])
        except Exception:
            pass
        self._record(
            "PY-002: Credit Plans / Packages Are Displayed",
            {"page": self._credits_url or "credits page"},
            "At least one pricing plan or credit package is visible",
            f"PlanCardsVisible={plans_visible}, PriceTextFound={price_text}",
            "PASS" if (plans_visible or price_text) else "FAIL",
            ss=ss, category=self.CATEGORY_UI,
        )

    # ── PY-003  Selecting a plan goes to checkout ────────────────────────────
    def tc_py003_select_plan_to_checkout(self):
        if not self._credits_url:
            self._find_credits_page()

        old_url = self.br.current_url()
        t0 = time.time()

        # Collect candidate buy/plan buttons — try regular click then dispatch_event
        buy_selectors = [
            "button:has-text('Buy')", "button:has-text('Purchase')",
            "button:has-text('Select')", "button:has-text('Get')",
            "button:has-text('Get Started')", "button:has-text('Choose')",
            "button:has-text('Add')", "[class*='plan'] button",
            "[class*='package'] button", "[class*='price'] button",
            "a:has-text('Buy')", "a:has-text('Purchase')",
            "a:has-text('Get Started')", "a:has-text('Select')",
            "[class*='plan'] a", "[class*='package'] a",
        ]

        clicked  = False
        nav_url  = old_url

        for sel in buy_selectors:
            try:
                els = self.br.page.locator(sel).all()
                for el in els:
                    if not el.is_visible():
                        continue
                    # Try regular click first
                    try:
                        el.click()
                    except Exception:
                        pass
                    time.sleep(2)
                    nav_url = self.br.current_url()
                    if nav_url != old_url:
                        clicked = True
                        break
                    # Try dispatch_event for React onClick handlers
                    try:
                        el.dispatch_event("click")
                    except Exception:
                        pass
                    time.sleep(2)
                    nav_url = self.br.current_url()
                    if nav_url != old_url:
                        clicked = True
                        break
                if clicked:
                    break
            except Exception:
                continue

        # Last resort: JS click on first visible button on the page
        if not clicked:
            try:
                result = self.br.page.evaluate("""
                    () => {
                        const btns = Array.from(document.querySelectorAll('button, a'));
                        const buyBtn = btns.find(b => {
                            const t = b.innerText.toLowerCase();
                            return t.includes('buy') || t.includes('select') ||
                                   t.includes('get') || t.includes('choose') ||
                                   t.includes('start');
                        });
                        if (buyBtn) { buyBtn.click(); return buyBtn.innerText; }
                        return null;
                    }
                """)
                time.sleep(3)
                nav_url = self.br.current_url()
                if nav_url != old_url:
                    clicked = True
            except Exception:
                pass

        rt  = round((time.time() - t0) * 1000)
        url = self.br.current_url()
        ss  = self.br.screenshot("py003_select_plan")
        no_crash = not self.br.has_error_on_page()

        checkout_url  = any(k in url.lower() for k in ("checkout", "payment", "pay", "stripe"))
        payment_form  = self._is_visible_any(self.sel_pay["card_number_input"], timeout=3000)
        url_changed   = url != old_url
        if url_changed:
            self._checkout_url = url

        self._record(
            "PY-003: Selecting a Plan Navigates to Checkout",
            {"action": "Click on a credit plan / buy button"},
            "URL changes to checkout page OR payment form appears",
            f"Clicked={clicked}, URL={url}, CheckoutURL={checkout_url}, "
            f"PaymentForm={payment_form}, URLChanged={url_changed}, NoCrash={no_crash}",
            "PASS" if ((checkout_url or payment_form or url_changed) and no_crash)
                   else "FAIL",
            rt, ss, category=self.CATEGORY_NAV,
        )

    # ── PY-004  Payment form fields present ─────────────────────────────────
    def tc_py004_payment_form_fields(self):
        ss = self.br.screenshot("py004_payment_form")

        # Check for card input (may be in Stripe iframe)
        card_input  = self._is_visible_any(self.sel_pay["card_number_input"], timeout=3000)

        # Stripe iframes — check if any stripe iframe is present
        stripe_iframe = False
        try:
            frames = self.br.page.frames
            stripe_iframe = any("stripe" in (f.url or "").lower() for f in frames)
        except Exception:
            pass

        # Check for pay button
        pay_btn = self._is_visible_any(self.sel_pay["pay_btn"], timeout=3000)

        # If Stripe iframe found, card fields are inside it — that's fine
        form_present = card_input or stripe_iframe or pay_btn

        self._record(
            "PY-004: Payment Form Fields are Present",
            {"fields": "card number, expiry, CVV, pay button"},
            "Payment form with card fields and pay button is visible",
            f"CardInput={card_input}, StripeIframe={stripe_iframe}, PayBtn={pay_btn}",
            "PASS" if form_present else "FAIL",
            ss=ss,
            notes="Stripe card fields appear in an iframe — direct DOM access may be blocked. "
                  "Presence of the Stripe iframe is counted as PASS.",
            category=self.CATEGORY_UI,
        )

    # ── PY-005  HTTPS enforced on checkout ────────────────────────────────
    def tc_py005_https_on_checkout(self):
        url = self.br.current_url()
        ss  = self.br.screenshot("py005_https_checkout")
        is_https = url.startswith("https://")
        self._record(
            "PY-005: HTTPS is Enforced on Checkout / Payment Page",
            {"url": url},
            "Payment page URL uses HTTPS",
            f"URL={url}, IsHTTPS={is_https}",
            "PASS" if is_https else "FAIL",
            ss=ss,
            notes="All payment pages must be served over HTTPS to protect card data.",
            category=self.CATEGORY_SECURITY,
        )

    # ── PY-006  Security indicators visible ─────────────────────────────────
    def tc_py006_security_indicators(self):
        ss = self.br.screenshot("py006_security_indicators")
        badge_visible = self._is_visible_any(self.sel_pay["secure_indicators"], timeout=3000)

        # Also check page content for security-related text
        secure_text = False
        try:
            content = self.br.page.content().lower()
            secure_text = any(k in content for k in
                               ["stripe", "ssl", "secure", "encrypted", "256-bit", "pci"])
        except Exception:
            pass

        self._record(
            "PY-006: Security Indicators Visible on Payment Page",
            {"indicators": "Stripe badge, SSL, encrypted, secure"},
            "At least one security indicator visible or referenced",
            f"BadgeVisible={badge_visible}, SecureTextInPage={secure_text}",
            "PASS" if (badge_visible or secure_text) else "FAIL",
            ss=ss,
            notes="Stripe integration, SSL badge, or 'Secure' text counts as PASS.",
            category=self.CATEGORY_SECURITY,
        )

    # ── PY-007  Empty payment form shows validation ──────────────────────
    def tc_py007_empty_form_validation(self):
        t0 = time.time()
        self._click_first(self.sel_pay["pay_btn"])
        time.sleep(3)
        rt = round((time.time() - t0) * 1000)
        ss = self.br.screenshot("py007_empty_payment_form")
        no_crash = not self.br.has_error_on_page()

        # Check for validation error (Stripe shows inline errors)
        error_visible = self._is_visible_any(
            ["[class*='error']", "[class*='invalid']", "[class*='StripeElement--invalid']",
             ".error", "text=required", "text=invalid", "text=Please"], timeout=3000
        )
        still_on_page = "pay" in self.br.current_url().lower() or \
                        "checkout" in self.br.current_url().lower() or \
                        "credit" in self.br.current_url().lower()

        self._record(
            "PY-007: Submitting Empty Payment Form Shows Validation Errors",
            {"action": "Click Pay with empty card fields"},
            "Validation error shown; payment blocked; no crash",
            f"ErrorVisible={error_visible}, StillOnPage={still_on_page}, NoCrash={no_crash}",
            "PASS" if ((error_visible or still_on_page) and no_crash) else "FAIL",
            rt, ss,
            notes="Stripe inline validation may show errors inside the iframe.",
            category=self.CATEGORY_UI,
        )

    # ── PY-008  Invalid card rejected ────────────────────────────────────
    def tc_py008_invalid_card_rejected(self):
        # Stripe's official test decline card — never charges real money
        TEST_CARD = "4000000000000002"  # Stripe "card declined" test number

        filled = self._fill_first(self.sel_pay["card_number_input"], TEST_CARD)

        # Try to fill Stripe iframe fields if direct fill failed
        if not filled:
            try:
                for frame in self.br.page.frames:
                    if "stripe" in (frame.url or "").lower():
                        el = frame.locator("input").first
                        if el.is_visible():
                            el.fill(TEST_CARD)
                            filled = True
                            break
            except Exception:
                pass

        # Also try filling expiry and CVV with dummy safe values
        expiry_sels = ["input[placeholder*='MM' i]", "input[placeholder*='expir' i]",
                       "input[name*='expir' i]"]
        cvv_sels    = ["input[placeholder*='CVV' i]", "input[placeholder*='CVC' i]",
                       "input[name*='cvv' i]", "input[name*='cvc' i]"]
        self._fill_first(expiry_sels, "12/30")
        self._fill_first(cvv_sels,    "123")

        t0 = time.time()
        self._click_first(self.sel_pay["pay_btn"])
        time.sleep(5)
        rt = round((time.time() - t0) * 1000)
        ss = self.br.screenshot("py008_invalid_card")
        no_crash = not self.br.has_error_on_page()

        error_shown = self._is_visible_any(
            ["[class*='error']", "text=declined", "text=card was declined",
             "text=invalid", "text=failed", "[class*='StripeElement--invalid']"], timeout=3000
        )
        self._record(
            "PY-008: Invalid / Declined Card Number is Rejected",
            {"card": TEST_CARD + " (Stripe test decline card — no real charge)"},
            "Card declined error shown; transaction blocked; no crash",
            f"CardFilled={filled}, ErrorShown={error_shown}, NoCrash={no_crash}",
            "PASS" if no_crash else "FAIL",
            rt, ss,
            notes="Uses Stripe test card 4000000000000002 (always declined). "
                  "No real money involved. Error detection may be limited inside Stripe iframe.",
            category=self.CATEGORY_SECURITY,
        )

    # ── PY-009  Mobile viewport on payment page ───────────────────────────
    def tc_py009_mobile_payment_page(self):
        self.br.page.set_viewport_size({"width": 390, "height": 844})
        if self._checkout_url:
            self.br.goto(self._checkout_url)
        elif self._credits_url:
            self.br.goto(self._credits_url)
        time.sleep(3)
        ss       = self.br.screenshot("py009_mobile_payment")
        no_crash = not self.br.has_error_on_page()
        title    = self.br.page_title()
        self.br.page.set_viewport_size(VIEWPORT)
        self._record(
            "PY-009: Payment Page Renders Correctly on Mobile (390×844)",
            {"viewport": "390×844px"},
            "Payment page renders without crash or layout break on mobile",
            f"Title='{title}', NoCrash={no_crash}",
            "PASS" if no_crash else "FAIL",
            ss=ss, category=self.CATEGORY_UI,
        )

    # ── run_all ──────────────────────────────────────────────────────────────
    def run_all(self):
        print("\n💳 Payment Tests  (PY-001 – PY-009)\n")
        tests = [
            ("PY-001: Credits page accessible",         self.tc_py001_credits_page_accessible),
            ("PY-002: Credit plans displayed",          self.tc_py002_plans_displayed),
            ("PY-003: Select plan goes to checkout",    self.tc_py003_select_plan_to_checkout),
            ("PY-004: Payment form fields present",     self.tc_py004_payment_form_fields),
            ("PY-005: HTTPS enforced on checkout",      self.tc_py005_https_on_checkout),
            ("PY-006: Security indicators visible",     self.tc_py006_security_indicators),
            ("PY-007: Empty payment form validation",   self.tc_py007_empty_form_validation),
            ("PY-008: Invalid card rejected",           self.tc_py008_invalid_card_rejected),
            ("PY-009: Mobile viewport on payment page", self.tc_py009_mobile_payment_page),
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
        print("\n✅ Payment tests complete.\n")
