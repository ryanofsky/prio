"""Pick PRs for a targeted re-assessment: ``prio select``.

A prompt or definition change invalidates nothing by itself (dossiers are
keyed by the PR's input hash, and re-doing every PR after each prompt edit
would cost a full cold start). Instead this command names the PRs worth
re-doing, by rule, and prints their numbers for ``prio dossier submit
--only @file --force``. Rules are unioned; the filters then narrow the
union. Each rule is one of:

- ``--top N``: the first N rows of every category page, in site order
  (the ranking pass merged with newer dossiers, as the renderer does it).
- ``--band P1,P2``: members of any category at these bands.
- ``--agreement Strong,Positive``, ``--reviewability Ready``,
  ``--confidence low``: by the dossier's one-word states.
- ``--flagged``: PRs with a feedback entry in the config repo.
- ``--missing``: open PRs with no usable dossier; ``--failed``: PRs whose
  latest stored output is a failure.

Filters: ``--category`` keeps only members of those categories (by the
dossier's membership, so PRs without a dossier drop out); ``--if-stale``
keeps only PRs whose latest dossier was made with a different prompt
(or, with ``--model``, a different model) than the current one, so a
selection can be re-run after each prompt change without paying twice
for PRs that already have the new prompt.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .categories import load_categories
from .config import Config
from .dossier import build_system, load_extract, prompt_hash
from .report import load_latest


def _latest_payload(dossier_dir: Path, n: int) -> dict | None:
    latest = dossier_dir / str(n) / "latest"
    if not latest.exists():
        return None
    try:
        with open(dossier_dir / str(n) / f"{latest.read_text().strip()}.json") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def run(cfg: Config, extract_dir: Path, dossier_dir: Path, rank_dir: Path | None, *,
        top: int | None = None, bands: set[str] | None = None, agreement: set[str] | None = None,
        reviewability: set[str] | None = None, confidence: set[str] | None = None, flagged: bool = False,
        missing: bool = False, failed: bool = False, categories: set[str] | None = None,
        if_stale: bool = False, model: str | None = None, fmt: str = "lines") -> dict:
    from .render import load_rank, merge_rank

    cats = load_categories(cfg.categories_dir)
    recs = load_extract(extract_dir, None)
    good = {n: d for n, d in load_latest(dossier_dir).items() if d.get("result")}
    chosen: dict[int, list[str]] = {}

    def pick(n: int, why: str) -> None:
        chosen.setdefault(n, []).append(why)

    # Membership rows per category, in site order.
    members: dict[str, list[tuple[float, int, dict]]] = {}
    for n, d in good.items():
        for c in d["result"].get("categories") or []:
            if c.get("member") and c.get("name"):
                members.setdefault(c["name"], []).append((c.get("score") or 0, n, c))
    for name, rows in members.items():
        rows.sort(key=lambda x: -x[0])
        rk = load_rank(rank_dir, name)
        if rk:
            members[name] = merge_rank(rows, rk, good)

    if top:
        for name, rows in members.items():
            for i, (_, n, _c) in enumerate(rows[:top], 1):
                pick(n, f"top {i} in {name}")
    if bands:
        for name, rows in members.items():
            for _, n, c in rows:
                b = c.get("rank_band") or c.get("band")
                if b in bands:
                    pick(n, f"{b} in {name}")
    for label, want, getter in (
        ("agreement", agreement, lambda r: (r.get("agreement") or {}).get("state")),
        ("reviewability", reviewability, lambda r: (r.get("reviewability") or {}).get("state")),
        ("confidence", confidence, lambda r: r.get("confidence")),
    ):
        if want:
            for n, d in good.items():
                v = getter(d["result"])
                if v in want:
                    pick(n, f"{label} {v}")
    if flagged:
        fb = cfg.feedback_dir / "prs"
        if fb.is_dir():
            for p in fb.iterdir():
                if p.name.isdigit() and int(p.name) in recs and any(p.iterdir()):
                    pick(int(p.name), "feedback entry")
    if missing:
        for n in recs:
            if n not in good:
                pick(n, "no dossier")
    if failed:
        for n in recs:
            d = _latest_payload(dossier_dir, n)
            if d is not None and not d.get("result"):
                pick(n, f"failed: {d.get('error') or d.get('stop_reason')}")

    counts_before = len(chosen)
    if categories:
        keep = {n for name, rows in members.items() if name in categories for _, n, _c in rows}
        chosen = {n: w for n, w in chosen.items() if n in keep}
    current = prompt_hash(build_system(cfg, cats))
    if if_stale:
        def stale(n: int) -> bool:
            d = good.get(n)
            if d is None:
                return True
            if model and d.get("model") != model:
                return True
            return d.get("prompt_hash") != current
        chosen = {n: w for n, w in chosen.items() if stale(n)}

    numbers = sorted(chosen)
    if fmt == "json":
        json.dump({"prompt_hash": current, "count": len(numbers), "prs": {str(n): chosen[n] for n in numbers}}, sys.stdout, indent=1)
        print()
    elif fmt == "comma":
        print(",".join(str(n) for n in numbers))
    else:
        for n in numbers:
            print(n)
    print(f"current prompt hash {current}; {len(numbers)} PRs selected"
          + (f" ({counts_before} before filters)" if counts_before != len(numbers) else ""), file=sys.stderr)
    return {"count": len(numbers), "prompt_hash": current}
