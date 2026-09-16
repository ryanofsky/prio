"""Parse ACK/NACK vocabulary from review and comment text.

Bitcoin Core reviewers open a comment with a verdict word: ``ACK <hash>``,
``Concept ACK``, ``Approach NACK``, ``re-ACK``, ``utACK``, ``Tested ACK``,
``Code Review ACK``. Only the first non-empty, non-quoted line is examined;
anything deeper is discussion, not a verdict.

This is a cross-check for adapter output (see adapters/drahtbot.py), and the
only source for projects without a bot. It keeps the latest verdict per
reviewer and marks a code-review ACK stale when the hash it names is not the
current head, or when it was given before the latest force push.
"""

from __future__ import annotations

import re

_VERDICT = re.compile(
    r"^\s*(?:\*\*|__|`)?\s*"
    r"(?P<prefix>concept|approach|tested|code[- ]review|cr|ut|re-?|light|weak|strong)?\s*"
    r"(?P<word>n?ack)\b[:\s]*"
    r"(?P<hash>[0-9a-f]{6,40})?",
    re.I,
)

CODE_REVIEW_PREFIXES = {"", "tested", "code review", "code-review", "cr", "ut", "re", "re-", "light", "weak", "strong"}


def first_line(text: str) -> str:
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith(">") or s.startswith("<!--"):
            continue
        return s
    return ""


def classify(text: str) -> tuple[str, str | None] | None:
    """Return (kind, hash) for a verdict line, or None.

    kind is one of ack, concept_ack, approach_ack, nack, concept_nack,
    approach_nack. Tested/utACK/re-ACK/Code Review ACK all count as ack: they
    are code-review verdicts and differ only in how much testing was done.
    """
    m = _VERDICT.match(first_line(text))
    if not m:
        return None
    prefix = (m.group("prefix") or "").lower().replace("-", " ").strip()
    word = m.group("word").lower()
    if prefix == "concept":
        kind = "concept_" + word
    elif prefix == "approach":
        kind = "approach_" + word
    elif prefix.replace(" ", "") in {p.replace(" ", "") for p in CODE_REVIEW_PREFIXES}:
        kind = word
    else:
        return None
    return kind, (m.group("hash").lower() if m.group("hash") else None)


def verdicts(timeline: list[dict], author: str, head_sha: str, last_force_push: str | None) -> dict:
    """Latest verdict per reviewer from comment/review timeline entries.

    ``timeline`` entries need ``who``, ``t``, ``kind`` (comment|review) and
    ``text``. Returns ``{login: {kind, hash, t, stale}}``.
    """
    latest: dict[str, dict] = {}
    for e in timeline:
        if e.get("kind") not in ("comment", "review"):
            continue
        who = e.get("who")
        if not who or who == author:
            continue
        c = classify(e.get("text", ""))
        if c is None:
            continue
        kind, h = c
        stale = False
        if kind == "ack":
            if h:
                stale = not head_sha.startswith(h) and not h.startswith(head_sha)
            elif last_force_push and e["t"] < last_force_push:
                stale = True
        latest[who] = {"kind": kind, "hash": h, "t": e["t"], "stale": stale}
    return latest


def tally(v: dict) -> dict:
    """Count verdicts by kind for the table: current acks, stale acks, nacks."""
    out = {k: 0 for k in ("ack", "stale_ack", "concept_ack", "approach_ack", "nack", "concept_nack", "approach_nack")}
    for r in v.values():
        if r["kind"] == "ack" and r["stale"]:
            out["stale_ack"] += 1
        else:
            out[r["kind"]] += 1
    return out
