"""Parse DrahtBot's summary comment on Bitcoin Core organization PRs.

DrahtBot keeps one comment per PR that it edits in place. The backup stores
the latest version, so the comment reflects current state. Two sections
matter here:

``### Reviews`` is a table of reviewer links by type. The types are ACK,
Concept ACK, Approach ACK, Stale ACK, NACK, Concept NACK, Approach NACK.
This is the ACK state the project itself treats as canonical, and it already
accounts for force pushes (ACKs on an old head move to "Stale ACK").

``### Conflicts`` lists other open PRs that conflict with this one, each as
``* [#N](url) (title by author)``.
"""

from __future__ import annotations

import re

NAME = "drahtbot"
LOGIN = "DrahtBot"

_ROW = re.compile(r"^\|\s*([A-Za-z ]+?)\s*\|\s*(.*?)\s*\|\s*$")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_CONFLICT = re.compile(r"^\*\s*\[#(\d+)\]\([^)]*\)\s*\((.*) by ([^ )]+)\)\s*$")

_TYPE_KEYS = {
    "ACK": "ack",
    "Concept ACK": "concept_ack",
    "Approach ACK": "approach_ack",
    "Stale ACK": "stale_ack",
    "NACK": "nack",
    "Concept NACK": "concept_nack",
    "Approach NACK": "approach_nack",
}


def find_summary(events: list[dict]) -> str | None:
    """Return the body of DrahtBot's summary comment, or None."""
    for ev in events:
        if ev.get("event") != "commented":
            continue
        actor = (ev.get("actor") or ev.get("user") or {}).get("login")
        if actor == LOGIN and "### Reviews" in (ev.get("body") or ""):
            return ev["body"]
    return None


def _section(body: str, title: str) -> str:
    m = re.search(rf"^### {re.escape(title)}\s*$(.*?)(?=^###? |\Z)", body, re.S | re.M)
    return m.group(1) if m else ""


def parse(events: list[dict]) -> dict:
    body = find_summary(events)
    out: dict = {"present": body is not None, "reviews": {}, "conflicts": []}
    if body is None:
        return out
    reviews: dict[str, list[dict]] = {}
    for line in _section(body, "Reviews").splitlines():
        m = _ROW.match(line)
        if not m:
            continue
        kind = m.group(1).strip()
        key = _TYPE_KEYS.get(kind)
        if key is None:
            continue
        reviews[key] = [
            {"login": login, "url": url} for login, url in _LINK.findall(m.group(2))
        ]
    out["reviews"] = reviews
    for line in _section(body, "Conflicts").splitlines():
        m = _CONFLICT.match(line.strip())
        if m:
            out["conflicts"].append(
                {"number": int(m.group(1)), "title": m.group(2), "author": m.group(3)}
            )
    return out
