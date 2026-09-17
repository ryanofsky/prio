"""Stage 1: turn github-metadata-backup records into compact per-PR facts.

Input is a backup directory as written by 0xB10C's github-metadata-backup:
``pulls/<n>.json`` and ``issues/<n>.json``, each holding the REST object plus
the issue timeline. Output is one ``prs/<n>.json`` per open PR plus an
``index.json`` of table rows, and it needs no model. Everything a later
stage or the site shows about size, ACKs, staleness, stacking, and linked
issues is decided here, in code, so it is reproducible and cheap.

The record deliberately keeps only what a reader (human or model) needs:
metadata, structured signals, and the human text of the discussion in
order. URL boilerplate and user objects from the API are dropped; that is
where most of the raw size goes.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .acks import tally, verdicts
from .adapters import load_adapter
from .config import Config

_REF = re.compile(r"(?<![\w/])#(\d{3,6})\b")
_DEP = re.compile(
    r"\b(depends on|based on|built on|builds on|on top of|blocked by|requires|after|follow-?up to|parent)\s*(?:pr\s*)?#?(\d{3,6})\b",
    re.I,
)
_FIX = re.compile(r"\b(fix(?:es|ed)?|close[sd]?|resolve[sd]?)\s*:?\s*#(\d{3,6})\b", re.I)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_HTML_TAG = re.compile(r"</?(details|summary|p|br|div|img|a|b|i|em|strong)\b[^>]*>", re.I)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def clean_text(text: str | None) -> str:
    """Drop quoted lines, HTML comments, and runs of blank lines."""
    if not text:
        return ""
    text = _HTML_COMMENT.sub("", text)
    text = _HTML_TAG.sub("", text)
    out: list[str] = []
    blank = 0
    for line in text.replace("\r\n", "\n").split("\n"):
        s = line.rstrip()
        if s.lstrip().startswith(">"):
            if not out or out[-1] != "[quoted text omitted]":
                out.append("[quoted text omitted]")
            continue
        if not s.strip():
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        out.append(s)
    return "\n".join(out).strip()


def _login(obj: dict | None) -> str | None:
    return (obj or {}).get("login")


def _is_bot(login: str | None, user: dict | None, cfg: Config) -> bool:
    if not login:
        return False
    if login in cfg.bot_logins or login.endswith("[bot]"):
        return True
    return (user or {}).get("type") == "Bot"


def load_refs_index(path: Path) -> dict[int, dict]:
    """Read a number -> {type, state, merged, title} index (TSV: number, type,
    state, merged_at, title). Built from a full backup so references to PRs
    and issues outside the current sample still resolve."""
    out: dict[int, dict] = {}
    with open(path) as f:
        for line in f:
            parts = line.rstrip("\n").split("\t", 4)
            if len(parts) < 5 or not parts[0].isdigit():
                continue
            merged = parts[3].strip().strip(",").strip('"')
            out[int(parts[0])] = {
                "type": parts[1], "state": parts[2],
                "merged": bool(merged and merged != "null"),
                "merged_at": merged[:10] if merged and merged != "null" else None,
                "title": parts[4],
            }
    return out


class Extractor:
    def __init__(self, cfg: Config, backup_dir: Path, refs_index: dict[int, dict] | None = None):
        self.cfg = cfg
        self.backup = backup_dir
        self.pulls = backup_dir / "pulls"
        self.issues = backup_dir / "issues"
        self.adapters = [load_adapter(n) for n in cfg.adapters]
        self._issue_titles: dict[int, str] = {}
        self.refs_index = refs_index or {}

    def describe_ref(self, n: int) -> dict:
        """Best available description of a referenced number."""
        r = self.refs_index.get(n)
        if r:
            return {"number": n, **r}
        if self.is_pr(n):
            return {"number": n, "type": "pull", "state": None, "merged": None, "merged_at": None, "title": None}
        return {"number": n, "type": "issue" if (self.issues / f"{n}.json").exists() else None,
                "state": None, "merged": None, "merged_at": None, "title": self.issue_title(n)}

    # ----- lookups -----

    def is_pr(self, n: int) -> bool:
        return (self.pulls / f"{n}.json").exists()

    def issue_title(self, n: int) -> str | None:
        if n in self._issue_titles:
            return self._issue_titles[n]
        p = self.issues / f"{n}.json"
        title = None
        if p.exists():
            with open(p) as f:
                d = json.load(f)
            title = (d.get("issue") or {}).get("title")
        self._issue_titles[n] = title
        return title

    # ----- per-PR -----

    def extract(self, data: dict) -> dict:
        pull = data["pull"]
        events = data.get("events") or []
        inline = data.get("comments") or []
        cfg = self.cfg
        author = _login(pull.get("user"))
        head_sha = pull["head"]["sha"]

        timeline: list[dict] = []
        commits: list[dict] = []
        head_history: list[dict] = []
        labels_log: list[dict] = []
        state_log: list[dict] = []
        bot_events: list[dict] = []

        for ev in events:
            kind = ev.get("event")
            who = _login(ev.get("actor")) or _login(ev.get("user"))
            user = ev.get("actor") or ev.get("user")
            t = ev.get("created_at") or ev.get("submitted_at")
            if kind == "commented":
                if _is_bot(who, user, cfg):
                    bot_events.append(ev)
                    continue
                timeline.append({"t": t, "kind": "comment", "who": who,
                                 "assoc": ev.get("author_association"),
                                 "text": clean_text(ev.get("body"))})
            elif kind == "reviewed":
                if _is_bot(who, user, cfg):
                    continue
                text = clean_text(ev.get("body"))
                state = ev.get("state")
                if not text and state == "COMMENTED":
                    continue  # inline-only review; its comments arrive via `inline`
                timeline.append({"t": t, "kind": "review", "who": who,
                                 "assoc": ev.get("author_association"),
                                 "state": state, "commit": ev.get("commit_id"),
                                 "text": text})
            elif kind == "committed":
                commits.append({"sha": ev.get("sha"),
                                "date": ((ev.get("committer") or {}).get("date")),
                                "message": clean_text(ev.get("message"))})
            elif kind == "head_ref_force_pushed":
                head_history.append({"t": t, "sha": ev.get("commit_id")})
                timeline.append({"t": t, "kind": "force_push", "who": who,
                                 "commit": ev.get("commit_id")})
            elif kind in ("labeled", "unlabeled"):
                labels_log.append({"t": t, "action": kind,
                                   "label": (ev.get("label") or {}).get("name"), "who": who})
            elif kind in ("renamed", "ready_for_review", "convert_to_draft", "closed", "reopened", "milestoned", "demilestoned"):
                entry = {"t": t, "kind": kind, "who": who}
                if kind == "renamed":
                    entry["from"] = (ev.get("rename") or {}).get("from")
                    entry["to"] = (ev.get("rename") or {}).get("to")
                state_log.append(entry)

        review_paths: set[str] = set()
        for c in inline:
            who = _login(c.get("user"))
            if _is_bot(who, c.get("user"), cfg):
                continue
            path = c.get("path")
            if path:
                review_paths.add(path)
            timeline.append({"t": c.get("created_at"), "kind": "review_comment", "who": who,
                             "assoc": c.get("author_association"), "path": path,
                             "commit": c.get("commit_id"), "in_reply_to": c.get("in_reply_to_id"),
                             "text": clean_text(c.get("body"))})

        timeline.sort(key=lambda e: e.get("t") or "")

        # Bot adapters (e.g. DrahtBot ACK table and conflicts).
        bot: dict = {}
        for mod in self.adapters:
            bot[mod.NAME] = mod.parse(events)

        # Our own ACK parse, as a cross-check or as the only source.
        last_fp = head_history[-1]["t"] if head_history else None
        own = verdicts(timeline, author, head_sha, last_fp)

        # Activity signals for reviewability.
        now = _now()
        last_author = None
        last_reviewer = None
        last_reviewer_who = None
        for e in timeline:
            if e["kind"] not in ("comment", "review", "review_comment", "force_push"):
                continue
            if e.get("who") == author:
                last_author = e["t"]
            elif e.get("who"):
                last_reviewer, last_reviewer_who = e["t"], e["who"]
        for c in commits:
            if c["date"] and (last_author is None or c["date"] > last_author):
                last_author = c["date"]

        def days_since(s: str | None) -> int | None:
            d = _dt(s)
            return None if d is None else (now - d).days

        waiting_days = 0
        if last_reviewer and (last_author is None or last_reviewer > last_author):
            waiting_days = days_since(last_reviewer) or 0
        label_names = [l["name"] for l in pull.get("labels") or []]

        # References to other issues/PRs.
        body = clean_text(pull.get("body"))
        all_text = "\n".join([body] + [e.get("text", "") for e in timeline] + [c["message"] for c in commits])
        refs = sorted({int(n) for n in _REF.findall(all_text) if int(n) != pull["number"]})
        deps = sorted({int(n) for _, n in _DEP.findall(body + "\n" + "\n".join(c["message"] for c in commits))})
        fixes = sorted({int(n) for _, n in _FIX.findall(body + "\n" + "\n".join(c["message"] for c in commits))})
        linked_issues = [self.describe_ref(n) for n in fixes if self.refs_index.get(n, {}).get("type", "issue" if not self.is_pr(n) else "pull") == "issue"]
        # Resolve every referenced number, most relevant first, capped so a
        # long thread does not flood the prompt.
        priority_refs = list(dict.fromkeys(deps + fixes))
        body_refs = [int(n) for n in _REF.findall(body + "\n" + "\n".join(c["message"] for c in commits)) if int(n) != pull["number"]]
        ordered = list(dict.fromkeys(priority_refs + body_refs + refs))
        references = [self.describe_ref(n) for n in ordered[:40]]

        lines = (pull.get("additions") or 0) + (pull.get("deletions") or 0)
        text_chars = len(all_text) + len(pull.get("title") or "")

        rec = {
            "number": pull["number"],
            "repo": pull["base"]["repo"]["full_name"] if pull.get("base", {}).get("repo") else None,
            "url": pull.get("html_url"),
            "title": pull.get("title"),
            "author": author,
            "author_association": pull.get("author_association"),
            "created_at": pull.get("created_at"),
            "updated_at": pull.get("updated_at"),
            "age_days": days_since(pull.get("created_at")),
            "draft": bool(pull.get("draft")),
            "labels": label_names,
            "milestone": (pull.get("milestone") or {}).get("title"),
            "base": pull["base"].get("ref"),
            "head_sha": head_sha,
            "head_ref": pull["head"].get("ref"),
            "head_repo": (pull["head"].get("repo") or {}).get("full_name"),
            "head_history": head_history,
            "additions": pull.get("additions"),
            "deletions": pull.get("deletions"),
            "changed_files": pull.get("changed_files"),
            "commit_count": pull.get("commits"),
            "size_bucket": cfg.size_bucket(lines),
            "mergeable_state": pull.get("mergeable_state"),
            "bot": bot,
            "acks_parsed": own,
            "acks_tally": tally(own),
            "reviews": {
                "approved": sum(1 for e in timeline if e["kind"] == "review" and e.get("state") == "APPROVED"),
                "changes_requested": sum(1 for e in timeline if e["kind"] == "review" and e.get("state") == "CHANGES_REQUESTED"),
                "distinct_reviewers": sorted({e["who"] for e in timeline if e["kind"] in ("review", "review_comment", "comment") and e.get("who") and e["who"] != author}),
            },
            "signals": {
                "needs_rebase": "Needs rebase" in label_names,
                "ci_failed": "CI failed" in label_names,
                "mergeable_state": pull.get("mergeable_state"),
                "last_author_activity": last_author,
                "last_reviewer_activity": last_reviewer,
                "last_reviewer": last_reviewer_who,
                "author_silent_days": days_since(last_author),
                "waiting_on_author_days": waiting_days,
                "days_since_update": days_since(pull.get("updated_at")),
            },
            "refs": {
                "mentioned": refs,
                "depends_on": deps,
                "fixes": fixes,
                "linked_issues": linked_issues,
                "references": references,
                "conflicts": [c["number"] for c in bot.get("drahtbot", {}).get("conflicts", [])],
            },
            "stack": {"shares_commits_with": [], "based_on": [], "base_for": []},
            "review_paths": sorted(review_paths),
            "body": body,
            "commits": commits,
            "timeline": timeline,
            "labels_log": labels_log,
            "state_log": state_log,
            "text_chars": text_chars,
            "text_tokens_estimate": text_chars // 4,
        }
        return rec

    # ----- cross-PR -----

    @staticmethod
    def link_stacks(records: dict[int, dict]) -> None:
        """Fill ``stack`` from shared commit SHAs across open PRs.

        If every commit of A also appears in B, B is based on A. Two PRs that
        merely share some commits are listed under shares_commits_with.
        """
        by_sha: dict[str, set[int]] = defaultdict(set)
        shas: dict[int, set[str]] = {}
        for n, r in records.items():
            s = {c["sha"] for c in r["commits"] if c.get("sha")}
            shas[n] = s
            for sha in s:
                by_sha[sha].add(n)
        for n, r in records.items():
            others: set[int] = set()
            for sha in shas[n]:
                others |= by_sha[sha]
            others.discard(n)
            r["stack"]["shares_commits_with"] = sorted(others)
            for m in others:
                if shas[n] and shas[n] < shas[m]:
                    r["stack"]["base_for"].append(m)
                elif shas[m] and shas[m] < shas[n]:
                    r["stack"]["based_on"].append(m)
            r["stack"]["base_for"].sort()
            r["stack"]["based_on"].sort()


def input_hash(rec: dict) -> str:
    """Stable hash of everything a model would see; used for change detection.

    Excludes the day-relative fields (ages and day counts) so a quiet PR does
    not look changed every morning.
    """
    skip = {"age_days", "input_hash", "extracted_at"}
    d = {k: v for k, v in rec.items() if k not in skip}
    d["signals"] = {k: v for k, v in rec["signals"].items() if not k.endswith("_days")}
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:16]


def index_row(r: dict) -> dict:
    db = r["bot"].get("drahtbot", {}).get("reviews", {})
    return {
        "number": r["number"],
        "title": r["title"],
        "author": r["author"],
        "age_days": r["age_days"],
        "draft": r["draft"],
        "labels": r["labels"],
        "size": f"+{r['additions']}/-{r['deletions']}",
        "size_bucket": r["size_bucket"],
        "ack": len(db.get("ack", [])),
        "stale_ack": len(db.get("stale_ack", [])),
        "concept_ack": len(db.get("concept_ack", [])),
        "approach_ack": len(db.get("approach_ack", [])),
        "nack": len(db.get("nack", [])) + len(db.get("concept_nack", [])) + len(db.get("approach_nack", [])),
        "needs_rebase": r["signals"]["needs_rebase"],
        "ci_failed": r["signals"]["ci_failed"],
        "waiting_on_author_days": r["signals"]["waiting_on_author_days"],
        "author_silent_days": r["signals"]["author_silent_days"],
        "based_on": r["stack"]["based_on"],
        "base_for": r["stack"]["base_for"],
        "conflicts": len(r["refs"]["conflicts"]),
        "text_tokens_estimate": r["text_tokens_estimate"],
        "input_hash": r["input_hash"],
    }


def run(cfg: Config, backup_dir: Path, out_dir: Path, only: set[int] | None = None, include_closed: bool = False,
        refs_index: Path | None = None) -> dict:
    ex = Extractor(cfg, backup_dir, load_refs_index(refs_index) if refs_index else None)
    out_prs = out_dir / "prs"
    out_prs.mkdir(parents=True, exist_ok=True)
    records: dict[int, dict] = {}
    for p in sorted(ex.pulls.glob("*.json"), key=lambda p: int(p.stem)):
        n = int(p.stem)
        if only and n not in only:
            continue
        with open(p) as f:
            data = json.load(f)
        if data.get("type") != "pull":
            continue
        if not include_closed and data["pull"].get("state") != "open":
            continue
        records[n] = ex.extract(data)
    Extractor.link_stacks(records)
    stamp = _now().isoformat(timespec="seconds")
    rows = []
    for n, r in records.items():
        r["input_hash"] = input_hash(r)
        r["extracted_at"] = stamp
        with open(out_prs / f"{n}.json", "w") as f:
            json.dump(r, f, indent=1, sort_keys=False)
        rows.append(index_row(r))
    with open(out_dir / "index.json", "w") as f:
        json.dump({"extracted_at": stamp, "count": len(rows), "rows": rows}, f, indent=1)
    return {"count": len(rows), "out": str(out_dir)}
