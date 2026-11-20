"""
ui_change_detector.py
─────────────────────────────────────────────────────────────────────────────
Phase 3 — UI Change Detection Engine

Captures a baseline snapshot of the site's key pages and compares future
runs against it. Automatically flags:

  • New / removed DOM elements
  • Selector count changes (e.g. nav link count dropped from 5 → 3)
  • Page title changes
  • HTTP status changes
  • Visual screenshot diffs (pixel-level, optional — needs Pillow)
  • Missing critical elements (Ask button, login form, etc.)

Baseline is stored in baselines/<RUN_ID>/baseline.json and screenshots in
baselines/<RUN_ID>/screenshots/.

Usage:
    detector = UIChangeDetector(browser, pages_to_snapshot)
    detector.capture_baseline()          # first run — saves baseline
    changes  = detector.detect_changes() # subsequent runs — returns diffs
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

BASELINE_DIR = "baselines"


# ── Page snapshot config ──────────────────────────────────────────────────────
# REUSABILITY NOTE: this used to be the only source of pages to snapshot,
# hardcoded with literal psychictells.com URLs — testing a different site
# meant editing this file. Now UIChangeDetector defaults to config.BASELINE_
# PAGES, which is built from the active site profile (site_profiles/<name>
# .json). This list only survives as an emergency fallback for standalone
# use of this module without a configured profile.
_FALLBACK_DEFAULT_PAGES = [
    {
        "id":    "homepage",
        "url":   "https://example.com",
        "checks": {
            "title_contains":   [],
            "min_elements":     {"a": 5, "button": 1},
            "critical_selectors": ["nav", "footer"],
        },
    },
]


# ── Snapshot model ────────────────────────────────────────────────────────────

def _empty_snapshot(page_id: str, url: str) -> dict:
    return {
        "page_id":          page_id,
        "url":              url,
        "captured_at":      "",
        "http_status":      0,
        "title":            "",
        "element_counts":   {},     # tag → count
        "selector_results": {},     # selector → found (bool)
        "nav_link_count":   0,
        "footer_link_count":0,
        "h1_texts":         [],
        "screenshot_path":  "",
    }


# ── Main detector ─────────────────────────────────────────────────────────────

class UIChangeDetector:
    """Captures DOM baselines and diffs them against live site state."""

    def __init__(self, browser, pages: list = None):
        self.br = browser
        if pages is not None:
            self.pages = pages
        else:
            # Prefer the active site profile's baseline pages; only fall
            # back to the inert example list if config isn't importable
            # (e.g. this module used standalone outside the full project).
            try:
                import config
                self.pages = config.BASELINE_PAGES
            except Exception:
                self.pages = _FALLBACK_DEFAULT_PAGES
        Path(BASELINE_DIR).mkdir(exist_ok=True)
        self._baseline_file = os.path.join(BASELINE_DIR, "baseline.json")
        self._baseline: dict = self._load_baseline()

    # ── Public API ─────────────────────────────────────────────────────────

    def capture_baseline(self) -> dict:
        """
        Snapshot every configured page and save as the new baseline.
        Call this once after confirming the site looks correct.
        """
        baseline = {
            "captured_at": datetime.now().isoformat(),
            "pages": {}
        }
        print("\n📸  Capturing UI baseline...\n")
        for page_cfg in self.pages:
            snap = self._snapshot_page(page_cfg)
            baseline["pages"][page_cfg["id"]] = snap
            status = "✅" if snap["http_status"] in (200, 301, 302) else "⚠️"
            print(f"  {status}  {page_cfg['id']:25s} "
                  f"status={snap['http_status']}  "
                  f"title='{snap['title'][:40]}'")

        with open(self._baseline_file, "w") as f:
            json.dump(baseline, f, indent=2)
        self._baseline = baseline
        print(f"\n  Baseline saved → {self._baseline_file}\n")
        return baseline

    def detect_changes(self) -> list[dict]:
        """
        Compare live site against stored baseline.
        Returns a list of Change dicts (empty list = no changes detected).
        """
        if not self._baseline:
            logger.warning("[UIChangeDetector] No baseline found — run capture_baseline() first.")
            return [{"type": "NO_BASELINE", "severity": "INFO",
                     "message": "No baseline exists. Run capture_baseline() first."}]

        changes = []
        print("\n🔍  Detecting UI changes...\n")

        for page_cfg in self.pages:
            pid   = page_cfg["id"]
            baseline_snap = self._baseline.get("pages", {}).get(pid)
            if not baseline_snap:
                changes.append({
                    "page_id":  pid,
                    "type":     "NEW_PAGE",
                    "severity": "LOW",
                    "message":  f"Page '{pid}' not in baseline — new page or renamed.",
                })
                continue

            live_snap = self._snapshot_page(page_cfg)
            page_changes = self._diff_snapshots(baseline_snap, live_snap, page_cfg)
            changes.extend(page_changes)

            status = "✅" if not page_changes else f"⚠️  {len(page_changes)} change(s)"
            print(f"  {status}  {pid}")

        print(f"\n  Total changes detected: {len(changes)}\n")
        return changes

    def validate_critical_selectors(self, url: str, selectors: list) -> dict:
        """
        Quick check: are all critical selectors still present on a page?
        Returns {selector: bool}
        """
        self.br.goto(url)
        time.sleep(2)
        results = {}
        for sel in selectors:
            try:
                el = self.br.page.locator(sel)
                results[sel] = el.count() > 0
            except Exception:
                results[sel] = False
        return results

    def get_baseline_summary(self) -> dict:
        """Return a human-readable summary of the stored baseline."""
        if not self._baseline:
            return {"status": "no_baseline"}
        return {
            "captured_at": self._baseline.get("captured_at"),
            "pages": list(self._baseline.get("pages", {}).keys()),
            "total_pages": len(self._baseline.get("pages", {})),
        }

    # ── Snapshot engine ────────────────────────────────────────────────────

    def _snapshot_page(self, page_cfg: dict) -> dict:
        snap = _empty_snapshot(page_cfg["id"], page_cfg["url"])
        snap["captured_at"] = datetime.now().isoformat()

        try:
            nav = self.br.goto(page_cfg["url"])
            time.sleep(2)
            snap["http_status"] = nav.get("status", 0) if nav else 0
            snap["title"]       = self.br.page_title()

            # Element counts for key tags
            for tag in ["a", "button", "input", "img", "h1", "h2", "nav", "footer", "form"]:
                try:
                    snap["element_counts"][tag] = self.br.page.locator(tag).count()
                except Exception:
                    snap["element_counts"][tag] = 0

            # Nav and footer link counts
            snap["nav_link_count"]    = self.br.page.locator("nav a").count()
            snap["footer_link_count"] = self.br.page.locator("footer a").count()

            # H1 text content
            try:
                h1s = self.br.page.locator("h1").all()
                snap["h1_texts"] = [h.inner_text().strip()[:80] for h in h1s[:3]]
            except Exception:
                pass

            # Critical selector presence
            for sel in page_cfg.get("checks", {}).get("critical_selectors", []):
                try:
                    snap["selector_results"][sel] = self.br.page.locator(sel).count() > 0
                except Exception:
                    snap["selector_results"][sel] = False

            # Screenshot
            ss_dir  = os.path.join(BASELINE_DIR, "screenshots")
            Path(ss_dir).mkdir(exist_ok=True)
            ss_path = os.path.join(ss_dir, f"{page_cfg['id']}_baseline.png")
            try:
                self.br.page.screenshot(path=ss_path, full_page=True)
                snap["screenshot_path"] = ss_path
            except Exception:
                pass

        except Exception as e:
            logger.error(f"[UIChangeDetector] Snapshot failed for {page_cfg['id']}: {e}")
            snap["error"] = str(e)

        return snap

    # ── Diff engine ────────────────────────────────────────────────────────

    def _diff_snapshots(self, baseline: dict, live: dict,
                        page_cfg: dict) -> list[dict]:
        changes = []
        pid = page_cfg["id"]

        # ── HTTP status change ─────────────────────────────────────────────
        if baseline["http_status"] != live["http_status"]:
            changes.append({
                "page_id":  pid, "type": "HTTP_STATUS_CHANGED",
                "severity": "CRITICAL" if live["http_status"] >= 400 else "HIGH",
                "message":  f"HTTP status changed: "
                            f"{baseline['http_status']} → {live['http_status']}",
                "baseline": baseline["http_status"],
                "current":  live["http_status"],
            })

        # ── Title change ───────────────────────────────────────────────────
        if baseline["title"] and live["title"] and \
           baseline["title"] != live["title"]:
            # Only flag if the change looks significant (not just whitespace)
            if baseline["title"].strip() != live["title"].strip():
                changes.append({
                    "page_id":  pid, "type": "TITLE_CHANGED",
                    "severity": "MEDIUM",
                    "message":  f"Page title changed: "
                                f"'{baseline['title']}' → '{live['title']}'",
                    "baseline": baseline["title"],
                    "current":  live["title"],
                })

        # ── Critical selectors gone ────────────────────────────────────────
        for sel, was_present in baseline.get("selector_results", {}).items():
            now_present = live.get("selector_results", {}).get(sel, False)
            if was_present and not now_present:
                changes.append({
                    "page_id":  pid, "type": "SELECTOR_MISSING",
                    "severity": "HIGH",
                    "message":  f"Critical element disappeared: '{sel}'",
                    "selector": sel,
                })
            elif not was_present and now_present:
                changes.append({
                    "page_id":  pid, "type": "SELECTOR_APPEARED",
                    "severity": "LOW",
                    "message":  f"New element appeared: '{sel}'",
                    "selector": sel,
                })

        # ── Element count changes ──────────────────────────────────────────
        THRESHOLDS = {"a": 3, "button": 2, "input": 1, "nav": 1, "footer": 1}
        for tag, threshold in THRESHOLDS.items():
            b_count = baseline.get("element_counts", {}).get(tag, 0)
            l_count = live.get("element_counts", {}).get(tag, 0)
            delta   = abs(l_count - b_count)
            if b_count > 0 and delta >= threshold:
                direction = "decreased" if l_count < b_count else "increased"
                changes.append({
                    "page_id":  pid, "type": "ELEMENT_COUNT_CHANGED",
                    "severity": "MEDIUM" if tag in ("nav", "footer") else "LOW",
                    "message":  f"<{tag}> count {direction}: "
                                f"{b_count} → {l_count} (delta={delta})",
                    "tag":      tag,
                    "baseline": b_count,
                    "current":  l_count,
                })

        # ── Nav link count change ──────────────────────────────────────────
        b_nav = baseline.get("nav_link_count", 0)
        l_nav = live.get("nav_link_count", 0)
        if b_nav > 0 and abs(l_nav - b_nav) >= 2:
            changes.append({
                "page_id":  pid, "type": "NAV_LINKS_CHANGED",
                "severity": "HIGH",
                "message":  f"Navigation link count changed: {b_nav} → {l_nav}",
                "baseline": b_nav,
                "current":  l_nav,
            })

        # ── H1 text change (indicates major content restructure) ───────────
        b_h1 = set(baseline.get("h1_texts", []))
        l_h1 = set(live.get("h1_texts", []))
        removed_h1 = b_h1 - l_h1
        added_h1   = l_h1 - b_h1
        if removed_h1:
            changes.append({
                "page_id":  pid, "type": "H1_REMOVED",
                "severity": "MEDIUM",
                "message":  f"H1 heading(s) removed: {removed_h1}",
                "baseline": list(b_h1),
                "current":  list(l_h1),
            })
        if added_h1:
            changes.append({
                "page_id":  pid, "type": "H1_ADDED",
                "severity": "LOW",
                "message":  f"New H1 heading(s) appeared: {added_h1}",
                "baseline": list(b_h1),
                "current":  list(l_h1),
            })

        # ── Visual screenshot diff (if Pillow is available) ────────────────
        if baseline.get("screenshot_path") and live.get("screenshot_path"):
            diff_pct = self._pixel_diff(
                baseline["screenshot_path"], live["screenshot_path"]
            )
            if diff_pct is not None and diff_pct > 5.0:
                changes.append({
                    "page_id":  pid, "type": "VISUAL_DIFF",
                    "severity": "MEDIUM" if diff_pct < 20 else "HIGH",
                    "message":  f"Visual screenshot diff: {diff_pct:.1f}% pixels changed",
                    "diff_pct": diff_pct,
                })

        return changes

    def _pixel_diff(self, path_a: str, path_b: str) -> float:
        """
        Compare two screenshots pixel-by-pixel using Pillow.
        Returns percentage of changed pixels, or None if Pillow unavailable.
        """
        try:
            from PIL import Image, ImageChops
            import numpy as np

            img_a = Image.open(path_a).convert("RGB")
            img_b = Image.open(path_b).convert("RGB")

            # Resize to same dimensions for comparison
            if img_a.size != img_b.size:
                img_b = img_b.resize(img_a.size, Image.LANCZOS)

            diff  = ImageChops.difference(img_a, img_b)
            arr   = np.array(diff)
            # A pixel is "changed" if any channel differs by more than 10
            changed = np.any(arr > 10, axis=2)
            return float(changed.sum() / changed.size * 100)

        except ImportError:
            return None   # Pillow/numpy not installed — skip visual diff
        except Exception as e:
            logger.debug(f"[UIChangeDetector] Pixel diff failed: {e}")
            return None

    # ── Persistence ────────────────────────────────────────────────────────

    def _load_baseline(self) -> dict:
        if os.path.exists(self._baseline_file):
            try:
                with open(self._baseline_file) as f:
                    return json.load(f)
            except Exception:
                pass
        return {}
