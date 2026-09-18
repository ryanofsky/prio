"""Prompts and definitions, resolved config-first.

A config repo may carry its own ``prompts/<name>.md``, ``definitions/
<name>.md``, or ``engine/<module>.py``; anything it does not carry comes
from the engine tree (or from a config it inherits). ``load_config`` sets
the search chain; the stages call ``read`` and never touch the engine
tree directly, so a hash of a prompt or definition is a hash of the text
actually used.
"""

from __future__ import annotations

from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
_CHAIN: list[Path] = []


def set_chain(dirs: list[Path]) -> None:
    """Config roots to search before the engine tree, most specific first."""
    _CHAIN[:] = list(dirs)


def find(rel: str) -> Path:
    for root in _CHAIN + [ENGINE_ROOT]:
        p = root / rel
        if p.exists():
            return p
    raise FileNotFoundError(f"{rel}: not in {[str(r) for r in _CHAIN]} or the engine tree")


def read(rel: str) -> str:
    return find(rel).read_text()
