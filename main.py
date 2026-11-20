"""
main.py
─────────────────────────────────────────────────────────────────────────────
PsychicTells AI Test Agent — Single Entry Point

Modes:
  Full site mode (default):
    python main.py
    → Crawls the entire site, Gemini generates tests from DOM snapshots.

  Targeted mode (new):
    python main.py --prompt "Test login functionality with valid credentials"
    → Skips the crawl. Gemini reads your instruction, visits only the
      relevant pages, and generates focused tests for exactly what you asked.

  Other options:
    python main.py --headless false      # visible browser
    python main.py --max-tests 20        # cap number of generated tests
    python main.py --site psychictells   # specify site profile
─────────────────────────────────────────────────────────────────────────────
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# ── CLI ───────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(
    description="PsychicTells AI Test Agent",
    formatter_class=argparse.RawTextHelpFormatter,
)
parser.add_argument("--site",       default=None,    help="Site profile (default: psychictells)")
parser.add_argument("--max-tests",  default=30,      type=int,
                    help="Max test cases to generate (default: 30)")
parser.add_argument("--headless",   default="true",  help="true | false (default: true)")
parser.add_argument("--slow",       default="60",    type=int,
                    help="Playwright slow-motion delay in ms (default: 60)")
parser.add_argument("--timeout",    default="15000", type=int,
                    help="Element wait timeout in ms (default: 15000)")
parser.add_argument(
    "--prompt",
    default=None,
    metavar="INSTRUCTION",
    help=(
        "Natural language instruction for targeted testing.\n"
        "Skips the full site crawl and focuses only on what you describe.\n"
        'Example: --prompt "Test login with valid and invalid credentials"\n'
        'Example: --prompt "Test the contact form happy path and edge cases"\n'
        'Example: --prompt "Verify psychics page filters work correctly"'
    ),
)
args = parser.parse_args()

if args.site:
    os.environ["SITE_PROFILE"] = args.site

import config
config.HEADLESS = args.headless.lower() == "true"
config.SLOW_MO  = args.slow
config.TIMEOUT  = args.timeout

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-14s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

# ── Agent modules ─────────────────────────────────────────────────────────────
from agent.crawler           import SiteCrawler
from agent.test_generator    import TestGenerator
from agent.targeted_generator import TargetedGenerator
from agent.executor          import TestExecutor
from agent.reporter          import AgentReporter
from playwright.sync_api     import sync_playwright


def main():
    run_id     = datetime.now().strftime("%Y%m%d_%H%M%S")
    banner     = "=" * 66
    is_targeted = bool(args.prompt)

    print(banner)
    print("  🔮  PsychicTells — AI Test Agent")
    print(banner)
    print(f"  Site      : {config.BASE_URL}")
    print(f"  Mode      : {'🎯 Targeted' if is_targeted else '🌐 Full site crawl'}")
    if is_targeted:
        print(f"  Prompt    : {args.prompt}")
    print(f"  Headless  : {config.HEADLESS}")
    print(f"  Max tests : {args.max_tests}")
    print(f"  Run ID    : {run_id}")
    print(f"  Gemini    : {'✓ API key set' if config.GEMINI_API_KEY else '✗ No key'}")
    print(f"  AI model  : {config.AI_MODELS[0]} (+{len(config.AI_MODELS) - 1} fallback(s))")
    print(banner + "\n")

    if not config.GEMINI_API_KEY:
        print("❌  GEMINI_API_KEY is not set in your .env file.")
        if not is_targeted:
            print("    Falling back to existing manual test suites …\n")
            _run_fallback()
        return

    credentials = {
        "user_email":      config.USER_EMAIL,
        "user_password":   config.USER_PASSWORD,
        "expert_email":    config.EXPERT_EMAIL,
        "expert_password": config.EXPERT_PASSWORD,
    }

    all_results     = []
    snapshots       = []
    generated_count = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=config.HEADLESS, slow_mo=config.SLOW_MO)
        context = browser.new_context(viewport=config.VIEWPORT)
        page    = context.new_page()
        page.set_default_timeout(config.TIMEOUT)

        try:
            if is_targeted:
                # ── TARGETED MODE ─────────────────────────────────────────────
                snapshots, test_cases = _run_targeted(
                    page, credentials, args.prompt, args.max_tests
                )
            else:
                # ── FULL SITE MODE ────────────────────────────────────────────
                snapshots, test_cases = _run_full_crawl(
                    page, credentials, args.max_tests
                )

            generated_count = len(test_cases)

            if not test_cases:
                print("  ⚠️   No test cases generated.")
                if not is_targeted:
                    print("       Running fallback …")
                    try:
                        browser.close()
                    except Exception:
                        pass
                    _run_fallback()
                return

            # ── EXECUTE ───────────────────────────────────────────────────────
            print(f"\n{'─'*66}")
            print(f"  Phase {'2' if is_targeted else '3'} — EXECUTE  ({generated_count} tests)")
            print(f"{'─'*66}\n")

            executor    = TestExecutor(page=page, timeout=config.TIMEOUT)
            all_results = executor.run_all(test_cases)

        finally:
            try:
                browser.close()
            except Exception:
                pass

    # ── REPORT ────────────────────────────────────────────────────────────────
    print(f"\n{'─'*66}")
    print(f"  Phase {'3' if is_targeted else '4'} — REPORT")
    print(f"{'─'*66}\n")

    reporter = AgentReporter(run_id=run_id, site_url=config.BASE_URL)
    reporter.save(all_results, snapshots, generated_count=generated_count)

    passed = sum(1 for r in all_results if r.status == "PASS")
    failed = len(all_results) - passed
    rate   = round(passed / len(all_results) * 100, 1) if all_results else 0.0

    print(f"  {'='*62}")
    print(f"  {'  PASSED':<20} {passed}")
    print(f"  {'  FAILED / ERROR':<20} {failed}")
    print(f"  {'  PASS RATE':<20} {rate}%")
    print(f"  {'='*62}")
    print(f"\n  📄  Reports saved:")
    print(f"      JSON  →  {reporter.json_path}")
    print(f"      HTML  →  {reporter.html_path}")
    print(f"\n  Open the HTML report in your browser for the full visual summary.\n")


# ── Targeted mode ──────────────────────────────────────────────────────────────

def _run_targeted(page, credentials, prompt, max_tests):
    """
    Targeted mode: Gemini reads the user's plain-English instruction,
    decides which pages are relevant, crawls only those, and generates
    focused tests. Much faster than a full crawl.
    """
    print(f"{'─'*66}")
    print("  Phase 1 — TARGETED GENERATE  (Gemini interpreting your prompt)")
    print(f"{'─'*66}\n")

    gen = TargetedGenerator(
        page        = page,
        base_url    = config.BASE_URL,
        api_key     = config.GEMINI_API_KEY,
        ai_model    = config.AI_MODELS,
        credentials = credentials,
        max_tests   = max_tests,
        timeout     = config.TIMEOUT,
    )
    snapshots, test_cases = gen.generate(prompt)

    print(f"\n  ✅  Generated {len(test_cases)} targeted test cases:\n")
    by_cat: dict[str, list] = {}
    for tc in test_cases:
        by_cat.setdefault(tc.category, []).append(tc)
    for cat, tcs in sorted(by_cat.items()):
        ids  = ", ".join(tc.id for tc in tcs[:5])
        more = f" (+{len(tcs)-5} more)" if len(tcs) > 5 else ""
        print(f"    [{cat}]  {len(tcs)} tests  —  {ids}{more}")

    return snapshots, test_cases


# ── Full crawl mode ────────────────────────────────────────────────────────────

def _run_full_crawl(page, credentials, max_tests):
    """Original full-site crawl + generate pipeline."""

    print(f"{'─'*66}")
    print("  Phase 1 — CRAWL  (discovering site structure)")
    print(f"{'─'*66}\n")

    crawler   = SiteCrawler(
        page           = page,
        base_url       = config.BASE_URL,
        gemini_api_key = config.GEMINI_API_KEY,
        ai_model       = config.AI_MODELS,
        timeout        = config.TIMEOUT,
    )
    snapshots = crawler.run()
    loaded    = [s for s in snapshots if s.error is None]
    print(f"\n  ✅  Crawl complete: {len(loaded)}/{len(snapshots)} pages loaded\n")

    if not loaded:
        print("  ❌  No pages could be loaded. Check the site URL and your connection.")
        return snapshots, []

    print(f"{'─'*66}")
    print("  Phase 2 — GENERATE  (Gemini writing test cases)")
    print(f"{'─'*66}\n")

    generator  = TestGenerator(
        api_key     = config.GEMINI_API_KEY,
        ai_model    = config.AI_MODELS,
        credentials = credentials,
        max_tests   = max_tests,
    )
    test_cases = generator.generate(snapshots)

    if test_cases:
        print(f"\n  ✅  Gemini generated {len(test_cases)} test cases:\n")
        by_cat: dict[str, list] = {}
        for tc in test_cases:
            by_cat.setdefault(tc.category, []).append(tc)
        for cat, tcs in sorted(by_cat.items()):
            ids  = ", ".join(tc.id for tc in tcs[:5])
            more = f" (+{len(tcs)-5} more)" if len(tcs) > 5 else ""
            print(f"    [{cat}]  {len(tcs)} tests  —  {ids}{more}")

    return snapshots, test_cases


# ── Fallback ──────────────────────────────────────────────────────────────────

def _run_fallback():
    print("  Running fallback: existing manual test suites …\n")
    try:
        from test_agent.ai_input_generator import AITestInputGenerator
        from test_agent.reporter           import TestReporter

        reporter  = TestReporter(f"{config.SITE_DISPLAY} — Fallback Run", site_url=config.BASE_URL)
        generator = AITestInputGenerator()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=config.HEADLESS, slow_mo=config.SLOW_MO)
            context = browser.new_context(viewport=config.VIEWPORT)
            page    = context.new_page()
            page.set_default_timeout(config.TIMEOUT)

            class _SyncBrowser:
                def __init__(self, p):
                    self.page    = p
                    self.context = context

                def goto(self, url, **kw):
                    try:
                        resp = self.page.goto(url, **kw)
                        return {"ok": resp.ok if resp else False, "status": resp.status if resp else 0,
                                "elapsed_ms": 0, "url": self.page.url}
                    except Exception as exc:
                        return {"ok": False, "status": 0, "elapsed_ms": 0, "error": str(exc), "url": url}

                def get_page(self): return self.page

                def fill(self, selector, value):
                    try:
                        self.page.locator(selector).first.fill(value); return True
                    except Exception:
                        return False

                def is_visible(self, selector, timeout=5000):
                    try:
                        self.page.locator(selector).first.wait_for(state="visible", timeout=timeout); return True
                    except Exception:
                        return False

                def screenshot(self, name):
                    try:
                        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
                        path = os.path.join(config.SCREENSHOTS_DIR, f"{safe}.png")
                        self.page.screenshot(path=path, full_page=True); return path
                    except Exception:
                        return ""

                def page_title(self):
                    try: return self.page.title()
                    except Exception: return ""

                def current_url(self):
                    try: return self.page.url
                    except Exception: return ""

                def has_error_on_page(self):
                    try:
                        title = self.page.title().lower()
                        return any(k in title for k in ["error", "500", "404", "not found", "oops"])
                    except Exception:
                        return True

            shim = _SyncBrowser(page)

            from test_agent.tests.test_navigation   import NavigationTests
            from test_agent.tests.test_ask_question import AskQuestionTests
            from test_agent.tests.test_user_auth    import UserAuthTests

            try: NavigationTests(shim, reporter).run_all()
            except Exception as e: print(f"  ⚠️  Navigation suite: {e}")
            try: AskQuestionTests(shim, reporter, generator).run_all()
            except Exception as e: print(f"  ⚠️  Ask-question suite: {e}")
            try: UserAuthTests(shim, reporter).run_all()
            except Exception as e: print(f"  ⚠️  Auth suite: {e}")

            browser.close()

        from test_agent.intelligent_reporter import IntelligentReporter
        intel = IntelligentReporter(reporter, gemini_api_key=config.GEMINI_API_KEY,
                                    site_display_name=config.SITE_DISPLAY)
        intel.save_all()
        print(f"\n  📄  Fallback report: {config.HTML_REPORT}")
    except Exception as e:
        print(f"  ❌  Fallback also failed: {e}")


if __name__ == "__main__":
    main()