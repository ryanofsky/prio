"""Adapters parse project-specific bot output into structured facts.

Each adapter exposes ``parse(events) -> dict`` and is selected by name in a
config repo's project.toml (``[bots] adapters = [...]``). Adapter output is
merged into the extract record under ``bot`` keyed by adapter name.
"""

from __future__ import annotations

from importlib import import_module


def load_adapter(name: str):
    return import_module(f"prio.adapters.{name}")
