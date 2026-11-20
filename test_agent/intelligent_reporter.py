"""
intelligent_reporter.py
─────────────────────────────────────────────────────────────────────────────
Phase 3 — Intelligent Bug Reporter

Wraps the base TestReporter with:
  • Automatic severity scoring (CRITICAL / HIGH / MEDIUM / LOW)
  • Bug grouping by root cause
  • Fix suggestions per failure pattern
  • Trend tracking across multiple runs
  • Gemini AI-powered failure analysis (when API key is set)
  • Enhanced HTML report with severity badges, grouped bugs, run history
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

RUNS_HISTORY_FILE = "reports/run_history.json"
BUGS_FILE         = "reports/known_bugs.json"


# ── Severity rules ────────────────────────────────────────────────────────────

def score_severity(test_name: str, actual_result: str, status: str) -> str:
    """
    Assign a severity level to a failed test based on what it tests and
    what the actual result says.
    """
    if status == "PASS":
        return "NONE"
    if status == "SKIP":
        return "INFO"

    name   = test_name.lower()
    actual = actual_result.lower()

    # CRITICAL — crash, server error, data loss risk
    if any(k in actual for k in ["crash", "500", "exception", "typeerror",
                                   "uncaught", "unexpected error"]):
        return "CRITICAL"
    if any(k in actual for k in ["sql", "drop table", "injection"]) and "nocrash=false" in actual:
        return "CRITICAL"
    if "xss" in name and "xssexecuted=true" in actual:
        return "CRITICAL"

    # HIGH — broken core flow, navigation failure, auth failure, payment broken
    if any(k in name for k in ["login", "signup", "checkout", "payment",
                                 "navigate", "journey", "round-trip"]):
        return "HIGH"
    if any(k in actual for k in ["navigated=false", "clicked=false", "status=404",
                                   "status=500", "nodashboard", "notfound"]):
        return "HIGH"
    if "https" in name and "ishttp=false" in actual.replace(" ", ""):
        return "HIGH"

    # MEDIUM — UI element missing, validation not working, content changed
    if any(k in name for k in ["visible", "present", "form", "button",
                                 "selector", "title", "h1"]):
        return "MEDIUM"
    if any(k in actual for k in ["found=false", "visible=false",
                                   "pagereach=false", "element"]):
        return "MEDIUM"

    # LOW — cosmetic, performance, optional features
    if any(k in name for k in ["load speed", "favicon", "console", "mobile",
                                 "responsive", "external"]):
        return "LOW"

    return "MEDIUM"   # default


# ── Root cause grouping ───────────────────────────────────────────────────────

ROOT_CAUSE_PATTERNS = [
    (r"navigated=false|clicked=false|url.*psychics.*psychics",
     "navigation",
     "React/Next.js client-side routing not responding to standard click events.",
     "Use dispatch_event('click') or navigate via direct goto() instead of clicking."),

    (r"user not found|no account|not registered",
     "missing_account",
     "Test user account does not exist on the site.",
     "Create a test user account on the target site, then update "
     "USER_EMAIL / USER_PASSWORD in .env"),

    (r"status=404|404 not found",
     "broken_link",
     "Page or resource returns HTTP 404.",
     "Check if the URL has changed. Update the URL in config.py or report to the dev team."),

    (r"pagereach=false|form.*not.*found|selector.*missing",
     "selector_outdated",
     "CSS selector no longer matches the DOM — site was likely updated.",
     "Inspect the page in DevTools, find the new element, update SELECTORS in config.py."),

    (r"loadtime=\d{5}|5[0-9]{3} ms",
     "performance",
     "Page load time exceeded threshold.",
     "Report to the dev team. May indicate server-side performance regression."),

    (r"favicon.*404|favicon.*not found",
     "missing_asset",
     "Static asset (favicon) missing from the server.",
     "Upload favicon.ico to the web root or configure a redirect."),

    (r"xssexecuted=true|script.*executed",
     "security_xss",
     "XSS payload executed — critical security vulnerability.",
     "Report immediately to the dev team. Input is not being sanitized."),

    (r"ishttp=false|uses http://",
     "insecure_page",
     "Payment or auth page is not served over HTTPS.",
     "Configure HTTPS redirect on the server. Report to DevOps."),
]


def classify_root_cause(actual_result: str) -> tuple[str, str, str]:
    """
    Returns (root_cause_key, description, fix_suggestion) for a failed test.
    """
    text = actual_result.lower()
    for pattern, key, desc, fix in ROOT_CAUSE_PATTERNS:
        if re.search(pattern, text):
            return key, desc, fix
    return "unknown", "Could not automatically determine root cause.", \
           "Review screenshot and actual result. Inspect the page manually."


# ── Bug deduplication ─────────────────────────────────────────────────────────

def group_failures(results: list[dict]) -> dict:
    """
    Group failed tests by root cause.
    Returns {root_cause_key: [list of test results]}
    """
    groups: dict[str, list] = {}
    for r in results:
        if r.get("status") not in ("FAIL", "ERROR"):
            continue
        key, desc, fix = classify_root_cause(r.get("actual_result", ""))
        if key not in groups:
            groups[key] = {"description": desc, "fix": fix, "tests": []}
        groups[key]["tests"].append(r)
    return groups


# ── Run history tracker ───────────────────────────────────────────────────────

class RunHistory:
    """Tracks pass/fail counts across multiple runs for trend analysis."""

    def __init__(self):
        self._history: list[dict] = self._load()

    def record(self, run_id: str, total: int, passed: int,
               failed: int, errors: int, duration_s: float):
        entry = {
            "run_id":     run_id,
            "timestamp":  datetime.now().isoformat(),
            "total":      total,
            "passed":     passed,
            "failed":     failed,
            "errors":     errors,
            "pass_rate":  round(passed / total * 100, 1) if total else 0,
            "duration_s": duration_s,
        }
        self._history.append(entry)
        self._save()
        return entry

    def get_trend(self, last_n: int = 5) -> list[dict]:
        return self._history[-last_n:]

    def is_regressing(self) -> bool:
        """True if last 2 runs show a declining pass rate."""
        if len(self._history) < 2:
            return False
        prev = self._history[-2]["pass_rate"]
        curr = self._history[-1]["pass_rate"]
        return curr < prev - 2.0   # more than 2% drop = regression

    def _load(self) -> list:
        if os.path.exists(RUNS_HISTORY_FILE):
            try:
                with open(RUNS_HISTORY_FILE) as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _save(self):
        Path("reports").mkdir(exist_ok=True)
        with open(RUNS_HISTORY_FILE, "w") as f:
            json.dump(self._history, f, indent=2)


# ── Gemini AI analyser ────────────────────────────────────────────────────────

class GeminiAnalyser:
    """
    Optional: uses Gemini API to analyse a batch of failures and suggest
    root causes and fixes. Falls back to rule-based analysis if no API key.
    """

    def __init__(self, api_key: str = "", site_display_name: str = "the target site"):
        self.api_key = api_key
        self.enabled = bool(api_key)
        self.site_display_name = site_display_name

    def analyse_failures(self, failures: list[dict]) -> str:
        """
        Returns a plain-text analysis and fix recommendations for the batch.
        """
        if not self.enabled or not failures:
            return self._static_analysis(failures)

        try:
            import json as _json
            import urllib.request as _ur
            prompt  = self._build_prompt(failures)
            api_url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-2.5-flash:generateContent?key={self.api_key}"
            )
            payload = _json.dumps({
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2000},
            }).encode()
            req = _ur.Request(api_url, data=payload,
                              headers={"Content-Type": "application/json"})
            with _ur.urlopen(req, timeout=30) as resp:
                data = _json.loads(resp.read())
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            logger.warning(f"[GeminiAnalyser] API call failed: {e}")
            return self._static_analysis(failures)

    def _build_prompt(self, failures: list[dict]) -> str:
        lines = [
            f"You are a QA engineer reviewing automated test failures for "
            f"{self.site_display_name}.",
            "Analyse the following failures and provide:",
            "1. A brief root cause for each group of related failures",
            "2. A prioritised fix list (most critical first)",
            "3. Any patterns suggesting a site-wide regression",
            "",
            "Test failures:",
        ]
        for i, f in enumerate(failures[:10], 1):
            lines.append(
                f"{i}. [{f.get('status')}] {f.get('test_name')} | "
                f"Expected: {f.get('expected_result', '')[:80]} | "
                f"Actual: {f.get('actual_result', '')[:80]}"
            )
        return "\n".join(lines)

    def _static_analysis(self, failures: list[dict]) -> str:
        if not failures:
            return "No failures to analyse."
        groups = group_failures(failures)
        lines  = ["── Static Analysis (Gemini not configured) ──\n"]
        for key, group in groups.items():
            lines.append(f"● Root Cause: {key.upper().replace('_', ' ')}")
            lines.append(f"  {group['description']}")
            lines.append(f"  Fix: {group['fix']}")
            lines.append(f"  Affects: {len(group['tests'])} test(s)")
            lines.append("")
        return "\n".join(lines)


# ── Intelligent Reporter (wraps base reporter) ────────────────────────────────

class IntelligentReporter:
    """
    Wraps the base TestReporter and adds Phase 3 intelligence:
    severity scoring, bug grouping, trend tracking, AI analysis.
    """

    def __init__(self, base_reporter, gemini_api_key: str = "",
                 site_display_name: str = "the target site"):
        self.rep       = base_reporter
        self.history   = RunHistory()
        self.analyser  = GeminiAnalyser(gemini_api_key, site_display_name)
        self.site_display_name = site_display_name
        self._start_time = time.time()

    def add_result(self, **kwargs):
        """Pass-through to base reporter."""
        self.rep.add_result(**kwargs)

    def save_all(self):
        """Save base report + generate Phase 3 intelligence report."""
        self.rep.save_all()
        self._generate_intelligence_report()

    def _generate_intelligence_report(self):
        """Build and save the enhanced Phase 3 HTML report."""
        results   = self.rep.results
        total     = len(results)
        passed    = sum(1 for r in results if r.get("status") == "PASS")
        failed    = sum(1 for r in results if r.get("status") == "FAIL")
        errors    = sum(1 for r in results if r.get("status") == "ERROR")
        skipped   = sum(1 for r in results if r.get("status") == "SKIP")
        duration  = round(time.time() - self._start_time, 1)

        failures  = [r for r in results if r.get("status") in ("FAIL", "ERROR")]
        groups    = group_failures(failures)
        ai_text   = self.analyser.analyse_failures(failures)

        # Attach severity to each result
        for r in results:
            r["severity"] = score_severity(
                r.get("test_name", ""), r.get("actual_result", ""), r.get("status", "")
            )

        # Record in run history
        from config import RUN_ID
        trend_entry = self.history.record(
            RUN_ID, total, passed, failed, errors, duration
        )
        trend = self.history.get_trend(5)
        regressing = self.history.is_regressing()

        html = self._render_html(
            results, total, passed, failed, errors, skipped,
            duration, groups, ai_text, trend, regressing
        )

        # Save alongside base report
        from config import REPORT_DIR
        intel_path = os.path.join(REPORT_DIR, "intelligence_report.html")
        with open(intel_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"    Intel: {intel_path}")

    def _render_html(self, results, total, passed, failed, errors, skipped,
                     duration, groups, ai_text, trend, regressing) -> str:
        pass_rate = round(passed / total * 100, 1) if total else 0

        # Severity counts
        sev_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for r in results:
            sev = r.get("severity", "")
            if sev in sev_counts:
                sev_counts[sev] += 1

        # Bug group cards HTML
        group_html = ""
        for key, group in groups.items():
            tests_html = "".join(
                f"<li>{t.get('test_name', '')}</li>"
                for t in group["tests"]
            )
            group_html += f"""
            <div class="bug-group">
                <div class="bug-group-header">
                    <span class="root-cause">{key.upper().replace('_',' ')}</span>
                    <span class="bug-count">{len(group['tests'])} test(s)</span>
                </div>
                <p class="bug-desc">{group['description']}</p>
                <p class="bug-fix"><strong>Fix:</strong> {group['fix']}</p>
                <ul class="bug-tests">{tests_html}</ul>
            </div>"""

        # Trend chart data
        trend_labels = [t["run_id"][-15:] for t in trend]
        trend_rates  = [t["pass_rate"] for t in trend]
        regression_banner = """
            <div class="regression-banner">
                ⚠️ REGRESSION DETECTED — Pass rate is declining across recent runs.
            </div>""" if regressing else ""

        # Results table rows
        rows_html = ""
        for i, r in enumerate(results):
            sev    = r.get("severity", "NONE")
            status = r.get("status", "")
            sev_cls = f"sev-{sev.lower()}" if sev != "NONE" else ""
            rows_html += f"""
            <tr data-status="{status}" data-sev="{sev}">
                <td class="mono">{r.get('test_name','')}</td>
                <td><span class="cat-badge">{r.get('category','')}</span></td>
                <td class="mono small">{r.get('actual_result','')[:120]}</td>
                <td><span class="badge badge-{status.lower()}">{status}</span></td>
                <td><span class="sev-badge {sev_cls}">{sev}</span></td>
                <td class="mono">{r.get('response_time_ms',0)} ms</td>
            </tr>"""

        ai_html = ai_text.replace("\n", "<br>").replace("●", "•")

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Intelligence Report — {self.site_display_name}</title>
<style>
:root {{
  --bg:#0d1117; --surface:#161b22; --surface2:#21262d;
  --border:#30363d; --text:#e6edf3; --muted:#8b949e;
  --pass:#3fb950; --fail:#f85149; --error:#d29922;
  --skip:#8b949e; --accent:#58a6ff;
  --crit:#ff4444; --high:#ff8c00; --med:#ffd700; --low:#58a6ff;
}}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ font-family:'Segoe UI',system-ui,sans-serif; background:var(--bg);
        color:var(--text); padding:24px 28px; line-height:1.5; font-size:14px; }}
h1 {{ font-size:1.5rem; font-weight:700; color:var(--accent); margin-bottom:4px; }}
h2 {{ font-size:1.1rem; color:var(--accent); margin:24px 0 12px;
      border-bottom:1px solid var(--border); padding-bottom:6px; }}
.meta {{ color:var(--muted); font-size:.82rem; margin-bottom:20px; }}
.cards {{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom:20px; }}
.card {{ background:var(--surface); border:1px solid var(--border);
          border-radius:8px; padding:12px 18px; min-width:100px; text-align:center; }}
.card .num {{ font-size:1.8rem; font-weight:700; }}
.card .lbl {{ font-size:.7rem; color:var(--muted); text-transform:uppercase; }}
.sev-cards {{ display:flex; gap:10px; flex-wrap:wrap; margin-bottom:20px; }}
.sev-card {{ border-radius:8px; padding:10px 16px; text-align:center; min-width:90px; }}
.sev-card.crit {{ background:#2a0a0a; border:1px solid var(--crit); }}
.sev-card.high {{ background:#2a1a00; border:1px solid var(--high); }}
.sev-card.med  {{ background:#2a2000; border:1px solid var(--med); }}
.sev-card.low  {{ background:#0a1a2a; border:1px solid var(--low); }}
.sev-card .num {{ font-size:1.6rem; font-weight:700; }}
.sev-card.crit .num {{ color:var(--crit); }}
.sev-card.high .num {{ color:var(--high); }}
.sev-card.med  .num {{ color:var(--med);  }}
.sev-card.low  .num {{ color:var(--low);  }}
.regression-banner {{ background:#3b1a1a; border:1px solid var(--fail);
  color:var(--fail); padding:10px 16px; border-radius:8px; margin-bottom:16px;
  font-weight:600; }}
.bug-group {{ background:var(--surface); border:1px solid var(--border);
  border-radius:8px; padding:14px; margin-bottom:12px; }}
.bug-group-header {{ display:flex; justify-content:space-between;
  align-items:center; margin-bottom:8px; }}
.root-cause {{ font-weight:700; color:var(--high); font-size:.9rem; }}
.bug-count {{ background:var(--surface2); color:var(--muted);
  padding:2px 8px; border-radius:12px; font-size:.75rem; }}
.bug-desc {{ color:var(--text); font-size:.85rem; margin-bottom:6px; }}
.bug-fix {{ color:#58d68d; font-size:.82rem; margin-bottom:8px; }}
.bug-tests {{ color:var(--muted); font-size:.78rem; padding-left:20px; }}
.ai-box {{ background:var(--surface); border:1px solid var(--accent);
  border-radius:8px; padding:16px; font-size:.83rem;
  color:var(--text); line-height:1.7; margin-bottom:20px; }}
table {{ width:100%; border-collapse:collapse; font-size:.8rem; }}
th {{ background:var(--surface); padding:8px 10px; text-align:left;
      color:var(--muted); font-weight:600; border-bottom:1px solid var(--border); }}
td {{ padding:7px 10px; border-bottom:1px solid var(--border); vertical-align:top; }}
.mono {{ font-family:monospace; }}
.small {{ font-size:.75rem; }}
.cat-badge {{ background:var(--surface2); color:var(--accent);
  border:1px solid var(--border); padding:2px 7px; border-radius:12px; font-size:.72rem; }}
.badge {{ display:inline-block; padding:2px 9px; border-radius:12px;
  font-size:.72rem; font-weight:700; }}
.badge-pass  {{ background:#1b3a25; color:var(--pass); border:1px solid var(--pass); }}
.badge-fail  {{ background:#3b1a1a; color:var(--fail); border:1px solid var(--fail); }}
.badge-error {{ background:#3b2e0e; color:var(--error);border:1px solid var(--error);}}
.badge-skip  {{ background:#1e2430; color:var(--skip); border:1px solid var(--skip); }}
.sev-badge {{ display:inline-block; padding:2px 7px; border-radius:10px;
  font-size:.7rem; font-weight:700; }}
.sev-critical {{ background:#2a0a0a; color:var(--crit); border:1px solid var(--crit); }}
.sev-high    {{ background:#2a1a00; color:var(--high); border:1px solid var(--high); }}
.sev-medium  {{ background:#2a2000; color:var(--med);  border:1px solid var(--med); }}
.sev-low     {{ background:#0a1a2a; color:var(--low);  border:1px solid var(--low); }}
.sev-none    {{ color:var(--muted); font-size:.7rem; }}
.trend-row {{ display:flex; gap:8px; align-items:flex-end; height:60px; margin:12px 0; }}
.trend-bar {{ background:var(--accent); border-radius:3px 3px 0 0;
  min-width:32px; display:flex; align-items:flex-end; justify-content:center;
  font-size:.68rem; color:#000; font-weight:700; padding:2px; }}
</style>
</head>
<body>
<h1>🔮 {self.site_display_name} — Intelligence Report</h1>
<p class="meta">Phase 3 Analysis &nbsp;·&nbsp;
  Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} &nbsp;·&nbsp;
  Duration: {duration}s</p>

{regression_banner}

<h2>Summary</h2>
<div class="cards">
  <div class="card"><div class="num">{total}</div><div class="lbl">Total</div></div>
  <div class="card"><div class="num" style="color:var(--pass)">{passed}</div><div class="lbl">Passed</div></div>
  <div class="card"><div class="num" style="color:var(--fail)">{failed}</div><div class="lbl">Failed</div></div>
  <div class="card"><div class="num" style="color:var(--error)">{errors}</div><div class="lbl">Errors</div></div>
  <div class="card"><div class="num" style="color:var(--skip)">{skipped}</div><div class="lbl">Skipped</div></div>
  <div class="card"><div class="num" style="color:var(--accent)">{pass_rate}%</div><div class="lbl">Pass Rate</div></div>
</div>

<h2>Severity Breakdown</h2>
<div class="sev-cards">
  <div class="sev-card crit"><div class="num">{sev_counts['CRITICAL']}</div><div class="lbl" style="color:var(--crit);font-size:.7rem">CRITICAL</div></div>
  <div class="sev-card high"><div class="num">{sev_counts['HIGH']}</div><div class="lbl" style="color:var(--high);font-size:.7rem">HIGH</div></div>
  <div class="sev-card med"><div class="num">{sev_counts['MEDIUM']}</div><div class="lbl" style="color:var(--med);font-size:.7rem">MEDIUM</div></div>
  <div class="sev-card low"><div class="num">{sev_counts['LOW']}</div><div class="lbl" style="color:var(--low);font-size:.7rem">LOW</div></div>
</div>

<h2>Pass Rate Trend (Last {len(trend)} Runs)</h2>
<div class="trend-row">
{''.join(f'<div class="trend-bar" style="height:{max(4,int(r*0.6))}px;background:{"var(--pass)" if r>=90 else "var(--error)" if r<70 else "var(--high)"}">{r}%</div>' for r in trend_rates)}
</div>

<h2>AI-Powered Failure Analysis</h2>
<div class="ai-box">{ai_html}</div>

<h2>Bug Groups by Root Cause ({len(groups)} group(s))</h2>
{group_html if group_html else '<p style="color:var(--pass)">✅ No failures to group.</p>'}

<h2>All Test Results</h2>
<table>
<thead><tr>
  <th>Test Name</th><th>Category</th><th>Actual Result</th>
  <th>Status</th><th>Severity</th><th>Time</th>
</tr></thead>
<tbody>{rows_html}</tbody>
</table>
</body></html>"""