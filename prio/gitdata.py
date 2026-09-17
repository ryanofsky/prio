"""Sidecar: fetch open PR heads into a local git repo and extract diff facts.

The github-metadata-backup data has diff *statistics* but not the changed
paths or the patch. Paths are the strongest deterministic signal for
category membership, and the model cannot judge what a PR really does
without seeing the change. This module keeps a bare clone of the project
repo, fetches ``refs/pull/N/head`` for each open PR into
``refs/prio/pull/N``, and writes ``git/<n>.json`` with:

- ``files``: every changed path with added/deleted line counts, from the
  merge base with the default branch to the head
- ``test_lines``: added+deleted lines under test paths, so the Size cell
  can show tests separately
- ``commits``: the PR's commits in order with subject and per-commit stat
- ``patch``: the unified diff, assembled per file smallest-first up to a
  character budget, so small focused changes are seen whole and huge
  generated or vendored files contribute only their stat line
- ``patch_truncated``: whether the budget cut anything

A PR is refetched only when the extract record's head SHA is not already
present in the repo, so a daily run costs one small fetch per changed PR.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

TEST_PREFIXES = ("test/", "src/test/", "src/wallet/test/", "src/qt/test/", "src/bench/", "ci/", "contrib/")


def _git(repo: Path, *args: str, check: bool = True, text: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=text)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def ensure_repo(repo: Path, url: str, reference: Path | None) -> None:
    """Create the bare clone if missing. ``reference`` borrows objects from an
    existing local clone (alternates) so the initial clone is fast and small;
    on a server with no local clone, omit it."""
    if (repo / "HEAD").exists():
        return
    cmd = ["git", "clone", "--bare"]
    if Path(url).exists():
        # Local source: share its object store via alternates instead of
        # copying packs (a bitcoin mirror is ~5 GB). Fine for a cache that
        # only ever reads objects the source keeps.
        cmd.append("--shared")
    elif reference and ((reference / ".git").exists() or (reference / "HEAD").exists()):
        cmd += ["--reference", str(reference)]
    cmd += [url, str(repo)]
    print(f"cloning {url} -> {repo}", file=sys.stderr)
    subprocess.run(cmd, check=True)


def fetch_prs(repo: Path, prs: dict[int, str], default_branch: str = "master",
              pull_ref: str = "refs/pull/{n}/head", branch_ref: str = "refs/heads/{branch}") -> dict[int, str]:
    """Fetch heads for PRs whose head SHA is not present. Returns {n: status}.

    ``pull_ref`` and ``branch_ref`` are templates for the remote's ref names:
    GitHub uses ``refs/pull/N/head``; a ``--mirror`` clone with namespaced
    refs uses ``refs/namespaces/origin/refs/pull/N/head``."""
    _git(repo, "fetch", "--quiet", "origin", f"+{branch_ref.format(branch=default_branch)}:refs/prio/{default_branch}")
    need = []
    status: dict[int, str] = {}
    for n, sha in prs.items():
        r = subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True)
        if r.returncode == 0:
            _git(repo, "update-ref", f"refs/prio/pull/{n}", sha)
            status[n] = "present"
        else:
            need.append(n)
    # Fetch in chunks; one refspec per PR.
    for i in range(0, len(need), 25):
        chunk = need[i:i + 25]
        specs = [f"+{pull_ref.format(n=n)}:refs/prio/pull/{n}" for n in chunk]
        r = subprocess.run(["git", "-C", str(repo), "fetch", "--quiet", "origin", *specs], capture_output=True, text=True)
        for n in chunk:
            status[n] = "fetched" if r.returncode == 0 else f"fetch failed: {r.stderr.strip()[:200]}"
    return status


def _numstat(repo: Path, rng: str) -> list[dict]:
    out = []
    for line in _git(repo, "diff", "--numstat", rng).splitlines():
        a, d, path = line.split("\t", 2)
        out.append({"path": path, "add": None if a == "-" else int(a), "del": None if d == "-" else int(d)})
    return out


def pr_data(repo: Path, n: int, head: str, default_branch: str, budget_chars: int) -> dict:
    ref = f"refs/prio/pull/{n}"
    actual = _git(repo, "rev-parse", ref).strip()
    base = _git(repo, "merge-base", f"refs/prio/{default_branch}", ref).strip()
    rng = f"{base}..{ref}"
    files = _numstat(repo, rng)
    test_lines = sum((f["add"] or 0) + (f["del"] or 0) for f in files if f["path"].startswith(TEST_PREFIXES))
    commits = []
    for line in _git(repo, "log", "--reverse", "--format=%H%x00%s", rng).splitlines():
        sha, subject = line.split("\0", 1)
        stat = _numstat(repo, f"{sha}^..{sha}")
        commits.append({"sha": sha, "subject": subject, "files": [f["path"] for f in stat],
                        "add": sum(f["add"] or 0 for f in stat), "del": sum(f["del"] or 0 for f in stat)})
    # Patch, smallest file first, until the budget is spent.
    order = sorted(files, key=lambda f: (f["add"] or 0) + (f["del"] or 0))
    parts = []
    used = 0
    truncated = False
    omitted = []
    for f in order:
        if f["add"] is None:  # binary
            omitted.append(f["path"])
            continue
        p = _git(repo, "diff", rng, "--", f["path"])
        if used + len(p) > budget_chars:
            truncated = True
            omitted.append(f["path"])
            continue
        parts.append(p)
        used += len(p)
    return {
        "number": n, "head": actual, "head_matches_backup": actual == head, "base": base,
        "files": files, "test_lines": test_lines, "commits": commits,
        "patch": "".join(parts), "patch_chars": used, "patch_truncated": truncated,
        "patch_omitted_files": omitted,
    }


def set_git_config(pairs: list[str]) -> None:
    """Apply KEY=VALUE git settings to every git process this module runs
    (and their children), without touching any config file. Used for
    ``safe.directory=<mirror>`` when the local mirror is owned by another user."""
    if not pairs:
        return
    base = int(os.environ.get("GIT_CONFIG_COUNT", "0") or 0)
    for i, kv in enumerate(pairs):
        k, _, v = kv.partition("=")
        os.environ[f"GIT_CONFIG_KEY_{base + i}"] = k
        os.environ[f"GIT_CONFIG_VALUE_{base + i}"] = v
    os.environ["GIT_CONFIG_COUNT"] = str(base + len(pairs))


def run(repo: Path, url: str, reference: Path | None, extract_dir: Path, out_dir: Path,
        only: set[int] | None, default_branch: str, budget_chars: int,
        pull_ref: str = "refs/pull/{n}/head", branch_ref: str = "refs/heads/{branch}",
        git_config: list[str] | None = None) -> dict:
    set_git_config(git_config or [])
    ensure_repo(repo, url, reference)
    prs: dict[int, str] = {}
    for p in sorted((extract_dir / "prs").glob("*.json"), key=lambda p: int(p.stem)):
        n = int(p.stem)
        if only and n not in only:
            continue
        with open(p) as f:
            prs[n] = json.load(f)["head_sha"]
    status = fetch_prs(repo, prs, default_branch, pull_ref, branch_ref)
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = 0
    for n, head in prs.items():
        if status.get(n, "").startswith("fetch failed"):
            print(f"  #{n}: {status[n]}", file=sys.stderr)
            continue
        try:
            d = pr_data(repo, n, head, default_branch, budget_chars)
        except RuntimeError as e:
            print(f"  #{n}: {e}", file=sys.stderr)
            continue
        with open(out_dir / f"{n}.json", "w") as f:
            json.dump(d, f, indent=1)
        ok += 1
        print(f"  #{n}: {status[n]}, {len(d['files'])} files, {len(d['commits'])} commits, patch {d['patch_chars']} chars"
              + (" (truncated)" if d["patch_truncated"] else "") + ("" if d["head_matches_backup"] else " HEAD MOVED since backup"),
              file=sys.stderr)
    return {"prs": len(prs), "ok": ok, "out": str(out_dir)}
