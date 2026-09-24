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
               dry_run: bool, prior_dir: Path | None, max_tokens: int = 16000, force: bool = False,
               as_of: str | None = None, run_kind: str = "", reads: int = 1, reread: bool = False,
               reread_budget: float = 0.0, reread_top: int = 5, order_file: Path | None = None) -> dict:
    """Thread reads for PRs with new or edited statements. Records read
    under an older schema (docs/schema-history.md) are re-read whole
    instead: with ``reread`` every PR in ``only``; otherwise, within
    ``reread_budget`` dollars (estimated, on the high side), first those in the top
    ``reread_top`` of any category in ``order_file`` (the last render's
    data/order.json), then those with new statements."""
    recs = load_extract(extract_dir, only)
    if as_of:
        recs = {n: ledger.as_of(r, as_of) for n, r in recs.items()}
    run = _run_id(run_kind)
    raw_dir = data_dir / "raw" / run.split(":", 1)[1]
    system = ledger.thread_system()
    ph = ledger.prompt_hash(system)
    manifest = {"id": run, "started": ledger._now(), "model": model, "prompt_hash": ph, "deltas": {}, "calls": [], "errors": [], "cost_usd": 0.0}
    client = None
    todo = []
    behind = {}  # n -> (record, d, path) for records below the current schema
    for n, rec in recs.items():
        path = ledger.record_path(data_dir, rec["repo"], n)
        record = ledger.load(path) or ledger.new_record(rec)
        if force:
            record = ledger.new_record(rec)
        d = ledger.delta(record, rec)
        if (record["processed"].get("schema_floor") or 1) < ledger.SCHEMA and not d["is_new"]:
            behind[n] = (record, d, path)
        if ledger.is_empty(d):
            continue
        manifest["deltas"][f"{rec['repo']}#{n}"] = {k: v for k, v in d.items() if v}
        if ledger.needs_thread_update(d):
            todo.append((n, rec, record, d, path))
        elif n not in behind:
            ledger.mark_processed(record, rec)  # a push or description change alone: nothing for the thread read
            ledger.save(path, record)
    picked = _pick_rereads(behind, recs, {n for n, *_ in todo}, reread, reread_budget, reread_top, order_file, model, reads)
    if picked:
        queued = {n for n, *_ in todo}
        for n in picked:
            record, d, path = behind[n]
            d["reread"] = True
            if n not in queued:
                todo.append((n, recs[n], record, d, path))
        manifest["rereads"] = {"prs": picked, "budget": reread_budget, "top": reread_top}
    for n, (record, d, path) in behind.items():  # below the schema, not re-read, only a push or description change
        if n not in picked and not ledger.is_empty(d) and not ledger.needs_thread_update(d):
            ledger.mark_processed(record, recs[n])
            ledger.save(path, record)
    print(f"{len(recs)} PRs, {len(manifest['deltas'])} with a delta, {len(todo)} thread reads ({len(picked)} re-reads; "
          f"{len(behind)} records below schema {ledger.SCHEMA})", file=sys.stderr)
    if dry_run:
        tot = 0
        for n, rec, record, d, _ in todo:
            _, user = ledger.build_thread_request(record, rec, d, _prior_text(prior_dir, n) if d["is_new"] else None)
            tot += len(user)
            print(f"  #{n}: {'seed' if d['is_new'] else 'reread' if d.get('reread') else 'update'}, {len(d['new'])} new, {len(d['edited'])} edited, user turn {len(user)} chars", file=sys.stderr)
        if todo:
            _, user = ledger.build_thread_request(todo[0][2], todo[0][1], todo[0][3], _prior_text(prior_dir, todo[0][0]) if todo[0][3]["is_new"] else None)
            print("\n===== SAMPLE USER TURN =====\n" + user[:5000] + ("\n...[truncated]" if len(user) > 5000 else ""))
        print(f"system ~{len(system[0]['text']) // 4} tokens; user turns ~{tot // 4} tokens total", file=sys.stderr)
        return {"dry_run": True, "reads": len(todo)}
    if not model.startswith("openrouter/"):
        client = _client()
    from .openrouter import run_many

    def one(job):
        n, rec, record, d, path = job
        sysm, user = ledger.build_thread_request(record, rec, d, _prior_text(prior_dir, n) if d["is_new"] else None)
        n_reads = reads if ((d["is_new"] or d.get("reread")) and reads > 1) else 1
        msgs, parsed_list, err = [], [], None
        try:
            for _ in range(n_reads):
                m_ = _call(model, sysm, user, effort, max_tokens, client)
                msgs.append(m_)
                parsed_list.append(json.loads(next((b.text for b in m_.content if b.type == "text"), "")))
        except Exception as e:
            err = str(e)[:300]
        return job, sysm, user, n_reads, msgs, parsed_list, err

    raw_dir.mkdir(parents=True, exist_ok=True)
    for res in run_many(todo, one):
        if isinstance(res, Exception):
            manifest["errors"].append(str(res)[:200]); continue
        (n, rec, record, d, path), sysm, user, n_reads, msgs, parsed_list, err = res
        stage = "seed" if d["is_new"] else "reread" if d.get("reread") else "thread"
        stem = f"{rec['repo'].replace('/', '-')}-{n}-{stage}"
        with open(raw_dir / f"{stem}.request.json", "w") as f:
            json.dump({"run": run, "pr": f"{rec['repo']}#{n}", "stage": stage, "model": model,
                       "prompt_hash": ph, "system_chars": len(sysm[0]["text"]), "user": user}, f, indent=1)
        msg = msgs[0] if msgs else None
        text = "\n\n=== second read ===\n\n".join(next((b.text for b in m_.content if b.type == "text"), "") for m_ in msgs)
        parsed = None
        if parsed_list and not err:
            parsed = parsed_list[0] if len(parsed_list) == 1 else ledger.merge_responses(parsed_list[0], parsed_list[1])
        cost = 0.0
        for m_ in msgs:
            c_ = getattr(m_.usage, "cost", None)
            cost += c_ if c_ is not None else cost_usd(model, m_.usage, False)
        report = None
        if parsed:
            ledger.mark_processed(record, rec, d["new"] + d["edited"])
            report = ledger.apply_thread_response(record, rec, d, parsed, run)
            ledger.mark_processed(record, rec)
            if d["is_new"] or d.get("reread"):
                record["processed"]["schema_floor"] = ledger.SCHEMA
            ledger.log_entry(record, run, d["new"] + d["edited"], report["changes"], cost or 0)
            ledger.save(path, record)
        with open(raw_dir / f"{stem}.response.json", "w") as f:
            json.dump({"run": run, "pr": f"{rec['repo']}#{n}", "stage": stage, "model": model, "reads": n_reads,
                       "created": ledger._now(), "stop_reason": getattr(msg, "stop_reason", None) if msg else None,
                       "usage": usage_dict(msg.usage) if msg else None, "cost_usd": cost, "error": err,
                       "raw_text": text, "result": parsed, "applied": report}, f, indent=1)
        manifest["calls"].append({"pr": f"{rec['repo']}#{n}", "stage": stage, "cost_usd": cost, "error": err,
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


def _pick_rereads(behind: dict, recs: dict, active: set[int], explicit: bool, budget: float, top: int,
                  order_file: Path | None, model: str, reads: int) -> list[int]:
    """Which records below the current schema to re-read this run. With
    ``explicit``, all of them. Otherwise within ``budget`` (an estimate from
    each request's length at list prices, times the reads per request):
    records in the top ``top`` of a category on the last render first, by
    best position, then records with new statements, by PR number."""
    if explicit:
        return sorted(behind)
    if budget <= 0 or not behind:
        return []
    best: dict[int, int] = {}
    if order_file and order_file.exists():
        with open(order_file) as f:
            for rows in json.load(f).values():
                for pos, n in enumerate(rows[:top]):
                    best[n] = min(best.get(n, pos), pos)
    order = sorted((n for n in behind if n in best), key=lambda n: (best[n], n)) + sorted(n for n in behind if n in active and n not in best)
    from .openrouter import is_openrouter, prices
    system = ledger.thread_system()[0]["text"]
    # Per read: input from characters/3.5; output (reasoning included) about 1.1x the input, measured
    # on the first re-reads (2026-09-24: 0.2x to 1.2x, cost $0.04 to $0.17 a PR with two reads).
    pin, pout = (prices(model) if is_openrouter(model) else None) or (0.75, 3.75)
    picked, spent = [], 0.0
    for n in order:
        record, d, _ = behind[n]
        _, user = ledger.build_thread_request(record, recs[n], dict(d, reread=True))
        tin = (len(system) + len(user)) / 3.5
        est = (tin * pin + 1.1 * tin * pout) / 1e6 * max(reads, 1)
        if spent + est > budget:
            continue
        picked.append(n); spent += est
    print(f"re-reads: {len(picked)} of {len(order)} candidates, estimated ${spent:.2f} of ${budget:.2f}", file=sys.stderr)
    return picked


def cmd_migrate(data_dir: Path, dry_run: bool = False) -> dict:
    """Rewrite every record at an older schema (``ledger.upgrade_v1``).
    The rewrite changes how claims are stored, not what they say, so a
    category judgment whose ``from.claims_digest`` matches the record
    before the rewrite is updated to match it after, rather than being
    judged again. Idempotent; runs before each ledger update."""
    import glob
    from . import stages
    records = judgments = marked = 0
    statuses: dict[str, int] = {}
    for p in sorted(glob.glob(str(data_dir / "*" / "*" / "prs" / "*.json")) + glob.glob(str(data_dir / "*" / "*" / "prs" / "closed" / "*.json"))):
        with open(p) as f:
            raw = json.load(f)
        if raw.get("schema") == ledger.SCHEMA:
            if ledger.add_markers(raw):
                marked += 1
                if not dry_run:
                    ledger.save(Path(p), raw)
            continue
        if raw.get("schema") != 1:
            continue
        old = stages.claims_digest_v1(raw)
        ledger.upgrade_v1(raw)
        ledger.add_markers(raw)
        new = stages.claims_digest(raw)
        for c in raw["claims"]:
            k = f"{c['clears_with']}/{c['status']}"
            statuses[k] = statuses.get(k, 0) + 1
        records += 1
        repo_dir = Path(p).parent.parent if Path(p).parent.name == "prs" else Path(p).parent.parent.parent
        for jp in glob.glob(str(repo_dir / "*categories" / "*" / f"{raw['number']}.json")):
            with open(jp) as f:
                j = json.load(f)
            if (j.get("from") or {}).get("claims_digest") == old and old != new:
                j["from"]["claims_digest"] = new
                judgments += 1
                if not dry_run:
                    stages._save(Path(jp), j)
        if not dry_run:
            ledger.save(Path(p), raw)
    print(f"{records} records migrated, {judgments} judgments carried over, {marked} given schema markers" + (" (dry run)" if dry_run else ""), file=sys.stderr)
    return {"records": records, "judgments": judgments, "marked": marked, "claims": dict(sorted(statuses.items())), "dry_run": dry_run}


def cmd_show(data_dir: Path, repo: str, n: int) -> str:
    record = ledger.load(ledger.record_path(data_dir, repo, n))
    if not record:
        return f"no record for {repo}#{n}\n"
    head = (f"{repo}#{n}: updated {record.get('updated')}; processed {len(record['processed']['events'])} statements, "
            f"head {(record['processed']['head_sha'] or '')[:10]}, patch-id {record['processed']['patch_id']}\n")
    state, why = ledger.derive_agreement(record)
    return (head + ledger.compact_view(record) + "\n" + ("notes: " + record["notes"] + "\n" if record.get("notes") else "")
            + f"derived agreement: {state} ({why})\n")
