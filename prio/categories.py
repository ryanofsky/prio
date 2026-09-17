"""Load category files from a config repo.

A category is one markdown file with front matter (title, owner, and
pre-filter hints: labels, paths, keywords) followed by the text the model
reads. The front matter values are either plain strings or JSON arrays.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_FM = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


@dataclass
class Category:
    name: str
    title: str
    owner: str | None
    labels: list[str]
    paths: list[str]
    keywords: list[str]
    body: str
    extra: dict = field(default_factory=dict)

    def hint_matches(self, rec: dict) -> dict:
        """Which pre-filter hints match an extract record (for the prompt and for pre-filtering)."""
        labels = [l for l in rec.get("labels", []) if l in self.labels]
        title = (rec.get("title") or "").lower()
        text = " ".join([rec.get("body") or ""] + [c.get("message", "") for c in rec.get("commits", [])]).lower()
        keywords = [k for k in self.keywords if k.lower() in title or k.lower() in text]
        paths = sorted({p for p in rec.get("review_paths", []) + rec.get("changed_paths", []) if any(p.startswith(h) for h in self.paths)})
        return {"labels": labels, "keywords": keywords, "paths": paths[:20]}

    def candidate_strength(self, rec: dict) -> int:
        """2 = a maintainer label or a changed path matches (strong); 1 = a keyword in
        the title or at least two distinct keywords in the text (weak); 0 = nothing.
        Keyword lists contain common words, so a single hit in a long body means little."""
        h = self.hint_matches(rec)
        if h["labels"] or h["paths"]:
            return 2
        title = (rec.get("title") or "").lower()
        if any(k.lower() in title for k in self.keywords) or len(h["keywords"]) >= 2:
            return 1
        return 0


def parse_front_matter(text: str) -> tuple[dict, str]:
    m = _FM.match(text)
    if not m:
        return {}, text
    meta: dict = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        v = v.strip()
        if v.startswith("["):
            try:
                v = json.loads(v)
            except json.JSONDecodeError:
                pass
        meta[k.strip()] = v
    return meta, text[m.end():]


def load_categories(cat_dir: Path) -> list[Category]:
    cats: list[Category] = []
    for p in sorted(cat_dir.glob("*.md")):
        meta, body = parse_front_matter(p.read_text())
        known = {"title", "owner", "labels", "paths", "keywords"}
        cats.append(Category(
            name=p.stem,
            title=meta.get("title", p.stem),
            owner=meta.get("owner"),
            labels=list(meta.get("labels", [])),
            paths=list(meta.get("paths", [])),
            keywords=list(meta.get("keywords", [])),
            body=body.strip(),
            extra={k: v for k, v in meta.items() if k not in known},
        ))
    return cats
