"""Stage 5: render extract + dossiers into a static site.

One page per category, one row per member PR sorted by score. Each PR is
two table rows: a summary row whose cells show a condensed value, and a
detail row under it that starts collapsed. Clicking anywhere in the
summary row that is not a link opens the detail row with a short
expansion and puts #pr-N in the URL; a #pr-N link opens that row on load.
Every PR number is a GitHub link followed by a small page icon that leads
to the PR's page on this site. Under 1000px the cells wrap; under 640px
each row becomes a block with labeled chips. No external assets; CSS and
JS are inlined so the pages work from a file:// URL and behind any static
server.

A PR page shows the same table with the PR's one row already open and the
priority column left out, because priority belongs to a category: under
the row, one card per category the PR is in carries that category's
priority cell, and the long analysis follows.

A computed category (``kind: computed`` in its file) lists every assessed
PR the model placed in none of the categories it names; its page has a
"Judged" column in place of priority, showing which categories were
asked and what they said.

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
from .dossier import dossier_stem

REVIEWABILITY_COLORS = {"Ready": "#d9f2d9", "Stale": "#fff3c4", "Paused": "#ffd6d6"}
AGREEMENT_COLORS = {
    "Strong": "#bfe8bf", "Positive": "#d9f2d9", "Positive w/ caveats": "#e6f2d9",
    "Neutral": "#f2f2f2", "Mild": "#fff3c4", "Disputed": "#ffe0b3", "Blocked": "#ffc9c9",
    "Crickets": "#ffffff",
}
SIZE_COLORS = {"S": "#d9f2d9", "M": "#fff3c4", "L": "#ffe0b3", "XL": "#ffd6d6"}
TEST_PREFIXES = ("test/", "src/test/", "src/wallet/test/", "src/qt/test/", "src/bench/", "ci/", "contrib/")
_SIZE_CFG = {"small": 100, "medium": 400, "large": 1000}


def cfg_bucket(lines: int) -> str:
    if lines <= _SIZE_CFG["small"]: return "S"
    if lines <= _SIZE_CFG["medium"]: return "M"
    if lines <= _SIZE_CFG["large"]: return "L"
    return "XL"

CSS = """
:root { --border:#ddd; --text:#222; --muted:#666; --link:#0645ad; }
body { font-family: system-ui, sans-serif; color: var(--text); margin: 0; background: #fafafa; }
main { max-width: 1400px; margin: 0 auto; padding: 1rem 1.5rem 4rem; }
a { color: var(--link); text-decoration: none; } a:hover { text-decoration: underline; }
h1 { font-size: 1.4rem; margin: .5rem 0 .25rem; } .sub { color: var(--muted); font-size: .85rem; margin-bottom: 1rem; }
.banner { background:#fff8e1; border:1px solid #f0d78c; padding:.5rem .5rem; font-size:.85rem; margin: 1rem 0 0; }
nav.cats a { margin-right: 1rem; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; background: #fff; table-layout: fixed; }
col.c-pr { width: 42%; } col.c-prio { width: 13%; } col.c-rev { width: 13%; } col.c-reviews { width: 8%; } col.c-agree { width: 13%; } col.c-size { width: 11%; }
table.noprio col.c-pr { width: 55%; }
td { overflow-wrap: anywhere; }
th, td { border: 1px solid var(--border); padding: .35rem .5rem; vertical-align: top; text-align: left; }
th { background: #f0f0f0; position: sticky; top: 0; }
td .brief { display: block; }
table.toggle tr.row td { cursor: pointer; }
tr.row { scroll-margin-top: 2.4rem; } /* a #pr-N link lands below the sticky header */
/* The detail row: its cells carry no padding or horizontal borders of their own, so a
   collapsed row is zero height and the grid line between summary rows stays single. The
   grid-template-rows transition is the expansion; the clip div hides the content at 0fr. */
tr.det td { padding: 0 .5rem; border-top: 0; border-bottom: 0; }
tr.det .dwrap { display: grid; grid-template-rows: 0fr; transition: grid-template-rows .12s ease-out; }
tr.det.open .dwrap { grid-template-rows: 1fr; }
tr.det .dclip { overflow: hidden; min-height: 0; }
tr.det .detail { padding: .4rem 0 .35rem; border-top: 1px dashed #bbb; font-size: .83rem; white-space: normal; font-weight: 400; }
@media (prefers-reduced-motion: reduce) { tr.det .dwrap { transition: none; } }
tr.row.open td { border-top: 2px solid #444; } tr.det.open td { border-bottom: 2px solid #444; }
tr.open td:first-child { border-left: 2px solid #444; } tr.open td:last-child { border-right: 2px solid #444; }
td.pr .title { overflow-wrap: anywhere; } td.pr .title { font-weight: 500; } td.pr .author { color: var(--muted); font-style: italic; }
td.prio { white-space: nowrap; } td.prio .brief { font-weight: 600; } td.prio .tag { font-weight: 400; color: #333; }
td.judged .brief { color: var(--muted); }
td.reviews .brief, td.size .brief { white-space: nowrap; }
td.reviews .nack { color: #b00020; font-weight: 700; } td.reviews .stale { font-style: italic; color: #555; }
.detail ul { margin: 0; padding-left: 1.1rem; } .detail li { margin: .15rem 0; }
.detail .k { color: var(--muted); }
/* PR page: the category cards under the row, one small table each so the priority cell
   keeps the look it has in a category table (header above, open cell below). */
tr.cards > td { padding: .6rem .5rem; background: #fafafa; }
.cardset { display: flex; flex-wrap: wrap; justify-content: center; gap: .6rem; }
table.card { width: 13%; min-width: 12rem; table-layout: fixed; background: #fff; }
table.card th { position: static; font-weight: 600; } table.card th .pos { display: block; font-weight: 400; color: var(--muted); font-size: .8rem; }
.legend { font-size: .8rem; color: var(--muted); background: #f7f7f7; border: 1px solid var(--border); border-top: none; padding: .4rem .5rem; margin: 0; }
.legend span { display:inline-block; padding: 0 .4rem; margin-right:.3rem; border:1px solid var(--border); background: #fff; }
tr.unranked td { color: var(--muted); }
td.pr .tg { float: right; color: var(--link); font-weight: 600; margin-left: .5rem; user-select: none; }
a.loc { color: #999; margin-left: .2em; vertical-align: 15%; } a.loc:hover { color: var(--link); } a.loc svg { display: inline-block; }
@media (max-width: 1000px) {
  main { padding: .6rem .5rem 3rem; }
  table { font-size: .82rem; } th, td { padding: .3rem .35rem; }
  td.prio, td.reviews .brief, td.size .brief { white-space: normal; }
  col.c-pr { width: 38%; } table.noprio col.c-pr { width: 50%; } col.c-prio, col.c-rev, col.c-agree { width: 14%; } col.c-size { width: 12%; }
  table.card { width: 30%; }
}
/* Phones: the summary row becomes a block with the PR on its own line and the other
   cells as labeled chips; the detail row stacks its cells with the same labels. */
@media (max-width: 640px) {
  table, tbody { display: block; } thead, colgroup { display: none; }
  tr.row { display: flex; flex-wrap: wrap; border-top: 1px solid var(--border); }
  tr.row td { border: 0; } tr.row td.pr { flex: 1 1 100%; }
  tr.row td:not(.pr) { flex: 0 1 auto; padding-top: 0; padding-bottom: .3rem; margin: 0 .35rem .1rem; border: 1px solid var(--border); padding: .1rem .4rem; }
  tr.row td:not(.pr)::before { content: attr(data-col) ": "; color: var(--muted); font-size: .75rem; }
  tr.det { display: block; } tr.det td { display: block; border: 0; }
  tr.det td::before { content: attr(data-col); display: block; color: var(--muted); font-size: .75rem; padding-top: .3rem; }
  tr.det td.pr::before { content: none; }
  tr.det td .detail { border-top: 0; padding-top: .1rem; }
  tr.det:not(.open) td::before { display: none; }
  tr.row.open td, tr.det.open td { border-left: 0; border-right: 0; } tr.row.open td { border-top: 0; } tr.det.open td { border-bottom: 0; }
  tr.row.open { border-top: 2px solid #444; } tr.det.open { border-bottom: 2px solid #444; }
  tr.cards { display: block; } tr.cards > td { display: block; } table.card { width: 100%; min-width: 0; display: table; } table.card thead { display: table-header-group; }
  table.card tr.row, table.card tr.det { display: table-row; } table.card td { display: table-cell; }
  table.card tr.row td::before, table.card tr.det td::before { content: none; }
  table.card tr.row td, table.card tr.det td { border: 1px solid var(--border); }
  .legend, .rankline { border-top: 1px solid var(--border); }
}
.more { font-size: .8rem; margin-top: .4rem; padding-top: .4rem; border-top: 1px dashed #bbb; }
.prpage .anchor { margin-top: 1.4rem; }
nav.top { font-size: .85rem; margin-bottom: .6rem; } nav.top a { margin-right: 1rem; }
h1 a { color: inherit; } h1 a:hover { text-decoration: underline; }
.intro { max-width: 60rem; } .intro p { margin: .4rem 0 .8rem; }
ul.catlist { line-height: 1.7; padding-left: 1.2rem; } ul.catlist .editor { color: var(--muted); font-size: .85rem; }
.foot .sub { margin: 1rem 0 0; }
.foot.rule { margin-top: 2rem; border-top: 1px solid var(--border); padding-top: .6rem; } .foot.rule .sub { margin: 0; }
.legend div { margin: .15rem 0; }
.rankline { font-size: .8rem; color: var(--muted); background: #fff; border: 1px solid var(--border); border-top: none; padding: .4rem .5rem; margin: 0; }
.covers { font-size: .9rem; background: #fff; border: 1px solid var(--border); padding: .4rem .5rem .6rem; margin: 1rem 0 0; }
.covers h2 { font-size: 1rem; margin: .8rem 0 .2rem; } .covers p { margin: .3rem 0; } .covers ul { margin: .2rem 0; }
.covers .src { font-size: .8rem; color: var(--muted); margin: .1rem 0 .2rem; }
.prpage .lead { font-weight: 600; } .prpage ul { margin: .3rem 0; padding-left: 1.2rem; }
.prpage h2 { font-size: 1.1rem; margin: 1.2rem 0 .3rem; border-bottom: 1px solid var(--border); }
.prpage .box { background: #fff; border: 1px solid var(--border); padding: .6rem .8rem; margin: .4rem 0; }
.prpage .scroll { overflow-x: auto; }
.prpage table.obj { border-collapse: collapse; font-size: .85rem; margin: .3rem 0; }
.prpage table.obj th, .prpage table.obj td { border: 1px solid var(--border); padding: .2rem .4rem; vertical-align: top; text-align: left; }
.prpage .muted { color: #666; }
.prpage .k { color: var(--muted); }
"""

JS = """
function setOpen(row, open) {
  row.classList.toggle('open', open);
  var det = row.nextElementSibling;
  if (det && det.classList.contains('det')) det.classList.toggle('open', open);
  var g = row.querySelector('td.pr .tg'); if (g) g.textContent = open ? '(\\u2212)' : '(+)';
}
document.addEventListener('click', function (ev) {
  if (ev.target.closest('a')) return;
  var row = ev.target.closest('tr.row');
  if (!row || !row.closest('table.toggle')) return;
  if (window.getSelection && String(window.getSelection())) return;
  var open = !row.classList.contains('open');
  setOpen(row, open);
  if (open && row.id) history.replaceState(null, '', '#' + row.id);
  else if (!open && location.hash === '#' + row.id) history.replaceState(null, '', location.pathname + location.search);
});
function openHash() {
  var row = location.hash.length > 1 && document.getElementById(location.hash.slice(1));
  if (row && row.classList.contains('row') && row.closest('table.toggle')) setOpen(row, true);
}
window.addEventListener('hashchange', openHash);
openHash();
"""


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


_REPO_URL = {"url": "https://github.com/bitcoin/bitcoin"}
_REF_RE = re.compile(r"(?<![\w/])(?:([\w.-]+/[\w.-]+))?#(\d{2,6})\b")
# PRs with a page on this site, the path prefix to reach pr/ from the page being
# rendered, and the PR whose own page is being rendered (no self link on it).
_PR_CTX: dict = {"pages": set(), "prefix": "pr/", "self": None}


def _local(n: int) -> str:
    """A small secondary link to the PR's page on this site, after a GitHub link."""
    if n not in _PR_CTX["pages"] or n == _PR_CTX["self"]:
        return ""
    return (f'<a class="loc" href="{_PR_CTX["prefix"]}{n}.html" title="#{n} on this site">'
            '<svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true"><path d="M2.5 1.5h5l2 2v7h-7z" fill="none" stroke="currentColor"/>'
            '<path d="M4.5 6h3M4.5 8h3" stroke="currentColor"/></svg></a>')


def _t(text) -> str:
    """Escape text and turn #1234 and owner/repo#1234 into GitHub links, each
    followed by the site's own page for the PR when there is one. GitHub
    redirects /pull/N to /issues/N when N is an issue, so one form works for both."""
    def sub(m):
        repo, n = m.group(1), m.group(2)
        url = f"https://github.com/{repo}/pull/{n}" if repo else f"{_REPO_URL['url']}/pull/{n}"
        return f'<a href="{url}">{m.group(0)}</a>' + ("" if repo else _local(int(n)))
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


def _objections(ag: dict) -> str:
    """The enumerated objections, support, participants, and the code's
    corrections, so a reader can check the state against quotes without
    opening the thread. Only for dossiers made with the enumeration schema."""
    if "objections" not in ag:
        return ""
    out = []
    obs = ag.get("objections") or []
    if obs:
        rows = []
        for o in obs:
            status = o.get("status") or ""
            if o.get("status_model") and o["status_model"] != status:
                status = f'{status} <span class="muted">(model said {_e(o["status_model"])})</span>'
            replied = "yes" if o.get("author_replied") else "no"
            if o.get("author_replied_model") and not o.get("author_replied"):
                replied = 'no <span class="muted">(model said yes)</span>'
            rows.append(f'<tr><td>{_e(o.get("reviewer"))}</td><td>{_e(o.get("kind") or "")}</td><td>{_e(o.get("harm") or "")}</td>'
                        f'<td>{status}</td><td>{"yes" if o.get("blocking") else "no"}</td><td>{replied}</td>'
                        f'<td>{_t(o.get("evidence") or "")}' + (f'<br><span class="k">Settled:</span> {_t(o["resolution_evidence"])}' if o.get("resolution_evidence") else "") + '</td></tr>')
        out.append('<p><span class="k">Objections:</span></p><div class="scroll"><table class="obj"><tr><th>Reviewer</th><th>Kind</th><th>Harm</th><th>Status</th><th>Blocking</th><th>Author replied</th><th>Quote</th></tr>'
                   + "".join(rows) + '</table></div>')
    else:
        out.append('<p><span class="k">Objections:</span> none enumerated.</p>')
    sup = ag.get("support") or []
    if sup:
        out.append('<p><span class="k">Support:</span></p>' + _ul([f'{x.get("reviewer")}: {x.get("reason") or "(no reason given)"}' + ("" if x.get("substantive") else " [not substantive]") for x in sup]))
    parts = ag.get("participants") or []
    if parts:
        out.append('<p><span class="k">Participants:</span> ' + ", ".join(f'{_e(x.get("login"))} ({_e(x.get("stance"))})' for x in parts) + '</p>')
    if ag.get("missing_participants"):
        out.append('<p><span class="k">Commenters the model did not classify:</span> ' + _e(", ".join(ag["missing_participants"])) + '</p>')
    if ag.get("corrections"):
        out.append('<p><span class="k">Checked against the thread:</span></p>' + _ul(ag["corrections"]))
    if ag.get("derivation"):
        out.append(f'<p class="muted">State derived from the lists: {_e(ag["derivation"])}' + (f' (model\'s own read: {_e(ag["model_state"])})' if ag.get("model_state") and ag.get("model_state") != ag.get("state") else "") + '</p>')
    return "".join(out)


def _ul(items) -> str:
    items = [i for i in items if i]
    return "<ul>" + "".join(f"<li>{_t(i)}</li>" for i in items) + "</ul>" if items else ""


COL_LABELS = {"prio": "Priority", "judged": "Judged", "rev": "Reviewability", "reviews": "Reviews", "agree": "Agreement", "size": "Size"}


class Cell:
    """One column of a PR: the condensed value for the summary row and the
    detail block for the row under it. ``detail_html`` replaces the bullet
    list built from ``lines`` when given; ``lines`` still feed the tooltip."""

    def __init__(self, col: str, brief: str, lines: list[str], style: str = "", extra_html: str = "", detail_html: str | None = None):
        self.col, self.brief, self.lines, self.style, self.extra_html, self.detail_html = col, brief, lines, style, extra_html, detail_html

    def summary_td(self) -> str:
        return f'<td class="{self.col}" data-col="{COL_LABELS.get(self.col, "")}" style="{self.style}"><span class="brief">{self.brief}</span></td>'

    def detail_td(self) -> str:
        inner = self.detail_html if self.detail_html is not None else _ul(self.lines)
        return (f'<td class="{self.col}" data-col="{COL_LABELS.get(self.col, "")}" style="{self.style}">'
                f'<div class="dwrap"><div class="dclip"><div class="detail">{inner}{self.extra_html}</div></div></div></td>')


def _rows(cells: list[Cell], cls: str = "", open: bool = False, anchor: str = "") -> str:
    """The summary row and the detail row for one PR (or one card)."""
    state = f'{cls} open' if open else cls
    return (f'<tr class="row {state}"' + (f' id="{anchor}"' if anchor else "") + '>' + "".join(c.summary_td() for c in cells) + '</tr>'
            f'<tr class="det {state}">' + "".join(c.detail_td() for c in cells) + '</tr>')


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


def _prio_cell(cat: dict, cats: dict, disp: dict | None, r: dict) -> Cell:
    """The priority cell of one category: band and reason tag, shaded by
    score, with the display stage's "why" lines. For a computed category
    the cell instead says which categories were asked about the PR and
    what each answered, since there is no priority to show."""
    if cat.get("computed"):
        judged = cat.get("judged") or []
        rejected = [j for j in judged if not j["member"]]
        accepted = [j for j in judged if j["member"]]
        lines = [f'{cats[j["name"]].title if j["name"] in cats else j["name"]}: {"member. " if j["member"] else "not a member. "}{j.get("evidence") or "(no reason recorded)"}'
                 for j in judged] or ["No category was asked about this PR"]
        brief = (f'{len(rejected)} rejected' if judged else "not judged") + (", in " + ", ".join(j["name"] for j in accepted) if accepted else "")
        return Cell("judged", _e(brief), lines)
    L = display_lines(disp, r, cat)
    tag = cat.get("reason_tag") or ""
    band = cat.get("rank_band") or cat["band"]
    brief = f'{_e(band)}' + (f' <span class="tag">· {_e(tag)}</span>' if tag else "")
    style = f"background:{_shade(cat['score'])};" if band != "Unranked" else ""
    if cat.get("rank_band"):
        why = [f'{band} after comparing with the other PRs here (assessed alone as {cat["dossier_band"]}): {cat["rank_note"]}'] + L["why"]
    elif cat.get("rank_note"):
        why = L["why"] + [f'Ranking pass: {cat["rank_note"]}']
    else:
        why = L["why"]
    return Cell("prio", brief, why, style=style)


def _pr_cells(rec: dict, d: dict, disp: dict | None, pr_href: str | None, toggle: bool = True) -> list[Cell]:
    """The cells every table shows for a PR: the PR itself, reviewability,
    reviews, agreement, size. ``pr_href`` adds the "Full analysis" link to
    the PR cell's detail; a PR page passes None."""
    r = d["result"]
    n = rec["number"]
    L = display_lines(disp, r, None)
    pr_brief = ((f'<span class="tg">(+)</span>' if toggle else "")
                + f'<a href="{_e(rec["url"])}">#{n}</a>{_local(n)} <span class="author">{_e(rec["author"])}</span> <span class="title">{_e(rec["title"])}</span>')
    pr_extra = f'<div class="more"><a href="{_e(pr_href)}">Full analysis</a></div>' if pr_href else ""
    rv = r["reviewability"]
    rv_style = f"background:{REVIEWABILITY_COLORS.get(rv['state'], '#fff')};"
    rw_brief, rw_lines, rw_links, rw_style = _reviews(rec)
    ag = r["agreement"]
    ag_style = f"background:{AGREEMENT_COLORS.get(ag['state'], '#fff')};"
    files = rec.get("files") or []
    if files:
        code_add = sum((f["add"] or 0) for f in files if not f["path"].startswith(TEST_PREFIXES))
        test_add = sum((f["add"] or 0) for f in files if f["path"].startswith(TEST_PREFIXES))
        sz_brief = f'{code_add:,}' + (f' <span class="stale">+ {test_add:,} tests</span>' if test_add else "")
        sz_lines = [f'{code_add:,} lines added or modified outside tests', f'{test_add:,} lines added or modified in tests',
                    f'{rec["deletions"]:,} lines removed in total', f'{rec["changed_files"]} files, {rec["commit_count"]} commits']
        sz_style = f"background:{SIZE_COLORS.get(cfg_bucket(code_add), '#fff')};"
    else:
        sz_brief = f'+{rec["additions"]}/-{rec["deletions"]}'
        sz_lines = [f'{rec["changed_files"]} files', f'{rec["commit_count"]} commits']
        sz_style = f"background:{SIZE_COLORS.get(rec['size_bucket'], '#fff')};"
    return [Cell("pr", pr_brief, L["goal"], extra_html=pr_extra),
            Cell("rev", _t(rv["label"]), L["reviewability"], style=rv_style),
            Cell("reviews", rw_brief, rw_lines, style=rw_style, detail_html=rw_links or None),
            Cell("agree", _e(ag["state"]), L["agreement"], style=ag_style),
            Cell("size", sz_brief, sz_lines, style=sz_style)]


def _row(rec: dict, d: dict, cat: dict, cats: dict, disp: dict | None, pr_href: str) -> str:
    """One PR's rows on a category page: the PR cells with the category's priority cell second."""
    cells = _pr_cells(rec, d, disp, pr_href)
    cells.insert(1, _prio_cell(cat, cats, disp, d["result"]))
    cls = "unranked" if cat["band"] == "Unranked" else ""
    return _rows(cells, cls, anchor=f"pr-{rec['number']}")


def _table_head(prio: str | None, toggle: bool = True) -> str:
    """The table opening: ``prio`` is the second column's header (None leaves the column out)."""
    cols = ['<col class="c-pr">'] + (['<col class="c-prio">'] if prio else []) + ['<col class="c-rev">', '<col class="c-reviews">', '<col class="c-agree">', '<col class="c-size">']
    heads = ['<th>PR</th>'] + ([f'<th>{_e(prio)}</th>'] if prio else []) + ['<th>Reviewability</th>', '<th>Reviews</th>', '<th>Agreement</th>', '<th>Size</th>']
    cls = " ".join(x for x in ["toggle" if toggle else "", "" if prio else "noprio"] if x)
    return f'<table class="{cls}"><colgroup>' + "".join(cols) + '</colgroup><thead><tr>' + "".join(heads) + '</tr></thead><tbody>'


def _cards(rec: dict, d: dict, cats: dict, disp: dict | None, ranks: dict[str, tuple[int, int]], merged: dict, ranked: set) -> str:
    """The category cards row of a PR page: for each category the PR is in,
    that category's priority cell as it appears on the category page (the
    entry merged with the ranking pass, so band and notes match), under the
    category's title and the PR's position there."""
    n = rec["number"]
    cards = []
    for c in d["result"]["categories"]:
        if not c["member"]:
            continue
        c = merged.get((c["name"], n), c)
        cat = cats.get(c["name"])
        title = cat.title if cat else c["name"]
        pos, total = ranks.get(c["name"], (0, 0))
        pos_html = f'<span class="pos">#{pos} of {total}</span>' if total and not c.get("computed") else (f'<span class="pos">{total} PRs, unranked</span>' if total else "")
        cell = _prio_cell(c, cats, disp, d["result"])
        if c["name"] in ranked:
            cell.extra_html = f'<div class="more"><a href="../rank/{_e(c["name"])}.html">Ranking notes</a></div>'
        cards.append(f'<table class="card"><thead><tr><th><a href="../{_e(c["name"])}.html#pr-{n}">{_e(title)}</a>{pos_html}</th></tr></thead><tbody>'
                     + _rows([cell], open=True) + '</tbody></table>')
    if not cards:
        cards.append('<div class="sub">In no category.</div>')
    return f'<tr class="cards"><td colspan="5"><div class="cardset">{"".join(cards)}</div></td></tr>'


def _pr_page(rec: dict, d: dict, cats: dict, disp: dict | None, ranks: dict[str, tuple[int, int]], legend: str, merged: dict, ranked: set) -> str:
    r = d["result"]
    n = rec["number"]
    L = display_lines(disp, r, None)
    b = []
    table = (_table_head(None, toggle=False) + _rows(_pr_cells(rec, d, disp, None, toggle=False), open=True, anchor=f"pr-{n}")
             + _cards(rec, d, cats, disp, ranks, merged, ranked) + "</tbody></table>" + legend)
    b.append(f'<p class="anchor"><a href="{_e(rec["url"])}">{_e(rec["url"])}</a> · <span class="author">{_e(rec["author"])}</span> · '
             f'+{rec["additions"]}/-{rec["deletions"]} in {rec["changed_files"]} files, {rec["commit_count"]} commits · '
             f'labels: {_e(", ".join(rec["labels"]) or "none")}{" · draft" if rec["draft"] else ""}</p>')
    b.append(f'<h2>Goal</h2><div class="box">{_ul(L["goal"])}<p>{_t(r["summary"])}</p><p><span class="k">Problem:</span> {_t(r["problem"])}</p></div>')
    for c in r["categories"]:
        if not c["member"] or c.get("computed"):
            continue
        c = merged.get((c["name"], n), c)
        f = c["factors"]
        title = cats[c["name"]].title if c["name"] in cats else c["name"]
        pos, total = ranks.get(c["name"], (0, 0))
        why = display_lines(disp, r, c)["why"]
        band = c.get("rank_band") or c["band"]
        lead_note = (f' <span class="muted">(assessed alone as {_e(c["dossier_band"])}; {_t(c["rank_note"])})</span>' if c.get("rank_band")
                     else (f' <span class="muted">(ranking pass: {_t(c["rank_note"])})</span>' if c.get("rank_note") else ""))
        b.append(f'<h2 id="cat-{_e(c["name"])}">Category: <a href="../{_e(c["name"])}.html#pr-{n}">{_e(title)}</a>'
                 + (f' (#{pos} of {total})' if total else "") + '</h2>'
                 f'<div class="box"><p class="lead">{_e(band)}' + (f' · {_e(c["reason_tag"])}' if c.get("reason_tag") else "") + f'{lead_note}</p>'
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
             + f'<p>{_t(ag["reason"])}</p>{_ul(ag["evidence"])}' + _objections(ag)
             + f'<p><span class="k">Review verdicts (DrahtBot):</span> {rw_brief}</p>{rw_links}</div>')
    dep = r["dependencies"]
    if dep["depends_on"] or dep["enables"] or rec["stack"]["based_on"] or rec["stack"]["base_for"]:
        b.append('<h2 id="deps">Dependencies</h2><div class="box">'
                 + (f'<p><span class="k">Depends on:</span> {_t(", ".join("#" + str(x) for x in dep["depends_on"]))}</p>' if dep["depends_on"] else "")
                 + (f'<p><span class="k">Enables:</span>{_ul(dep["enables"])}</p>' if dep["enables"] else "")
                 + (f'<p><span class="k">Based on (shares commits with):</span> {_t(", ".join("#" + str(x) for x in rec["stack"]["based_on"]))}</p>' if rec["stack"]["based_on"] else "")
                 + (f'<p><span class="k">Base for:</span> {_t(", ".join("#" + str(x) for x in rec["stack"]["base_for"]))}</p>' if rec["stack"]["base_for"] else "") + '</div>')
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
    return table + '<div class="prpage">' + "".join(b) + "</div>"


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
            "notes": res.get("notes", ""), "created": payload.get("created"), "model": payload.get("model"),
            "dossier_hashes": payload.get("dossier_hashes") or {}}


BAND_ORDER = {"P1": 1, "P2": 2, "P3": 3, "P4": 4, "Unranked": 5}


def merge_rank(rows: list, rk: dict, dossiers: dict) -> list:
    """Combine a category's ranking pass with newer dossiers.

    A ranking entry applies only while the dossier it saw is unchanged (same
    input hash). Ranked PRs keep the pass's band and relative order. A PR
    the pass did not see, or whose dossier changed since, uses its own band
    and is slotted among the ranked PRs of that band by score. Result: a
    stable weekly order with daily arrivals interleaved, never dumped at the
    bottom."""
    by, hashes = rk["by"], rk["dossier_hashes"]
    ranked, fresh = [], []
    for score, n, c in rows:
        e = by.get(n)
        if e and hashes.get(str(n)) in (dossiers[n].get("input_hash"), dossier_stem(dossiers[n])):
            c = dict(c, rank_note=e["note"])
            if e["band"] != c["band"]:
                c.update(rank_band=e["band"], dossier_band=c["band"])
            ranked.append((e["position"], score, n, c))
        else:
            fresh.append((score, n, c))
    ranked.sort()
    out: list = []
    for band in ("P1", "P2", "P3", "P4", "Unranked"):
        band_ranked = [(sc, n, c) for _, sc, n, c in ranked if (c.get("rank_band") or c["band"]) == band]
        band_fresh = sorted([(sc, n, c) for sc, n, c in fresh if c["band"] == band], key=lambda x: -x[0])
        merged: list = []
        for item in band_ranked:
            while band_fresh and band_fresh[0][0] > item[0]:
                merged.append(band_fresh.pop(0))
            merged.append(item)
        merged.extend(band_fresh)
        out.extend(merged)
    return out


def computed_members(cat, members: dict, dossiers: dict, recs: dict) -> list:
    """Rows of a computed category: every assessed PR that is a member of none
    of the categories it names, newest first. Each row's category dict carries
    the PR's judgments so the page can show what was asked and answered."""
    excluded = {n for name in cat.not_in for _, n, _c in members.get(name, [])}
    rows = []
    for n, d in dossiers.items():
        r = d.get("result")
        if not r or n not in recs or n in excluded:
            continue
        judged = [{"name": c["name"], "member": bool(c["member"]), "evidence": c.get("evidence") or ""} for c in r["categories"] if not c.get("computed")]
        rows.append((float(n), n, {"name": cat.name, "member": True, "computed": True, "band": "", "score": 0.0, "reason_tag": "",
                                    "rationale": "", "evidence": "", "factors": {}, "judged": judged}))
    rows.sort(key=lambda x: -x[1])
    return rows


def render(cfg: Config, extract_dir: Path, dossier_dir: Path | None, out_dir: Path, display_dir: Path | None = None,
           rank_dir: Path | None = None, data_dir: Path | None = None) -> dict:
    cats = {c.name: c for c in load_categories(cfg.categories_dir, computed=True)}
    _SIZE_CFG.update({"small": cfg.size_small, "medium": cfg.size_medium, "large": cfg.size_large})
    if cfg.repos:
        _REPO_URL["url"] = f"https://github.com/{cfg.repos[0].full_name}"
    recs: dict[int, dict] = {}
    if data_dir:
        from .dossier import load_extract
        from .ledgerview import build_view
        recs = load_extract(extract_dir, None)
        dossiers = build_view(cfg, data_dir, recs)
        recs = {n: recs[n] for n in dossiers}
    else:
        dossiers = load_latest(dossier_dir)
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
        if data_dir:
            with open(out_dir / "data" / f"dossier-{n}.json", "w") as f:
                json.dump(d, f, indent=1)
        else:
            shutil.copy(dossier_dir / str(n) / f"{(dossier_dir / str(n) / 'latest').read_text().strip()}.json", out_dir / "data" / f"dossier-{n}.json")
        shutil.copy(extract_dir / "prs" / f"{n}.json", out_dir / "data" / f"extract-{n}.json")
        for c in r["categories"]:
            if c["member"]:
                members.setdefault(c["name"], []).append((c["score"], n, c))
    for rows in members.values():
        rows.sort(key=lambda x: -x[0])
    for cat in cats.values():
        if cat.computed:
            members[cat.name] = computed_members(cat, members, dossiers, recs)
    rank_info: dict[str, dict] = {}
    for name, rows in members.items():
        rk = load_rank(rank_dir, name) if not (name in cats and cats[name].computed) else None
        if not rk:
            continue
        rank_info[name] = rk
        members[name] = merge_rank(rows, rk, dossiers)
    ranks: dict[int, dict[str, tuple[int, int]]] = {}
    merged: dict[tuple[str, int], dict] = {}  # (category, PR) -> the row's entry after the ranking merge
    for name, rows in members.items():
        for i, (_, n, c) in enumerate(rows, 1):
            ranks.setdefault(n, {})[name] = (i, len(rows))
            merged[(name, n)] = c
            if c.get("computed"):  # so the PR page's cards see the computed membership too
                dossiers[n]["result"]["categories"].append(c)
    _PR_CTX.update(pages={n for n, d in dossiers.items() if d.get("result") and n in recs}, prefix="pr/", self=None)
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
              '<div>Size: lines added or modified outside tests, then in tests; greener = smaller.</div></div>')
    nav = '<nav class="top"><a href="index.html">Home</a></nav>'
    repo_short = repo_url.replace("https://github.com/", "") if repo_url else ""
    pages = []
    for name, rows in sorted(members.items()):
        cat = cats.get(name)
        title = cat.title if cat else name
        computed = bool(cat and cat.computed)
        head = _table_head("Judged" if computed else "Priority")
        body_rows = "".join(_row(recs[n], dossiers[n], c, cats, displays.get(n), f"pr/{n}.html") for _, n, c in rows)
        covers = (f'<div class="covers"><div class="src">Category definition: <a href="{_e(cat_src(name))}">{_e(repo_short)}/categories/{_e(name)}.md</a>'
                  + (f' · editor <a href="https://github.com/{_e(cat.owner)}">{_e(cat.owner)}</a>' if cat.owner else "") + '</div>'
                  f'{md_to_html(cat.body)}</div>') if cat else ""
        if computed:
            listed = ", ".join(f'<a href="{_e(x)}.html">{_e(cats[x].title if x in cats else x)}</a>' for x in cat.not_in)
            callout = ('<div class="banner">This list is computed, not judged: it holds every assessed PR that the model placed in none of '
                       f'{listed}. Each row\'s Judged column says which categories were asked about the PR and what they answered. '
                       'A PR here may mean a definition has a gap, or may just be one that fits no category. '
                       'Every state and summary in the other columns is model output, shown with its rationale. Click a row to expand it.'
                       + (f' The list is defined in <a href="{_e(cat_src(name))}">{_e(repo_url.replace("https://github.com/", ""))}/categories/{_e(name)}.md</a>.' if repo_url else "") + '</div>')
        else:
            callout = ('<div class="banner">Every band, state, and summary on this page is model output against a '
                       'written category definition, shown with its rationale. It is an unofficial tool and does not speak for the '
                       'project. Click a row to expand it.'
                       + (f' The category definition lives in <a href="{_e(cat_src(name))}">{_e(repo_url.replace("https://github.com/", ""))}/categories/{_e(name)}.md</a>; '
                          'pull requests that improve it are welcome.' if repo_url else "") + '</div>')
        rk = rank_info.get(name)
        rank_block = ""
        rank_line = ""
        if rk:
            changes = [(n, c) for _, n, c in rows if c.get("rank_band") or c.get("rank_note")]
            _PR_CTX["prefix"] = "../pr/"
            notes_html = ('<div class="prpage">'
                          + (f'<h2>Category notes</h2><div class="box"><p>{_t(rk["notes"])}</p></div>' if rk["notes"] else "")
                          + (f'<h2>Review order and overlapping PRs</h2><div class="box">{_ul(rk["inconsistencies"])}</div>' if rk["inconsistencies"] else "")
                          + (f'<h2>Band and position changes</h2><div class="box">' + _ul(
                                (f'#{n}: {c["dossier_band"]} alone, {c["rank_band"]} after comparison. {c["rank_note"]}' if c.get("rank_band")
                                 else f'#{n}: {c["rank_note"]}') for n, c in changes) + '</div>' if changes else "")
                          + f'<h2>About</h2><div class="box"><p>This pass by {_e(rk["model"])} on {_e((rk["created"] or "")[:10])} saw every PR in the category at once and '
                            'checked the bands given to each PR alone against each other, ordered the PRs, and noted chains and overlaps. '
                            f'<a href="../{_e(name)}.html">Back to the category</a>.</p></div></div>')
            (out_dir / "rank").mkdir(exist_ok=True)
            _PR_CTX["prefix"] = "../pr/"
            (out_dir / "rank" / f"{name}.html").write_text(_page(f"{title}: ranking notes", notes_html,
                                                               nav='<nav class="top"><a href="../index.html">Home</a></nav>'))
            _PR_CTX["prefix"] = "pr/"
            n_notes = len(rk["inconsistencies"]) + len(changes)
            rank_line = (f'<div class="rankline">Ranking pass ({_e((rk["created"] or "")[:10])}): all PRs here were compared with each other; '
                         f'<a href="rank/{_e(name)}.html">{n_notes} notes on review order, overlaps, and band changes</a>.</div>')
        legend_here = legend + rank_line
        body = (head + body_rows + "</tbody></table>" + legend_here + covers
                + f'<div class="foot">{callout}<div class="sub" title="{len(rows)} PRs in this category, {len(dossiers)} assessed in total">generated {stamp}</div></div>')
        h1 = f'<a href="{_e(cat_src(name))}">{_e(title)}</a>'
        (out_dir / f"{name}.html").write_text(_page(f"{title}: {cfg.site_title}", body, nav=nav, h1=h1))
        pages.append(name)
    _PR_CTX["prefix"] = ""
    for n, d in dossiers.items():
        if not d.get("result") or n not in recs:
            continue
        _PR_CTX["self"] = n
        (out_dir / "pr" / f"{n}.html").write_text(_page(f"#{n} {recs[n]['title']}", _pr_page(recs[n], d, cats, displays.get(n), ranks.get(n, {}), legend, merged, set(rank_info)),
                                                          nav='<nav class="top"><a href="../index.html">Home</a></nav>'))
    _PR_CTX.update(prefix="pr/", self=None)
    repo_short = repo_url.replace("https://github.com/", "") if repo_url else ""
    default_intro = (
        "This site helps reviewers find pull requests to review in a category they care about. "
        "A language model sorts open pull requests into categories and ranks them against written category definitions. "
        "It is an unofficial tool and does not speak for the Bitcoin Core project."
        + (f' The definitions live in <a href="{_e(repo_url)}">{_e(repo_short)}</a> and can be changed by pull request. '
           'Anyone can volunteer to edit an existing category or create a new one.' if repo_url else ""))
    intro = '<div class="intro"><p>' + (_e(project["description"]) if project.get("description") else default_intro) + '</p></div>'
    def cat_item(name: str, note: str = "") -> str:
        return (f'<li><a href="{_e(name)}.html">{_e(cats[name].title if name in cats else name)}</a>'
                + f' <span class="editor">· {note}<a href="{_e(cat_src(name))}">definition</a>'
                + (f', editor <a href="https://github.com/{_e(cats[name].owner)}">{_e(cats[name].owner)}</a>' if name in cats and cats[name].owner else "") + '</span></li>')
    by_title = sorted(members, key=lambda name: (cats[name].title if name in cats else name).lower())
    catlist = '<ul class="catlist">' + "".join(cat_item(name) for name in by_title if not (name in cats and cats[name].computed)) + "</ul>"
    computed_names = [name for name in by_title if name in cats and cats[name].computed]
    if computed_names:
        catlist += ('<div class="intro"><p>Computed lists, not model output:</p></div><ul class="catlist">'
                    + "".join(cat_item(name, f'{len(members[name])} PRs · ') for name in computed_names) + "</ul>")
    engine_url = project.get("engine_url")
    feedback = ""
    if repo_url or engine_url:
        parts = []
        if repo_url:
            parts.append(f'<a href="{_e(repo_url)}/issues/new">open an issue in {_e(repo_short)}</a> about the information shown on category pages')
        if engine_url:
            parts.append(f'<a href="{_e(engine_url)}/issues/new">open an issue in {_e(engine_url.replace("https://github.com/", ""))}</a> about the site itself')
        feedback = ('<div class="intro"><p>Feedback of any kind, requests for help, and discussion are welcome: '
                    + ", or ".join(parts) + '.</p></div>')
    index = intro + catlist + feedback + f'<div class="foot rule"><div class="sub" title="{len(dossiers)} PRs assessed">generated {stamp} · <a href="status.html">pipeline status</a></div></div>'
    (out_dir / "index.html").write_text(_page(cfg.site_title, index))
    return {"pages": pages, "prs": len(dossiers), "out": str(out_dir), "display_files": sum(1 for v in displays.values() if v)}
