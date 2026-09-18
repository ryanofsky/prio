"""A dossier-shaped view of the ledger, so the display stage, the ranking
pass, and the renderer read the data layout without knowing it.

``build_view`` returns ``{n: payload}`` where each payload has the keys
those stages take from a stored dossier (``result``, ``input_hash``,
``model``, ``prompt_hash``, ``created``), and ``result`` has the fields of
the dossier schema they read: summary, problem, card, discussion,
reviewability, agreement (with objections/support/participants in the
shape the PR page renders), dependencies, categories (from the
judgments), confidence, uncertainties, needs.

Agreement and Reviewability are computed here, at view time, from the
record, the extract's signals, and the config thresholds; nothing in the
data layout stores them. ``input_hash`` is a digest of what the view was
built from, so the ranking pass's skip-unchanged check and the display
stage's keying work as before.
"""

from __future__ import annotations

import glob
import hashlib
import json
from pathlib import Path

from . import ledger
from .categories import load_categories
from .config import Config
from .stages import _load, code_path, judgment_path


def derive_reviewability(rec: dict, record: dict, cfg: Config) -> dict:
    """Ready / Paused / Stale from the signals and the record, per
    definitions/reviewability.md: Paused when a material reviewer request
    has waited on the author longer than the threshold; Stale when the
    author has been silent longer than the stale threshold; otherwise
    Ready, with a label naming the first thing a reviewer should know."""
    sig = rec.get("signals") or {}
    silent = sig.get("author_silent_days") or 0
    waiting = sig.get("waiting_on_author_days") or 0
    unanswered = [c for c in record["claims"] if c.get("status") == "open" and not c.get("author_replies")]
    if unanswered and waiting >= cfg.waiting_on_author_days:
        who = ", ".join(sorted({c["author"] for c in unanswered})[:3])
        return {"state": "Paused", "label": "Waiting on author",
                "reason": f"Open objection{'s' if len(unanswered) > 1 else ''} from {who} with no author reply for {waiting} days; review would repeat what has been asked."}
    if silent >= cfg.stale_author_silent_days:
        return {"state": "Stale", "label": f"Author silent {silent}d",
                "reason": f"No author activity for {silent} days; a review may wait a long time for a response."}
    based_on = [b for b in (rec.get("stack") or {}).get("based_on") or []]
    if based_on:
        first = based_on[0] if isinstance(based_on[0], int) else (based_on[0].get("number") if isinstance(based_on[0], dict) else None)
        if first:
            return {"state": "Ready", "label": f"Review #{first} first", "reason": f"Stacked on #{first}; the base PR's changes are included in this diff."}
    if sig.get("needs_rebase"):
        return {"state": "Ready", "label": "Needs rebase", "reason": "Conflicts with master; review the logic now, the rebase is mechanical."}
    if sig.get("ci_failed"):
        return {"state": "Ready", "label": "CI failing", "reason": "CI is red; check whether the failure is the PR's before a deep review."}
    return {"state": "Ready", "label": "Ready", "reason": "Nothing known that would invalidate a review now."}


def _agreement(record: dict) -> dict:
    state, why = ledger.derive_agreement(record)
    open_claims = [c for c in record["claims"] if c.get("status") == "open"]
    lines = []
    for c in open_claims:
        lines.append(f"{c['author']} ({c['kind']}, {'blocking' if c.get('blocking') else 'nonblocking'}{', no author reply' if not c.get('author_replies') else ''}): {c.get('harm') or ''}")
    for s in record["support"]:
        lines.append(f"{s['author']}: {s.get('verdict') or 'support'}{' — ' + s['reason'] if s.get('reason') else ''}")
    objections = [{"reviewer": c["author"], "kind": c.get("kind"), "harm": c.get("harm") or "", "blocking": bool(c.get("blocking")),
                   "author_replied": bool(c.get("author_replies")), "fix_pushed": bool(c.get("fix")), "status": c.get("status"),
                   "evidence": f"{c.get('at')}: '{c.get('quote') or ''}'", "url": c.get("url"), "id": c["id"],
                   "resolution_evidence": (f"{c['settled_by'].get('at')}: {c['settled_by'].get('by')}: '{c['settled_by'].get('quote', '')}'" if c.get("settled_by") else ""),
                   "pin": c.get("pin")} for c in record["claims"]]
    support = [{"reviewer": s["author"], "reason": s.get("reason") or "", "substantive": bool(s.get("substantive")), "verdict": s.get("verdict") or "", "id": s["id"], "url": s.get("url")}
               for s in record["support"]]
    participants = [{"login": p["login"], "stance": p.get("stance"), "note": p.get("note") or ""} for p in record["participants"]]
    summary = f"{state}: {why}"
    return {"state": state, "summary": summary, "reason": why + ".", "evidence": lines, "objections": objections, "support": support,
            "participants": participants, "derivation": why, "model_state": None, "corrections": [], "notes": record.get("notes")}


def _discussion(record: dict) -> dict:
    open_c = [f"{c['author']}: {c.get('harm') or c.get('quote') or ''}" for c in record["claims"] if c.get("status") == "open"]
    resolved = [f"{c['author']}: {c.get('harm') or c.get('quote') or ''} (settled by {c['settled_by'].get('by')} {c['settled_by'].get('at')})" if c.get("settled_by") else f"{c['author']}: {c.get('harm') or ''}"
                for c in record["claims"] if c.get("status") != "open"]
    last = record["processed"].get("last_event_at") or ""
    return {"author_status": f"last statement processed {last[:10]}" if last else "no discussion", "open_concerns": open_c, "resolved_concerns": resolved}


def build_view(cfg: Config, data_dir: Path, recs: dict[int, dict]) -> dict[int, dict]:
    cats = {c.name: c for c in load_categories(cfg.categories_dir)}
    out: dict[int, dict] = {}
    for n, rec in recs.items():
        record = ledger.load(ledger.record_path(data_dir, rec["repo"], n))
        if not record or not record["processed"]["events"] and record["processed"]["last_event_at"] is None and not record["updated"]:
            continue
        pid = rec.get("patch_id") or "nopatch"
        code = _load(code_path(data_dir, rec["repo"], n, pid))
        if code is None:  # fall back to the newest code file the PR has
            olds = sorted(glob.glob(str(code_path(data_dir, rec["repo"], n, "*"))))
            code = _load(Path(olds[-1])) if olds else None
        if code is None:
            continue
        judgments = []
        for p in sorted(glob.glob(str(judgment_path(data_dir, rec["repo"], "*", n)))):
            j = _load(Path(p))
            if j and j["category"] in cats:
                judgments.append(j)
        categories = [{"name": j["category"], "member": bool(j.get("member")), "evidence": j.get("evidence") or "",
                       "band": j.get("band") if j.get("member") else "Unranked", "reason_tag": j.get("reason_tag") or "",
                       "score": float(j.get("score") or 0), "factors": j.get("factors") or {}, "rationale": j.get("rationale") or ""} for j in judgments]
        result = {
            "summary": code.get("summary") or "", "problem": code.get("problem") or "", "card": code.get("card") or "",
            "evidence": code.get("evidence") or [], "scope_notes": code.get("scope_notes") or "",
            "discussion": _discussion(record),
            "reviewability": derive_reviewability(rec, record, cfg),
            "agreement": _agreement(record),
            "dependencies": code.get("dependencies") or {"depends_on": [], "enables": []},
            "categories": categories,
            "confidence": code.get("confidence") or "medium", "uncertainties": code.get("uncertainties") or [], "needs": code.get("needs") or [],
        }
        digest = hashlib.sha256(json.dumps({"pid": pid, "claims": [(c["id"], c.get("status"), bool(c.get("blocking"))) for c in record["claims"]],
                                            "support": [s["id"] for s in record["support"]],
                                            "judgments": [(j["category"], j.get("band"), j.get("score"), j.get("category_hash")) for j in judgments],
                                            "code": code.get("assessed_at")}, sort_keys=True).encode()).hexdigest()[:16]
        out[n] = {"number": n, "input_hash": digest, "model": "ledger", "prompt_hash": None, "created": record.get("updated"),
                  "result": result, "cost_usd": 0.0, "source": {"record": record.get("updated"), "code": code.get("assessed_at"), "judgments": len(judgments)}}
    return out
