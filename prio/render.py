"""Stage 5: render extract + dossiers into a static site.

One page per category, one row per member PR sorted by score. Every cell
shows a condensed value and holds a detail block: click a cell to toggle
its detail, click the PR cell to toggle the whole row, click a column
header to toggle that column, and hover for the detail as a tooltip. No
external assets; CSS and JS are inlined so the pages work from a file://
URL and behind any static server.

Color carries state: the priority cell shades from white (highest score)
to gray (lowest) and the score itself is never shown; reviewability,
agreement, and size use traffic-light backgrounds; the reviews cell goes
white to green with ACK count.
"""

from __future__ import annotations

import html
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .categories import load_categories
from .config import Config
from .report import load_latest

REVIEWABILITY_COLORS = {"Ready": "#d9f2d9", "Stale": "#fff3c4", "Paused": "#ffd6d6"}
AGREEMENT_COLORS = {
    "Strong": "#bfe8bf", "Positive": "#d9f2d9", "Positive w/ caveats": "#e6f2d9",
    "Neutral": "#f2f2f2", "Mild": "#fff3c4", "Disputed": "#ffe0b3", "Blocked": "#ffc9c9",
    "Crickets": "#ffffff",
}
SIZE_COLORS = {"S": "#d9f2d9", "M": "#fff3c4", "L": "#ffe0b3", "XL": "#ffd6d6"}

CSS = """
:root { --border:#ddd; --text:#222; --muted:#666; --link:#0645ad; }
body { font-family: system-ui, sans-serif; color: var(--text); margin: 0; background: #fafafa; }
main { max-width: 1400px; margin: 0 auto; padding: 1rem 1.5rem 4rem; }
a { color: var(--link); text-decoration: none; } a:hover { text-decoration: underline; }
h1 { font-size: 1.4rem; margin: .5rem 0 .25rem; } .sub { color: var(--muted); font-size: .85rem; margin-bottom: 1rem; }
.banner { background:#fff8e1; border:1px solid #f0d78c; padding:.5rem .75rem; font-size:.85rem; margin:.5rem 0 1rem; }
nav.cats a { margin-right: 1rem; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; background: #fff; }
th, td { border: 1px solid var(--border); padding: .35rem .5rem; vertical-align: top; text-align: left; }
th { background: #f0f0f0; cursor: pointer; user-select: none; position: sticky; top: 0; }
th:hover { background: #e4e4e4; }
td.cell { cursor: pointer; }
td .brief { display: block; }
td .detail { display: none; margin-top: .4rem; padding-top: .4rem; border-top: 1px dashed #bbb; font-size: .83rem; white-space: pre-wrap; cursor: auto; }
td.open .detail { display: block; }
td.pr { min-width: 22rem; } td.pr .title { font-weight: 500; } td.pr .author { color: var(--muted); font-style: italic; }
td.prio { white-space: nowrap; font-weight: 600; } td.prio .tag { font-weight: 400; color: #333; }
td.rev, td.agree, td.size, td.reviews { white-space: nowrap; }
td.reviews .nack { color: #b00020; font-weight: 700; } td.reviews .stale { font-style: italic; color: #555; }
.detail ul { margin: .2rem 0 .2rem 1rem; padding: 0; } .detail li { margin: .1rem 0; }
.detail .k { color: var(--muted); }
.legend { font-size: .8rem; color: var(--muted); margin: .5rem 0 1rem; } .legend span { display:inline-block; padding: 0 .4rem; margin-right:.3rem; border:1px solid var(--border); }
tr.unranked td { color: var(--muted); }
"""

JS = """
function toggleCell(td, force) {
  if (force === undefined) td.classList.toggle('open'); else td.classList.toggle('open', force);
}
document.addEventListener('click', function (ev) {
  if (ev.target.closest('a')) return;
  if (ev.target.closest('.detail')) return;
  var th = ev.target.closest('th[data-col]');
  if (th) {
    var col = th.dataset.col, cells = document.querySelectorAll('td.cell[data-col="' + col + '"]');
    var anyClosed = Array.prototype.some.call(cells, function (c) { return !c.classList.contains('open'); });
    cells.forEach(function (c) { toggleCell(c, anyClosed); });
    return;
  }
  var td = ev.target.closest('td.cell');
  if (!td) return;
  if (td.classList.contains('pr')) {
    var row = td.parentElement.querySelectorAll('td.cell');
    var anyClosedRow = Array.prototype.some.call(row, function (c) { return !c.classList.contains('open'); });
    row.forEach(function (c) { toggleCell(c, anyClosedRow); });
  } else {
    toggleCell(td);
  }
});
"""


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def _shade(score: float) -> str:
    """White at score 1 to medium gray at score 0."""
    v = int(255 - (1 - max(0.0, min(1.0, score))) * 90)
    return f"rgb({v},{v},{v})"


def _cell(col: str, brief: str, detail_html: str, tooltip: str, extra_class: str = "", style: str = "") -> str:
    return (f'<td class="cell {col} {extra_class}" data-col="{col}" title="{_e(tooltip)}" style="{style}">'
            f'<span class="brief">{brief}</span><div class="detail">{detail_html}</div></td>')


def _ul(items) -> str:
    items = [i for i in items if i]
    return "<ul>" + "".join(f"<li>{_e(i)}</li>" for i in items) + "</ul>" if items else ""


def _reviews(rec: dict) -> tuple[str, str, str, str]:
    db = rec.get("bot", {}).get("drahtbot", {}).get("reviews", {})
    ack = db.get("ack", []); stale = db.get("stale_ack", [])
    nacks = db.get("nack", []) + db.get("concept_nack", []) + db.get("approach_nack", [])
    brief = str(len(ack))
    if stale:
        brief += f' <span class="stale">(+{len(stale)})</span>'
    if nacks:
        brief += f' <span class="nack">-{len(nacks)}</span>'
    parts = []
    tip = []
    for key, label in (("ack", "ACK"), ("stale_ack", "Stale ACK"), ("approach_ack", "Approach ACK"),
                       ("concept_ack", "Concept ACK"), ("nack", "NACK"), ("approach_nack", "Approach NACK"),
                       ("concept_nack", "Concept NACK")):
        who = db.get(key, [])
        if who:
            links = ", ".join(f'<a href="{_e(w["url"])}">{_e(w["login"])}</a>' for w in who)
            parts.append(f'<div><span class="k">{label}:</span> {links}</div>')
            tip.append(f"{label}: " + ", ".join(w["login"] for w in who))
    detail = "".join(parts) or "<div>No review verdicts recorded by DrahtBot.</div>"
    g = min(len(ack), 4)
    style = f"background: rgb({255 - g * 22},255,{255 - g * 22});"
    return brief, detail, "\n".join(tip) or "No review verdicts", style


def _row(rec: dict, d: dict, cat: dict, cat_name: str, data_href: str, extract_href: str) -> str:
    r = d["result"]
    n = rec["number"]
    # PR cell
    others = [f"{c['name']} {c['band']}" for c in r["categories"] if c["member"] and c["name"] != cat_name]
    pr_brief = (f'<a href="{_e(rec["url"])}">#{n}</a> <span class="author">{_e(rec["author"])}</span> '
                f'<span class="title">{_e(rec["title"])}</span>')
    pr_detail = (f'<div>{_e(r["summary"])}</div><div style="margin-top:.3rem"><span class="k">Problem:</span> {_e(r["problem"])}</div>'
                 + (f'<div><span class="k">Also in:</span> {_e(", ".join(others))}</div>' if others else "")
                 + (f'<div><span class="k">Depends on:</span> {_e(", ".join("#" + str(x) for x in r["dependencies"]["depends_on"]))}</div>' if r["dependencies"]["depends_on"] else "")
                 + (f'<div><span class="k">Enables:</span> {_e("; ".join(r["dependencies"]["enables"]))}</div>' if r["dependencies"]["enables"] else "")
                 + (f'<div><span class="k">Uncertainties:</span>{_ul(r["uncertainties"])}</div>' if r["uncertainties"] else "")
                 + f'<div style="margin-top:.3rem"><span class="k">Data:</span> <a href="{_e(data_href)}">dossier</a> · <a href="{_e(extract_href)}">extract</a>'
                 f' · model {_e(d.get("model"))}, {_e((d.get("created") or "")[:10])}, confidence {_e(r["confidence"])}</div>')
    pr_tip = r["summary"]
    # Priority cell
    f = cat["factors"]
    tag = cat.get("reason_tag") or ""
    prio_brief = f'{_e(cat["band"])}' + (f' <span class="tag">· {_e(tag)}</span>' if tag else "")
    prio_detail = (f'<div>{_e(cat["rationale"])}</div>'
                   f'<div style="margin-top:.3rem"><span class="k">Factors:</span> security/stability {f["security_stability"]}, bug {f["bug_severity"]}, '
                   f'performance {f["performance"]}, user value {f["user_value"]}, leverage {f["leverage"]}</div>'
                   f'<div><span class="k">Membership:</span> {_e(cat["evidence"])}</div>')
    prio_style = f"background:{_shade(cat['score'])};" if cat["band"] != "Unranked" else ""
    # Reviewability
    rv = r["reviewability"]
    rv_detail = (f'<div>{_e(rv["reason"])}</div><div style="margin-top:.3rem"><span class="k">Author:</span> {_e(r["discussion"]["author_status"])}</div>'
                 + (f'<div><span class="k">Open concerns:</span>{_ul(r["discussion"]["open_concerns"])}</div>' if r["discussion"]["open_concerns"] else "")
                 + (f'<div><span class="k">Resolved:</span>{_ul(r["discussion"]["resolved_concerns"])}</div>' if r["discussion"]["resolved_concerns"] else ""))
    rv_style = f"background:{REVIEWABILITY_COLORS.get(rv['state'], '#fff')};"
    # Reviews
    rw_brief, rw_detail, rw_tip, rw_style = _reviews(rec)
    # Agreement
    ag = r["agreement"]
    ag_summary = ag.get("summary") or ag["reason"]
    ag_detail = f'<div>{_e(ag_summary)}</div>' + (f'<div style="margin-top:.3rem">{_e(ag["reason"])}</div>' if ag.get("summary") else "") + _ul(ag["evidence"])
    ag_style = f"background:{AGREEMENT_COLORS.get(ag['state'], '#fff')};"
    # Size
    sz_brief = f'+{rec["additions"]}/-{rec["deletions"]}'
    if rec.get("test_lines"):
        sz_brief += f' <span class="stale">({rec["test_lines"]} tests)</span>'
    files = rec.get("files") or []
    sz_detail = (f'<div>{rec["changed_files"]} files, {rec["commit_count"]} commits, bucket {rec["size_bucket"]}'
                 + (f', {rec["test_lines"]} lines under test/bench/ci' if rec.get("test_lines") is not None else "") + '</div>'
                 + (_ul(f'{f["path"]} +{f["add"]}/-{f["del"]}' for f in sorted(files, key=lambda f: -((f["add"] or 0) + (f["del"] or 0)))[:40]) if files else ""))
    sz_style = f"background:{SIZE_COLORS.get(rec['size_bucket'], '#fff')};"
    cls = "unranked" if cat["band"] == "Unranked" else ""
    return (f'<tr class="{cls}" id="pr-{n}">'
            + _cell("pr", pr_brief, pr_detail, pr_tip)
            + _cell("prio", prio_brief, prio_detail, cat["rationale"], style=prio_style)
            + _cell("rev", _e(rv["label"]), rv_detail, rv["reason"], style=rv_style)
            + _cell("reviews", rw_brief, rw_detail, rw_tip, style=rw_style)
            + _cell("agree", _e(ag["state"]), ag_detail, ag_summary, style=ag_style)
            + _cell("size", sz_brief, sz_detail, f'{rec["changed_files"]} files, {rec["commit_count"]} commits', style=sz_style)
            + "</tr>")


def _page(title: str, body: str, sub: str = "") -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{_e(title)}</title><style>{CSS}</style></head><body><main>'
            f'<h1>{_e(title)}</h1><div class="sub">{sub}</div>{body}</main><script>{JS}</script></body></html>')


def render(cfg: Config, extract_dir: Path, dossier_dir: Path, out_dir: Path) -> dict:
    cats = {c.name: c for c in load_categories(cfg.categories_dir)}
    dossiers = load_latest(dossier_dir)
    recs: dict[int, dict] = {}
    for n in dossiers:
        p = extract_dir / "prs" / f"{n}.json"
        if p.exists():
            with open(p) as f:
                recs[n] = json.load(f)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "data").mkdir(exist_ok=True)
    members: dict[str, list[tuple[float, int, dict]]] = {}
    for n, d in dossiers.items():
        r = d.get("result")
        if not r or n not in recs:
            continue
        shutil.copy(dossier_dir / str(n) / f"{d['input_hash']}.json", out_dir / "data" / f"dossier-{n}.json")
        shutil.copy(extract_dir / "prs" / f"{n}.json", out_dir / "data" / f"extract-{n}.json")
        for c in r["categories"]:
            if c["member"]:
                members.setdefault(c["name"], []).append((c["score"], n, c))
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    banner = ('<div class="banner">Every band, state, and summary on this page is model output against '
              'version-controlled definitions, shown with its rationale. It is one person\'s tool for finding PRs worth '
              'reviewing, not a project process. Click any cell for its reasoning; click a column header to expand the column; '
              'click the PR cell to expand the row.</div>')
    legend = ('<div class="legend">Priority cell shade: lighter is higher within the band. '
              f'Reviewability: <span style="background:{REVIEWABILITY_COLORS["Ready"]}">Ready</span>'
              f'<span style="background:{REVIEWABILITY_COLORS["Stale"]}">Stale</span>'
              f'<span style="background:{REVIEWABILITY_COLORS["Paused"]}">Paused</span> '
              'Reviews: current ACKs (+stale) <b style="color:#b00020">-NACKs</b>. Agreement: '
              + "".join(f'<span style="background:{v}">{k}</span>' for k, v in AGREEMENT_COLORS.items()) + "</div>")
    nav = '<nav class="cats">' + " ".join(
        f'<a href="{_e(name)}.html">{_e(cats[name].title if name in cats else name)} ({len(rows)})</a>'
        for name, rows in sorted(members.items())) + "</nav>"
    pages = []
    for name, rows in sorted(members.items()):
        rows.sort(key=lambda x: -x[0])
        cat = cats.get(name)
        title = cat.title if cat else name
        head = ('<table><thead><tr>'
                '<th data-col="pr" title="click to expand all">PR</th><th data-col="prio" title="click to expand all">Priority</th>'
                '<th data-col="rev" title="click to expand all">Reviewability</th><th data-col="reviews" title="click to expand all">Reviews</th>'
                '<th data-col="agree" title="click to expand all">Agreement</th><th data-col="size" title="click to expand all">Size</th>'
                '</tr></thead><tbody>')
        body_rows = "".join(_row(recs[n], dossiers[n], c, name, f"data/dossier-{n}.json", f"data/extract-{n}.json") for _, n, c in rows)
        covers = ""
        if cat:
            covers = f'<details style="margin:.5rem 0 1rem;font-size:.85rem"><summary>What this category covers and what matters in it</summary><pre style="white-space:pre-wrap">{_e(cat.body)}</pre></details>'
        body = banner + nav + covers + legend + head + body_rows + "</tbody></table>"
        (out_dir / f"{name}.html").write_text(_page(f"{title}: review map", body, f"{len(rows)} PRs · generated {stamp}"))
        pages.append(name)
    index = banner + "<ul>" + "".join(
        f'<li><a href="{_e(name)}.html">{_e(cats[name].title if name in cats else name)}</a> ({len(rows)} PRs)</li>'
        for name, rows in sorted(members.items())) + "</ul>"
    (out_dir / "index.html").write_text(_page(cfg.site_title, index, f"{len(dossiers)} PRs assessed · generated {stamp}"))
    return {"pages": pages, "prs": len(dossiers), "out": str(out_dir)}
