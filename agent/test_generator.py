"""
agent/test_generator.py
─────────────────────────────────────────────────────────────────────────────
Test Generator — Phase 2 of the agent pipeline.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from agent.gemini_client import generate_content, model_candidates
from agent.models import PageSnapshot, TestCase, TestStep

log = logging.getLogger("test_generator")

_SYSTEM_PROMPT = """
You are a senior QA engineer. You have been given the live DOM structure of a
psychic reading platform. Your job is to generate executable test cases that a
Playwright automation script can run directly.

─── VERIFIED SITE ARCHITECTURE ─────────────────────────────────────────────────
These facts have been confirmed by inspecting the live site. Use them exactly.

/login PAGE — TWO TABS, ONE PAGE:
  Sign In tab (default):
    - Email input:    input[placeholder='your@email.com']
    - Password input: input[type='password']
    - Submit button:  button:has-text('Sign In')

  Sign Up tab (click to reveal):
    - Tab button:     button:has-text('Sign Up')   ← click this FIRST to switch tabs
    - First name:     input[placeholder='Enter first name']
    - Last name:      input[placeholder='Enter last name']
    - Phone field:    input[placeholder='Enter mobile number']
      NOTE: The phone field has a custom country-code flag picker (div.login-phone-input).
            The input itself is: input[placeholder='Enter mobile number']
            Do NOT use placeholder='1 (702) 123-4567' — that placeholder does NOT exist.
    - Email input:    input[placeholder='your@email.com']   (shared with Sign In tab)
    - Password:       input[type='password']
    - Submit button:  button:has-text('Sign Up')   ← second click submits the form

/contact PAGE:
  - Name input:     input[placeholder='Your full name']
  - Email input:    input[placeholder='your@email.com']
                    OR input[type='email']
  - Subject:        select                          ← native <select>, default option is "General Inquiry"
                    DO NOT use select[type='select-one'] — that is invalid CSS
  - Message:        textarea[placeholder='Tell us more...']
                    DO NOT use textarea[type='textarea'] — that is invalid CSS
  - Submit button:  button:has-text('Submit Message')

FOOTER LINKS — these open in a NEW TAB (target="_blank"):
  Both footer links open a new browser tab when clicked.
  The executor automatically detects and switches to the new tab.
  So after clicking, assert_url immediately sees the destination URL — no wait needed.

  - "Terms of Service" link → opens /terms in new tab
    Only test from homepage (/), NOT from /login (no footer there).
    Correct pattern:
      {"action": "goto", "url": "https://BASE/"}
      {"action": "click", "selector": "a:has-text('Terms of Service')"}
      {"action": "assert_url", "value": "/terms"}

  - "Money-Back Policy" link → opens /money-back in new tab
    Only test from homepage (/), NOT from /login (no footer there).
    Correct pattern:
      {"action": "goto", "url": "https://BASE/"}
      {"action": "click", "selector": "a:has-text('Money-Back Policy')"}
      {"action": "assert_url", "value": "/money-back"}

COOKIE BANNER (homepage only):
  - Only ONE button exists: button:has-text('Accept All')
  - There is NO "Decline" button — do NOT generate a test for it

NAVIGATION LINKS (confirmed working routes):
  - a:has-text('Psychics')   → /psychics   ✅ real route
  - a:has-text('Pricing')    → /pricing    ✅ real route
  - a:has-text('Contact Us') → /contact    ✅ real route
  - a:has-text('Services')   → same-page scroll anchor, NOT a route — do not assert_url
  - a:has-text('Articles')   → same-page scroll anchor, NOT a route — do not assert_url

─── AVAILABLE ACTIONS ──────────────────────────────────────────────────────────
Each test step uses exactly ONE of these actions:

  goto            — navigate to a URL
                    {"action": "goto", "url": "https://full-url-here"}

  fill            — type text into an input or textarea
                    {"action": "fill", "selector": "CSS", "value": "text"}

  click           — click a button, link, or element
                    {"action": "click", "selector": "CSS"}

  select          — choose an option from a <select> dropdown
                    {"action": "select", "selector": "CSS", "value": "Option Text"}

  wait            — pause for milliseconds (use sparingly, max 2000ms)
                    {"action": "wait", "value": "1000"}

  wait_visible    — wait until an element appears (max 5s)
                    {"action": "wait_visible", "selector": "CSS"}

  assert_visible  — FAIL the test if this element is not on the page
                    {"action": "assert_visible", "selector": "CSS"}

  assert_not_visible — FAIL the test if this element IS on the page
                    {"action": "assert_not_visible", "selector": "CSS"}

  assert_text     — FAIL if element does not contain expected text
                    {"action": "assert_text", "selector": "CSS", "value": "expected substring"}

  assert_url      — FAIL if current URL does not contain this string
                    {"action": "assert_url", "value": "substring"}

  screenshot      — capture a screenshot at this point
                    {"action": "screenshot"}

─── SELECTOR RULES ─────────────────────────────────────────────────────────────
Write selectors that are robust on React/Next.js apps:
  ✅ button:has-text('Login')               — text-based, stable
  ✅ input[placeholder='Enter mobile number'] — placeholder-based, exact match
  ✅ input[type='email']                    — semantic, stable
  ✅ input[type='password']                 — semantic, stable
  ✅ textarea[placeholder='Tell us more...'] — placeholder-based
  ✅ select                                 — plain tag, correct for native <select>
  ❌ select[type='select-one']             — INVALID CSS, never use
  ❌ textarea[type='textarea']             — INVALID CSS, never use
  ❌ .css-1a2b3c4                          — generated class names, fragile
  ❌ div > div > span:nth-child(3)          — path-dependent, fragile

IMPORTANT JSON RULE:
- Prefer single quotes inside CSS selectors so outer JSON double quotes don't break.
- Bad:  {"selector": "button:has-text("Login")"}
- Good: {"selector": "button:has-text('Login')"}

─── COVERAGE REQUIREMENTS ──────────────────────────────────────────────────────
Cover ALL of these thoroughly:

  /login — Sign In form:
    happy path (valid user), happy path (valid expert), invalid password,
    empty submission, SQL injection, XSS in email field

  /login — Sign Up form (click Sign Up tab first):
    happy path (all fields filled including phone), missing required fields,
    invalid email format, edge case (emojis + long name), XSS in name fields

  /contact:
    happy path (name + email + select subject + textarea message),
    missing fields, invalid email, long message edge case, XSS in message

  /psychics:
    click 'Ask a Free Question', click 'Book a Session',
    filter '4.5+', filter 'Online Now'

  homepage (/):
    cookie banner accept, navigate to /psychics, /pricing, /contact

  /pricing:
    visible elements, click 'Ask Your Question', click 'Book Now'

  /join-as-psychic:
    form visible, click Submit Application (empty — triggers validation)

  footer (from homepage):
    Terms of Service → /terms, Money-Back Policy → /money-back

─── PRIORITIES ─────────────────────────────────────────────────────────────────
  HIGH   — auth, payment, core user journeys
  MEDIUM — form validation, navigation, UI visibility
  LOW    — edge cases, cosmetic

─── OUTPUT FORMAT ──────────────────────────────────────────────────────────────
Return ONLY valid JSON. No markdown fences. No explanation. No extra text.
Output ALL test cases completely. Do NOT truncate.

{
  "test_cases": [
    {
      "id": "TC-AI-001",
      "name": "Descriptive name",
      "category": "Authentication | Navigation | Ask a Question | Payment | Security | Form Validation | UI Visibility",
      "priority": "HIGH | MEDIUM | LOW",
      "expected_outcome": "One sentence describing success",
      "inputs": {"field_name": "value"},
      "steps": [
        {"action": "goto", "url": "https://..."},
        {"action": "fill", "selector": "input[placeholder='your@email.com']", "value": "test@example.com"},
        {"action": "click", "selector": "button:has-text('Sign In')"},
        {"action": "screenshot"}
      ]
    }
  ]
}
""".strip()


class TestGenerator:

    def __init__(
        self,
        api_key: str,
        ai_model,
        credentials: dict,
        max_tests: Optional[int] = None,
    ):
        self.api_key     = api_key
        self.ai_models   = model_candidates(ai_model)
        self.ai_model    = self.ai_models[0]
        self.credentials = credentials
        self.max_tests   = max_tests or 30

    # ── Public ────────────────────────────────────────────────────────────────

    def generate(self, snapshots: list[PageSnapshot]) -> list[TestCase]:
        if not snapshots:
            log.warning("No snapshots provided — returning empty list")
            return []
        if not self.api_key:
            log.warning("No Gemini API key — cannot generate test cases")
            return []

        log.info(f"🧠  Sending {len(snapshots)} page snapshots to Gemini …")
        prompt = self._build_prompt(snapshots)
        try:
            raw = self._call_gemini(prompt)
            try:
                test_cases = self._parse_response(raw)
            except json.JSONDecodeError as parse_error:
                log.warning(f"Gemini returned malformed JSON; attempting repair: {parse_error}")
                repaired   = self._repair_json(raw)
                test_cases = self._parse_response(repaired)

            if not test_cases:
                fallback_cases = self._fallback_from_snapshots(snapshots)
                if fallback_cases:
                    log.warning(f"   Using {len(fallback_cases)} local fallback test cases")
                    return fallback_cases

            log.info(f"   Gemini generated {len(test_cases)} test cases")
            return test_cases
        except Exception as e:
            log.error(f"   Gemini generation failed: {e}")
            fallback_cases = self._fallback_from_snapshots(snapshots)
            if fallback_cases:
                log.warning(f"   Generated {len(fallback_cases)} local fallback test cases")
                return fallback_cases
            return []

    # ── Prompt construction ───────────────────────────────────────────────────

    def _build_prompt(self, snapshots: list[PageSnapshot]) -> str:
        pages_json = json.dumps(
            [s.as_dict() for s in snapshots],
            indent=2,
            ensure_ascii=False,
        )

        creds_section = ""
        if self.credentials:
            creds_section = f"""
─── AVAILABLE CREDENTIALS ──────────────────────────────────────────────────────
Use these real credentials for auth tests:
  Regular user email    : {self.credentials.get('user_email', '')}
  Regular user password : {self.credentials.get('user_password', '')}
  Expert/Psychic email  : {self.credentials.get('expert_email', '')}
  Expert/Psychic password: {self.credentials.get('expert_password', '')}
""".strip()

        base_url = next(
            (s.url.rstrip("/") for s in snapshots if s.url and s.error is None),
            "https://psychictells-com.onrender.com"
        )

        return f"""
{_SYSTEM_PROMPT}

{creds_section}

─── BASE URL ────────────────────────────────────────────────────────────────────
{base_url}

─── CRAWLED PAGE STRUCTURE ──────────────────────────────────────────────────────
{pages_json}

─── YOUR TASK ───────────────────────────────────────────────────────────────────
Generate exactly {self.max_tests} test cases covering all the pages and features listed above.

CRITICAL REMINDERS:
1. Sign Up tests: goto /login → click 'Sign Up' tab → fill fields using the
   EXACT placeholders listed in VERIFIED SITE ARCHITECTURE above.
   Phone field selector: input[placeholder='Enter mobile number']
2. Contact form textarea selector: textarea[placeholder='Tell us more...']
   NOT textarea[type='textarea'] — that is invalid CSS.
3. Contact form subject selector: select
   NOT select[type='select-one'] — that is invalid CSS.
4. Footer tests (Terms of Service, Money-Back Policy): ONLY from homepage (/).
   After clicking a footer link add wait 1000 before assert_url.
5. Cookie banner: only 'Accept All' exists — never assert_visible 'Decline'.
6. Number IDs: TC-AI-001, TC-AI-002, ... up to TC-AI-{self.max_tests:03d}
7. Return ONLY the JSON. No markdown. Output ALL {self.max_tests} tests completely.
""".strip()

    # ── Response parsing ──────────────────────────────────────────────────────

    def _parse_response(self, raw: str) -> list[TestCase]:
        data      = _parse_json(raw)
        raw_cases = data.get("test_cases", [])

        if not raw_cases:
            log.warning("Gemini returned empty test_cases list")
            return []

        test_cases = []
        for i, raw_tc in enumerate(raw_cases):
            try:
                tc = TestCase.from_dict(raw_tc)
                tc.generated_by = "gemini"
                if not tc.id or tc.id == "TC-?":
                    tc.id = f"TC-AI-{i+1:03d}"
                test_cases.append(tc)
            except Exception as e:
                log.warning(f"Could not parse test case {i}: {e} — skipping")

        priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        test_cases.sort(key=lambda tc: priority_order.get(tc.priority, 1))
        return test_cases

    # ── Gemini calls ──────────────────────────────────────────────────────────

    def _call_gemini(self, prompt: str) -> str:
        return generate_content(
            api_key=self.api_key,
            ai_models=self.ai_models,
            prompt=prompt,
            generation_config={
                "temperature":      0.2,
                "maxOutputTokens":  16000,
                "responseMimeType": "application/json",
            },
            timeout=120,
            logger=log,
            label="Gemini test generation",
        )

    def _repair_json(self, raw: str) -> str:
        repair_prompt = f"""
The text below is intended to be a JSON object with a top-level "test_cases" array,
but it is malformed. Repair it into valid JSON only.

Rules:
- Return ONLY valid JSON.
- Keep as many complete test cases as possible.
- Escape all double quotes inside string values, or replace inner selector quotes with single quotes.
- Do not add markdown fences or explanations.

Malformed JSON:
{raw}
""".strip()

        return generate_content(
            api_key=self.api_key,
            ai_models=self.ai_models,
            prompt=repair_prompt,
            generation_config={
                "temperature":      0.0,
                "maxOutputTokens":  16000,
                "responseMimeType": "application/json",
            },
            timeout=120,
            logger=log,
            label="Gemini JSON repair",
        )

    def _fallback_from_snapshots(self, snapshots: list[PageSnapshot]) -> list[TestCase]:
        test_cases: list[TestCase] = []

        for snap in snapshots:
            if snap.error:
                continue
            if len(test_cases) >= self.max_tests:
                break

            test_cases.append(TestCase(
                id=f"TC-AI-{len(test_cases) + 1:03d}",
                name=f"Page loads: {snap.url}",
                category="Navigation",
                priority="HIGH" if snap.url.rstrip("/").endswith(("login", "ask")) else "MEDIUM",
                expected_outcome="The page should load and render visible content.",
                inputs={},
                steps=[
                    TestStep(action="goto", url=snap.url),
                    TestStep(action="assert_visible", selector="body"),
                ],
                generated_by="local_fallback",
                source_page=snap.url,
            ))

            for form in snap.forms:
                if len(test_cases) >= self.max_tests:
                    break

                steps  = [TestStep(action="goto", url=snap.url)]
                inputs = {}
                for field in form.fields:
                    value = self._value_for_field(field)
                    if value is None:
                        continue
                    steps.append(TestStep(
                        action="fill",
                        selector=field.selector or field.tag,
                        value=value,
                    ))
                    inputs[field.name or field.label or field.selector or field.tag] = value

                if form.submit_text:
                    safe_text = form.submit_text.replace("'", "\\'")[:40]
                    steps.append(TestStep(action="click",
                                          selector=f"button:has-text('{safe_text}')"))
                steps.append(TestStep(action="screenshot"))

                test_cases.append(TestCase(
                    id=f"TC-AI-{len(test_cases) + 1:03d}",
                    name=f"Form smoke test: {form.submit_text or snap.url}",
                    category="Form Validation",
                    priority="HIGH",
                    expected_outcome="The form should accept input and respond without error.",
                    inputs=inputs,
                    steps=steps,
                    generated_by="local_fallback",
                    source_page=snap.url,
                ))

        return test_cases[: self.max_tests]

    def _value_for_field(self, field) -> Optional[str]:
        selector_text = " ".join([
            field.field_type or "",
            field.name or "",
            field.label or "",
            field.placeholder or "",
            field.selector or "",
        ]).lower()

        if field.tag == "select":
            return field.options[0] if field.options else None
        if field.field_type in {"checkbox", "radio", "submit", "button", "file", "hidden"}:
            return None
        if "email" in selector_text:
            return self.credentials.get("user_email") or "test@example.com"
        if "password" in selector_text:
            return self.credentials.get("user_password") or "Test@1234"
        if "mobile" in selector_text or "phone" in selector_text:
            return "9876543210"
        if field.tag == "textarea" or "question" in selector_text or "message" in selector_text:
            return "This is an automated smoke-test message."
        if "name" in selector_text:
            return self.credentials.get("user_name") or "Test User"
        return "Test input"


# ── Utility ───────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict:
    text = text.strip()
    if "```" in text:
        start = text.find("{")
        end   = text.rfind("}") + 1
        if start != -1 and end > start:
            text = text[start:end]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end   = text.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(text[start:end])
        raise