"""
site_profile.py
─────────────────────────────────────────────────────────────────────────────
Site Profile Loader — The Reusability Engine

This module is what makes the test agent work on ANY website, not just
psychictells.com. All URLs and selectors that used to be hardcoded directly
in config.py now live in a JSON file under site_profiles/, and this module
loads whichever one is requested.

To point the entire framework at a different website:
    python main.py --site my_other_site
    (loads site_profiles/my_other_site.json)

or via environment variable:
    SITE_PROFILE=my_other_site python main.py

No Python code needs to change — only the JSON profile.

See site_profiles/TEMPLATE.json for the required structure when adding a
new site, and README.md → "Testing a Different Website" for the full guide.
─────────────────────────────────────────────────────────────────────────────
"""

import json
import os
from pathlib import Path
from urllib.parse import urlparse

PROFILES_DIR = Path(__file__).parent.parent / "site_profiles"


class SiteProfileError(Exception):
    """Raised when a profile is missing or malformed."""
    pass


class SiteProfile:
    """
    Loads and exposes a site profile JSON as a clean, validated object.
    All derived URLs (login, signup, listing page, etc.) are built here
    once, so config.py and every test file can just read plain attributes.
    """

    REQUIRED_TOP_LEVEL_KEYS = ["site_name", "urls", "selectors"]

    def __init__(self, data: dict, source_path: Path):
        self._data = data
        self.source_path = source_path
        self._validate()
        self._build_derived_urls()

    # ── Loading ────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, name: str = None) -> "SiteProfile":
        """
        Load a profile by name (without .json extension).
        Falls back to the SITE_PROFILE env var, then to 'psychictells'
        if neither is given, preserving backward compatibility for anyone
        running the agent without specifying a site.
        """
        name = name or os.getenv("SITE_PROFILE", "psychictells")
        path = PROFILES_DIR / f"{name}.json"

        if not path.exists():
            available = cls.list_available()
            raise SiteProfileError(
                f"Site profile '{name}' not found at {path}.\n"
                f"Available profiles: {available}\n"
                f"To add a new site, copy site_profiles/TEMPLATE.json to "
                f"site_profiles/{name}.json and fill it in."
            )

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise SiteProfileError(f"Site profile '{name}' has invalid JSON: {e}")

        return cls(data, path)

    @staticmethod
    def list_available() -> list:
        """Return names of all profiles available in site_profiles/, excluding TEMPLATE."""
        if not PROFILES_DIR.exists():
            return []
        return sorted(
            p.stem for p in PROFILES_DIR.glob("*.json")
            if p.stem != "TEMPLATE"
        )

    # ── Validation ─────────────────────────────────────────────────────────

    def _validate(self):
        missing = [k for k in self.REQUIRED_TOP_LEVEL_KEYS if k not in self._data]
        if missing:
            raise SiteProfileError(
                f"Site profile '{self.source_path}' is missing required "
                f"top-level key(s): {missing}. See site_profiles/TEMPLATE.json."
            )
        if "base" not in self._data.get("urls", {}):
            raise SiteProfileError(
                f"Site profile '{self.source_path}' is missing urls.base "
                f"(the site's root URL, e.g. 'https://example.com')."
            )

    def _build_derived_urls(self):
        """Combine urls.base + each relative path into full URLs, once."""
        urls = self._data["urls"]
        base = urls["base"].rstrip("/")

        def full(key: str, fallback: str = "") -> str:
            val = urls.get(key, fallback)
            if not val:
                return ""
            return val if val.startswith("http") else base + val

        self.base_url     = base
        self.listing_url  = full("listing_page", "/")
        self.login_url    = full("login_page",   "/login")
        self.signup_url   = full("signup_page",  "/signup")
        self.account_url  = full("account_page", "/account")

        expert_base = urls.get("expert_base", "")
        self.expert_base       = expert_base.rstrip("/") if expert_base else ""
        self.expert_login_url  = (self.expert_base + urls.get("expert_login_page", "/login")) \
                                  if self.expert_base else ""
        self.expert_dashboard  = (self.expert_base + urls.get("expert_dashboard", "/dashboard")) \
                                  if self.expert_base else ""

    # ── Public accessors ───────────────────────────────────────────────────

    @property
    def site_name(self) -> str:
        return self._data["site_name"]

    @property
    def display_name(self) -> str:
        return self._data.get("display_name", self.site_name)

    @property
    def domain(self) -> str:
        """Bare domain (no scheme) — used for same-site URL checks that
        used to hardcode 'psychictells.com' directly."""
        explicit = self._data.get("domain", "")
        if explicit:
            return explicit
        return urlparse(self.base_url).netloc

    @property
    def expert_domain(self) -> str:
        """Bare expert-panel domain — separate from the main site domain
        since many sites (including psychictells) host the expert/admin
        panel on an entirely different subdomain or host."""
        explicit = self._data.get("expert_domain", "")
        if explicit:
            return explicit
        return urlparse(self.expert_base).netloc if self.expert_base else ""

    @property
    def selectors(self) -> dict:
        return self._data["selectors"]

    @property
    def credentials(self) -> dict:
        return self._data.get("credentials", {})

    @property
    def non_profile_path_segments(self) -> set:
        """Used by SiteNavigator to reject non-content pages (e.g. /about,
        /pricing) when hunting for a genuine content/profile page."""
        return set(self._data.get("non_profile_path_segments", []))

    @property
    def profile_url_prefixes(self) -> tuple:
        return tuple(self._data.get("profile_url_prefixes", []))

    @property
    def baseline_pages(self) -> list:
        """
        Resolves each baseline page's relative path into a full URL.
        Supports the special path token '__EXPERT_LOGIN__' which resolves
        to this profile's expert_login_url (since that lives on a
        different domain than the main site).
        """
        pages = []
        for entry in self._data.get("baseline_pages", []):
            path = entry.get("path", "/")
            if path == "__EXPERT_LOGIN__":
                url = self.expert_login_url
                if not url:
                    continue   # site has no expert panel — skip this page
            else:
                url = self.base_url + path if not path.startswith("http") else path
            pages.append({
                "id":     entry["id"],
                "url":    url,
                "checks": entry.get("checks", {}),
            })
        return pages

    def is_on_domain(self, url: str) -> bool:
        """Replaces hardcoded 'psychictells.com' in url substring checks."""
        return self.domain in url

    def __repr__(self):
        return f"<SiteProfile '{self.site_name}' ({self.base_url})>"
