"""``prio ledger``: update PR records from an extract (step 2: thread reads).

    prio ledger update --extract E --data D [--only ...] [--model M] [--dry-run] [--prior DOSSIER_DIR]
    prio ledger show --data D N

Per PR: load or create the record, compute the delta, and if there are
new or edited statements build the thread request, call the model, apply
the response with the checks, mark the statements processed, and save.
Every call's request and response are written under
``<data>/raw/<run-id>/``. Code assessment and judgments (steps 3 and 4)
are not here yet; the delta's patch and description flags are recorded
in the run manifest so nothing is lost.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import ledger
from .config import Config
from .dossier import load_extract, _client, request_params
from .prices import cost_usd, usage_dict


def _run_id(kind: str = "") -> str:
    return "run:" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M") + (f"-{kind}" if kind else "")


def _prior_text(prior_dir: Path | None, n: int) -> str | None:
    """The old dossier's discussion state, as a prior for a seed read."""
    if not prior_dir:
        return None
    latest = prior_dir / str(n) / "latest"
    if not latest.exists():
        return None
    try:
        with open(prior_dir / str(n) / f"{latest.read_text().strip()}.json") as f:
            r = json.load(f).get("result") or {}
    except (OSError, json.JSONDecodeError):
        return None
    out = []
    disc = r.get("discussion") or {}
    for k in ("open_concerns", "resolved_concerns"):
        for x in disc.get(k) or []:
            out.append(f"- {k.replace('_', ' ')}: {x}")
    ag = r.get("agreement") or {}
    for o in ag.get("objections") or []:
        out.append(f"- objection by {o.get('reviewer')} ({o.get('status')}): {o.get('harm') or ''} [{(o.get('evidence') or '')[:160]}]")
    for s in ag.get("support") or []:
        out.append(f"- support by {s.get('reviewer')}: {(s.get('reason') or '')[:160]}")
    for x in ag.get("evidence") or []:
        out.append(f"- {x}")
    return "\n".join(out) or None


def _call(model: str, system: list[dict], user: str, effort: str, max_tokens: int, client=None):
    from .openrouter import is_openrouter, chat
    if is_openrouter(model):
        return chat(model, system, user, ledger.THREAD_SCHEMA, max_tokens)
    return client.messages.create(**request_params(model, system, user, effort, max_tokens, ledger.THREAD_SCHEMA))


def cmd_update(cfg: Config, extract_dir: Path, data_dir: Path, only: set[int] | None, model: str, effort: str,
               dry_run: bool, prior_dir: Path | None, max_tokens: int = 16000, force: bool = False) -> dict:
    recs = load_extract(extract_dir, only)
    run = _run_id()
    raw_dir = data_dir / "raw" / run.split(":", 1)[1]
    system = ledger.thread_system()
    ph = ledger.prompt_hash(system)
    manifest = {"id": run, "started": ledger._now(), "model": model, "prompt_hash": ph, "deltas": {}, "calls": [], "errors": [], "cost_usd": 0.0}
    client = None
    todo = []
    for n, rec in recs.items():
        path = ledger.record_path(data_dir, rec["repo"], n)
        record = ledger.load(path) or ledger.new_record(rec)
        if force:
            record = ledger.new_record(rec)
        d = ledger.delta(record, rec)
        if ledger.is_empty(d):
            continue
        manifest["deltas"][f"{rec['repo']}#{n}"] = {k: v for k, v in d.items() if v}
        if ledger.needs_thread_update(d):
            todo.append((n, rec, record, d, path))
        else:
            ledger.mark_processed(record, rec)  # a push or description change alone: nothing for the thread read
            ledger.save(path, record)
    print(f"{len(recs)} PRs, {len(manifest['deltas'])} with a delta, {len(todo)} thread reads", file=sys.stderr)
    if dry_run:
        tot = 0
        for n, rec, record, d, _ in todo:
            _, user = ledger.build_thread_request(record, rec, d, _prior_text(prior_dir, n))
            tot += len(user)
            print(f"  #{n}: {'seed' if d['is_new'] else 'update'}, {len(d['new'])} new, {len(d['edited'])} edited, user turn {len(user)} chars", file=sys.stderr)
        if todo:
            _, user = ledger.build_thread_request(todo[0][2], todo[0][1], todo[0][3], _prior_text(prior_dir, todo[0][0]))
            print("\n===== SAMPLE USER TURN =====\n" + user[:5000] + ("\n...[truncated]" if len(user) > 5000 else ""))
        print(f"system ~{len(system[0]['text']) // 4} tokens; user turns ~{tot // 4} tokens total", file=sys.stderr)
        return {"dry_run": True, "reads": len(todo)}
    if not model.startswith("openrouter/"):
        client = _client()
    for n, rec, record, d, path in todo:
        sysm, user = ledger.build_thread_request(record, rec, d, _prior_text(prior_dir, n))
        stem = f"{rec['repo'].replace('/', '-')}-{n}-{'seed' if d['is_new'] else 'thread'}"
        raw_dir.mkdir(parents=True, exist_ok=True)
        with open(raw_dir / f"{stem}.request.json", "w") as f:
            json.dump({"run": run, "pr": f"{rec['repo']}#{n}", "stage": "seed" if d["is_new"] else "thread", "model": model,
                       "prompt_hash": ph, "system_chars": len(sysm[0]["text"]), "user": user}, f, indent=1)
        try:
            msg = _call(model, sysm, user, effort, max_tokens, client)
            text = next((b.text for b in msg.content if b.type == "text"), "")
            parsed = json.loads(text)
            err = None
        except Exception as e:
            msg, text, parsed, err = None, "", None, str(e)[:300]
        cost = (getattr(msg.usage, "cost", None) if msg else None)
        if msg and cost is None:
            cost = cost_usd(model, msg.usage, False)
        report = None
        if parsed:
            ledger.mark_processed(record, rec, d["new"] + d["edited"])
            report = ledger.apply_thread_response(record, rec, d, parsed, run)
            ledger.mark_processed(record, rec)
            ledger.log_entry(record, run, d["new"] + d["edited"], report["changes"], cost or 0)
            ledger.save(path, record)
        with open(raw_dir / f"{stem}.response.json", "w") as f:
            json.dump({"run": run, "pr": f"{rec['repo']}#{n}", "stage": "seed" if d["is_new"] else "thread", "model": model,
                       "created": ledger._now(), "stop_reason": getattr(msg, "stop_reason", None) if msg else None,
                       "usage": usage_dict(msg.usage) if msg else None, "cost_usd": cost, "error": err,
                       "raw_text": text, "result": parsed, "applied": report}, f, indent=1)
        manifest["calls"].append({"pr": f"{rec['repo']}#{n}", "stage": "seed" if d["is_new"] else "thread", "cost_usd": cost, "error": err,
                                  "changes": len(report["changes"]) if report else 0, "rejected": len(report["rejected"]) if report else 0,
                                  "checks": len(report["checks"]) if report else 0})
        manifest["cost_usd"] += cost or 0
        if err:
            manifest["errors"].append(f"#{n}: {err}")
        summary = "ERROR " + err if err else f"{len(report['changes'])} changes, {len(report['rejected'])} rejected, {len(report['checks'])} checks"
        print(f"  #{n}: {summary} ${(cost or 0):.4f}", file=sys.stderr)
    manifest["ended"] = ledger._now()
    (data_dir / "runs").mkdir(parents=True, exist_ok=True)
    with open(data_dir / "runs" / f"{run.split(':', 1)[1]}.json", "w") as f:
        json.dump(manifest, f, indent=1)
    print(f"total ${manifest['cost_usd']:.4f}; manifest runs/{run.split(':', 1)[1]}.json", file=sys.stderr)
    return {"run": run, "reads": len(todo), "cost_usd": round(manifest["cost_usd"], 4), "errors": len(manifest["errors"])}


def cmd_show(data_dir: Path, repo: str, n: int) -> str:
    record = ledger.load(ledger.record_path(data_dir, repo, n))
    if not record:
        return f"no record for {repo}#{n}\n"
    head = (f"{repo}#{n}: updated {record.get('updated')}; processed {len(record['processed']['events'])} statements, "
            f"head {(record['processed']['head_sha'] or '')[:10]}, patch-id {record['processed']['patch_id']}\n")
    state, why = ledger.derive_agreement(record)
    return (head + ledger.compact_view(record) + "\n" + ("notes: " + record["notes"] + "\n" if record.get("notes") else "")
            + f"derived agreement: {state} ({why})\n")
