"""
agent/crawler.py
─────────────────────────────────────────────────────────────────────────────
Site Crawler — Phase 1 of the agent pipeline.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Page

from agent.gemini_client import generate_content, model_candidates
from agent.models import FormField, PageForm, PageSnapshot

log = logging.getLogger("crawler")

# How long to wait for a cold-start host (Render free tier etc.) to wake up
_WARMUP_TIMEOUT = 60000

_EXTRACT_JS = r"""
() => {
    const forms = Array.from(document.querySelectorAll('form')).map(form => {
        const fields = Array.from(
            form.querySelectorAll('input:not([type="hidden"]):not([type="submit"]), textarea, select')
        ).map(el => {
            const id = el.id || '';
            const labelEl = id
                ? document.querySelector(`label[for="${id}"]`)
                : el.closest('label') || el.previousElementSibling;
            const labelText = labelEl ? labelEl.textContent.trim().slice(0, 60) : '';

            let selector = '';
            if (id)            selector = `#${id}`;
            else if (el.name)  selector = `[name="${el.name}"]`;
            else               selector = el.tagName.toLowerCase() + (el.type ? `[type="${el.type}"]` : '');

            const options = el.tagName === 'SELECT'
                ? Array.from(el.options).map(o => o.text.trim()).filter(Boolean)
                : [];

            return {
                tag:         el.tagName.toLowerCase(),
                type:        el.type || '',
                name:        el.name || '',
                id,
                placeholder: el.placeholder || '',
                label:       labelText,
                selector,
                options,
            };
        });

        const submitEl = form.querySelector('[type="submit"], button[type="submit"], button:not([type])');
        return {
            action:      form.action || '',
            method:      (form.method || 'get').toLowerCase(),
            fields,
            submit_text: submitEl ? submitEl.textContent.trim().slice(0, 40) : 'Submit',
        };
    });

    const buttons = Array.from(document.querySelectorAll('button, [role="button"], a.btn, a.button'))
        .slice(0, 25)
        .map(el => {
            const text = el.textContent.trim().replace(/\s+/g, ' ').slice(0, 50);
            const id   = el.id || '';
            let selector = '';
            if (id) {
                selector = `#${id}`;
            } else if (text) {
                const tag = el.tagName.toLowerCase();
                selector = `${tag}:has-text("${text.slice(0, 30)}")`;
            } else {
                selector = el.tagName.toLowerCase();
            }
            return { text, type: el.type || el.tagName.toLowerCase(), selector };
        })
        .filter(b => b.text);

    const origin = window.location.origin;
    const links = Array.from(document.querySelectorAll('a[href]'))
        .map(a => ({ text: a.textContent.trim().replace(/\s+/g, ' ').slice(0, 50), href: a.href }))
        .filter(l => l.href.startsWith(origin) && !l.href.includes('#') && l.text)
        .slice(0, 30);

    const headings = Array.from(document.querySelectorAll('h1, h2, h3'))
        .map(h => h.textContent.trim().replace(/\s+/g, ' ').slice(0, 80))
        .filter(Boolean)
        .slice(0, 10);

    const nav = Array.from(document.querySelectorAll('nav a, header a, [role="navigation"] a'))
        .map(a => a.textContent.trim().replace(/\s+/g, ' ').slice(0, 40))
        .filter(Boolean)
        .slice(0, 15);

    // Full href for each nav link so Gemini can tell which are hash anchors vs real routes
    const navLinks = Array.from(document.querySelectorAll('nav a[href], header a[href], [role="navigation"] a[href]'))
        .map(a => ({ text: a.textContent.trim().replace(/\s+/g, ' ').slice(0, 40), href: a.href }))
        .filter(l => l.text)
        .slice(0, 20);

    return { forms, buttons, links, headings, nav, navLinks };
}
"""


class SiteCrawler:

    def __init__(
        self,
        page: Page,
        base_url: str,
        gemini_api_key: str,
        ai_model: str,
        timeout: int = 15000,
    ):
        self.page      = page
        self.base_url  = base_url.rstrip("/")
        self.api_key   = gemini_api_key
        self.ai_models = model_candidates(ai_model)
        self.ai_model  = self.ai_models[0]
        self.timeout   = timeout
        self._domain   = urlparse(base_url).netloc

    # ── Public ────────────────────────────────────────────────────────────────

    def run(self) -> list[PageSnapshot]:
        log.info("🕸️   Starting site crawl …")

        # Warm up first — free-tier hosts (Render, Fly, Railway) spin down after
        # inactivity and need up to 60 s to respond. Without this, every subsequent
        # page.goto() times out at 15 s and we get 0 crawled pages.
        self._warmup()

        all_links = self._collect_homepage_links()
        log.info(f"   Found {len(all_links)} internal links on homepage")

        urls_to_crawl = self._pick_pages_to_crawl(all_links)
        log.info(f"   Gemini selected {len(urls_to_crawl)} pages to crawl: {urls_to_crawl}")

        snapshots: list[PageSnapshot] = []
        for url in urls_to_crawl:
            snap = self._crawl_page(url)
            snapshots.append(snap)
            status = "✅" if snap.error is None else "❌"
            log.info(f"   {status}  {url}  —  {len(snap.forms)} form(s), "
                     f"{len(snap.buttons)} button(s)")

        return snapshots

    # ── Warm-up ───────────────────────────────────────────────────────────────

    def _warmup(self) -> None:
        """
        Hit the homepage with a 60-second timeout so free-tier hosts (Render,
        Railway, Fly) have time to wake from their sleep before we start crawling.
        After a successful warm-up the server is awake and all subsequent
        page.goto() calls use the normal 15-second timeout.
        """
        import time as _time
        log.info("   ⏳  Warming up server (free-tier hosts may need up to 60 s) …")
        t0 = _time.time()
        try:
            self.page.goto(
                self.base_url,
                wait_until="domcontentloaded",
                timeout=_WARMUP_TIMEOUT,
            )
            log.info(f"   ✅  Server responded in {round(_time.time() - t0, 1)}s")
        except Exception as e:
            log.warning(
                f"   ⚠️  Warm-up did not complete after "
                f"{round(_time.time() - t0, 1)}s: {e}"
            )
            log.warning("       Continuing anyway — pages may still load individually.")

    # ── Step 1: Collect homepage links ────────────────────────────────────────

    def _collect_homepage_links(self) -> list[dict]:
        try:
            # After _warmup() the page is already on base_url — only re-navigate
            # if something drifted (e.g. a redirect moved us elsewhere)
            from urllib.parse import urlparse as _up
            if _up(self.page.url).netloc != self._domain:
                self.page.goto(
                    self.base_url, wait_until="domcontentloaded", timeout=self.timeout
                )
            try:
                self.page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            time.sleep(0.5)

            data  = self.page.evaluate(_EXTRACT_JS)
            links = data.get("links", [])
            seen, unique = set(), []
            for l in links:
                if l["href"] not in seen:
                    seen.add(l["href"])
                    unique.append(l)
            return unique
        except Exception as e:
            log.warning(f"Homepage crawl failed: {e}")
            return []

    # ── Step 2: Gemini page selection ─────────────────────────────────────────

    def _pick_pages_to_crawl(self, links: list[dict]) -> list[str]:
        if not self.api_key:
            return self._default_urls()

        links_text = "\n".join(f"  - [{l['text']}] {l['href']}" for l in links[:30])

        prompt = f"""
You are a QA engineer crawling a web application at {self.base_url}.

I found these internal pages on the homepage:
{links_text or "(no links found)"}

IMPORTANT SITE NOTE:
- This site has Sign In and Sign Up as TWO TABS on a SINGLE PAGE at /login.
  There is NO separate /signup route — it is the same page as /login.
  Do NOT select /signup as a separate URL to crawl.

Always include these base URLs:
  - {self.base_url}  (homepage)
  - {self.base_url}/login  (contains BOTH the Sign In form AND the Sign Up form as tabs)
  - {self.base_url}/psychics
  - {self.base_url}/contact

Select up to 6 pages that are most important for generating thorough test cases.
Prioritise pages with:
  - User-facing forms (login/signup are both on /login, contact, ask a question)
  - Core navigation pages (home, listing pages)
  - Pages where things can go wrong (payment, profile, chat)

Do NOT include /signup — it is not a real separate page on this site.

Return ONLY valid JSON, no explanation:
{{
  "pages": [
    {{"url": "https://...", "reason": "why this page matters for testing"}}
  ]
}}
""".strip()

        try:
            raw   = self._gemini(prompt)
            data  = _parse_json(raw)
            pages = data.get("pages", [])

            # Filter out any /signup the model hallucinates anyway
            urls = [
                p["url"] for p in pages
                if p.get("url") and not p["url"].rstrip("/").endswith("/signup")
            ]

            for entry in pages:
                url = entry.get("url", "")
                if not url.rstrip("/").endswith("/signup"):
                    log.info(f"   Gemini chose: {url} — {entry.get('reason', '')}")

            return urls if urls else self._default_urls()
        except Exception as e:
            log.warning(f"Gemini page selection failed ({e}) — using defaults")
            return self._default_urls()

    def _default_urls(self) -> list[str]:
        # NOTE: /login hosts both Sign In and Sign Up tabs — no separate /signup
        return [
            self.base_url,
            f"{self.base_url}/login",
            f"{self.base_url}/psychics",
            f"{self.base_url}/contact",
            f"{self.base_url}/join-as-psychic",
        ]

    # ── Step 3: Crawl one page ────────────────────────────────────────────────

    def _crawl_page(self, url: str) -> PageSnapshot:
        """Visit a URL and extract its DOM structure into a PageSnapshot."""
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
                        tag         = rf.get("tag", "input"),
                        field_type  = rf.get("type", "text"),
                        name        = rf.get("name", ""),
                        id          = rf.get("id", ""),
                        placeholder = rf.get("placeholder", ""),
                        label       = rf.get("label", ""),
                        selector    = rf.get("selector", "input"),
                        options     = rf.get("options", []),
                    ))
                snap.forms.append(PageForm(
                    action      = raw_form.get("action", ""),
                    method      = raw_form.get("method", "get"),
                    fields      = fields,
                    submit_text = raw_form.get("submit_text", "Submit"),
                ))

            snap.buttons   = data.get("buttons", [])
            snap.links     = data.get("links", [])
            snap.headings  = data.get("headings", [])
            snap.nav_items = data.get("nav", [])
            snap.nav_links = data.get("navLinks", [])

        except Exception as e:
            snap.error = str(e)[:200]
            log.warning(f"   Failed to crawl {url}: {e}")

        return snap

    # ── Gemini helper ─────────────────────────────────────────────────────────

    def _gemini(self, prompt: str) -> str:
        return generate_content(
            api_key=self.api_key,
            ai_models=self.ai_models,
            prompt=prompt,
            generation_config={
                "temperature": 0.1,
                "maxOutputTokens": 1000,
                "responseMimeType": "application/json",
            },
            timeout=30,
            logger=log,
            label="Gemini page selection",
        )


def _parse_json(text: str) -> dict:
    text = text.strip()
    if "```" in text:
        start = text.find("{")
        end   = text.rfind("}") + 1
        if start != -1 and end > start:
            text = text[start:end]
    return json.loads(text)