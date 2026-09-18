"""Load a config repo's project.toml.

A config repo (for example prio-bitcoin) describes one project: which GitHub
repositories it covers, which accounts are bots, which adapters parse bot
output, and the thresholds used by the extract stage. The engine never
hardcodes any of this.

A config may inherit another (``[project] inherit``): it then sees the
base's categories, prompts, definitions, and settings, and adds or
overrides its own. That is how a second view of the same project is a
second config rather than a fork. Related knobs: ``[data] prefix`` keeps
a config's judgment files apart from another's in a shared data repo;
``[site] columns`` and ``[engine] modules`` let a config add table columns
computed by its own Python module under ``engine/``.
"""

from __future__ import annotations

import importlib.util
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import texts

DEFAULT_COLUMNS = ["pr", "prio", "rev", "reviews", "agree", "size"]


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
    chain: list[Path] = field(default_factory=list)  # this config's root, then the ones it inherits

    @property
    def categories_dir(self) -> Path:
        return self.root / "categories"

    @property
    def categories_dirs(self) -> list[Path]:
        """Own categories first, then inherited ones; a file in an earlier dir shadows the same name later."""
        return [r / "categories" for r in self.chain if (r / "categories").is_dir()]

    @property
    def feedback_dir(self) -> Path:
        return self.root / "feedback"

    @property
    def data_prefix(self) -> str:
        """Path prefix for this config's judgment-layer files inside a data repo (empty for the main config)."""
        p = (self.raw.get("data", {}) or {}).get("prefix", "")
        return p.strip("/") + "/" if p.strip("/") else ""

    @property
    def columns(self) -> list[str]:
        return list((self.raw.get("site", {}) or {}).get("columns", DEFAULT_COLUMNS))

    def load_modules(self) -> list:
        """Import the config's ``engine/<name>.py`` modules named in ``[engine] modules``."""
        mods = []
        for name in (self.raw.get("engine", {}) or {}).get("modules", []):
            path = texts.find(f"engine/{name}.py")
            spec = importlib.util.spec_from_file_location(f"prio_config_{name}", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mods.append(mod)
        return mods

    def size_bucket(self, lines: int) -> str:
        if lines <= self.size_small:
            return "S"
        if lines <= self.size_medium:
            return "M"
        if lines <= self.size_large:
            return "L"
        return "XL"


def _merge(base: dict, over: dict) -> dict:
    """Table-wise merge: a table in ``over`` updates the same table in ``base``; other keys replace."""
    out = dict(base)
    for k, v in over.items():
        out[k] = {**base[k], **v} if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def _read_chain(root: Path, seen: tuple = ()) -> tuple[dict, list[Path]]:
    """The merged project.toml of a config and its inherited bases, and the root chain."""
    root = root.resolve()
    if root in seen:
        raise ValueError(f"config inheritance loop at {root}")
    with open(root / "project.toml", "rb") as f:
        raw = tomllib.load(f)
    inherit = (raw.get("project", {}) or {}).get("inherit")
    if not inherit:
        return raw, [root]
    candidates = [inherit] if isinstance(inherit, str) else list(inherit)
    for cand in candidates:  # the first candidate path that exists; a list allows different layouts per host
        base_root = (root / cand)
        if (base_root / "project.toml").exists():
            base_raw, base_chain = _read_chain(base_root, seen + (root,))
            merged = _merge(base_raw, raw)
            merged["project"] = {k: v for k, v in merged["project"].items() if k != "inherit"}
            return merged, [root] + base_chain
    raise FileNotFoundError(f"{root}/project.toml inherits {candidates}, none of which has a project.toml")


def load_config(root: Path | str) -> Config:
    root = Path(root)
    raw, chain = _read_chain(root)
    texts.set_chain(chain)
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
        chain=chain,
    )
