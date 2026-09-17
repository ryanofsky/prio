"""Status page: what the pipeline is doing, what it did, what it cost.

Written straight into the site directory by the pipeline at every stage
(so it updates while a run is in progress), from files the pipeline
already keeps: the current run's step marks, batch manifests, stored
model outputs with their cost, and the run logs. Needs no model call.
Batches still marked in progress are looked up on the API when a key is
available, so the page shows their real state.
"""

from __future__ import annotations

import glob
import html
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(p: Path) -> dict | None:
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def batch_rows(data_dir: Path, lookup: bool) -> list[dict]:
    rows = []
    client = None
    if lookup and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic
            client = anthropic.Anthropic()
        except Exception:
            client = None
    for stage in ("dossier", "display"):
        for p in sorted(glob.glob(str(data_dir / stage / "batches" / "msgbatch_*.json"))):
            m = _read_json(Path(p)) or {}
            row = {"stage": stage, "id": m.get("id"), "created": m.get("created"), "model": m.get("model"),
                   "requests": len(m.get("requests", [])), "status": m.get("status"),
                   "succeeded": m.get("succeeded"), "failed": m.get("failed"), "cost_usd": m.get("cost_usd")}
            if row["status"] != "collected" and client and row["id"]:
                try:
                    b = client.messages.batches.retrieve(row["id"])
                    row["status"] = f"{b.processing_status} (api)"
                    row["succeeded"] = b.request_counts.succeeded
                    row["failed"] = b.request_counts.errored
                    row["processing"] = b.request_counts.processing
                except Exception as e:  # network or auth problem: show the manifest state
                    row["status"] = f"{row['status']} (api lookup failed: {type(e).__name__})"
            rows.append(row)
    rows.sort(key=lambda r: r.get("created") or "", reverse=True)
    return rows


def spend(data_dir: Path) -> dict:
    """Cost by month from every stored model output (dossier, display, rank)."""
    by_month: dict[str, float] = {}
    n = 0
    for stage in ("dossier", "display", "rank"):
        for p in glob.glob(str(data_dir / stage / "*" / "*.json")):
            if "/batches/" in p:
                continue
            d = _read_json(Path(p))
            if not d or "cost_usd" not in d:
                continue
            month = (d.get("created") or "")[:7]
            by_month[month] = by_month.get(month, 0.0) + (d.get("cost_usd") or 0.0)
            n += 1
    return {"by_month": dict(sorted(by_month.items(), reverse=True)), "outputs": n}


def needs_summary(data_dir: Path) -> dict:
    """How often dossiers report each missing input, and low-confidence PRs."""
    needs: dict[str, int] = {}
    low = []
    total = 0
    for p in glob.glob(str(data_dir / "dossier" / "*" / "latest")):
        d = _read_json(Path(p).parent / f"{Path(p).read_text().strip()}.json") or {}
        r = d.get("result") or {}
        if not r:
            continue
        total += 1
        for x in r.get("needs") or []:
            needs[x] = needs.get(x, 0) + 1
        if r.get("confidence") == "low":
            low.append(int(Path(p).parent.name))
    return {"total": total, "needs": dict(sorted(needs.items(), key=lambda kv: -kv[1])), "low_confidence": sorted(low)}


def counts(data_dir: Path) -> dict:
    idx = _read_json(data_dir / "extract" / "index.json") or {}
    dossiers = len([p for p in glob.glob(str(data_dir / "dossier" / "*" / "latest"))])
    displays = len([p for p in glob.glob(str(data_dir / "display" / "*" / "latest"))])
    ranks = {}
    for p in glob.glob(str(data_dir / "rank" / "*" / "latest")):
        cat = Path(p).parent.name
        r = _read_json(Path(p).parent / f"{Path(p).read_text().strip()}.json") or {}
        ranks[cat] = (r.get("created") or "")[:16]
    return {"open_prs": idx.get("count"), "extracted_at": idx.get("extracted_at"), "dossiers": dossiers,
            "displays": displays, "ranked_categories": dict(sorted(ranks.items()))}


def current_run(data_dir: Path) -> list[tuple[str, str]]:
    p = data_dir / "status" / "current.log"
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        t, _, msg = line.partition(" ")
        out.append((t, msg))
    return out


def render(data_dir: Path, site_dir: Path, next_runs: str, lookup: bool = True, log_count: int = 10) -> dict:
    site_dir.mkdir(parents=True, exist_ok=True)
    steps = current_run(data_dir)
    batches = batch_rows(data_dir, lookup)
    sp = spend(data_dir)
    ct = counts(data_dir)
    ns = needs_summary(data_dir)
    logs = sorted(glob.glob(str(data_dir / "logs" / "*.log")), reverse=True)[:log_count]
    (site_dir / "status" / "logs").mkdir(parents=True, exist_ok=True)
    log_links = []
    for p in logs:
        dst = site_dir / "status" / "logs" / Path(p).name
        shutil.copy(p, dst)
        log_links.append(Path(p).name)
    now = _now()
    running = bool(steps) and not any(m.startswith("done") or m.startswith("FAILED") for _, m in steps)
    payload = {"generated": now.isoformat(timespec="seconds"), "running": running, "current_run": steps,
               "batches": batches, "spend": sp, "counts": ct, "needs": ns, "next_runs": next_runs, "logs": log_links}
    with open(site_dir / "status.json", "w") as f:
        json.dump(payload, f, indent=1)

    css = ("body{font-family:system-ui,sans-serif;max-width:60rem;margin:1.5rem auto;padding:0 1rem;color:#222}"
           "h1{font-size:1.3rem}h2{font-size:1.05rem;margin-top:1.4rem;border-bottom:1px solid #ddd}"
           "table{border-collapse:collapse;font-size:.9rem}td,th{border:1px solid #ddd;padding:.25rem .5rem;text-align:left}"
           ".ok{color:#2a7}.run{color:#c80}.bad{color:#b00020}.muted{color:#666;font-size:.85rem}")
    b = [f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
         f'<title>Status</title><style>{css}</style></head><body><nav><a href="index.html">Home</a></nav><h1>Pipeline status</h1>'
         f'<p class="muted">Generated {now.strftime("%Y-%m-%d %H:%M UTC")} by the pipeline itself; it rewrites this page at every stage. '
         f'Machine-readable: <a href="status.json">status.json</a>.</p>']
    b.append('<h2>Current or last run</h2>')
    if steps:
        state = '<span class="run">running</span>' if running else ('<span class="bad">failed</span>' if any(m.startswith("FAILED") for _, m in steps) else '<span class="ok">finished</span>')
        b.append(f'<p>State: {state}. Started {_e(steps[0][0])}.</p><table><tr><th>Time (UTC)</th><th>Step</th></tr>'
                 + "".join(f'<tr><td>{_e(t)}</td><td>{_e(m)}</td></tr>' for t, m in steps) + '</table>')
    else:
        b.append('<p>No run recorded yet.</p>')
    b.append(f'<h2>Schedule</h2><p>{_e(next_runs)}</p>')
    b.append('<h2>Batches (Anthropic Batch API)</h2><p class="muted">Model work is submitted as batches and collected when they end, usually within an hour, up to 24 hours.</p>')
    if batches:
        b.append('<table><tr><th>Stage</th><th>Created</th><th>Model</th><th>Requests</th><th>Status</th><th>OK</th><th>Failed</th><th>Cost</th></tr>'
                 + "".join(f'<tr><td>{_e(r["stage"])}</td><td>{_e((r["created"] or "")[:16])}</td><td>{_e(r["model"])}</td><td>{r["requests"]}</td>'
                           f'<td>{_e(r["status"])}{(" · " + str(r.get("processing")) + " processing") if r.get("processing") else ""}</td>'
                           f'<td>{_e(r["succeeded"] if r["succeeded"] is not None else "")}</td><td>{_e(r["failed"] if r["failed"] is not None else "")}</td>'
                           f'<td>{("$%.2f" % r["cost_usd"]) if r.get("cost_usd") is not None else ""}</td></tr>' for r in batches[:20]) + '</table>')
    else:
        b.append('<p>None.</p>')
    b.append('<h2>Spend (estimated from token usage, list prices)</h2><table><tr><th>Month</th><th>USD</th></tr>'
             + "".join(f'<tr><td>{_e(m)}</td><td>${v:.2f}</td></tr>' for m, v in sp["by_month"].items()) + f'</table><p class="muted">{sp["outputs"]} stored model outputs.</p>')
    b.append(f'<h2>Data</h2><table><tr><td>Open PRs extracted</td><td>{_e(ct["open_prs"])} at {_e((ct["extracted_at"] or "")[:16])}</td></tr>'
             f'<tr><td>PRs with a dossier</td><td>{ct["dossiers"]}</td></tr><tr><td>PRs with display lines</td><td>{ct["displays"]}</td></tr>'
             f'<tr><td>Categories ranked</td><td>{_e(", ".join(f"{k} ({v})" for k, v in ct["ranked_categories"].items()) or "none")}</td></tr></table>')
    if ns["total"]:
        b.append('<h2>What the model says it was missing</h2><p class="muted">From the <code>needs</code> field of each dossier; recurring items are data-source work.</p>'
                 + ('<table><tr><th>Missing input</th><th>Dossiers</th></tr>' + "".join(f'<tr><td>{_e(k)}</td><td>{v}</td></tr>' for k, v in ns["needs"].items()) + '</table>' if ns["needs"] else '<p>Nothing reported.</p>')
                 + (f'<p>Low-confidence assessments: {", ".join("#" + str(n) for n in ns["low_confidence"][:40])}</p>' if ns["low_confidence"] else ""))
    b.append('<h2>Run logs</h2>' + ('<ul>' + "".join(f'<li><a href="status/logs/{_e(n)}">{_e(n)}</a></li>' for n in log_links) + '</ul>' if log_links else '<p>None yet.</p>'))
    b.append('</body></html>')
    (site_dir / "status.html").write_text("".join(b))
    return {"running": running, "batches": len(batches), "out": str(site_dir / "status.html")}
