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
import re
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
.banner { background:#fff8e1; border:1px solid #f0d78c; padding:.5rem .5rem; font-size:.85rem; margin: 1rem 0 0; }
nav.cats a { margin-right: 1rem; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; background: #fff; }
th, td { border: 1px solid var(--border); padding: .35rem .5rem; vertical-align: top; text-align: left; }
th { background: #f0f0f0; position: sticky; top: 0; }
td .brief { display: block; }
td .detail { display: none; margin-top: .4rem; padding-top: .4rem; border-top: 1px dashed #bbb; font-size: .83rem; white-space: normal; }
tr.open td .detail { display: block; }
td .brief { cursor: pointer; }
td.pr { min-width: 22rem; } td.pr .title { font-weight: 500; } td.pr .author { color: var(--muted); font-style: italic; }
td.prio { white-space: nowrap; } td.prio .brief { font-weight: 600; } td.prio .tag { font-weight: 400; color: #333; }
td .detail { font-weight: 400; }
td.rev, td.agree, td.size, td.reviews { white-space: nowrap; }
td.reviews .nack { color: #b00020; font-weight: 700; } td.reviews .stale { font-style: italic; color: #555; }
.detail ul { margin: 0; padding-left: 1.1rem; } .detail li { margin: .15rem 0; }
.detail .k { color: var(--muted); }
.legend { font-size: .8rem; color: var(--muted); background: #f7f7f7; border: 1px solid var(--border); border-top: none; padding: .4rem .5rem; margin: 0; }
.legend span { display:inline-block; padding: 0 .4rem; margin-right:.3rem; border:1px solid var(--border); background: #fff; }
tr.unranked td { color: var(--muted); }
td.pr .tg { float: right; color: var(--link); font-weight: 600; margin-left: .5rem; user-select: none; }
.more { font-size: .8rem; margin-top: .4rem; padding-top: .4rem; border-top: 1px dashed #bbb; }
nav.top { font-size: .85rem; margin-bottom: .6rem; } nav.top a { margin-right: 1rem; }
h1 a { color: inherit; } h1 a:hover { text-decoration: underline; }
.intro { max-width: 60rem; } .intro p { margin: .4rem 0 .8rem; }
ul.catlist { line-height: 1.7; padding-left: 1.2rem; } ul.catlist .editor { color: var(--muted); font-size: .85rem; }
.foot .sub { margin: 1rem 0 0; }
.foot.rule { margin-top: 2rem; border-top: 1px solid var(--border); padding-top: .6rem; } .foot.rule .sub { margin: 0; }
.legend div { margin: .15rem 0; }
.covers { font-size: .9rem; background: #fff; border: 1px solid var(--border); padding: .4rem .5rem .6rem; margin: 1rem 0 0; }
.covers h2 { font-size: 1rem; margin: .8rem 0 .2rem; } .covers p { margin: .3rem 0; } .covers ul { margin: .2rem 0; }
.covers .src { font-size: .8rem; color: var(--muted); margin: .1rem 0 .2rem; }
.prpage .lead { font-weight: 600; } .prpage ul { margin: .3rem 0; padding-left: 1.2rem; }
.prpage h2 { font-size: 1.1rem; margin: 1.2rem 0 .3rem; border-bottom: 1px solid var(--border); }
.prpage .box { background: #fff; border: 1px solid var(--border); padding: .6rem .8rem; margin: .4rem 0; }
.prpage .k { color: var(--muted); }
"""

JS = """
document.addEventListener('click', function (ev) {
  if (ev.target.closest('a')) return;
  var brief = ev.target.closest('.brief');
  if (!brief) return;
  var tr = brief.closest('tr');
  if (!tr) return;
  tr.classList.toggle('open');
  var g = tr.querySelector('td.pr .tg'); if (g) g.textContent = tr.classList.contains('open') ? '(\\u2212)' : '(+)';
});
"""


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


_REPO_URL = {"url": "https://github.com/bitcoin/bitcoin"}
_REF_RE = re.compile(r"(?<![\w/])(?:([\w.-]+/[\w.-]+))?#(\d{2,6})\b")


def _t(text) -> str:
    """Escape text and turn #1234 and owner/repo#1234 into GitHub links.
    GitHub redirects /pull/N to /issues/N when N is an issue, so one form works for both."""
    def sub(m):
        repo, n = m.group(1), m.group(2)
        url = f"https://github.com/{repo}/pull/{n}" if repo else f"{_REPO_URL['url']}/pull/{n}"
        return f'<a href="{url}">{m.group(0)}</a>'
    return _REF_RE.sub(sub, _e(text))


def _shade(score: float) -> str:
    """White at score 1 to medium gray at score 0."""
    v = int(255 - (1 - max(0.0, min(1.0, score))) * 90)
    return f"rgb({v},{v},{v})"


import re as _re
_SENT = _re.compile(r"(?<=[.!?])\s+(?=[A-Z#`\"'(])")


def lead(text: str, n: int = 2) -> str:
    """First n sentences of a text: the expanded-cell tier."""
    parts = _SENT.split((text or "").strip())
    return " ".join(parts[:n])


def _ul(items) -> str:
    items = [i for i in items if i]
    return "<ul>" + "".join(f"<li>{_t(i)}</li>" for i in items) + "</ul>" if items else ""


def _cell(col: str, brief: str, lines: list[str], style: str = "", extra_html: str = "") -> str:
    tip = "\n".join(lines)
    return (f'<td class="{col}" title="{_e(tip)}" style="{style}">'
            f'<span class="brief">{brief}</span><div class="detail">{_ul(lines)}{extra_html}</div></td>')


def load_display(display_dir: Path | None, n: int, d: dict) -> dict | None:
    """Display lines: the dossier's own display object, else a sidecar file."""
    r = d.get("result") or {}
    if display_dir:
        latest = display_dir / str(n) / "latest"
        if latest.exists():  # stage output: display/<n>/<hash>.json
            with open(display_dir / str(n) / f"{latest.read_text().strip()}.json") as f:
                payload = json.load(f)
            if payload.get("result"):
                out = dict(payload["result"])
                out["source"] = f"display stage, {payload.get('model')}"
                return out
        if (display_dir / f"{n}.json").exists():  # sidecar file (subagent-written)
            with open(display_dir / f"{n}.json") as f:
                return json.load(f)
    if r.get("display"):
        return r["display"]
    return None


def display_lines(disp: dict | None, r: dict, cat: dict | None) -> dict:
    """Lines for each cell; falls back to leading sentences of the long text."""
    out = {
        "goal": [lead(r["summary"], 2)],
        "reviewability": [lead(r["reviewability"]["reason"], 1)],
        "agreement": [r["agreement"].get("summary") or lead(r["agreement"]["reason"], 1)],
        "why": [lead(cat["rationale"], 2)] if cat else [],
    }
    if disp:
        out["goal"] = disp.get("goal") or out["goal"]
        out["reviewability"] = disp.get("reviewability") or out["reviewability"]
        out["agreement"] = disp.get("agreement") or out["agreement"]
        if cat:
            for c in disp.get("categories", []):
                if c.get("name") == cat["name"] and c.get("why"):
                    out["why"] = c["why"]
    return out


def md_to_html(text: str) -> str:
    """Small markdown subset for category files: headings, paragraphs, lists, code spans, bold."""
    def inline(t: str) -> str:
        t = _t(t)
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
        return t
    out = []
    para: list[str] = []
    in_list = False
    def flush():
        nonlocal para
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para = []
    for line in text.splitlines():
        if line.startswith("#"):
            flush()
            if in_list: out.append("</ul>"); in_list = False
            out.append(f"<h2>{inline(line.lstrip('#').strip())}</h2>")
        elif line.lstrip().startswith("- "):
            flush()
            if not in_list: out.append("<ul>"); in_list = True
            out.append(f"<li>{inline(line.lstrip()[2:])}</li>")
        elif not line.strip():
            flush()
            if in_list: out.append("</ul>"); in_list = False
        else:
            if in_list and line.startswith("  "):
                out[-1] = out[-1][:-5] + " " + inline(line.strip()) + "</li>"
            else:
                if in_list: out.append("</ul>"); in_list = False
                para.append(line.strip())
    flush()
    if in_list: out.append("</ul>")
    return "".join(out)


def _reviews(rec: dict) -> tuple[str, list[str], str, str]:
    db = rec.get("bot", {}).get("drahtbot", {}).get("reviews", {})
    ack = db.get("ack", []); stale = db.get("stale_ack", [])
    nacks = db.get("nack", []) + db.get("concept_nack", []) + db.get("approach_nack", [])
    brief = str(len(ack))
    if stale:
        brief += f' <span class="stale">(+{len(stale)})</span>'
    if nacks:
        brief += f' <span class="nack">-{len(nacks)}</span>'
    lines, links = [], []
    for key, label in (("ack", "ACK"), ("stale_ack", "Stale ACK"), ("approach_ack", "Approach ACK"),
                       ("concept_ack", "Concept ACK"), ("nack", "NACK"), ("approach_nack", "Approach NACK"),
                       ("concept_nack", "Concept NACK")):
        who = db.get(key, [])
        if who:
            lines.append(f"{label}: " + ", ".join(w["login"] for w in who))
            links.append(f'<li>{label}: ' + ", ".join(f'<a href="{_e(w["url"])}">{_e(w["login"])}</a>' for w in who) + "</li>")
    if not lines:
        lines = ["No review verdicts recorded"]
    g = min(len(ack), 4)
    style = f"background: rgb({255 - g * 22},255,{255 - g * 22});"
    return brief, lines, ("<ul>" + "".join(links) + "</ul>") if links else "", style


def _row(rec: dict, d: dict, cat: dict, cat_name: str, disp: dict | None, pr_href: str) -> str:
    r = d["result"]
    n = rec["number"]
    L = display_lines(disp, r, cat)
    pr_brief = (f'<span class="tg" title="expand/collapse row">(+)</span><a href="{_e(rec["url"])}">#{n}</a> '
                f'<span class="author">{_e(rec["author"])}</span> <span class="title">{_e(rec["title"])}</span>')
    pr_extra = f'<div class="more"><a href="{_e(pr_href)}">Full analysis</a></div>'
    tag = cat.get("reason_tag") or ""
    band = cat.get("rank_band") or cat["band"]
    prio_brief = f'{_e(band)}' + (f' <span class="tag">· {_e(tag)}</span>' if tag else "")
    prio_style = f"background:{_shade(cat['score'])};" if band != "Unranked" else ""
    if cat.get("rank_band"):
        L["why"] = [f'{band} after comparing with the other PRs here (assessed alone as {cat["dossier_band"]}): {cat["rank_note"]}'] + L["why"]
    elif cat.get("rank_note"):
        L["why"] = L["why"] + [f'Ranking pass: {cat["rank_note"]}']
    rv = r["reviewability"]
    rv_style = f"background:{REVIEWABILITY_COLORS.get(rv['state'], '#fff')};"
    rw_brief, rw_lines, rw_links, rw_style = _reviews(rec)
    ag = r["agreement"]
    ag_style = f"background:{AGREEMENT_COLORS.get(ag['state'], '#fff')};"
    sz_brief = f'+{rec["additions"]}/-{rec["deletions"]}'
    if rec.get("test_lines"):
        sz_brief += f' <span class="stale">({rec["test_lines"]} tests)</span>'
    sz_lines = [f'{rec["changed_files"]} files', f'{rec["commit_count"]} commits']
    if rec.get("test_lines") is not None:
        sz_lines.append(f'{rec["test_lines"]} lines under test/bench/ci')
    sz_style = f"background:{SIZE_COLORS.get(rec['size_bucket'], '#fff')};"
    cls = "unranked" if cat["band"] == "Unranked" else ""
    reviews_td = (f'<td class="reviews" title="{_e(chr(10).join(rw_lines))}" style="{rw_style}">'
                  f'<span class="brief">{rw_brief}</span><div class="detail">{rw_links or _ul(rw_lines)}</div></td>')
    return (f'<tr class="{cls}" id="pr-{n}">'
            + _cell("pr", pr_brief, L["goal"], extra_html=pr_extra)
            + _cell("prio", prio_brief, L["why"], style=prio_style)
            + _cell("rev", _t(rv["label"]), L["reviewability"], style=rv_style)
            + reviews_td
            + _cell("agree", _e(ag["state"]), L["agreement"], style=ag_style)
            + _cell("size", sz_brief, sz_lines, style=sz_style)
            + "</tr>")


def _pr_page(rec: dict, d: dict, cats: dict, disp: dict | None, ranks: dict[str, tuple[int, int]]) -> str:
    r = d["result"]
    n = rec["number"]
    L = display_lines(disp, r, None)
    b = []
    b.append(f'<p><a href="{_e(rec["url"])}">{_e(rec["url"])}</a> · <span class="author">{_e(rec["author"])}</span> · '
             f'+{rec["additions"]}/-{rec["deletions"]} in {rec["changed_files"]} files, {rec["commit_count"]} commits · '
             f'labels: {_e(", ".join(rec["labels"]) or "none")}{" · draft" if rec["draft"] else ""}</p>')
    b.append(f'<h2>Goal</h2><div class="box">{_ul(L["goal"])}<p>{_t(r["summary"])}</p><p><span class="k">Problem:</span> {_t(r["problem"])}</p></div>')
    for c in r["categories"]:
        if not c["member"]:
            continue
        f = c["factors"]
        title = cats[c["name"]].title if c["name"] in cats else c["name"]
        pos, total = ranks.get(c["name"], (0, 0))
        why = display_lines(disp, r, c)["why"]
        b.append(f'<h2 id="cat-{_e(c["name"])}">Category: <a href="../{_e(c["name"])}.html#pr-{n}">{_e(title)}</a>'
                 + (f' (#{pos} of {total})' if total else "") + '</h2>'
                 f'<div class="box"><p class="lead">{_e(c["band"])}' + (f' · {_e(c["reason_tag"])}' if c.get("reason_tag") else "") + '</p>'
                 f'{_ul(why)}<p>{_t(c["rationale"])}</p><p><span class="k">Membership:</span> {_t(c["evidence"])}</p>'
                 f'<p><span class="k">Factors:</span> security/stability {f["security_stability"]}, bug {f["bug_severity"]}, performance {f["performance"]}, '
                 f'user value {f["user_value"]}, leverage {f["leverage"]}</p></div>')
    rv = r["reviewability"]
    rv_title = rv["state"] if rv["label"].strip().lower() == rv["state"].lower() else f'{rv["state"]}: {rv["label"]}'
    b.append(f'<h2 id="reviewability">Reviewability: {_e(rv_title)}</h2><div class="box">{_ul(L["reviewability"])}<p>{_t(rv["reason"])}</p>'
             f'<p><span class="k">Author status:</span> {_t(r["discussion"]["author_status"])}</p>'
             + (f'<p><span class="k">Open concerns:</span>{_ul(r["discussion"]["open_concerns"])}</p>' if r["discussion"]["open_concerns"] else "")
             + (f'<p><span class="k">Resolved concerns:</span>{_ul(r["discussion"]["resolved_concerns"])}</p>' if r["discussion"]["resolved_concerns"] else "") + '</div>')
    ag = r["agreement"]
    rw_brief, rw_lines, rw_links, _ = _reviews(rec)
    b.append(f'<h2 id="agreement">Agreement: {_e(ag["state"])}</h2><div class="box">{_ul(L["agreement"])}'
             + (f'<p>{_t(ag["summary"])}</p>' if ag.get("summary") else "")
             + f'<p>{_t(ag["reason"])}</p>{_ul(ag["evidence"])}<p><span class="k">Review verdicts (DrahtBot):</span> {rw_brief}</p>{rw_links}</div>')
    dep = r["dependencies"]
    if dep["depends_on"] or dep["enables"] or rec["stack"]["based_on"] or rec["stack"]["base_for"]:
        b.append('<h2 id="deps">Dependencies</h2><div class="box">'
                 + (f'<p><span class="k">Depends on:</span> {_e(", ".join("#" + str(x) for x in dep["depends_on"]))}</p>' if dep["depends_on"] else "")
                 + (f'<p><span class="k">Enables:</span>{_ul(dep["enables"])}</p>' if dep["enables"] else "")
                 + (f'<p><span class="k">Based on (shares commits with):</span> {_e(", ".join("#" + str(x) for x in rec["stack"]["based_on"]))}</p>' if rec["stack"]["based_on"] else "")
                 + (f'<p><span class="k">Base for:</span> {_e(", ".join("#" + str(x) for x in rec["stack"]["base_for"]))}</p>' if rec["stack"]["base_for"] else "") + '</div>')
    files = rec.get("files") or []
    b.append(f'<h2 id="files">Files</h2><div class="box">'
             + (f'<p>{rec["test_lines"]} lines under test/bench/ci.</p>' if rec.get("test_lines") is not None else "")
             + (_ul(f'{x["path"]} +{x["add"]}/-{x["del"]}' for x in sorted(files, key=lambda x: -((x["add"] or 0) + (x["del"] or 0)))) if files else "<p>File list not available for this run.</p>") + '</div>')
    if r["uncertainties"]:
        b.append(f'<h2>Uncertainties</h2><div class="box">{_ul(r["uncertainties"])}</div>')
    b.append(f'<h2>Card</h2><div class="box"><p>{_t(r["card"])}</p></div>')
    src = f' · display text: {_e(disp.get("source"))}' if disp and disp.get("synthetic") else ""
    b.append(f'<h2>Data</h2><div class="box"><a href="../data/dossier-{n}.json">dossier JSON</a> · <a href="../data/extract-{n}.json">extract JSON</a> · '
             f'model {_e(d.get("model"))}, generated {_e((d.get("created") or "")[:16])}, confidence {_e(r["confidence"])}, '
             f'input hash {_e(d.get("input_hash"))}{src}</div>')
    return '<div class="prpage">' + "".join(b) + "</div>"


def _page(title: str, body: str, sub: str = "", nav: str = "", h1: str | None = None) -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{_e(title)}</title><style>{CSS}</style></head><body><main>'
            f'{nav}<h1>{h1 if h1 is not None else _e(title)}</h1>' + (f'<div class="sub">{sub}</div>' if sub else "") + f'{body}</main><script>{JS}</script></body></html>')


def load_rank(rank_dir: Path | None, cat_name: str) -> dict | None:
    """Latest rank-stage output for a category: {number: {band, position, note}}, plus meta."""
    if not rank_dir:
        return None
    latest = rank_dir / cat_name / "latest"
    if not latest.exists():
        return None
    with open(rank_dir / cat_name / f"{latest.read_text().strip()}.json") as f:
        payload = json.load(f)
    res = payload.get("result") or {}
    return {"by": {e["number"]: e for e in res.get("ranking", [])}, "inconsistencies": res.get("inconsistencies", []),
            "notes": res.get("notes", ""), "created": payload.get("created"), "model": payload.get("model")}


def render(cfg: Config, extract_dir: Path, dossier_dir: Path, out_dir: Path, display_dir: Path | None = None,
           rank_dir: Path | None = None) -> dict:
    cats = {c.name: c for c in load_categories(cfg.categories_dir)}
    if cfg.repos:
        _REPO_URL["url"] = f"https://github.com/{cfg.repos[0].full_name}"
    dossiers = load_latest(dossier_dir)
    recs: dict[int, dict] = {}
    for n in dossiers:
        p = extract_dir / "prs" / f"{n}.json"
        if p.exists():
            with open(p) as f:
                recs[n] = json.load(f)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "data").mkdir(exist_ok=True)
    (out_dir / "pr").mkdir(exist_ok=True)
    displays = {n: load_display(display_dir, n, d) for n, d in dossiers.items()}
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
    for rows in members.values():
        rows.sort(key=lambda x: -x[0])
    rank_info: dict[str, dict] = {}
    for name, rows in members.items():
        rk = load_rank(rank_dir, name)
        if not rk:
            continue
        rank_info[name] = rk
        by = rk["by"]
        for i, (score, n, c) in enumerate(rows):
            e = by.get(n)
            if not e:
                continue
            if e["band"] != c["band"]:
                c = dict(c, rank_band=e["band"], dossier_band=c["band"], rank_note=e["note"])
            else:
                c = dict(c, rank_note=e["note"])
            rows[i] = (score, n, c)
        rows.sort(key=lambda x: (by.get(x[1], {}).get("position", 10**6), -x[0]))
    ranks: dict[int, dict[str, tuple[int, int]]] = {}
    for name, rows in members.items():
        for i, (_, n, _c) in enumerate(rows, 1):
            ranks.setdefault(n, {})[name] = (i, len(rows))
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    project = cfg.raw.get("project", {}) or {}
    repo_url = project.get("repo_url")
    def cat_src(name: str) -> str:
        return f"{repo_url}/blob/main/categories/{name}.md" if repo_url else "#"
    legend = ('<div class="legend">'
              f'<div>Reviewability: <span style="background:{REVIEWABILITY_COLORS["Ready"]}">Ready</span>'
              f'<span style="background:{REVIEWABILITY_COLORS["Stale"]}">Stale</span>'
              f'<span style="background:{REVIEWABILITY_COLORS["Paused"]}">Paused</span></div>'
              '<div>Agreement: ' + "".join(f'<span style="background:{v}">{k}</span>' for k, v in AGREEMENT_COLORS.items()) + '</div>'
              '<div>Reviews: current code-review ACKs, then (+stale ACKs) and <b style="color:#b00020">-NACKs</b>; greener = more ACKs.</div>'
              '<div>Size: added/deleted lines, tests in parentheses; greener = smaller.</div></div>')
    nav = '<nav class="top"><a href="index.html">Home</a></nav>'
    repo_short = repo_url.replace("https://github.com/", "") if repo_url else ""
    pages = []
    for name, rows in sorted(members.items()):
        cat = cats.get(name)
        title = cat.title if cat else name
        head = ('<table><thead><tr><th>PR</th><th>Priority</th><th>Reviewability</th><th>Reviews</th>'
                '<th>Agreement</th><th>Size</th></tr></thead><tbody>')
        body_rows = "".join(_row(recs[n], dossiers[n], c, name, displays.get(n), f"pr/{n}.html") for _, n, c in rows)
        covers = (f'<div class="covers"><div class="src">Category definition: <a href="{_e(cat_src(name))}">{_e(repo_short)}/categories/{_e(name)}.md</a>'
                  + (f' · editor <a href="https://github.com/{_e(cat.owner)}">{_e(cat.owner)}</a>' if cat.owner else "") + '</div>'
                  f'{md_to_html(cat.body)}</div>') if cat else ""
        callout = ('<div class="banner">Every band, state, and summary on this page is model output against a '
                   'written category definition, shown with its rationale. It is an unofficial tool and does not speak for the '
                   'project. Click any cell\'s summary text to expand the row; hover a cell for the same text.'
                   + (f' The category definition lives in <a href="{_e(cat_src(name))}">{_e(repo_url.replace("https://github.com/", ""))}/categories/{_e(name)}.md</a>; '
                      'pull requests that improve it are welcome.' if repo_url else "") + '</div>')
        rk = rank_info.get(name)
        rank_block = ""
        if rk and (rk["inconsistencies"] or rk["notes"]):
            rank_block = ('<div class="covers"><h2>Notes from the ranking pass</h2>'
                          + (f'<p>{_t(rk["notes"])}</p>' if rk["notes"] else "") + _ul(rk["inconsistencies"])
                          + f'<p class="src">Ranking pass by {_e(rk["model"])} on {_e((rk["created"] or "")[:10])}, comparing all PRs in this category at once.</p></div>')
        body = (head + body_rows + "</tbody></table>" + legend + covers + rank_block
                + f'<div class="foot">{callout}<div class="sub" title="{len(rows)} PRs in this category, {len(dossiers)} assessed in total">generated {stamp}</div></div>')
        h1 = f'<a href="{_e(cat_src(name))}">{_e(title)}</a>'
        (out_dir / f"{name}.html").write_text(_page(f"{title}: {cfg.site_title}", body, nav=nav, h1=h1))
        pages.append(name)
    for n, d in dossiers.items():
        if not d.get("result") or n not in recs:
            continue
        (out_dir / "pr" / f"{n}.html").write_text(_page(f"#{n} {recs[n]['title']}", _pr_page(recs[n], d, cats, displays.get(n), ranks.get(n, {})), "full analysis",
                                                          nav='<nav class="top"><a href="../index.html">Home</a></nav>'))
    repo_short = repo_url.replace("https://github.com/", "") if repo_url else ""
    default_intro = (
        "This site helps reviewers find pull requests to review in a category they care about. "
        "A language model sorts open pull requests into categories and ranks them against written category definitions. "
        "It is an unofficial tool and does not speak for the Bitcoin Core project."
        + (f' The definitions live in <a href="{_e(repo_url)}">{_e(repo_short)}</a> and can be changed by pull request. '
           'Anyone can volunteer to edit an existing category or create a new one.' if repo_url else ""))
    intro = '<div class="intro"><p>' + (_e(project["description"]) if project.get("description") else default_intro) + '</p></div>'
    catlist = '<ul class="catlist">' + "".join(
        f'<li><a href="{_e(name)}.html">{_e(cats[name].title if name in cats else name)}</a>'
        + f' <span class="editor">· <a href="{_e(cat_src(name))}">definition</a>'
        + (f', editor <a href="https://github.com/{_e(cats[name].owner)}">{_e(cats[name].owner)}</a>' if name in cats and cats[name].owner else "") + '</span></li>'
        for name, rows in sorted(members.items(), key=lambda kv: (cats[kv[0]].title if kv[0] in cats else kv[0]).lower())) + "</ul>"
    engine_url = project.get("engine_url")
    feedback = ""
    if repo_url or engine_url:
        parts = []
        if repo_url:
            parts.append(f'<a href="{_e(repo_url)}/issues/new">open an issue in {_e(repo_short)}</a> about the information shown on category pages')
        if engine_url:
            parts.append(f'<a href="{_e(engine_url)}/issues/new">open an issue in {_e(engine_url.replace("https://github.com/", ""))}</a> about the site itself')
        feedback = ('<div class="intro"><p>Feedback, requests for help, and discussion are all welcome: '
                    + ", or ".join(parts) + '. Feedback of any kind is welcome.</p></div>')
    index = intro + catlist + feedback + f'<div class="foot rule"><div class="sub" title="{len(dossiers)} PRs assessed">generated {stamp}</div></div>'
    (out_dir / "index.html").write_text(_page(cfg.site_title, index))
    return {"pages": pages, "prs": len(dossiers), "out": str(out_dir), "display_files": sum(1 for v in displays.values() if v)}
