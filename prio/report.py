"""Render dossiers as markdown category tables for review.

A precursor to the HTML site: one table per category, rows sorted by
score, with the columns from the design (PR, size, reviewability, reviews,
agreement, band) and an expanded block per PR with the model's summary,
rationale, and evidence. Used to eyeball a run before anything is
published.
"""

from __future__ import annotations

import json
from pathlib import Path


def load_latest(dossier_dir: Path) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for d in dossier_dir.iterdir():
        if not d.is_dir() or not d.name.isdigit():
            continue
        latest = d / "latest"
        if not latest.exists():
            continue
        h = latest.read_text().strip()
        with open(d / f"{h}.json") as f:
            out[int(d.name)] = json.load(f)
    return out


def _reviews_cell(rec: dict) -> str:
    db = rec.get("bot", {}).get("drahtbot", {}).get("reviews", {})
    ack = len(db.get("ack", []))
    stale = len(db.get("stale_ack", []))
    nack = len(db.get("nack", [])) + len(db.get("concept_nack", [])) + len(db.get("approach_nack", []))
    s = str(ack)
    if stale:
        s += f" (+{stale})"
    if nack:
        s += f" **-{nack}**"
    return s


def render(extract_dir: Path, dossier_dir: Path, categories: list[str] | None = None, expand: bool = True) -> str:
    dossiers = load_latest(dossier_dir)
    recs: dict[int, dict] = {}
    for n in dossiers:
        p = extract_dir / "prs" / f"{n}.json"
        if p.exists():
            with open(p) as f:
                recs[n] = json.load(f)
    cats: dict[str, list[tuple[float, int, dict]]] = {}
    failed = []
    for n, d in dossiers.items():
        r = d.get("result")
        if not r:
            failed.append((n, d.get("error")))
            continue
        for c in r["categories"]:
            if c["member"]:
                cats.setdefault(c["name"], []).append((c["score"], n, c))
    lines = [f"# prio report ({len(dossiers)} PRs assessed, {len(cats)} categories)\n"]
    if failed:
        lines.append("Failed: " + ", ".join(f"#{n} ({e})" for n, e in failed) + "\n")
    total = sum(d.get("cost_usd") or 0 for d in dossiers.values())
    lines.append(f"Model cost for these dossiers: ${total:.2f}\n")
    for cat in sorted(cats):
        if categories and cat not in categories:
            continue
        rows = sorted(cats[cat], key=lambda x: -x[0])
        lines.append(f"\n## {cat} ({len(rows)} PRs)\n")
        lines.append("| Band | Score | PR | Size | Reviewability | Reviews | Agreement |")
        lines.append("|------|------:|----|------|---------------|---------|-----------|")
        for score, n, c in rows:
            r = recs.get(n, {})
            d = dossiers[n]["result"]
            title = (r.get("title") or "")[:70]
            size = f"+{r.get('additions')}/-{r.get('deletions')} {r.get('size_bucket', '')}"
            lines.append(f"| {c['band']} | {score:.2f} | [#{n}]({r.get('url')}) _{r.get('author')}_ {title} | {size} | "
                         f"{d['reviewability']['label']} | {_reviews_cell(r)} | {d['agreement']['state']} |")
        if expand:
            lines.append("")
            for score, n, c in rows:
                r = recs.get(n, {})
                d = dossiers[n]["result"]
                f = c["factors"]
                lines.append(f"\n### #{n} {r.get('title')}\n")
                lines.append(f"**{cat} {c['band']} ({score:.2f})** · factors: sec/stab {f['security_stability']}, bug {f['bug_severity']}, "
                             f"perf {f['performance']}, user {f['user_value']}, leverage {f['leverage']} · confidence {d['confidence']}\n")
                lines.append(f"- **Summary:** {d['summary']}")
                lines.append(f"- **Problem:** {d['problem']}")
                lines.append(f"- **Why this band:** {c['rationale']}")
                lines.append(f"- **Membership:** {c['evidence']}")
                lines.append(f"- **Reviewability:** {d['reviewability']['state']} ({d['reviewability']['label']}): {d['reviewability']['reason']}")
                lines.append(f"- **Agreement:** {d['agreement']['state']}: {d['agreement']['reason']}")
                for ev in d["agreement"]["evidence"]:
                    lines.append(f"  - {ev}")
                if d["discussion"]["open_concerns"]:
                    lines.append("- **Open concerns:** " + "; ".join(d["discussion"]["open_concerns"]))
                if d["dependencies"]["depends_on"] or d["dependencies"]["enables"]:
                    lines.append(f"- **Depends on:** {d['dependencies']['depends_on']} · **Enables:** {'; '.join(d['dependencies']['enables']) or 'nothing stated'}")
                lines.append(f"- **Author status:** {d['discussion']['author_status']}")
                if d["uncertainties"]:
                    lines.append("- **Uncertainties:** " + "; ".join(d["uncertainties"]))
                others = [f"{x['name']} {x['band']}" for x in d["categories"] if x["member"] and x["name"] != cat]
                if others:
                    lines.append("- **Also in:** " + ", ".join(others))
                lines.append(f"- **Card:** {d['card']}")
    return "\n".join(lines) + "\n"
