"""
agent/reporter.py
─────────────────────────────────────────────────────────────────────────────
Reporter — Phase 4 of the agent pipeline.

Takes the list of TestResult objects and writes:
  - reports/<run_id>/report.json  — machine-readable full data
  - reports/<run_id>/report.html  — human-readable visual report

The HTML report shows:
  - Summary stats and donut chart
  - Which pages the agent crawled
  - How many tests Gemini generated vs how many ran
  - Per-test: name, category, priority badge, status, inputs, steps, screenshot
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime
from pathlib import Path

from agent.models import PageSnapshot, TestCase, TestResult

REPORTS_DIR = "reports"


class AgentReporter:
    """
    Usage:
        reporter = AgentReporter(run_id="20260721_153000", site_url="https://...")
        reporter.save(results, snapshots, generated_count=25)
        print(reporter.json_path, reporter.html_path)
    """

    def __init__(self, run_id: str, site_url: str):
        self.run_id    = run_id
        self.site_url  = site_url
        self.report_dir = Path(REPORTS_DIR) / run_id
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.json_path = str(self.report_dir / "report.json")
        self.html_path = str(self.report_dir / "report.html")

    # ── Public ────────────────────────────────────────────────────────────────

    def save(
        self,
        results:         list[TestResult],
        snapshots:       list[PageSnapshot],
        generated_count: int = 0,
    ) -> None:
        stats = self._compute_stats(results)
        self._write_json(results, snapshots, stats, generated_count)
        self._write_html(results, snapshots, stats, generated_count)

    # ── Stats ─────────────────────────────────────────────────────────────────

    def _compute_stats(self, results: list[TestResult]) -> dict:
        passed  = sum(1 for r in results if r.status == "PASS")
        failed  = sum(1 for r in results if r.status == "FAIL")
        errors  = sum(1 for r in results if r.status == "ERROR")
        total   = len(results)
        rate    = round(passed / total * 100, 1) if total else 0.0
        dur_s   = round(sum(r.duration_ms for r in results) / 1000, 1)

        cats: dict[str, dict] = {}
        for r in results:
            cat = r.test_case.category
            if cat not in cats:
                cats[cat] = {"pass": 0, "fail": 0, "error": 0}
            cats[cat][r.status.lower()] = cats[cat].get(r.status.lower(), 0) + 1

        return {
            "total": total, "passed": passed, "failed": failed,
            "errors": errors, "pass_rate": rate,
            "duration_s": dur_s, "by_category": cats,
        }

    # ── JSON ──────────────────────────────────────────────────────────────────

    def _write_json(self, results, snapshots, stats, generated_count):
        data = {
            "run_id":          self.run_id,
            "site_url":        self.site_url,
            "generated_at":    datetime.now().isoformat(),
            "pages_crawled":   [s.url for s in snapshots],
            "tests_generated": generated_count,
            "tests_executed":  stats["total"],
            "stats":           stats,
            "results":         [r.as_dict() for r in results],
        }
        Path(self.json_path).write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ── HTML ──────────────────────────────────────────────────────────────────

    def _write_html(self, results, snapshots, stats, generated_count):
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Test Agent Report — {self.run_id}</title>
<style>
  :root {{
    --bg:      #0d1117; --surface: #161b22; --border: #30363d;
    --text:    #e6edf3; --muted:   #8b949e;
    --green:   #3fb950; --red:     #f85149; --yellow:  #d29922;
    --blue:    #388bfd; --purple:  #bc8cff;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 14px; line-height: 1.5; }}
  .container {{ max-width: 1100px; margin: 0 auto; padding: 32px 16px; }}
  h1 {{ font-size: 22px; margin-bottom: 4px; }}
  .meta {{ color: var(--muted); font-size: 12px; margin-bottom: 32px; }}
  .meta a {{ color: var(--blue); }}
  .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; margin-bottom: 32px; }}
  .stat-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; text-align: center; }}
  .stat-card .num {{ font-size: 32px; font-weight: 700; }}
  .stat-card .lbl {{ color: var(--muted); font-size: 12px; margin-top: 4px; }}
  .green {{ color: var(--green); }} .red {{ color: var(--red); }} .yellow {{ color: var(--yellow); }} .blue {{ color: var(--blue); }}
  .section-title {{ font-size: 16px; font-weight: 600; margin: 28px 0 12px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }}
  .crawled-pages {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 24px; }}
  .page-chip {{ background: var(--surface); border: 1px solid var(--border); border-radius: 20px; padding: 4px 12px; font-size: 12px; color: var(--muted); }}
  .filter-bar {{ display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }}
  .filter-btn {{ background: var(--surface); border: 1px solid var(--border); color: var(--muted); padding: 6px 14px; border-radius: 20px; cursor: pointer; font-size: 12px; }}
  .filter-btn.active {{ border-color: var(--blue); color: var(--blue); }}
  .test-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 10px; overflow: hidden; }}
  .test-header {{ display: flex; align-items: center; gap: 10px; padding: 12px 16px; cursor: pointer; }}
  .test-header:hover {{ background: rgba(255,255,255,.03); }}
  .badge {{ border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: 600; letter-spacing: .05em; }}
  .badge-pass {{ background: rgba(63,185,80,.15); color: var(--green); }}
  .badge-fail {{ background: rgba(248,81,73,.15); color: var(--red); }}
  .badge-error {{ background: rgba(210,153,34,.15); color: var(--yellow); }}
  .badge-high {{ background: rgba(248,81,73,.1); color: var(--red); }}
  .badge-medium {{ background: rgba(210,153,34,.1); color: var(--yellow); }}
  .badge-low {{ background: rgba(63,185,80,.1); color: var(--green); }}
  .test-id {{ font-family: monospace; font-size: 11px; color: var(--muted); }}
  .test-name {{ flex: 1; font-size: 13px; }}
  .test-cat {{ font-size: 11px; color: var(--muted); }}
  .test-dur {{ font-size: 11px; color: var(--muted); margin-left: auto; white-space: nowrap; }}
  .test-body {{ display: none; padding: 0 16px 16px; border-top: 1px solid var(--border); }}
  .test-body.open {{ display: block; }}
  .inputs-row {{ margin: 10px 0 6px; font-size: 12px; color: var(--muted); }}
  .inputs-row strong {{ color: var(--text); }}
  .outcome-row {{ font-size: 12px; margin-bottom: 10px; }}
  .steps-table {{ width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 6px; }}
  .steps-table th {{ text-align: left; color: var(--muted); padding: 4px 8px; border-bottom: 1px solid var(--border); }}
  .steps-table td {{ padding: 5px 8px; border-bottom: 1px solid rgba(255,255,255,.04); vertical-align: top; }}
  .steps-table code {{ font-family: monospace; font-size: 11px; background: rgba(255,255,255,.05); padding: 1px 5px; border-radius: 3px; word-break: break-all; }}
  .ss-link {{ color: var(--blue); font-size: 12px; display: inline-block; margin-top: 8px; }}
  .category-table {{ width: 100%; border-collapse: collapse; margin-bottom: 28px; }}
  .category-table th {{ text-align: left; color: var(--muted); padding: 6px 10px; font-size: 12px; border-bottom: 1px solid var(--border); }}
  .category-table td {{ padding: 6px 10px; border-bottom: 1px solid rgba(255,255,255,.04); font-size: 13px; }}
  .ai-badge {{ display: inline-block; background: rgba(188,140,255,.1); color: var(--purple); border-radius: 4px; padding: 1px 7px; font-size: 10px; font-weight: 700; letter-spacing: .06em; margin-left: 6px; }}
</style>
</head>
<body>
<div class="container">

  <h1>🔮 AI Test Agent Report <span class="ai-badge">GEMINI GENERATED</span></h1>
  <div class="meta">
    Run ID: <strong>{self.run_id}</strong> &nbsp;·&nbsp;
    Site: <a href="{self.site_url}" target="_blank">{self.site_url}</a> &nbsp;·&nbsp;
    Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
  </div>

  {self._html_summary(stats, snapshots, generated_count)}
  {self._html_category_breakdown(stats)}
  {self._html_crawled_pages(snapshots)}
  {self._html_test_list(results)}

</div>
<script>
document.querySelectorAll('.test-header').forEach(h => {{
  h.addEventListener('click', () => {{
    h.nextElementSibling.classList.toggle('open');
  }});
}});
document.querySelectorAll('.filter-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    const f = btn.dataset.filter;
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.test-card').forEach(card => {{
      if (f === 'all' || card.dataset.status === f) {{
        card.style.display = '';
      }} else {{
        card.style.display = 'none';
      }}
    }});
  }});
}});
</script>
</body>
</html>"""
        Path(self.html_path).write_text(html, encoding="utf-8")

    # ── HTML sections ─────────────────────────────────────────────────────────

    def _html_summary(self, stats, snapshots, generated_count) -> str:
        donut = _make_donut(stats)
        return f"""
<div class="summary-grid">
  <div class="stat-card" style="display:flex;align-items:center;justify-content:center">{donut}</div>
  <div class="stat-card"><div class="num green">{stats['passed']}</div><div class="lbl">PASSED</div></div>
  <div class="stat-card"><div class="num red">{stats['failed'] + stats['errors']}</div><div class="lbl">FAILED / ERROR</div></div>
  <div class="stat-card"><div class="num blue">{stats['pass_rate']}%</div><div class="lbl">PASS RATE</div></div>
  <div class="stat-card"><div class="num">{len(snapshots)}</div><div class="lbl">PAGES CRAWLED</div></div>
  <div class="stat-card"><div class="num" style="color:var(--purple)">{generated_count}</div><div class="lbl">AI-GENERATED TESTS</div></div>
  <div class="stat-card"><div class="num">{stats['total']}</div><div class="lbl">TESTS EXECUTED</div></div>
  <div class="stat-card"><div class="num">{stats['duration_s']}s</div><div class="lbl">TOTAL DURATION</div></div>
</div>"""

    def _html_category_breakdown(self, stats) -> str:
        rows = ""
        for cat, counts in sorted(stats["by_category"].items()):
            p = counts.get("pass", 0)
            f = counts.get("fail", 0) + counts.get("error", 0)
            total = p + f
            rate  = round(p / total * 100) if total else 0
            bar_color = "#3fb950" if rate >= 80 else ("#d29922" if rate >= 50 else "#f85149")
            rows += f"""
<tr>
  <td>{cat}</td>
  <td class="green">{p}</td>
  <td class="red">{f}</td>
  <td>
    <div style="display:flex;align-items:center;gap:8px">
      <div style="flex:1;background:var(--border);border-radius:3px;height:6px">
        <div style="width:{rate}%;background:{bar_color};height:6px;border-radius:3px"></div>
      </div>
      <span style="font-size:11px;color:var(--muted);width:35px">{rate}%</span>
    </div>
  </td>
</tr>"""
        return f"""
<div class="section-title">Results by Category</div>
<table class="category-table">
  <tr><th>Category</th><th>Passed</th><th>Failed</th><th>Pass Rate</th></tr>
  {rows}
</table>"""

    def _html_crawled_pages(self, snapshots) -> str:
        chips = "".join(f'<div class="page-chip">{s.url}</div>' for s in snapshots)
        return f"""
<div class="section-title">Pages Crawled by Agent</div>
<div class="crawled-pages">{chips}</div>"""

    def _html_test_list(self, results) -> str:
        cards = ""
        for r in results:
            tc     = r.test_case
            status = r.status
            st_cls = {"PASS": "badge-pass", "FAIL": "badge-fail", "ERROR": "badge-error"}.get(status, "")
            pr_cls = {"HIGH": "badge-high", "MEDIUM": "badge-medium", "LOW": "badge-low"}.get(tc.priority, "")

            # Steps table
            step_rows = ""
            for sr in r.step_results:
                s_icon = "✅" if sr.status == "PASS" else ("⚠️" if sr.status == "SKIP" else "❌")
                step_rows += f"""
<tr>
  <td>{s_icon}</td>
  <td><code>{sr.step.action}</code></td>
  <td><code>{(sr.step.selector or sr.step.url or sr.step.value)[:60]}</code></td>
  <td style="color:var(--muted)">{sr.message[:80]}</td>
</tr>"""

            # Inputs summary
            inputs_html = ""
            if tc.inputs:
                pairs = ", ".join(f"<strong>{k}</strong>: {v}" for k, v in list(tc.inputs.items())[:4])
                inputs_html = f'<div class="inputs-row">Inputs: {pairs}</div>'

            # Screenshot
            ss_html = ""
            if r.screenshot and os.path.exists(r.screenshot):
                rel = os.path.relpath(r.screenshot, str(self.report_dir))
                ss_html = f'<a class="ss-link" href="{rel}" target="_blank">📷 View failure screenshot</a>'

            cards += f"""
<div class="test-card" data-status="{status.lower()}">
  <div class="test-header">
    <span class="badge {st_cls}">{status}</span>
    <span class="badge {pr_cls}">{tc.priority}</span>
    <span class="test-id">{tc.id}</span>
    <span class="test-name">{tc.name}</span>
    <span class="test-cat">{tc.category}</span>
    <span class="test-dur">{r.duration_ms:.0f}ms</span>
  </div>
  <div class="test-body">
    {inputs_html}
    <div class="outcome-row">
      <strong>Expected:</strong> {tc.expected_outcome}<br>
      <strong>Actual:</strong> {r.actual_outcome or r.error or '(same as expected)'}
    </div>
    <table class="steps-table">
      <tr><th></th><th>Action</th><th>Target / Value</th><th>Result</th></tr>
      {step_rows}
    </table>
    {ss_html}
  </div>
</div>"""

        passed_count = sum(1 for r in results if r.status == "PASS")
        failed_count = len(results) - passed_count
        return f"""
<div class="section-title">Test Results ({len(results)} total)</div>
<div class="filter-bar">
  <button class="filter-btn active" data-filter="all">All ({len(results)})</button>
  <button class="filter-btn" data-filter="pass">Passed ({passed_count})</button>
  <button class="filter-btn" data-filter="fail">Failed ({failed_count})</button>
</div>
{cards}"""


# ── Donut chart ───────────────────────────────────────────────────────────────

def _make_donut(stats: dict) -> str:
    total = stats["total"]
    if total == 0:
        return '<svg width="80" height="80"><circle r="34" cx="40" cy="40" fill="none" stroke="#30363d" stroke-width="10"/></svg>'

    R, cx, cy = 34, 40, 40
    circumf   = 2 * math.pi * R
    segments  = [
        (stats["passed"], "#3fb950"),
        (stats["failed"], "#f85149"),
        (stats["errors"], "#d29922"),
    ]
    arcs, offset = [], 0.0
    for count, color in segments:
        if count <= 0:
            continue
        dash  = (count / total) * circumf
        rest  = circumf - dash
        arcs.append(
            f'<circle r="{R}" cx="{cx}" cy="{cy}" fill="none" stroke="{color}" '
            f'stroke-width="10" stroke-dasharray="{dash:.2f} {rest:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {cx} {cy})"/>'
        )
        offset += dash

    pct = f"{stats['pass_rate']}%"
    return (
        f'<svg width="80" height="80" viewBox="0 0 80 80">'
        f'<circle r="{R}" cx="{cx}" cy="{cy}" fill="none" stroke="#30363d" stroke-width="10"/>'
        + "".join(arcs) +
        f'<text x="{cx}" y="{cy+5}" text-anchor="middle" fill="#e6edf3" '
        f'font-size="12" font-weight="700">{pct}</text>'
        f'</svg>'
    )
