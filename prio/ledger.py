"""The ledger: one record of facts per PR, updated from deltas.

A record holds what the pipeline has established about a PR's discussion
(participants, claims, support) and what it has processed (event ids with
body hashes, the head and patch-id, the description hash). Everything
that depends on category or definition text lives elsewhere (see
ledger-design.md in the notes repo): this file never stores a band or an
Agreement state.

Records live in the data repo at ``<data>/<owner>/<repo>/prs/<n>.json``.
They are written only by the pipeline; a human correction arrives as a
feedback entry and is applied here with a pin.

This module covers step 1 of the plan: the record shape, loading and
saving, and delta detection against an extract record. The model-facing
parts (compact view, applying a thread-update response) come next.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 1
CLAIM_KINDS = ["safety", "correctness", "approach", "scope", "interface", "maintenance", "usefulness", "style"]
CLAIM_STATUS = ["open", "resolved", "agreed_to_disagree"]
STANCES = ["objection", "support", "question", "neutral"]
HISTORY_LIMIT = 50
LOG_LIMIT = 50

# Timeline kinds that are statements by people and can anchor a claim.
STATEMENT_KINDS = ("comment", "review", "review_comment")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_path(data_dir: Path, repo: str, n: int, closed: bool = False) -> Path:
    owner, name = repo.split("/", 1)
    return data_dir / owner / name / "prs" / ("closed" if closed else "") / f"{n}.json"


def new_record(rec: dict) -> dict:
    """An empty record for a PR the ledger has not seen: nothing processed."""
    return {
        "schema": SCHEMA,
        "repo": rec["repo"],
        "number": rec["number"],
        "updated": None,
        "processed": {"head_sha": None, "patch_id": None, "description_hash": None, "events": {}, "last_event_at": None},
        "participants": [],
        "claims": [],
        "support": [],
        "log": [],
    }


def load(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path) as f:
        r = json.load(f)
    if r.get("schema") != SCHEMA:
        raise ValueError(f"{path}: schema {r.get('schema')}, expected {SCHEMA}")
    return r


def save(path: Path, record: dict) -> None:
    """Pretty-printed with sorted keys so diffs in the data repo are readable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    record["claims"].sort(key=lambda c: (c.get("at") or "", c.get("id") or ""))
    record["support"].sort(key=lambda c: (c.get("at") or "", c.get("id") or ""))
    record["participants"].sort(key=lambda p: (p.get("first") or "", p.get("login") or ""))
    with open(path, "w") as f:
        json.dump(record, f, indent=1, sort_keys=True)
        f.write("\n")


def statements(rec: dict) -> list[dict]:
    """Timeline events that are statements by people, with identity."""
    return [e for e in rec["timeline"] if e.get("kind") in STATEMENT_KINDS and e.get("id")]


def delta(record: dict, rec: dict) -> dict:
    """What the extract record ``rec`` contains that ``record`` has not
    processed. Pure; nothing is modified.

    - ``new``: statement ids not in processed.events
    - ``edited``: statement ids whose body hash changed since processing
    - ``removed``: processed ids no longer in the extract (deleted comments)
    - ``description_changed``, ``patch_changed``, ``head_changed``
    - ``rebase_only``: the head moved but the diff did not
    - ``is_new``: the record has processed nothing yet
    """
    seen = record["processed"]["events"]
    new, edited, present = [], [], set()
    for e in statements(rec):
        present.add(e["id"])
        h = seen.get(e["id"])
        if h is None:
            new.append(e["id"])
        elif h != e.get("hash"):
            edited.append(e["id"])
    removed = sorted(set(seen) - present)
    p = record["processed"]
    head_changed = bool(rec.get("head_sha")) and p["head_sha"] != rec["head_sha"]
    patch_changed = bool(rec.get("patch_id")) and p["patch_id"] != rec["patch_id"]
    return {
        "is_new": p["last_event_at"] is None and not seen,
        "new": new,
        "edited": edited,
        "removed": removed,
        "description_changed": bool(rec.get("description_hash")) and p["description_hash"] != rec["description_hash"],
        "head_changed": head_changed,
        "patch_changed": patch_changed,
        "rebase_only": head_changed and not patch_changed and p["patch_id"] is not None,
    }


def is_empty(d: dict) -> bool:
    return not (d["new"] or d["edited"] or d["removed"] or d["description_changed"] or d["patch_changed"] or d["head_changed"])


def needs_thread_update(d: dict) -> bool:
    return bool(d["new"] or d["edited"] or d["removed"])


def needs_code_assessment(d: dict) -> bool:
    return bool(d["patch_changed"] or d["description_changed"])


def mark_processed(record: dict, rec: dict, event_ids: list[str] | None = None) -> None:
    """Record that the statements in ``event_ids`` (default: all) and the
    current head, patch-id, and description have been processed."""
    p = record["processed"]
    ids = set(event_ids) if event_ids is not None else None
    last = p["last_event_at"]
    for e in statements(rec):
        if ids is None or e["id"] in ids:
            p["events"][e["id"]] = e.get("hash")
            if e.get("t") and (last is None or e["t"] > last):
                last = e["t"]
    present = {e["id"] for e in statements(rec)}
    for gone in [k for k in p["events"] if k not in present]:
        del p["events"][gone]
    p["last_event_at"] = last
    p["head_sha"] = rec.get("head_sha")
    p["patch_id"] = rec.get("patch_id")
    p["description_hash"] = rec.get("description_hash")
    record["updated"] = _now()


def log_entry(record: dict, run: str, events: list[str], changes: list[str], cost_usd: float = 0.0) -> None:
    record["log"].append({"run": run, "at": _now(), "events": events, "changes": changes, "cost_usd": round(cost_usd, 5)})
    del record["log"][:-LOG_LIMIT]


def validate(record: dict) -> list[str]:
    """Structural problems in a record; empty means fine."""
    errs = []
    for k in ("schema", "repo", "number", "processed", "participants", "claims", "support", "log"):
        if k not in record:
            errs.append(f"missing {k}")
    if errs:
        return errs
    seen = set(record["processed"]["events"])
    for c in record["claims"]:
        for k in ("id", "author", "kind", "harm", "status", "blocking"):
            if k not in c:
                errs.append(f"claim {c.get('id')}: missing {k}")
        if c.get("id") not in seen:
            errs.append(f"claim {c.get('id')}: anchor not a processed event")
        if c.get("kind") not in CLAIM_KINDS:
            errs.append(f"claim {c.get('id')}: kind {c.get('kind')}")
        if c.get("status") not in CLAIM_STATUS:
            errs.append(f"claim {c.get('id')}: status {c.get('status')}")
        if c.get("status") != "open" and not c.get("settled_by") and not c.get("pin"):
            errs.append(f"claim {c.get('id')}: {c.get('status')} without settled_by")
    for x in record["support"]:
        if x.get("id") not in seen:
            errs.append(f"support {x.get('id')}: anchor not a processed event")
    for p in record["participants"]:
        if p.get("stance") not in STANCES:
            errs.append(f"participant {p.get('login')}: stance {p.get('stance')}")
    return errs
