"""Stage 3: one listwise call per category to make bands consistent.

Dossiers judge each PR alone. This stage shows the model every member PR
of a category at once (a short card each) and asks for consistent bands,
an order from most to least worth reviewing, one-line reasons for any
band it changes, and inconsistencies the order cannot express. Output is
``rank/<category>/<timestamp>.json`` plus a ``latest`` pointer; the
renderer uses it for row order and bands when present.

Run on demand (``prio rank submit --sync``) or in batch. Not scheduled
until its results have been looked at.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .categories import load_categories
from .config import Config
from .dossier import ENGINE_ROOT, _client, load_extract, dossier_stem
from .prices import cost_usd, usage_dict
from .report import load_latest

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["ranking", "inconsistencies", "notes"],
    "properties": {
        "ranking": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["number", "band", "position", "note"],
            "properties": {
                "number": {"type": "integer"},
                "band": {"type": "string", "enum": ["P1", "P2", "P3", "P4", "Unranked"]},
                "position": {"type": "integer", "description": "1 = most worth reviewing in this category"},
                "note": {"type": "string", "description": "one line: why the band changed, or why the position differs by five or more from its position by score; empty otherwise"},
            },
        }},
        "inconsistencies": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string", "description": "anything about the category as a whole, or empty"},
    },
}


def build_system(cat) -> list[dict]:
    parts = [(ENGINE_ROOT / "prompts" / "rank.md").read_text().strip()]
    for name in ("priority.md", "bands.md"):
        parts.append(f"# Definition: {name}\n\n" + (ENGINE_ROOT / "definitions" / name).read_text().strip())
    parts.append(f"# Category: {cat.name} ({cat.title})\n\n" + cat.body)
    return [{"type": "text", "text": "\n\n---\n\n".join(parts), "cache_control": {"type": "ephemeral"}}]


def cards(cat_name: str, recs: dict, dossiers: dict, displays: dict) -> list[tuple[int, str]]:
    out = []
    scored = []
    for n, d in dossiers.items():
        r = d.get("result")
        c = r and next((c for c in r["categories"] if c["name"] == cat_name and c["member"]), None)
        if c and n in recs:
            scored.append((-(c["score"] or 0), n))
    alone_pos = {n: i + 1 for i, (_, n) in enumerate(sorted(scored))}
    for n, d in dossiers.items():
        r = d.get("result")
        if not r or n not in recs:
            continue
        c = next((c for c in r["categories"] if c["name"] == cat_name and c["member"]), None)
        if not c:
            continue
        disp = displays.get(n) or {}
        why = next((x["why"] for x in disp.get("categories", []) if x.get("name") == cat_name), [])
        goal = disp.get("goal") or []
        text = (f"#{n} {recs[n]['title']} (by {recs[n]['author']})\n"
                f"Assessed alone: {c['band']}" + (f" · {c.get('reason_tag')}" if c.get("reason_tag") else "")
                + f", position {alone_pos.get(n, '?')} of {len(alone_pos)} by its score\n"
                + ("Goal: " + " ".join(goal) + "\n" if goal else "")
                + ("Why: " + " ".join(why) + "\n" if why else "")
                + "Card: " + r["card"])
        out.append((n, text))
    return out


def build_user(cat, items: list[tuple[int, str]]) -> str:
    body = "\n\n".join(t for _, t in items)
    return (f"Category: {cat.name}. {len(items)} PRs. Return a ranking entry for every one of them.\n\n"
            f"<cards>\n{body}\n</cards>")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run(cfg: Config, extract_dir: Path, dossier_dir: Path | None, display_dir: Path | None, out_dir: Path,
        only: set[str] | None, model: str, effort: str, dry_run: bool, force: bool = False, data_dir: Path | None = None) -> dict:
    from .render import load_display
    cats = [c for c in load_categories(cfg.categories_dir) if not only or c.name in only]
    recs = load_extract(extract_dir, None)
    if data_dir:
        from .ledgerview import build_view
        dossiers = build_view(cfg, data_dir, recs)
    else:
        dossiers = load_latest(dossier_dir)
    displays = {n: load_display(display_dir, n, d) for n, d in dossiers.items()}
    client = _client()
    total = 0.0
    summary = {}
    for cat in cats:
        items = cards(cat.name, recs, dossiers, displays)
        if not items:
            continue
        # Skip a category whose members and dossiers are unchanged since its last ranking.
        latest = out_dir / cat.name / "latest"
        if latest.exists() and not force:
            with open(out_dir / cat.name / f"{latest.read_text().strip()}.json") as f:
                prev = json.load(f)
            if prev.get("dossier_hashes") == {str(n): dossier_stem(dossiers[n]) for n, _ in items}:
                print(f"  {cat.name}: unchanged since {prev.get('created', '')[:10]}, skipped", file=sys.stderr)
                summary[cat.name] = {"prs": len(items), "skipped": True}
                continue
        system = build_system(cat)
        user = build_user(cat, items)
        if dry_run:
            t = client.messages.count_tokens(model=model, system=system, messages=[{"role": "user", "content": user}]).input_tokens
            print(f"  {cat.name}: {len(items)} PRs, ~{t} input tokens", file=sys.stderr)
            summary[cat.name] = {"prs": len(items), "input_tokens": t}
            continue
        # Streaming: the SDK refuses non-streaming requests that may run past
        # ten minutes, which a 48k-token cap over a large category can.
        with client.messages.stream(model=model, max_tokens=48000, system=system,
                                    messages=[{"role": "user", "content": user}],
                                    output_config={"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}}) as stream:
            msg = stream.get_final_message()
        text = next((b.text for b in msg.content if b.type == "text"), "")
        parsed = json.loads(text) if msg.stop_reason != "refusal" else None
        cost = cost_usd(model, msg.usage, False) or 0
        total += cost
        d = out_dir / cat.name
        d.mkdir(parents=True, exist_ok=True)
        stamp = _now()
        payload = {"category": cat.name, "created": stamp, "model": model, "effort": effort,
                   "inputs": sorted(n for n, _ in items), "dossier_hashes": {str(n): dossier_stem(dossiers[n]) for n, _ in items},
                   "usage": usage_dict(msg.usage), "cost_usd": cost, "stop_reason": msg.stop_reason, "result": parsed}
        fname = stamp.replace(":", "").replace("+00:00", "Z")
        with open(d / f"{fname}.json", "w") as f:
            json.dump(payload, f, indent=1)
        (d / "latest").write_text(fname + "\n")
        changed = sum(1 for e in (parsed or {}).get("ranking", []) if e["note"])
        print(f"  {cat.name}: {len(items)} PRs, {changed} band changes, {len((parsed or {}).get('inconsistencies', []))} inconsistencies, ${cost:.3f}", file=sys.stderr)
        summary[cat.name] = {"prs": len(items), "band_changes": changed, "cost_usd": round(cost, 3)}
    if not dry_run:
        print(f"total ${total:.3f}", file=sys.stderr)
    return {"categories": summary, "cost_usd": round(total, 3)}
