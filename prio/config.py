"""Load a config repo's project.toml.

A config repo (for example prio-bitcoin) describes one project: which GitHub
repositories it covers, which accounts are bots, which adapters parse bot
output, and the thresholds used by the extract stage. The engine never
hardcodes any of this.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Repo:
    owner: str
    repo: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass
class Config:
    root: Path
    name: str
    site_title: str
    orgs: list[str]
    repos: list[Repo]
    bot_logins: set[str]
    adapters: list[str]
    size_small: int
    size_medium: int
    size_large: int
    waiting_on_author_days: int
    stale_author_silent_days: int
    raw: dict = field(repr=False)

    @property
    def categories_dir(self) -> Path:
        return self.root / "categories"

    @property
    def feedback_dir(self) -> Path:
        return self.root / "feedback"

    def size_bucket(self, lines: int) -> str:
        if lines <= self.size_small:
            return "S"
        if lines <= self.size_medium:
            return "M"
        if lines <= self.size_large:
            return "L"
        return "XL"


def load_config(root: Path | str) -> Config:
    root = Path(root)
    path = root / "project.toml"
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    project = raw.get("project", {})
    bots = raw.get("bots", {})
    size = raw.get("size", {})
    rev = raw.get("reviewability", {})
    return Config(
        root=root,
        name=project.get("name", root.name),
        site_title=project.get("site_title", project.get("name", root.name)),
        orgs=list(project.get("orgs", [])),
        repos=[Repo(r["owner"], r["repo"]) for r in raw.get("repos", [])],
        bot_logins=set(bots.get("logins", [])),
        adapters=list(bots.get("adapters", [])),
        size_small=int(size.get("small", 100)),
        size_medium=int(size.get("medium", 400)),
        size_large=int(size.get("large", 1000)),
        waiting_on_author_days=int(rev.get("waiting_on_author_days", 7)),
        stale_author_silent_days=int(rev.get("stale_author_silent_days", 60)),
        raw=raw,
    )
