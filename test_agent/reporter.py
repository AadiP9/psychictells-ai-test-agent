"""
reporter.py
Collects test results, computes statistics, and writes a JSON + rich HTML report.
"""

import json
import math
import os
import time
from datetime import datetime
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import REPORTS_DIR, HTML_REPORT, REPORT_FILE

Path(REPORTS_DIR).mkdir(parents=True, exist_ok=True)


# ── SVG donut chart ────────────────────────────────────────────────────────────
def _make_donut_svg(stats: dict) -> str:
    total = stats["total"]
    if total == 0:
        return (
            '<svg width="120" height="120" viewBox="0 0 120 120">'
            '<circle r="50" cx="60" cy="60" fill="none" stroke="#30363d" stroke-width="14"/>'
            '<text x="60" y="65" text-anchor="middle" fill="#8b949e" font-size="12">No data</text>'
            "</svg>"
        )

    R           = 50
    cx, cy      = 60, 60
    circumf     = 2 * math.pi * R      # ≈ 314.159
    passed      = stats["passed"]
    failed      = stats["failed"]
    errors      = stats["errors"]
    skipped     = stats["skipped"]

    segments = [
        (passed,  "#3fb950"),
        (failed,  "#f85149"),
        (errors,  "#d29922"),
        (skipped, "#8b949e"),
    ]

    arcs   = []
    offset = 0.0
    for count, color in segments:
        if count <= 0:
            continue
        dash   = (count / total) * circumf
        rest   = circumf - dash
        arcs.append(
            f'<circle r="{R}" cx="{cx}" cy="{cy}" fill="none" stroke="{color}" '
            f'stroke-width="14" '
            f'stroke-dasharray="{dash:.3f} {rest:.3f}" '
            f'stroke-dashoffset="{-offset:.3f}" '
            f'transform="rotate(-90 {cx} {cy})"/>'
        )
        offset += dash

    rate_text = f'{stats["pass_rate"]}%'
    return (
        '<svg width="120" height="120" viewBox="0 0 120 120">'
        f'<circle r="{R}" cx="{cx}" cy="{cy}" fill="none" stroke="#21262d" stroke-width="14"/>'
        + "".join(arcs)
        + f'<text x="{cx}" y="{cy - 5}" text-anchor="middle" fill="#e6edf3" '
          f'font-size="18" font-weight="bold">{rate_text}</text>'
        + f'<text x="{cx}" y="{cy + 12}" text-anchor="middle" fill="#8b949e" '
          f'font-size="10">Pass Rate</text>'
        + "</svg>"
    )


class TestReporter:
    def __init__(self, suite_name: str = "AI Test Suite", site_url: str = ""):
        self.suite_name   = suite_name
        self.site_url     = site_url
        self.start_time   = time.time()
        self.results: list[dict] = []
        self._id_counter  = 1

    # ── Result recording ───────────────────────────────────────────────────────
    def add_result(
        self,
        test_name:        str,
        input_data:       dict,
        expected_result:  str,
        actual_result:    str,
        status:           str,          # PASS | FAIL | ERROR | SKIP
        response_time_ms: int  = 0,
        screenshot:       str  = "",
        notes:            str  = "",
        category:         str  = "General",
    ):
        self.results.append({
            "id":               f"TC-{self._id_counter:03d}",
            "name":             test_name,
            "category":         category,
            "input":            input_data,
            "expected_result":  expected_result,
            "actual_result":    actual_result,
            "status":           status,
            "response_time_ms": response_time_ms,
            "screenshot":       screenshot,
            "notes":            notes,
            "timestamp":        datetime.now().isoformat(),
        })
        icon = {"PASS": "✅", "FAIL": "❌", "ERROR": "⚠️", "SKIP": "⏭️"}.get(status, "•")
        print(f"    {icon} [{status}] {test_name}")
        self._id_counter += 1

    # ── Stats ──────────────────────────────────────────────────────────────────
    @property
    def stats(self) -> dict:
        total  = len(self.results)
        counts = {"PASS": 0, "FAIL": 0, "ERROR": 0, "SKIP": 0}
        for r in self.results:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        return {
            "total":      total,
            "passed":     counts["PASS"],
            "failed":     counts["FAIL"],
            "errors":     counts["ERROR"],
            "skipped":    counts["SKIP"],
            "pass_rate":  round(counts["PASS"] / total * 100, 1) if total else 0,
            "duration_s": round(time.time() - self.start_time, 2),
        }

    # ── JSON export ───────────────────────────────────────────────────────────
    def save_json(self):
        payload = {
            "suite":     self.suite_name,
            "generated": datetime.now().isoformat(),
            "stats":     self.stats,
            "results":   self.results,
        }
        with open(REPORT_FILE, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"[Reporter] JSON → {REPORT_FILE}")
        return REPORT_FILE

    # ── HTML export ───────────────────────────────────────────────────────────
    def save_html(self):
        st = self.stats

        # Unique categories for filter buttons
        categories = sorted({r["category"] for r in self.results})
        cat_buttons = "".join(
            f'<button class="filter-btn" onclick="filterCat(\'{c}\')" '
            f'title="Filter by {c}">{c}</button>'
            for c in categories
        )

        # Table rows
        rows = ""
        for r in self.results:
            badge_cls = {
                "PASS":  "badge-pass",
                "FAIL":  "badge-fail",
                "ERROR": "badge-error",
                "SKIP":  "badge-skip",
            }.get(r["status"], "badge-skip")

            sc_html = (
                f'<a href="../{r["screenshot"]}" target="_blank" '
                f'class="sc-link">📷 View</a>'
                if r["screenshot"] else "—"
            )
            raw_q  = r["input"].get("question", "")
            q_disp = (raw_q[:70] + "…") if len(raw_q) > 70 else raw_q
            q_full = raw_q.replace('"', "&quot;").replace("<", "&lt;")

            notes_html = (
                f'<br><span class="notes">{r["notes"]}</span>'
                if r["notes"] else ""
            )

            rows += f"""
            <tr data-status="{r['status']}" data-category="{r['category']}">
              <td class="mono tc-id">{r['id']}</td>
              <td>{r['name']}{notes_html}</td>
              <td><span class="cat-badge">{r['category']}</span></td>
              <td class="mono q-cell" title="{q_full}">{q_disp}</td>
              <td class="expect">{r['expected_result']}</td>
              <td class="actual">{r['actual_result']}</td>
              <td><span class="badge {badge_cls}">{r['status']}</span></td>
              <td class="mono rt-cell">{r['response_time_ms']} ms</td>
              <td>{sc_html}</td>
            </tr>"""

        donut = _make_donut_svg(st)

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{self.suite_name} – Report</title>
<style>
  :root {{
    --bg:#0d1117; --surface:#161b22; --surface2:#21262d;
    --border:#30363d; --border2:#3d444d;
    --pass:#3fb950; --fail:#f85149; --error:#d29922; --skip:#8b949e;
    --accent:#58a6ff; --text:#e6edf3; --muted:#8b949e;
    --row-hover:#1c2128;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:'Segoe UI',system-ui,sans-serif; background:var(--bg);
          color:var(--text); padding:24px 28px; line-height:1.5; }}

  /* ── Header ── */
  .header {{ display:flex; align-items:flex-start; gap:24px; margin-bottom:28px; }}
  .header-text h1 {{ font-size:1.55rem; font-weight:700; margin-bottom:3px; }}
  .meta {{ color:var(--muted); font-size:.82rem; }}

  /* ── Summary cards ── */
  .cards {{ display:flex; gap:14px; flex-wrap:wrap; margin-bottom:28px; align-items:center; }}
  .card {{ background:var(--surface); border:1px solid var(--border);
           border-radius:10px; padding:14px 20px; min-width:110px; text-align:center; }}
  .card .num {{ font-size:1.9rem; font-weight:700; line-height:1.15; }}
  .card .lbl {{ font-size:.72rem; color:var(--muted); text-transform:uppercase;
                letter-spacing:.07em; margin-top:2px; }}
  .card.total .num {{ color:var(--text); }}
  .card.pass  .num {{ color:var(--pass); }}
  .card.fail  .num {{ color:var(--fail); }}
  .card.error .num {{ color:var(--error); }}
  .card.skip  .num {{ color:var(--skip); }}

  /* ── Filter bar ── */
  .filters {{ display:flex; flex-wrap:wrap; gap:8px; margin-bottom:18px; align-items:center; }}
  .filters-label {{ font-size:.8rem; color:var(--muted); margin-right:4px; }}

  .filter-btn {{
    background:var(--surface2); border:1px solid var(--border2);
    color:var(--text); padding:4px 14px; border-radius:20px;
    font-size:.78rem; cursor:pointer; transition:all .15s;
  }}
  .filter-btn:hover  {{ border-color:var(--accent); color:var(--accent); }}
  .filter-btn.active {{ background:var(--accent); color:#000; border-color:var(--accent); font-weight:600; }}

  .status-filters {{ display:flex; gap:8px; }}
  .sf {{ background:var(--surface2); border:1px solid var(--border2);
         color:var(--text); padding:4px 14px; border-radius:20px;
         font-size:.78rem; cursor:pointer; transition:all .15s; }}
  .sf:hover {{ opacity:.8; }}
  .sf-pass  {{ border-color:var(--pass);  }}
  .sf-fail  {{ border-color:var(--fail);  }}
  .sf-error {{ border-color:var(--error); }}
  .sf-pass.active  {{ background:var(--pass);  color:#000; }}
  .sf-fail.active  {{ background:var(--fail);  color:#fff; }}
  .sf-error.active {{ background:var(--error); color:#000; }}

  /* ── Table ── */
  .table-wrap {{ overflow-x:auto; border-radius:8px; border:1px solid var(--border); }}
  table {{ width:100%; border-collapse:collapse; font-size:.83rem; }}
  th {{
    background:var(--surface); border-bottom:1px solid var(--border2);
    padding:10px 12px; text-align:left; color:var(--muted); font-weight:600;
    white-space:nowrap; position:sticky; top:0; z-index:1;
  }}
  td {{ border-bottom:1px solid var(--border); padding:9px 12px; vertical-align:top; }}
  tr:hover td {{ background:var(--row-hover); }}
  tr:last-child td {{ border-bottom:none; }}

  .mono {{ font-family:'Courier New',Courier,monospace; font-size:.80rem; }}
  .tc-id {{ white-space:nowrap; color:var(--muted); }}
  .q-cell {{ max-width:220px; word-break:break-word; }}
  .expect, .actual {{ max-width:260px; word-break:break-word; font-size:.80rem; }}
  .rt-cell {{ white-space:nowrap; }}
  .notes {{ color:var(--muted); font-size:.75rem; font-style:italic; }}

  .badge {{
    display:inline-block; padding:3px 11px; border-radius:20px;
    font-size:.74rem; font-weight:700; white-space:nowrap;
  }}
  .badge-pass  {{ background:#1b3a25; color:var(--pass);  border:1px solid var(--pass);  }}
  .badge-fail  {{ background:#3b1a1a; color:var(--fail);  border:1px solid var(--fail);  }}
  .badge-error {{ background:#3b2e0e; color:var(--error); border:1px solid var(--error); }}
  .badge-skip  {{ background:#1e2430; color:var(--skip);  border:1px solid var(--skip);  }}

  .cat-badge {{
    background:var(--surface2); color:var(--accent);
    border:1px solid var(--border2); padding:2px 9px;
    border-radius:20px; font-size:.73rem; white-space:nowrap;
  }}
  .sc-link {{ color:var(--accent); text-decoration:none; }}
  .sc-link:hover {{ text-decoration:underline; }}

  /* ── Legend ── */
  .legend {{ display:flex; gap:16px; flex-wrap:wrap; margin-top:6px; }}
  .legend-item {{ display:flex; align-items:center; gap:5px; font-size:.76rem; color:var(--muted); }}
  .legend-dot {{ width:10px; height:10px; border-radius:50%; }}

  /* ── Hidden rows ── */
  tr.hidden {{ display:none; }}
</style>
</head>
<body>

<div class="header">
  <div>{donut}</div>
  <div class="header-text">
    <h1>🔮 {self.suite_name}</h1>
    <p class="meta">
      Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} &nbsp;·&nbsp;
      Duration: {st['duration_s']}s &nbsp;·&nbsp;
      Site: {self.site_url or 'N/A'}
    </p>
    <div class="legend" style="margin-top:10px;">
      <span class="legend-item"><span class="legend-dot" style="background:var(--pass)"></span>Pass</span>
      <span class="legend-item"><span class="legend-dot" style="background:var(--fail)"></span>Fail</span>
      <span class="legend-item"><span class="legend-dot" style="background:var(--error)"></span>Error</span>
      <span class="legend-item"><span class="legend-dot" style="background:var(--skip)"></span>Skip</span>
    </div>
  </div>
</div>

<div class="cards">
  <div class="card total"><div class="num">{st['total']}</div><div class="lbl">Total</div></div>
  <div class="card pass"><div class="num">{st['passed']}</div><div class="lbl">Passed</div></div>
  <div class="card fail"><div class="num">{st['failed']}</div><div class="lbl">Failed</div></div>
  <div class="card error"><div class="num">{st['errors']}</div><div class="lbl">Errors</div></div>
  <div class="card skip"><div class="num">{st['skipped']}</div><div class="lbl">Skipped</div></div>
</div>

<div class="filters">
  <span class="filters-label">Status:</span>
  <div class="status-filters">
    <button class="sf sf-pass"  onclick="filterStatus('PASS')">✅ Pass ({st['passed']})</button>
    <button class="sf sf-fail"  onclick="filterStatus('FAIL')">❌ Fail ({st['failed']})</button>
    <button class="sf sf-error" onclick="filterStatus('ERROR')">⚠️ Error ({st['errors']})</button>
    <button class="sf" onclick="filterStatus(null)">All</button>
  </div>
</div>

<div class="filters">
  <span class="filters-label">Category:</span>
  <button class="filter-btn active" onclick="filterCat(null)">All</button>
  {cat_buttons}
</div>

<div class="table-wrap">
<table>
<thead><tr>
  <th>ID</th>
  <th>Test Name</th>
  <th>Category</th>
  <th>Input</th>
  <th>Expected</th>
  <th>Actual</th>
  <th>Status</th>
  <th>Time</th>
  <th>Screenshot</th>
</tr></thead>
<tbody id="tbody">{rows}</tbody>
</table>
</div>

<script>
  let activeStatus = null;
  let activeCat    = null;

  function applyFilters() {{
    document.querySelectorAll('#tbody tr').forEach(row => {{
      const statusOk = !activeStatus || row.dataset.status   === activeStatus;
      const catOk    = !activeCat    || row.dataset.category === activeCat;
      row.classList.toggle('hidden', !(statusOk && catOk));
    }});
  }}

  function filterStatus(val) {{
    activeStatus = (activeStatus === val) ? null : val;
    document.querySelectorAll('.sf').forEach(b => b.classList.remove('active'));
    if (val) {{
      const map = {{ 'PASS': 0, 'FAIL': 1, 'ERROR': 2 }};
      const idx = map[val];
      if (idx !== undefined) document.querySelectorAll('.sf')[idx].classList.add('active');
    }}
    applyFilters();
  }}

  function filterCat(val) {{
    activeCat = (activeCat === val) ? null : val;
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    if (!val) {{
      document.querySelectorAll('.filter-btn')[0].classList.add('active');
    }} else {{
      document.querySelectorAll('.filter-btn').forEach(b => {{
        if (b.textContent === val) b.classList.add('active');
      }});
    }}
    applyFilters();
  }}
</script>
</body>
</html>"""

        with open(HTML_REPORT, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[Reporter] HTML → {HTML_REPORT}")
        return HTML_REPORT

    def save_all(self):
        self.save_json()
        self.save_html()
        self._print_summary()

    def _print_summary(self):
        st = self.stats
        w  = 58
        print(f"\n{'=' * w}")
        print(f"  {self.suite_name}")
        print(f"{'─' * w}")
        print(f"  Duration   : {st['duration_s']} s")
        print(f"  Total      : {st['total']}")
        print(f"  ✅ PASS    : {st['passed']}  ({st['pass_rate']}%)")
        print(f"  ❌ FAIL    : {st['failed']}")
        print(f"  ⚠️  ERROR   : {st['errors']}")
        print(f"  ⏭️  SKIP    : {st['skipped']}")
        print(f"{'=' * w}\n")
