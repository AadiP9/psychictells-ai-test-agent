"""
site_navigator.py
─────────────────────────────────────────────────────────────────────────────
Shared Navigation Helper — Single Source of Truth

BUG THIS FILE ORIGINALLY FIXED:
Three different test files each had their own copy of "find a real content
page (e.g. psychic profile) on the listing page" logic. All three copies
were too permissive — they accepted ANY same-domain URL that wasn't the
exact listing/home page, which meant unrelated nav links like /services,
/about, /join-as-psychic were wrongly treated as profile pages.

REUSABILITY UPDATE:
The domain and non-profile-page blocklist used to be hardcoded constants
in this file ('psychictells.com', a fixed set of path segments). That meant
testing a different website required editing this file's source code. Both
now come from the active site profile (site_profiles/<name>.json) via
config.py, so switching sites is a JSON edit, not a code change — this file
no longer contains anything specific to psychictells.

Usage:
    from test_agent.site_navigator import SiteNavigator
    from config import PSYCHICS_URL, BASE_URL, SITE_DOMAIN, \\
                        NON_PROFILE_PATH_SEGMENTS, PROFILE_URL_PREFIXES

    nav = SiteNavigator(
        browser, listing_url=PSYCHICS_URL, base_url=BASE_URL,
        domain=SITE_DOMAIN,
        non_profile_segments=NON_PROFILE_PATH_SEGMENTS,
        profile_prefixes=PROFILE_URL_PREFIXES,
    )
    profile_url = nav.find_profile_url()   # "" if none found
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import time
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Fallback defaults used only if a caller doesn't pass explicit values
# (keeps this module usable standalone / in older call sites without
# forcing every constructor call to be updated).
_DEFAULT_NON_PROFILE_SEGMENTS = {
    "", "about", "about-us", "contact", "contact-us",
    "login", "signup", "sign-up", "register", "create-account",
    "pricing", "credits", "checkout", "payment",
    "blog", "faq", "help", "support", "terms", "privacy", "policy",
    "dashboard", "account", "settings", "cart",
}
_DEFAULT_PROFILE_PREFIXES = ()


class SiteNavigator:
    """
    Shared navigation helper for locating real content/detail pages
    (e.g. a psychic profile, a product page, a listing detail) starting
    from a listing/index page. Wraps a BrowserController.

    All site-specific knowledge (domain, which path segments are NOT
    content pages, which prefixes ARE) is passed in by the caller —
    typically sourced from the active site profile via config.py — so
    this class itself has zero hardcoded knowledge of any one website.
    """

    def __init__(self, browser, listing_url: str, base_url: str,
                 domain: str = "",
                 non_profile_segments: set = None,
                 profile_prefixes: tuple = None):
        self.br          = browser
        self.listing_url = listing_url
        self.base_url    = base_url
        # Domain defaults to whatever's embedded in base_url if not given
        self.domain = domain or urlparse(base_url).netloc
        self.non_profile_segments = (
            non_profile_segments if non_profile_segments is not None
            else _DEFAULT_NON_PROFILE_SEGMENTS
        )
        self.profile_prefixes = (
            profile_prefixes if profile_prefixes is not None
            else _DEFAULT_PROFILE_PREFIXES
        )
        self._cached_profile_url: str = ""

    # ── Public API ─────────────────────────────────────────────────────────

    def is_profile_url(self, url: str) -> bool:
        """
        Strict validation: True only if `url` looks like a genuine content/
        detail page — not the listing, homepage, or any other static site
        section (services, about, pricing, etc). Site-specific rules come
        entirely from self.domain / self.non_profile_segments /
        self.profile_prefixes, set at construction time from the active
        site profile.
        """
        if not url or self.domain not in url:
            return False

        parsed        = urlparse(url)
        path           = parsed.path.rstrip("/")
        listing_path   = urlparse(self.listing_url).path.rstrip("/")

        # Bare listing or homepage — never a profile
        if path in ("", listing_path):
            return False

        # A query-string-only variant of the listing page (e.g. filters)
        # is still the listing page, not a profile.
        if path == listing_path and parsed.query:
            return False

        # Reject any URL whose first path segment is a known static section
        segments = [s for s in path.split("/") if s]
        if not segments:
            return False
        if segments[0].lower() in self.non_profile_segments:
            return False

        # Positive signal: matches a known profile URL pattern
        if self.profile_prefixes and path.startswith(self.profile_prefixes):
            return True

        # Fallback: a URL with 1+ path segments that isn't a known static
        # page is treated as a plausible content/profile page. This keeps
        # the check useful even if the site's URL scheme changes.
        return True

    def find_profile_url(self, force_refresh: bool = False) -> str:
        """
        Navigate to the listing page and return a genuine content/detail
        page URL. Returns "" if none could be found.

        Strategy (in order):
        1. Return cached URL if still valid (unless force_refresh=True).
        2. Scan all <a href> tags on the listing page, validate each with
           is_profile_url(), and goto() the first valid one directly —
           this sidesteps React/Next.js onClick routing issues entirely.
        3. Fallback: dispatch_event('click') on visible card-like elements
           and check if the resulting URL validates as a profile.
        """
        if not force_refresh and self._cached_profile_url and \
           self.is_profile_url(self._cached_profile_url):
            self.br.goto(self._cached_profile_url)
            time.sleep(2)
            return self._cached_profile_url

        self.br.goto(self.listing_url)
        time.sleep(3)

        # ── Strategy 1: scan <a href> tags, navigate directly ──────────────
        found = self._scan_anchor_hrefs()
        if found:
            self._cached_profile_url = found
            return found

        # ── Strategy 2: dispatch_event fallback on card-like elements ──────
        found = self._dispatch_click_fallback()
        if found:
            self._cached_profile_url = found
            return found

        logger.warning("[SiteNavigator] Could not find a valid profile URL "
                        f"on {self.listing_url}")
        return ""

    # ── Internal strategies ────────────────────────────────────────────────

    def _scan_anchor_hrefs(self) -> str:
        try:
            anchors = self.br.page.locator("a[href]").all()
        except Exception:
            return ""

        for anchor in anchors:
            try:
                href = anchor.get_attribute("href") or ""
                if not href or href.startswith("#") or href.startswith("javascript"):
                    continue

                target = self.base_url + href if href.startswith("/") else href
                if not target.startswith("http"):
                    continue
                if not self.is_profile_url(target):
                    continue

                # Navigate directly by URL — avoids React onClick issues
                self.br.goto(target)
                time.sleep(2)
                actual = self.br.current_url()
                if self.is_profile_url(actual):
                    return actual

                # Didn't land where expected (redirect?) — go back and
                # keep scanning other candidates.
                self.br.goto(self.listing_url)
                time.sleep(1.5)
            except Exception:
                continue
        return ""

    def _dispatch_click_fallback(self) -> str:
        card_selectors = ["[class*='card']", "[class*='psychic']", "article"]
        for sel in card_selectors:
            try:
                cards = self.br.page.locator(sel).all()
            except Exception:
                continue

            for card in cards:
                try:
                    if not card.is_visible():
                        continue
                    old_url = self.br.current_url()
                    card.dispatch_event("click")

                    deadline = time.time() + 6.0
                    while time.time() < deadline:
                        cur = self.br.current_url()
                        if cur != old_url and self.is_profile_url(cur):
                            return cur
                        time.sleep(0.3)

                    # Reset for next candidate
                    self.br.goto(self.listing_url)
                    time.sleep(1.5)
                except Exception:
                    continue
        return ""
