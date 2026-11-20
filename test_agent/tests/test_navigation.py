import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from test_agent.browser_controller import BrowserController
from test_agent.reporter import TestReporter
from config import BASE_URL, PSYCHICS_URL, SELECTORS


class NavigationTests:
    CATEGORY = "Navigation"

    def __init__(self, browser: BrowserController, reporter: TestReporter):
        self.br  = browser
        self.rep = reporter

    def _record(self, name, input_data, expected, actual, status,
                rt=0, ss="", notes=""):
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

    # ── N-01  Homepage load speed ──────────────────────────────────────────────
    def tc_n01_page_load_speed(self):
        t0  = time.time()
        nav = self.br.goto(BASE_URL)
        time.sleep(2)
        rt  = round((time.time() - t0) * 1000)
        ss  = self.br.screenshot("nav01_load_speed")
        self._record(
            "N-01: Homepage Load Speed < 5s",
            {"url": BASE_URL, "threshold_ms": 5000},
            "Page loads in < 5 000 ms",
            f"LoadTime={rt} ms",
            "PASS" if rt < 5000 else "FAIL",
            rt, ss,
        )

    # ── N-02  Page title present ───────────────────────────────────────────────
    def tc_n02_title_present(self):
        self.br.goto(BASE_URL)
        time.sleep(2)
        title = self.br.page_title()
        ss    = self.br.screenshot("nav02_title")
        self._record(
            "N-02: Homepage Page Title Present",
            {"url": BASE_URL},
            "Non-empty page title (> 3 chars)",
            f"Title='{title}'",
            "PASS" if (title and len(title) > 3) else "FAIL",
            0, ss,
        )

    # ── N-03  HTTP → HTTPS redirect ───────────────────────────────────────────
    def tc_n03_https_redirect(self):
        http_url = BASE_URL.replace("https://", "http://")
        self.br.goto(http_url)
        time.sleep(1.5)
        final = self.br.current_url()
        ss    = self.br.screenshot("nav03_https")
        self._record(
            "N-03: HTTP → HTTPS Redirect",
            {"url": http_url},
            "Final URL uses HTTPS",
            f"FinalURL={final}",
            "PASS" if final.startswith("https://") else "FAIL",
            0, ss,
        )

    # ── N-04  /psychics page load speed ───────────────────────────────────────
    def tc_n04_psychics_page_speed(self):
        t0  = time.time()
        nav = self.br.goto(PSYCHICS_URL)
        time.sleep(2)
        rt  = round((time.time() - t0) * 1000)
        ss  = self.br.screenshot("nav04_psychics_speed")
        ok  = nav.get("status", 0) in (200, 301, 302)
        self._record(
            "N-04: /psychics Page Load Speed < 6s",
            {"url": PSYCHICS_URL, "threshold_ms": 6000},
            "Page loads in < 6 000 ms",
            f"LoadTime={rt} ms, Status={nav.get('status', 0)}",
            "PASS" if (ok and rt < 6000) else "FAIL",
            rt, ss,
        )

    # ── N-05  404 handling ─────────────────────────────────────────────────────
    def tc_n05_404_handling(self):
        url  = f"{BASE_URL}/this-page-does-not-exist-xyz-99999"
        nav  = self.br.goto(url)
        time.sleep(1)
        ss     = self.br.screenshot("nav05_404")
        title  = self.br.page_title()
        status = nav.get("status", 0)
        graceful = status in (404, 200) and not self.br.has_error_on_page()
        self._record(
            "N-05: Unknown URL Handled Gracefully (404)",
            {"url": url},
            "Custom 404 page or graceful redirect; no crash",
            f"Status={status}, Title='{title}'",
            "PASS" if graceful else "FAIL",
            0, ss,
        )

    # ── N-06  'Ask a Free Question' button in DOM ─────────────────────────────
    def tc_n06_ask_button_in_dom(self):
        self.br.goto(BASE_URL)
        time.sleep(2)
        ss    = self.br.screenshot("nav06_ask_btn_dom")
        found = False
        text  = ""
        for sel in SELECTORS["ask_btn_fallbacks"]:
            try:
                el = self.br.page.query_selector(sel)
                if el:
                    text  = el.inner_text().strip()
                    found = True
                    break
            except Exception:
                continue
        self._record(
            "N-06: 'Ask a Free Question' Button Found in DOM",
            {"selectors_tried": SELECTORS["ask_btn_fallbacks"]},
            "Button with 'Ask' text is present in DOM",
            f"Found={found}, Text='{text}'",
            "PASS" if found else "FAIL",
            0, ss,
        )

    # ── N-07  /psychics → back → homepage ─────────────────────────────────────
    def tc_n07_back_navigation(self):
        self.br.goto(BASE_URL)
        time.sleep(1)
        self.br.goto(PSYCHICS_URL)
        time.sleep(1)
        self.br.page.go_back()
        time.sleep(1.5)
        ss    = self.br.screenshot("nav07_back")
        url   = self.br.current_url()
        no_cr = not self.br.has_error_on_page()
        self._record(
            "N-07: Browser Back from /psychics Returns to Homepage",
            {"action": "Navigate /psychics → back"},
            "Returns to homepage URL",
            f"FinalURL='{url}', NoCrash={no_cr}",
            "PASS" if (BASE_URL in url and no_cr) else "FAIL",
            0, ss,
        )

    # ── N-08  Favicon present ─────────────────────────────────────────────────
    def tc_n08_favicon_present(self):
        self.br.goto(BASE_URL)
        time.sleep(1)
        favicon_url = BASE_URL + "/favicon.ico"
        nav  = self.br.goto(favicon_url)
        ss   = self.br.screenshot("nav08_favicon")
        ok   = nav.get("status", 0) in (200, 301, 302)
        self.br.goto(BASE_URL)  # restore page
        self._record(
            "N-08: Favicon Accessible",
            {"url": favicon_url},
            "favicon.ico returns HTTP 200",
            f"Status={nav.get('status', 0)}",
            "PASS" if ok else "FAIL",
            0, ss,
        )

    # ── N-09  Console error-free page load ────────────────────────────────────
    def tc_n09_no_console_errors(self):
        """Capture JS console errors during homepage load."""
        console_errors = []

        def on_console(msg):
            if msg.type == "error":
                console_errors.append(msg.text)

        self.br.page.on("console", on_console)
        self.br.goto(BASE_URL)
        time.sleep(2)
        self.br.page.remove_listener("console", on_console)
        ss = self.br.screenshot("nav09_console")

        self._record(
            "N-09: Homepage Loads Without JS Console Errors",
            {"url": BASE_URL},
            "0 JS console errors on page load",
            f"ErrorCount={len(console_errors)}, Errors={console_errors[:3]}",
            "PASS" if len(console_errors) == 0 else "FAIL",
            0, ss,
            notes="Minor third-party errors may be acceptable; review manually.",
        )

    def run_all(self):
        print("\n🌐 Navigation Tests  (N-01 – N-09)\n")
        tests = [
            ("N-01: Homepage load speed",             self.tc_n01_page_load_speed),
            ("N-02: Page title present",              self.tc_n02_title_present),
            ("N-03: HTTPS redirect",                  self.tc_n03_https_redirect),
            ("N-04: /psychics page speed",            self.tc_n04_psychics_page_speed),
            ("N-05: 404 handling",                    self.tc_n05_404_handling),
            ("N-06: Ask button in DOM",               self.tc_n06_ask_button_in_dom),
            ("N-07: Back navigation integrity",       self.tc_n07_back_navigation),
            ("N-08: Favicon accessible",              self.tc_n08_favicon_present),
            ("N-09: No JS console errors on load",    self.tc_n09_no_console_errors),
        ]
        for label, fn in tests:
            print(f"  ▶ {label}")
            try:
                fn()
            except Exception as exc:
                print(f"    ⚠️  {exc}")
                self.rep.add_result(
                    test_name=label, input_data={},
                    expected_result="Completes",
                    actual_result=str(exc),
                    status="ERROR",
                    category=self.CATEGORY,
                )
