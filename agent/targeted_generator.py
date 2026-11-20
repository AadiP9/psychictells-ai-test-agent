"""
agent/targeted_generator.py
─────────────────────────────────────────────────────────────────────────────
Targeted Generator — powers the --prompt mode.

Instead of crawling the entire site, it:
  1. Sends the user's plain-English instruction to Gemini.
  2. Gemini decides which pages are relevant and what to test.
  3. The agent visits ONLY those pages to confirm DOM details.
  4. Gemini generates focused, accurate test cases for exactly
     what the user asked for.

Usage:
    gen = TargetedGenerator(page, base_url, api_key, ai_model,
                            credentials, max_tests, timeout)
    snapshots, test_cases = gen.generate("Test login with valid credentials")
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

from playwright.sync_api import Page

from agent.gemini_client import generate_content, model_candidates
from agent.crawler       import SiteCrawler, _EXTRACT_JS
from agent.models        import FormField, PageForm, PageSnapshot, TestCase, TestStep

log = logging.getLogger("targeted")

# ── Verified site facts injected into every targeted prompt ──────────────────
# Same source-of-truth as test_generator.py so selectors are always correct.
_SITE_FACTS = """
─── VERIFIED SITE ARCHITECTURE ─────────────────────────────────────────────────
/login — Sign In tab (default):
  input[placeholder='your@email.com'], input[type='password'], button:has-text('Sign In')

/login — Sign Up tab (click tab first):
  Tab:       button:has-text('Sign Up')
  First name: input[placeholder='Enter first name']
  Last name:  input[placeholder='Enter last name']
  Phone:      input[placeholder='Enter mobile number']   ← custom flag picker, use this exact placeholder
  Email:      input[placeholder='your@email.com']
  Password:   input[type='password']
  Submit:     button:has-text('Sign Up')   ← second click

/contact:
  input[placeholder='Your full name'], input[placeholder='your@email.com'],
  select  (native <select>, options include General Inquiry / Billing / Technical Support / Other),
  textarea[placeholder='Tell us more...'],
  button:has-text('Submit Message')

FOOTER LINKS — these open in a NEW TAB (target="_blank"):
  Both footer links open a new tab. Executor auto-switches to it — no wait needed.
  a:has-text('Terms of Service')   → new tab at /terms    (test from homepage / only)
  a:has-text('Money-Back Policy')  → new tab at /money-back (test from homepage / only)
  Pattern: goto / → click → assert_url (no wait step needed)

COOKIE BANNER (homepage only):
  Only button:has-text('Accept All') exists — no Decline button.

WORKING NAV ROUTES:
  a:has-text('Psychics') → /psychics
  a:has-text('Pricing')  → /pricing
  a:has-text('Contact Us') → /contact

INVALID SELECTORS — never use:
  ❌ select[type='select-one']      (invalid CSS)
  ❌ textarea[type='textarea']      (invalid CSS)
  ❌ input[placeholder='1 (702) 123-4567']  (wrong placeholder)
""".strip()

_ACTIONS_BLOCK = """
─── AVAILABLE ACTIONS ──────────────────────────────────────────────────────────
goto, fill, click, select, wait, wait_visible,
assert_visible, assert_not_visible, assert_text, assert_url, screenshot

Each step:
  {"action": "goto",   "url": "https://..."}
  {"action": "fill",   "selector": "CSS", "value": "text"}
  {"action": "click",  "selector": "CSS"}
  {"action": "select", "selector": "CSS", "value": "Option Text"}
  {"action": "wait",   "value": "1000"}
  {"action": "assert_visible",     "selector": "CSS"}
  {"action": "assert_not_visible", "selector": "CSS"}
  {"action": "assert_text",        "selector": "CSS", "value": "substring"}
  {"action": "assert_url",         "value": "substring"}
  {"action": "screenshot"}

Selector tips:
  ✅ button:has-text('Sign In')   ✅ input[placeholder='your@email.com']
  ✅ input[type='password']       ✅ textarea[placeholder='Tell us more...']
  ✅ select                       ❌ div > span:nth-child(3)
  Single quotes inside selectors: button:has-text('text') not button:has-text("text")
""".strip()


class TargetedGenerator:
    """
    Generates focused test cases from a plain-English user instruction.
    Visits only the pages that are relevant to the instruction.
    """

    def __init__(
        self,
        page: Page,
        base_url: str,
        api_key: str,
        ai_model,
        credentials: dict,
        max_tests: int = 10,
        timeout: int = 15000,
    ):
        self.page        = page
        self.base_url    = base_url.rstrip("/")
        self.api_key     = api_key
        self.ai_models   = model_candidates(ai_model)
        self.credentials = credentials
        self.max_tests   = max_tests
        self.timeout     = timeout

    # ── Public ────────────────────────────────────────────────────────────────

    def generate(self, user_prompt: str) -> tuple[list[PageSnapshot], list[TestCase]]:
        """
        Main entry point.
        Returns (snapshots, test_cases) — same shape as the full pipeline
        so the rest of main.py works unchanged.
        """
        log.info(f"🎯  Targeted mode — interpreting: \"{user_prompt}\"")

        # Step 1: Ask Gemini which pages to visit for this instruction
        pages_to_visit = self._resolve_pages(user_prompt)
        log.info(f"   Pages to visit: {pages_to_visit}")

        # Step 2: Warm up server (same as full crawl)
        self._warmup()

        # Step 3: Visit only the relevant pages and snapshot them
        snapshots = self._snapshot_pages(pages_to_visit)
        loaded    = [s for s in snapshots if s.error is None]
        log.info(f"   Snapshotted {len(loaded)}/{len(snapshots)} pages")

        # Step 4: Generate focused tests from the instruction + snapshots
        test_cases = self._generate_tests(user_prompt, snapshots)

        return snapshots, test_cases

    # ── Step 1: Page resolution ───────────────────────────────────────────────

    def _resolve_pages(self, user_prompt: str) -> list[str]:
        """
        Ask Gemini: given this instruction and site, which pages matter?
        Falls back to a sensible default if Gemini is slow or fails.
        """
        prompt = f"""
You are a QA engineer. A user wants to test a psychic reading platform at {self.base_url}.

Their instruction is:
"{user_prompt}"

The site has these known pages:
  {self.base_url}/              — homepage with cookie banner, nav, CTAs
  {self.base_url}/login         — Sign In + Sign Up tabs on one page
  {self.base_url}/psychics      — psychic listing, filters, Ask/Book buttons
  {self.base_url}/contact       — contact form (name, email, subject, message)
  {self.base_url}/pricing       — pricing plans, Book Now button
  {self.base_url}/join-as-psychic — psychic application form

Which pages should be visited to test what the user asked for?
Select 1–4 pages maximum — only what is truly needed.

Return ONLY valid JSON:
{{"pages": ["https://url1", "https://url2"]}}
""".strip()

        try:
            raw   = self._gemini(prompt, max_tokens=300)
            data  = json.loads(raw.strip())
            pages = data.get("pages", [])
            if pages:
                return pages[:4]
        except Exception as e:
            log.warning(f"   Page resolution failed ({e}) — using keyword fallback")

        return self._keyword_fallback(user_prompt)

    def _keyword_fallback(self, user_prompt: str) -> list[str]:
        """Simple keyword matching when Gemini page resolution fails."""
        prompt_lower = user_prompt.lower()
        pages = []

        if any(w in prompt_lower for w in ["login", "sign in", "signin", "auth", "credential", "password", "logout"]):
            pages.append(f"{self.base_url}/login")
        if any(w in prompt_lower for w in ["sign up", "signup", "register", "registration", "account"]):
            if f"{self.base_url}/login" not in pages:
                pages.append(f"{self.base_url}/login")
        if any(w in prompt_lower for w in ["contact", "message", "inquiry", "support", "form"]):
            pages.append(f"{self.base_url}/contact")
        if any(w in prompt_lower for w in ["psychic", "filter", "listing", "book", "session", "question", "free"]):
            pages.append(f"{self.base_url}/psychics")
        if any(w in prompt_lower for w in ["pricing", "price", "plan", "package"]):
            pages.append(f"{self.base_url}/pricing")
        if any(w in prompt_lower for w in ["home", "homepage", "cookie", "nav", "navigation", "footer"]):
            pages.append(self.base_url)
        if any(w in prompt_lower for w in ["join", "apply", "psychic application"]):
            pages.append(f"{self.base_url}/join-as-psychic")

        # Default to login + homepage if nothing matched
        if not pages:
            pages = [f"{self.base_url}/login", self.base_url]

        return pages

    # ── Step 2: Warm-up ───────────────────────────────────────────────────────

    def _warmup(self) -> None:
        log.info("   ⏳  Warming up server …")
        t0 = time.time()
        try:
            self.page.goto(self.base_url, wait_until="domcontentloaded", timeout=60000)
            log.info(f"   ✅  Server responded in {round(time.time()-t0, 1)}s")
        except Exception as e:
            log.warning(f"   ⚠️  Warm-up incomplete after {round(time.time()-t0, 1)}s: {e}")

    # ── Step 3: Snapshot pages ────────────────────────────────────────────────

    def _snapshot_pages(self, urls: list[str]) -> list[PageSnapshot]:
        snapshots = []
        for url in urls:
            snap = PageSnapshot(url=url, title="")
            try:
                self.page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)
                try:
                    self.page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                try:
                    self.page.wait_for_selector("button, input, form, a", timeout=5000)
                except Exception:
                    pass
                time.sleep(0.5)

                snap.title = self.page.title()[:100]
                data       = self.page.evaluate(_EXTRACT_JS)

                for raw_form in data.get("forms", []):
                    fields = []
                    for rf in raw_form.get("fields", []):
                        fields.append(FormField(
                            tag=rf.get("tag","input"), field_type=rf.get("type","text"),
                            name=rf.get("name",""), id=rf.get("id",""),
                            placeholder=rf.get("placeholder",""), label=rf.get("label",""),
                            selector=rf.get("selector","input"), options=rf.get("options",[]),
                        ))
                    snap.forms.append(PageForm(
                        action=raw_form.get("action",""), method=raw_form.get("method","get"),
                        fields=fields, submit_text=raw_form.get("submit_text","Submit"),
                    ))

                snap.buttons   = data.get("buttons", [])
                snap.links     = data.get("links", [])
                snap.headings  = data.get("headings", [])
                snap.nav_items = data.get("nav", [])
                snap.nav_links = data.get("navLinks", [])

                log.info(f"   ✅  {url}  —  {len(snap.forms)} form(s), {len(snap.buttons)} button(s)")
            except Exception as e:
                snap.error = str(e)[:200]
                log.warning(f"   ❌  {url}: {e}")

            snapshots.append(snap)
        return snapshots

    # ── Step 4: Generate focused tests ────────────────────────────────────────

    def _generate_tests(
        self, user_prompt: str, snapshots: list[PageSnapshot]
    ) -> list[TestCase]:

        pages_json = json.dumps(
            [s.as_dict() for s in snapshots if s.error is None],
            indent=2, ensure_ascii=False,
        )

        creds = (
            f"Regular user  — email: {self.credentials.get('user_email','')} "
            f"/ password: {self.credentials.get('user_password','')}\n"
            f"Expert/Psychic — email: {self.credentials.get('expert_email','')} "
            f"/ password: {self.credentials.get('expert_password','')}"
        )

        prompt = f"""
You are a senior QA engineer generating Playwright test cases.

─── USER INSTRUCTION ────────────────────────────────────────────────────────────
"{user_prompt}"

─── CREDENTIALS ────────────────────────────────────────────────────────────────
{creds}

{_SITE_FACTS}

{_ACTIONS_BLOCK}

─── LIVE DOM SNAPSHOT ───────────────────────────────────────────────────────────
{pages_json}

─── YOUR TASK ───────────────────────────────────────────────────────────────────
Generate up to {self.max_tests} test cases that directly address the user's instruction.

Coverage rules based on what the user asked for:
- If they mention "login" or "sign in": test happy path (valid user), happy path (valid expert),
  invalid password, empty fields, SQL injection, XSS.
- If they mention "sign up" or "register": test happy path (all fields), missing fields,
  invalid email, edge case (emoji/long), XSS.
- If they mention "contact": test happy path, missing fields, invalid email, long message, XSS.
- If they mention "filter" or "psychics": test each filter button, Ask a Free Question, Book a Session.
- If they mention "navigation": test working nav links only (Psychics, Pricing, Contact Us).
- For any area: always include at least 1 happy path, 1 invalid/empty test, 1 security test.

Test ID format: TC-AI-001, TC-AI-002, ...

Return ONLY valid JSON, no markdown, no explanation:
{{
  "test_cases": [
    {{
      "id": "TC-AI-001",
      "name": "Descriptive test name",
      "category": "Authentication | Navigation | Form Validation | Security | ...",
      "priority": "HIGH | MEDIUM | LOW",
      "expected_outcome": "One sentence describing what success looks like",
      "inputs": {{"field": "value"}},
      "steps": [
        {{"action": "goto", "url": "https://..."}},
        {{"action": "fill", "selector": "input[placeholder='your@email.com']", "value": "test@example.com"}},
        {{"action": "click", "selector": "button:has-text('Sign In')"}},
        {{"action": "screenshot"}}
      ]
    }}
  ]
}}
""".strip()

        try:
            raw = self._gemini(prompt, max_tokens=16000, temperature=0.2, timeout=120)
            return self._parse(raw)
        except Exception as e:
            log.error(f"   Test generation failed: {e}")
            return []

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _gemini(
        self,
        prompt: str,
        max_tokens: int = 8000,
        temperature: float = 0.1,
        timeout: int = 30,
    ) -> str:
        return generate_content(
            api_key=self.api_key,
            ai_models=self.ai_models,
            prompt=prompt,
            generation_config={
                "temperature":      temperature,
                "maxOutputTokens":  max_tokens,
                "responseMimeType": "application/json",
            },
            timeout=timeout,
            logger=log,
            label="Targeted generation",
        )

    def _parse(self, raw: str) -> list[TestCase]:
        text = raw.strip()
        if "```" in text:
            start = text.find("{"); end = text.rfind("}") + 1
            if start != -1 and end > start:
                text = text[start:end]
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{"); end = text.rfind("}") + 1
            if start != -1 and end > start:
                data = json.loads(text[start:end])
            else:
                raise

        raw_cases  = data.get("test_cases", [])
        test_cases = []
        priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

        for i, raw_tc in enumerate(raw_cases):
            try:
                tc = TestCase.from_dict(raw_tc)
                tc.generated_by = "gemini-targeted"
                if not tc.id or tc.id == "TC-?":
                    tc.id = f"TC-AI-{i+1:03d}"
                test_cases.append(tc)
            except Exception as e:
                log.warning(f"   Could not parse test case {i}: {e}")

        test_cases.sort(key=lambda tc: priority_order.get(tc.priority, 1))
        log.info(f"   Parsed {len(test_cases)} test cases from Gemini response")
        return test_cases