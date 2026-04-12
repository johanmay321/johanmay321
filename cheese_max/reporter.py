"""
HTML report generator for Cheese Max 2K26.

Produces a single self-contained .html file (all CSS + JS inline).
No external dependencies at runtime — share as a file attachment.

Usage (via CLI):
    python cheese_max.py report --season 2026 [--output report.html]
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from cheese_max.data_manager import DataManager
from cheese_max.models import Race, Regatta, RaceResult, UNRESOLVED_TEAM

# ---------------------------------------------------------------------------
# School colours
# ---------------------------------------------------------------------------

TEAM_COLORS: dict[str, dict] = {
    "HVD":     {"primary": "#A51C30", "secondary": "#C9B577", "text": "#fff"},
    "HVD-LW":  {"primary": "#A51C30", "secondary": "#C9B577", "text": "#fff"},
    "YLE":     {"primary": "#00356B", "secondary": "#ADB5BD", "text": "#fff"},
    "YLE-LW":  {"primary": "#00356B", "secondary": "#ADB5BD", "text": "#fff"},
    "PRI":     {"primary": "#E77500", "secondary": "#000000", "text": "#000"},
    "PRI-LW":  {"primary": "#E77500", "secondary": "#000000", "text": "#000"},
    "UPE":     {"primary": "#011F5B", "secondary": "#990000", "text": "#fff"},
    "UPE-LW":  {"primary": "#011F5B", "secondary": "#990000", "text": "#fff"},
    "DAR":     {"primary": "#00693E", "secondary": "#FFFFFF", "text": "#fff"},
    "DAR-LW":  {"primary": "#00693E", "secondary": "#FFFFFF", "text": "#fff"},
    "COL":     {"primary": "#75AADB", "secondary": "#012169", "text": "#000"},
    "COL-LW":  {"primary": "#75AADB", "secondary": "#012169", "text": "#000"},
    "COR":     {"primary": "#B31B1B", "secondary": "#FFFFFF", "text": "#fff"},
    "BRN":     {"primary": "#4E3629", "secondary": "#C00404", "text": "#fff"},
    "MIT":     {"primary": "#A31F34", "secondary": "#8A8B8C", "text": "#fff"},
    "MIT-LW":  {"primary": "#A31F34", "secondary": "#8A8B8C", "text": "#fff"},
    "GEO":     {"primary": "#041E42", "secondary": "#8D817B", "text": "#fff"},
    "GEO-LW":  {"primary": "#041E42", "secondary": "#8D817B", "text": "#fff"},
    "NAVY":    {"primary": "#00205B", "secondary": "#C5A900", "text": "#fff"},
    "NAVY-LW": {"primary": "#00205B", "secondary": "#C5A900", "text": "#fff"},
    "UVA":     {"primary": "#232D4B", "secondary": "#E57200", "text": "#fff"},
    "UWA":     {"primary": "#4B2E83", "secondary": "#B7A57A", "text": "#fff"},
    "CAL":     {"primary": "#003262", "secondary": "#FDB515", "text": "#fff"},
    "STA":     {"primary": "#8C1515", "secondary": "#B3995D", "text": "#fff"},
    "WIS":     {"primary": "#C5050C", "secondary": "#F0F0F0", "text": "#fff"},
    "OSU":     {"primary": "#BB0000", "secondary": "#666666", "text": "#fff"},
    "SYR":     {"primary": "#D44500", "secondary": "#002147", "text": "#fff"},
    "NEU":     {"primary": "#C8102E", "secondary": "#000000", "text": "#fff"},
    "BU":      {"primary": "#CC0000", "secondary": "#FFFFFF", "text": "#fff"},
}
_DEFAULT_COLOR = {"primary": "#4A5568", "secondary": "#718096", "text": "#fff"}


def _color(abbr: str) -> dict:
    return TEAM_COLORS.get(abbr, _DEFAULT_COLOR)


# ---------------------------------------------------------------------------
# Formatting helpers (no imports from cli to avoid circular deps)
# ---------------------------------------------------------------------------

def _fmt_time(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m}:{s:05.2f}"


def _fmt_margin(seconds: float | None) -> str:
    if seconds is None or seconds == 0.0:
        return "—"
    return f"+{seconds:.2f}s"


def _cond_badges(cond) -> str:
    parts = []
    if cond.water_state:
        colour = {"calm": "#22c55e", "choppy": "#f59e0b", "rough": "#ef4444"}.get(
            cond.water_state, "#6b7280"
        )
        parts.append(f'<span class="badge" style="background:{colour}">{cond.water_state}</span>')
    if cond.wind_speed_kph is not None:
        dir_ = cond.wind_direction or ""
        parts.append(
            f'<span class="badge" style="background:#6366f1">'
            f'&#128168; {dir_} {cond.wind_speed_kph:.0f} kph</span>'
        )
    if cond.temp_celsius is not None:
        parts.append(
            f'<span class="badge" style="background:#0ea5e9">'
            f'{cond.temp_celsius:.0f}°C</span>'
        )
    return " ".join(parts) if parts else '<span class="badge" style="background:#374151">conditions unknown</span>'


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ---------------------------------------------------------------------------
# Data builder
# ---------------------------------------------------------------------------

def _load_rankings(rankings_dir: Path) -> dict[str, dict]:
    """Load all ranking JSON files keyed by '{season}_{class}'."""
    out: dict[str, dict] = {}
    for p in sorted(rankings_dir.glob("*.json")):
        try:
            data = json.loads(p.read_text())
            key = p.stem  # e.g. "2026_V1"
            out[key] = data
        except Exception:
            pass
    return out


def _build_data_section(
    regattas: list[Regatta],
    races: list[Race],
    teams_map: dict,
) -> str:
    """Return HTML for the Data tab."""
    regatta_map = {r.id: r for r in regattas}
    races_by_reg: dict[str, list[Race]] = {}
    for race in races:
        races_by_reg.setdefault(race.regatta_id, []).append(race)

    # Sort regattas by date descending
    sorted_regs = sorted(regattas, key=lambda r: r.date, reverse=True)

    total_results = sum(len(r.results) for r in races)
    flagged_note = (
        f'<div class="summary-bar">'
        f'<span>{len(regattas)} regattas &nbsp;·&nbsp; {len(races)} races &nbsp;·&nbsp; {total_results} results</span>'
        f'<button class="btn-export" onclick="exportFlags()">&#128229; Export flagged errors</button>'
        f'</div>'
    )

    cards = []
    for reg in sorted_regs:
        reg_races = races_by_reg.get(reg.id, [])
        if not reg_races:
            continue

        source_link = (
            f'<a href="{_esc(reg.source_url)}" target="_blank" class="source-link">'
            f'{_esc(reg.source_label)} &#8599;</a>'
        ) if reg.source_url else f'<span class="source-link">{_esc(reg.source_label)}</span>'

        race_htmls = []
        for race in sorted(reg_races, key=lambda r: r.boat_class):
            cls_color = {
                "V1": "#6366f1", "V2": "#8b5cf6", "V3": "#a78bfa",
                "LW1": "#059669", "LW2": "#34d399",
                "JV": "#f59e0b", "F": "#64748b", "N": "#64748b",
            }.get(race.boat_class, "#6b7280")

            rows_html = []
            for result in sorted(race.results, key=lambda r: (r.placement or 99)):
                c = _color(result.team)
                pill = (
                    f'<span class="team-pill" style="background:{c["primary"]};color:{c["text"]}">'
                    f'{_esc(result.team)}</span>'
                )
                if result.team == UNRESOLVED_TEAM:
                    raw = re.search(r"raw_team_name='([^']*)'", result.notes or "")
                    raw_str = raw.group(1) if raw else "?"
                    pill = f'<span class="team-pill unresolved">??? {_esc(raw_str)}</span>'

                dnf_dns = ""
                if result.dnf:
                    dnf_dns = '<span class="badge" style="background:#ef4444">DNF</span>'
                elif result.dns:
                    dnf_dns = '<span class="badge" style="background:#6b7280">DNS</span>'

                rows_html.append(
                    f'<tr data-result-id="{result.id}" data-team="{_esc(result.team)}" '
                    f'    data-race="{_esc(race.race_name or race.boat_class)}" '
                    f'    data-regatta="{_esc(reg.name)}">'
                    f'  <td style="border-left:4px solid {c["primary"]};padding-left:8px">'
                    f'      {result.placement or "—"}</td>'
                    f'  <td>{result.lane or "—"}</td>'
                    f'  <td>{pill}</td>'
                    f'  <td class="mono">{_fmt_time(result.finish_time_seconds)}</td>'
                    f'  <td class="mono">{_fmt_margin(result.margin_to_winner_seconds)}</td>'
                    f'  <td>{dnf_dns}</td>'
                    f'  <td><button class="btn-flag" onclick="toggleFlag(this)">&#9873;</button>'
                    f'      <span class="flag-note"></span></td>'
                    f'</tr>'
                    f'<tr class="flag-row" style="display:none">'
                    f'  <td colspan="7" class="flag-input-cell">'
                    f'    <input type="text" class="flag-input" placeholder="Describe the error…" '
                    f'           oninput="saveFlag(this)" />'
                    f'  </td>'
                    f'</tr>'
                )

            race_htmls.append(
                f'<div class="race-block">'
                f'  <div class="race-header">'
                f'    <span class="class-badge" style="background:{cls_color}">{race.boat_class}</span>'
                f'    <span class="event-type">{race.event_type.upper()}</span>'
                f'    <span class="race-name">{_esc(race.race_name or "")}</span>'
                f'  </div>'
                f'  <table class="result-table">'
                f'    <thead><tr>'
                f'      <th>#</th><th>Lane</th><th>Team</th>'
                f'      <th>Time</th><th>Margin</th><th></th><th>Flag</th>'
                f'    </tr></thead>'
                f'    <tbody>{"".join(rows_html)}</tbody>'
                f'  </table>'
                f'</div>'
            )

        cards.append(
            f'<div class="regatta-card">'
            f'  <div class="regatta-header" onclick="toggleCard(this)">'
            f'    <div class="regatta-title">'
            f'      <span class="chevron">&#9660;</span>'
            f'      <strong>{_esc(reg.name)}</strong>'
            f'    </div>'
            f'    <div class="regatta-meta">'
            f'      <span>{reg.date}</span>'
            f'      {" &nbsp;·&nbsp; " + _esc(reg.course) if reg.course else ""}'
            f'      &nbsp;·&nbsp; {_cond_badges(reg.conditions)}'
            f'      &nbsp;·&nbsp; {source_link}'
            f'      &nbsp;·&nbsp; <span class="race-count">{len(reg_races)} races</span>'
            f'    </div>'
            f'  </div>'
            f'  <div class="regatta-body">{"".join(race_htmls)}</div>'
            f'</div>'
        )

    return flagged_note + "\n".join(cards)


def _build_rankings_section(rankings: dict[str, dict], season: int) -> str:
    """Return HTML for the Rankings tab."""
    # Filter to requested season
    season_rankings = {k: v for k, v in rankings.items() if k.startswith(str(season))}

    if not season_rankings:
        return (
            '<div class="empty-state">'
            '<p>No ranking data found for this season.</p>'
            '<p>Run <code>python cheese_max.py rank --class V1 --season '
            + str(season)
            + '</code> first.</p></div>'
        )

    class_order = ["V1", "V2", "V3", "LW1", "LW2", "JV", "F"]
    available = sorted(season_rankings.keys(), key=lambda k: (
        class_order.index(k.split("_", 1)[1]) if k.split("_", 1)[1] in class_order else 99
    ))

    tabs = []
    panels = []

    for idx, key in enumerate(available):
        cls = key.split("_", 1)[1]
        data = season_rankings[key]
        active = "active" if idx == 0 else ""

        tabs.append(
            f'<button class="class-tab {active}" onclick="showClass(\'{key}\')" id="tab-{key}">'
            f'{cls}</button>'
        )

        cfg = data.get("config", {})
        cfg_parts = []
        if cfg.get("normalize_margins", True):
            cfg_parts.append("% back (normalized)")
        else:
            cfg_parts.append("raw seconds")
        if cfg.get("discount_large_gaps"):
            cfg_parts.append(f'gap cap {cfg.get("gap_threshold_pct", 5)}%')
        if cfg.get("discount_bad_conditions"):
            cfg_parts.append("condition weighting")
        cfg_str = " &nbsp;·&nbsp; ".join(cfg_parts)

        rows = []
        for entry in data.get("rankings", []):
            c = _color(entry["team"])
            low = entry.get("low_sample", False)
            pill = (
                f'<span class="team-pill" style="background:{c["primary"]};color:{c["text"]}">'
                f'{_esc(entry["team"])}</span>'
            )
            rating_str = f'{entry["rating"]:+.3f}%' if cfg.get("normalize_margins", True) else f'{entry["rating"]:+.2f}s'
            ref_str = f'{entry["rating_at_ref_seconds"]:+.2f}s'
            low_flag = ' <span class="low-sample" title="Fewer than min races">*</span>' if low else ""
            rows.append(
                f'<tr style="border-left:4px solid {c["primary"]}">'
                f'  <td class="rank-num">{entry["rank"]}</td>'
                f'  <td>{pill}</td>'
                f'  <td class="mono">{rating_str}{low_flag}</td>'
                f'  <td class="mono">{ref_str}</td>'
                f'  <td>{entry["races"]}</td>'
                f'</tr>'
            )

        has_low = any(e.get("low_sample") for e in data.get("rankings", []))

        panels.append(
            f'<div class="class-panel {"" if idx == 0 else "hidden"}" id="panel-{key}">'
            f'  <div class="cfg-bar">{cfg_str} &nbsp;·&nbsp; '
            f'      {data.get("num_races",0)} races &nbsp;·&nbsp; {data.get("num_teams",0)} teams</div>'
            f'  <table class="rank-table">'
            f'    <thead><tr><th>#</th><th>Team</th><th>Rating</th>'
            f'      <th>@ 5:35 pace</th><th>Races</th></tr></thead>'
            f'    <tbody>{"".join(rows)}</tbody>'
            f'  </table>'
            + (
                '<p class="low-note">* Low sample — fewer than '
                + str(cfg.get("min_races_threshold", 3))
                + " races, rating unreliable.</p>"
                if has_low
                else ""
            )
            + f'</div>'
        )

    return (
        f'<div class="class-tabs">{"".join(tabs)}</div>'
        f'<div class="class-panels">{"".join(panels)}</div>'
    )


# ---------------------------------------------------------------------------
# Main assembler
# ---------------------------------------------------------------------------

CSS = """
:root {
  --bg: #0f1117;
  --surface: #1a1d2e;
  --surface2: #252840;
  --border: #2e3150;
  --text: #e2e8f0;
  --text-muted: #94a3b8;
  --accent: #6366f1;
  --accent2: #22d3ee;
  --warn: #f59e0b;
  --danger: #ef4444;
  --success: #22c55e;
  --radius: 10px;
  --font: 'Inter', system-ui, -apple-system, sans-serif;
  --mono: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font-family: var(--font);
       font-size: 14px; line-height: 1.6; }
a { color: var(--accent2); text-decoration: none; }
a:hover { text-decoration: underline; }
.mono { font-family: var(--mono); font-size: 13px; }

/* ── Header ── */
.site-header {
  background: linear-gradient(135deg, #1e1b4b 0%, #312e81 50%, #1e3a5f 100%);
  padding: 28px 40px 20px;
  border-bottom: 1px solid var(--border);
}
.site-header h1 { font-size: 26px; font-weight: 800; letter-spacing: -0.5px;
  background: linear-gradient(90deg, #a5b4fc, #67e8f9); -webkit-background-clip: text;
  -webkit-text-fill-color: transparent; display: inline-block; }
.site-header .subtitle { color: var(--text-muted); font-size: 13px; margin-top: 2px; }
.generated { color: var(--text-muted); font-size: 12px; margin-top: 6px; }

/* ── Main tabs ── */
.main-tabs { display: flex; gap: 4px; padding: 16px 40px 0;
             background: var(--surface); border-bottom: 1px solid var(--border); }
.main-tab { background: none; border: none; color: var(--text-muted); padding: 10px 22px;
            font-size: 14px; font-weight: 600; cursor: pointer; border-radius: 8px 8px 0 0;
            border-bottom: 2px solid transparent; transition: all .15s; }
.main-tab:hover { color: var(--text); background: var(--surface2); }
.main-tab.active { color: var(--accent2); border-bottom-color: var(--accent2);
                   background: var(--surface2); }

/* ── Content ── */
.tab-content { display: none; padding: 28px 40px; }
.tab-content.active { display: block; }

/* ── Summary bar ── */
.summary-bar { display: flex; justify-content: space-between; align-items: center;
               margin-bottom: 20px; padding: 12px 16px;
               background: var(--surface); border-radius: var(--radius);
               border: 1px solid var(--border); }
.btn-export { background: var(--accent); color: #fff; border: none; padding: 7px 16px;
              border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 600; }
.btn-export:hover { background: #4f46e5; }

/* ── Regatta cards ── */
.regatta-card { background: var(--surface); border: 1px solid var(--border);
                border-radius: var(--radius); margin-bottom: 14px; overflow: hidden; }
.regatta-header { display: flex; justify-content: space-between; align-items: flex-start;
                  padding: 14px 18px; cursor: pointer; user-select: none;
                  transition: background .15s; }
.regatta-header:hover { background: var(--surface2); }
.regatta-title { display: flex; align-items: center; gap: 10px; font-size: 15px; }
.chevron { transition: transform .2s; display: inline-block; }
.collapsed .chevron { transform: rotate(-90deg); }
.regatta-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
                font-size: 12px; color: var(--text-muted); }
.regatta-body { padding: 0 18px 16px; }
.collapsed .regatta-body { display: none; }
.race-count { color: var(--text-muted); }

/* ── Race block ── */
.race-block { margin-top: 14px; }
.race-header { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.class-badge { padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 700;
               color: #fff; letter-spacing: .5px; }
.event-type { font-size: 11px; color: var(--text-muted); text-transform: uppercase;
              letter-spacing: 1px; font-weight: 600; }
.race-name { color: var(--text-muted); font-size: 13px; }

/* ── Result table ── */
.result-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.result-table th { color: var(--text-muted); font-weight: 600; text-align: left;
                   padding: 6px 10px; border-bottom: 1px solid var(--border);
                   font-size: 11px; text-transform: uppercase; letter-spacing: .5px; }
.result-table td { padding: 7px 10px; border-bottom: 1px solid rgba(255,255,255,.04); }
.result-table tbody tr:hover { background: rgba(255,255,255,.03); }
.result-table tbody tr.flagged { background: rgba(245,158,11,.08);
                                  border-left: 3px solid var(--warn) !important; }

/* ── Team pill ── */
.team-pill { display: inline-block; padding: 2px 10px; border-radius: 20px;
             font-size: 12px; font-weight: 700; letter-spacing: .3px; white-space: nowrap; }
.team-pill.unresolved { background: #7f1d1d !important; color: #fca5a5 !important;
                        border: 1px solid #ef4444; }

/* ── Badges ── */
.badge { display: inline-block; padding: 2px 8px; border-radius: 12px;
         font-size: 11px; font-weight: 600; color: #fff; }

/* ── Source link ── */
.source-link { font-size: 11px; color: var(--accent2); }

/* ── Flag button ── */
.btn-flag { background: none; border: 1px solid var(--border); color: var(--text-muted);
            padding: 2px 8px; border-radius: 6px; cursor: pointer; font-size: 13px;
            transition: all .15s; }
.btn-flag:hover, .btn-flag.active { background: var(--warn); color: #000;
                                     border-color: var(--warn); }
.flag-note { font-size: 11px; color: var(--warn); margin-left: 6px; }
.flag-input-cell { background: rgba(245,158,11,.06); padding: 8px 10px !important; }
.flag-input { width: 100%; background: var(--surface2); border: 1px solid var(--warn);
              border-radius: 6px; padding: 6px 10px; color: var(--text); font-size: 13px; }

/* ── Rankings tab ── */
.class-tabs { display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; }
.class-tab { background: var(--surface); border: 1px solid var(--border);
             color: var(--text-muted); padding: 8px 20px; border-radius: 20px;
             font-size: 13px; font-weight: 700; cursor: pointer; transition: all .15s; }
.class-tab:hover { border-color: var(--accent); color: var(--text); }
.class-tab.active { background: var(--accent); border-color: var(--accent);
                    color: #fff; }
.class-panels .hidden { display: none; }
.cfg-bar { font-size: 12px; color: var(--text-muted); margin-bottom: 14px;
           padding: 8px 12px; background: var(--surface2); border-radius: 6px; }
.rank-table { width: 100%; max-width: 680px; border-collapse: collapse; font-size: 14px; }
.rank-table th { color: var(--text-muted); font-weight: 600; text-align: left;
                 padding: 8px 14px; border-bottom: 1px solid var(--border);
                 font-size: 11px; text-transform: uppercase; letter-spacing: .5px; }
.rank-table td { padding: 10px 14px; border-bottom: 1px solid rgba(255,255,255,.04); }
.rank-table tbody tr:hover { background: rgba(255,255,255,.04); }
.rank-num { font-size: 18px; font-weight: 800; color: var(--text-muted); width: 40px; }
.rank-table tbody tr:first-child .rank-num { color: #fbbf24; }
.rank-table tbody tr:nth-child(2) .rank-num { color: #94a3b8; }
.rank-table tbody tr:nth-child(3) .rank-num { color: #b45309; }
.low-sample { color: var(--warn); font-size: 12px; cursor: help; }
.low-note { font-size: 12px; color: var(--warn); margin-top: 12px; }

/* ── Empty state ── */
.empty-state { text-align: center; padding: 60px 20px; color: var(--text-muted); }
.empty-state code { background: var(--surface2); padding: 4px 10px; border-radius: 6px;
                    font-family: var(--mono); color: var(--accent2); }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
"""

JS = r"""
// ── Tab switching ──
function showTab(name) {
  document.querySelectorAll('.main-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  document.getElementById('content-' + name).classList.add('active');
}

// ── Regatta collapse ──
function toggleCard(header) {
  header.parentElement.classList.toggle('collapsed');
}

// ── Boat class tabs (rankings) ──
function showClass(key) {
  document.querySelectorAll('.class-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.class-panel').forEach(p => p.classList.add('hidden'));
  document.getElementById('tab-' + key).classList.add('active');
  document.getElementById('panel-' + key).classList.remove('hidden');
}

// ── Flag errors ──
const FLAGS_KEY = 'cheesemax_flags';

function loadFlags() {
  try { return JSON.parse(localStorage.getItem(FLAGS_KEY) || '{}'); }
  catch { return {}; }
}
function saveFlags(flags) {
  localStorage.setItem(FLAGS_KEY, JSON.stringify(flags));
}

function toggleFlag(btn) {
  const row = btn.closest('tr');
  const flagRow = row.nextElementSibling;
  const resultId = row.dataset.resultId;
  const isOpen = flagRow.style.display !== 'none';

  if (isOpen) {
    flagRow.style.display = 'none';
    btn.classList.remove('active');
  } else {
    flagRow.style.display = 'table-row';
    btn.classList.add('active');
    const input = flagRow.querySelector('.flag-input');
    const flags = loadFlags();
    if (flags[resultId]) input.value = flags[resultId].note || '';
    input.focus();
  }
}

function saveFlag(input) {
  const flagRow = input.closest('tr');
  const dataRow = flagRow.previousElementSibling;
  const resultId = dataRow.dataset.resultId;
  const note = input.value.trim();
  const flags = loadFlags();

  if (note) {
    flags[resultId] = {
      note,
      team: dataRow.dataset.team,
      race: dataRow.dataset.race,
      regatta: dataRow.dataset.regatta,
      flagged_at: new Date().toISOString(),
    };
    dataRow.classList.add('flagged');
    dataRow.querySelector('.flag-note').textContent = note;
    dataRow.querySelector('.btn-flag').classList.add('active');
  } else {
    delete flags[resultId];
    dataRow.classList.remove('flagged');
    dataRow.querySelector('.flag-note').textContent = '';
  }
  saveFlags(flags);
}

// ── Export flags ──
function exportFlags() {
  const flags = loadFlags();
  if (!Object.keys(flags).length) { alert('No flags set yet.'); return; }
  const blob = new Blob([JSON.stringify(flags, null, 2)], {type: 'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'flags_' + new Date().toISOString().slice(0,10) + '.json';
  a.click();
}

// ── Restore flags from localStorage on page load ──
document.addEventListener('DOMContentLoaded', () => {
  const flags = loadFlags();
  Object.entries(flags).forEach(([resultId, info]) => {
    const row = document.querySelector(`tr[data-result-id="${resultId}"]`);
    if (!row) return;
    row.classList.add('flagged');
    row.querySelector('.flag-note').textContent = info.note || '';
    row.querySelector('.btn-flag').classList.add('active');
    const flagRow = row.nextElementSibling;
    if (flagRow) {
      const input = flagRow.querySelector('.flag-input');
      if (input) input.value = info.note || '';
    }
  });
});
"""


def generate(
    dm: DataManager,
    season: int,
    output_path: Path | None = None,
) -> Path:
    """
    Generate a self-contained HTML report and write it to output_path.
    Returns the path written.
    """
    regattas = dm.get_confirmed_regattas(season=season)
    races = dm.get_confirmed_races(season=season)
    teams = dm.get_teams()
    rankings = _load_rankings(dm.rankings_dir)

    data_html = _build_data_section(regattas, races, teams)
    rankings_html = _build_rankings_section(rankings, season)

    has_rankings = any(k.startswith(str(season)) for k in rankings)
    rankings_tab_note = "" if has_rankings else " (no data yet)"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cheese Max 2K26 — {season}</title>
<style>{CSS}</style>
</head>
<body>

<header class="site-header">
  <h1>&#127939; Cheese Max 2K26</h1>
  <div class="subtitle">US Collegiate Rowing Race Analysis &amp; Rankings</div>
  <div class="generated">Season {season} &nbsp;·&nbsp; Generated {date.today().isoformat()}</div>
</header>

<nav class="main-tabs">
  <button class="main-tab active" id="tab-data" onclick="showTab('data')">
    &#128196; Data ({len(regattas)} regattas)
  </button>
  <button class="main-tab" id="tab-rankings" onclick="showTab('rankings')">
    &#127942; Rankings{rankings_tab_note}
  </button>
</nav>

<div class="tab-content active" id="content-data">
  {data_html}
</div>

<div class="tab-content" id="content-rankings">
  {rankings_html}
</div>

<script>{JS}</script>
</body>
</html>"""

    if output_path is None:
        output_path = Path(f"cheese_max_report_{season}.html")

    output_path.write_text(html, encoding="utf-8")
    return output_path
