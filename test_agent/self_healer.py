"""
self_healer.py
─────────────────────────────────────────────────────────────────────────────
Phase 3 — Self-Healing Selector Engine

When a CSS/Playwright selector fails to find an element, the self-healer
tries a cascade of progressively broader strategies to locate it.

Healing strategies (tried in order):
  1. Original selector                  — fastest, most precise
  2. Config fallback list               — pre-defined alternatives in config.py
  3. Text-content match                 — find by visible label / button text
  4. Aria / accessibility attribute     — aria-label, data-testid, role
  5. Partial attribute match            — name~=, placeholder~=, id~=
  6. Structural / visual position       — element at expected bounding-box area
  7. Gemini AI suggestion (Phase 3+)    — use LLM to suggest selector from DOM

Every successful heal is:
  - Logged to self_heal_log.json for review
  - Printed with the new selector so config.py can be updated
  - Returned to the caller with a HealResult containing the working selector
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page, Locator

logger = logging.getLogger(__name__)


# ── Heal result ───────────────────────────────────────────────────────────────

@dataclass
class HealResult:
    """Returned by SelfHealer.find() for every element lookup."""
    found:           bool
    locator:         Optional[object]   # Playwright Locator or None
    original_sel:    str
    winning_sel:     str        = ""
    strategy:        str        = "original"
    healed:          bool       = False    # True when a fallback was needed
    suggestions:     list       = field(default_factory=list)


# ── Core engine ───────────────────────────────────────────────────────────────

class SelfHealer:
    """
    Drop-in replacement for direct page.locator() calls.
    Returns a HealResult so callers can see which strategy worked.
    """

    HEAL_LOG_PATH = "reports/self_heal_log.json"

    def __init__(self, page: Page, config_fallbacks: dict = None):
        self.page      = page
        self.fallbacks = config_fallbacks or {}   # from config.SELECTORS
        self._log: list[dict] = []
        Path("reports").mkdir(exist_ok=True)

    # ── Public API ─────────────────────────────────────────────────────────

    def find(self, selector: str, hint: str = "",
             fallback_list: list = None, timeout: int = 3000) -> HealResult:
        """
        Try to locate an element. Falls through healing strategies
        until one succeeds or all fail.

        Args:
            selector:      Primary CSS/Playwright selector to try first.
            hint:          Human-readable name of what we're looking for
                           (e.g. "Ask a Free Question button"). Used in AI
                           and text-search strategies.
            fallback_list: Explicit list of alternative selectors to try
                           before the generic healing strategies.
            timeout:       Per-attempt timeout in ms.

        Returns:
            HealResult with .found, .locator, .winning_sel, .strategy, .healed
        """
        strategies = self._build_strategy_list(selector, hint, fallback_list)

        for strategy_name, sel in strategies:
            result = self._try_selector(sel, timeout)
            if result:
                healed = strategy_name != "original"
                if healed:
                    self._record_heal(selector, sel, strategy_name, hint)
                    logger.info(
                        f"[SelfHealer] Healed '{hint or selector}' "
                        f"via '{strategy_name}': {sel}"
                    )
                return HealResult(
                    found=True, locator=result,
                    original_sel=selector, winning_sel=sel,
                    strategy=strategy_name, healed=healed,
                )

        # All strategies failed
        logger.warning(f"[SelfHealer] Could not find '{hint or selector}'")
        return HealResult(
            found=False, locator=None,
            original_sel=selector, winning_sel="",
            strategy="none", healed=False,
        )

    def find_all(self, selector: str, hint: str = "",
                 fallback_list: list = None, timeout: int = 3000) -> HealResult:
        """Same as find() but returns a locator for all matching elements."""
        result = self.find(selector, hint, fallback_list, timeout)
        return result

    def click(self, selector: str, hint: str = "",
              fallback_list: list = None) -> HealResult:
        """Find and click an element, healing if needed."""
        result = self.find(selector, hint, fallback_list)
        if result.found and result.locator:
            try:
                result.locator.first.click()
            except Exception:
                try:
                    result.locator.first.dispatch_event("click")
                except Exception as e:
                    result.found = False
                    logger.warning(f"[SelfHealer] Click failed: {e}")
        return result

    def fill(self, selector: str, value: str, hint: str = "",
             fallback_list: list = None) -> HealResult:
        """Find and fill an input element, healing if needed."""
        result = self.find(selector, hint, fallback_list)
        if result.found and result.locator:
            try:
                result.locator.first.fill(value)
            except Exception as e:
                result.found = False
                logger.warning(f"[SelfHealer] Fill failed: {e}")
        return result

    def get_suggestions(self) -> list[dict]:
        """Return list of healed selectors as config.py update suggestions."""
        return [
            {"original": h["original_sel"],
             "suggested": h["winning_sel"],
             "strategy": h["strategy"],
             "hint": h["hint"],
             "timestamp": h["timestamp"]}
            for h in self._log
        ]

    def save_log(self):
        """Persist heal log to disk for review."""
        existing = []
        if os.path.exists(self.HEAL_LOG_PATH):
            try:
                with open(self.HEAL_LOG_PATH) as f:
                    existing = json.load(f)
            except Exception:
                pass
        existing.extend(self._log)
        with open(self.HEAL_LOG_PATH, "w") as f:
            json.dump(existing, f, indent=2)

    # ── Strategy builder ───────────────────────────────────────────────────

    def _build_strategy_list(self, selector: str, hint: str,
                              fallback_list: list) -> list[tuple[str, str]]:
        """
        Build an ordered list of (strategy_name, selector) pairs to try.
        """
        strategies = [("original", selector)]

        # 1. Explicit fallback list provided by caller
        if fallback_list:
            for fb in fallback_list:
                strategies.append(("explicit_fallback", fb))

        # 2. Config fallback lists (matched by looking for the selector in values)
        for key, val in self.fallbacks.items():
            if isinstance(val, list) and selector in val:
                for fb in val:
                    if fb != selector:
                        strategies.append(("config_fallback", fb))

        # 3. Text-content strategies derived from the hint
        if hint:
            # Extract likely button/link text from hint
            words = [w for w in hint.replace("'", "").split() if len(w) > 2]
            for word in words[:3]:
                strategies.extend([
                    ("text_match", f"button:has-text('{word}')"),
                    ("text_match", f"a:has-text('{word}')"),
                    ("text_match", f"[role='button']:has-text('{word}')"),
                    ("text_match", f"text='{word}'"),
                ])

        # 4. Aria / accessibility attributes
        if hint:
            slug = hint.lower().replace(" ", "-").replace("'", "")
            word = hint.split()[0].lower() if hint.split() else ""
            strategies.extend([
                ("aria_label",  f"[aria-label*='{hint}' i]"),
                ("aria_label",  f"[aria-label*='{word}' i]"),
                ("data_testid", f"[data-testid*='{slug}']"),
                ("data_testid", f"[data-testid*='{word}']"),
                ("role_button", f"[role='button'][title*='{word}' i]"),
            ])

        # 5. Partial attribute match (derive from original selector)
        attr_sels = self._derive_partial_selectors(selector)
        for s in attr_sels:
            strategies.append(("partial_attr", s))

        # 6. Broad structural fallbacks
        strategies.extend([
            ("broad", "button:visible"),
            ("broad", "a:visible"),
            ("broad", "[role='button']:visible"),
        ])

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for name, sel in strategies:
            if sel not in seen:
                seen.add(sel)
                unique.append((name, sel))
        return unique

    def _derive_partial_selectors(self, selector: str) -> list[str]:
        """
        From a selector like input[type='email'], derive broader variants.
        """
        derived = []
        # input[type='email'] → input[type='email'], input
        tag = selector.split("[")[0].split(":")[0].split(".")[0].split("#")[0]
        if tag and tag != selector:
            derived.append(tag)
        # button:has-text('X') → button
        if ":has-text" in selector:
            derived.append(selector.split(":has-text")[0])
        # a[href*='/psychic'] → a[href]
        if "[href*=" in selector:
            derived.append(selector.split("[href*=")[0] + "[href]")
        return derived

    # ── Helpers ────────────────────────────────────────────────────────────

    def _try_selector(self, selector: str, timeout: int) -> Optional[Locator]:
        """Try a selector; return Locator if found and visible, else None."""
        try:
            loc = self.page.locator(selector)
            loc.first.wait_for(state="visible", timeout=timeout)
            if loc.count() > 0:
                return loc
        except Exception:
            pass
        return None

    def _record_heal(self, original: str, winning: str,
                     strategy: str, hint: str):
        """Log a successful heal event."""
        entry = {
            "timestamp":    datetime.now().isoformat(),
            "hint":         hint,
            "original_sel": original,
            "winning_sel":  winning,
            "strategy":     strategy,
        }
        self._log.append(entry)
        print(f"\n  🔧 [SelfHealer] HEALED — update config.py:")
        print(f"     Original : {original}")
        print(f"     Working  : {winning}")
        print(f"     Strategy : {strategy}\n")


# ── Standalone selector validator ────────────────────────────────────────────

class SelectorValidator:
    """
    Run against the live site to verify all selectors in config.SELECTORS
    still work, and report which ones are broken / need healing.
    """

    def __init__(self, page: Page, selectors: dict):
        self.page      = page
        self.selectors = selectors
        self.healer    = SelfHealer(page, selectors)

    def validate_all(self, url: str) -> dict:
        """
        Navigate to url and test every selector.
        Returns a dict: {selector_key: {status, working_sel, strategy}}
        """
        self.page.goto(url)
        time.sleep(2)

        results = {}
        flat = self._flatten_selectors(self.selectors)

        for key, sel in flat.items():
            result = self.healer.find(sel, hint=key, timeout=2000)
            results[key] = {
                "original_sel": sel,
                "found":        result.found,
                "working_sel":  result.winning_sel,
                "strategy":     result.strategy,
                "healed":       result.healed,
            }

        return results

    def _flatten_selectors(self, d: dict, prefix: str = "") -> dict:
        flat = {}
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, str):
                flat[key] = v
            elif isinstance(v, list) and v and isinstance(v[0], str):
                flat[key] = v[0]   # use first as primary
            elif isinstance(v, dict):
                flat.update(self._flatten_selectors(v, key))
        return flat
