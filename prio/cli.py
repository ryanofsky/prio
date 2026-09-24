"""Command line entry point: ``prio <stage> --config CONFIG_REPO ...``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import load_config


def parse_only(spec: str | None) -> set[int] | None:
    """PR numbers from --only: comma- or whitespace-separated, or @FILE (one
    per line, as 'prio select' prints), or '-' for stdin."""
    if not spec:
        return None
    if spec == "-":
        text = sys.stdin.read()
    elif spec.startswith("@"):
        text = Path(spec[1:]).read_text()
    else:
        text = spec
    return {int(x) for x in text.replace(",", " ").split()} or None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="prio")
    ap.add_argument("--config", type=Path, default=os.environ.get("PRIO_CONFIG"),
                    help="path to a config repo checkout (contains project.toml); default $PRIO_CONFIG")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ex = sub.add_parser("extract", help="stage 1: backup JSON -> compact per-PR facts")
    ex.add_argument("--backup", required=True, type=Path, help="github-metadata-backup dir containing pulls/ and issues/")
    ex.add_argument("--out", required=True, type=Path, help="output dir (writes prs/<n>.json and index.json)")
    ex.add_argument("--only", help="comma-separated PR numbers to extract")
    ex.add_argument("--include-closed", action="store_true")
    ex.add_argument("--refs-index", type=Path, help="TSV (number, type, state, merged_at, title) covering all PRs/issues, to resolve references")
    ex.add_argument("--git", type=Path, help="git sidecar output dir (from 'prio git'); adds changed paths and test lines")

    do = sub.add_parser("dossier", help="stage 2: per-PR model assessment")
    dsub = do.add_subparsers(dest="dcmd", required=True)
    ds = dsub.add_parser("submit", help="build prompts and submit (batch by default)")
    ds.add_argument("--extract", required=True, type=Path, help="extract output dir (contains prs/)")
    ds.add_argument("--out", required=True, type=Path, help="dossier output dir")
    ds.add_argument("--only", help="PR numbers (comma-separated), @FILE with one per line, or - for stdin")
    ds.add_argument("--model", default="claude-opus-5")
    ds.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ds.add_argument("--budget-tokens", type=int, default=40000, help="approximate cap on the PR content per request")
    ds.add_argument("--max-tokens", type=int, default=16000)
    ds.add_argument("--git", type=Path, help="git sidecar output dir; includes the patch in the prompt")
    ds.add_argument("--patch-chars", type=int, default=80000, help="max patch characters per request (smallest files first)")
    ds.add_argument("--max-cost", type=float, help="estimate first and refuse to submit if the estimate (USD) exceeds this")
    ds.add_argument("--dry-run", action="store_true", help="count tokens, estimate cost, print one prompt; no model calls")
    ds.add_argument("--sync", action="store_true", help="call the API directly instead of the Batch API")
    ds.add_argument("--force", action="store_true", help="re-assess even if a dossier for this input hash exists")
    ds.add_argument("--agreement-reads", type=int, default=1, choices=[1, 2],
                    help="2 = also read the thread alone for objections and merge by union (sync and OpenRouter paths)")
    dc = dsub.add_parser("collect", help="fetch batch results into the dossier dir")
    dc.add_argument("--out", required=True, type=Path)
    dc.add_argument("--batch", help="batch id (default: every uncollected batch in --out/batches)")
    dc.add_argument("--wait", action="store_true", help="poll until the batch ends")
    dst = dsub.add_parser("status", help="show batch status (local manifests, and the API)")
    dst.add_argument("--out", required=True, type=Path)
    dst.add_argument("--all", action="store_true", help="also list batches on the workspace that have no local manifest")

    rp = sub.add_parser("report", help="render dossiers as markdown category tables")
    rp.add_argument("--extract", required=True, type=Path)
    rp.add_argument("--dossier", required=True, type=Path)
    rp.add_argument("--category", action="append", help="limit to a category (repeatable)")
    rp.add_argument("--no-expand", action="store_true", help="tables only")

    gd = sub.add_parser("git", help="sidecar: fetch PR heads into a local repo and extract file lists and patches")
    gd.add_argument("--repo", required=True, type=Path, help="bare clone to create/use")
    gd.add_argument("--url", default="https://github.com/bitcoin/bitcoin.git", help="clone URL (or local mirror path)")
    gd.add_argument("--reference", type=Path, help="existing local clone to borrow objects from")
    gd.add_argument("--extract", required=True, type=Path)
    gd.add_argument("--out", required=True, type=Path, help="writes <n>.json per PR")
    gd.add_argument("--only")
    gd.add_argument("--branch", default="master")
    gd.add_argument("--pull-ref", default="refs/pull/{n}/head", help="remote ref template for a PR head")
    gd.add_argument("--branch-ref", default="refs/heads/{branch}", help="remote ref template for the default branch")
    gd.add_argument("--budget-chars", type=int, default=120000, help="patch budget per PR (chars)")
    gd.add_argument("--git-config", action="append", default=[], metavar="KEY=VALUE",
                    help="git setting for this run only, e.g. safe.directory=/path/to/mirror (repeatable)")

    dp = sub.add_parser("display", help="stage 2b: rewrite dossiers into short display lines (separate small model call)")
    dpsub = dp.add_subparsers(dest="pcmd", required=True)
    dps = dpsub.add_parser("submit")
    dps.add_argument("--extract", required=True, type=Path)
    dps.add_argument("--dossier", type=Path, help="dossier dir (or use --data)")
    dps.add_argument("--data", type=Path, help="ledger data dir: read the ledger view instead of dossiers")
    dps.add_argument("--out", required=True, type=Path, help="display output dir (display/<n>/<dossier-hash>.json)")
    dps.add_argument("--only")
    dps.add_argument("--model", default="claude-sonnet-5")
    dps.add_argument("--dry-run", action="store_true")
    dps.add_argument("--sync", action="store_true")
    dps.add_argument("--force", action="store_true")
    dpc = dpsub.add_parser("collect")
    dpc.add_argument("--out", required=True, type=Path)
    dpc.add_argument("--batch")
    dpc.add_argument("--wait", action="store_true")
    dpt = dpsub.add_parser("status")
    dpt.add_argument("--out", required=True, type=Path)
    dpt.add_argument("--all", action="store_true")

    rk = sub.add_parser("rank", help="stage 3: one listwise call per category for consistent bands and order (on demand)")
    rk.add_argument("--extract", required=True, type=Path)
    rk.add_argument("--dossier", type=Path, help="dossier dir (or use --data)")
    rk.add_argument("--data", type=Path, help="ledger data dir: read the ledger view instead of dossiers")
    rk.add_argument("--display", type=Path)
    rk.add_argument("--out", required=True, type=Path, help="rank output dir (rank/<category>/<stamp>.json)")
    rk.add_argument("--category", action="append", help="limit to a category (repeatable)")
    rk.add_argument("--model", default="claude-opus-5")
    rk.add_argument("--effort", default="high")
    rk.add_argument("--dry-run", action="store_true")
    rk.add_argument("--force", action="store_true", help="re-rank even if nothing changed since the last ranking")

    se = sub.add_parser("select", help="pick PRs for a targeted re-assessment; prints numbers for 'dossier submit --only @FILE --force'")
    se.add_argument("--extract", required=True, type=Path)
    se.add_argument("--dossier", required=True, type=Path)
    se.add_argument("--rank", type=Path, help="rank output dir, for site order with --top")
    se.add_argument("--top", type=int, help="first N rows of every category page")
    se.add_argument("--band", help="comma-separated bands, e.g. P1,P2")
    se.add_argument("--agreement", help="comma-separated Agreement states")
    se.add_argument("--reviewability", help="comma-separated Reviewability states")
    se.add_argument("--confidence", help="comma-separated confidence levels, e.g. low")
    se.add_argument("--flagged", action="store_true", help="PRs with a feedback entry in the config repo")
    se.add_argument("--missing", action="store_true", help="open PRs with no usable dossier")
    se.add_argument("--failed", action="store_true", help="PRs whose latest stored output is a failure")
    se.add_argument("--category", action="append", help="keep only members of this category (repeatable)")
    se.add_argument("--if-stale", action="store_true", help="keep only PRs whose latest dossier used a different prompt (or model, with --model)")
    se.add_argument("--model", help="with --if-stale: also treat dossiers by another model as stale")
    se.add_argument("--format", default="lines", choices=["lines", "comma", "json"])
    se.add_argument("--agreement-reads", type=int, default=1, choices=[1, 2], help="must match the submit setting for --if-stale to compare the right prompt hash")

    lg = sub.add_parser("ledger", help="incremental PR records (facts): thread reads applied to <data>/<owner>/<repo>/prs/<n>.json")
    lgsub = lg.add_subparsers(dest="lcmd", required=True)
    lu = lgsub.add_parser("update", help="compute deltas and run thread reads for PRs with new or edited statements")
    lu.add_argument("--extract", required=True, type=Path)
    lu.add_argument("--data", required=True, type=Path, help="data repo checkout")
    lu.add_argument("--only")
    lu.add_argument("--model", default="openrouter/google/gemini-3.8-flash")
    lu.add_argument("--effort", default="high")
    lu.add_argument("--prior", type=Path, help="old dossier dir; its discussion state is given as a prior on seed reads")
    lu.add_argument("--dry-run", action="store_true")
    lu.add_argument("--force", action="store_true", help="start every record from empty (re-seed)")
    lu.add_argument("--as-of", help="drift test: treat the extract as of this date (YYYY-MM-DD), dropping later statements")
    lu.add_argument("--run-kind", default="", help="suffix for the run id (e.g. replay)")
    lu.add_argument("--reads", type=int, default=1, choices=[1, 2], help="2 = two reads merged by union for seed reads (fresh records)")
    la = lgsub.add_parser("assess", help="code assessment (per patch-id) and category judgments for PRs whose files are missing or stale")
    la.add_argument("--extract", required=True, type=Path)
    la.add_argument("--data", required=True, type=Path)
    la.add_argument("--only")
    la.add_argument("--model", default="openrouter/google/gemini-3.8-flash")
    la.add_argument("--effort", default="high")
    la.add_argument("--git", type=Path, help="git sidecar dir (patch for the code assessment)")
    la.add_argument("--patch-chars", type=int, default=40000)
    la.add_argument("--what", default="both", choices=["both", "code", "judge"])
    la.add_argument("--prior", type=Path, help="old dossier dir: copy a dossier's code half when it was made from the current input hash")
    la.add_argument("--dry-run", action="store_true")
    la.add_argument("--force", action="store_true")
    ls = lgsub.add_parser("show", help="print one record as the model sees it")
    ls.add_argument("--data", required=True, type=Path)
    ls.add_argument("--repo", default=None, help="owner/name (default: the first repo in project.toml)")
    ls.add_argument("number", type=int)

    st = sub.add_parser("status-page", help="write status.html/status.json into the site dir from pipeline state")
    st.add_argument("--data-dir", required=True, type=Path)
    st.add_argument("--site-dir", required=True, type=Path)
    st.add_argument("--next-runs", default="", help="text describing the schedule")
    st.add_argument("--no-lookup", action="store_true", help="do not query the API for in-progress batches")
    st.add_argument("--ledger", type=Path, help="ledger pipeline data dir (default: DATA_DIR/data)")

    rd = sub.add_parser("render", help="stage 5: render extract + dossiers to a static site")
    rd.add_argument("--extract", required=True, type=Path)
    rd.add_argument("--dossier", type=Path, help="dossier dir (or use --data)")
    rd.add_argument("--data", type=Path, help="ledger data dir: read the ledger view instead of dossiers")
    rd.add_argument("--out", required=True, type=Path)
    rd.add_argument("--display", type=Path, help="dir of sidecar display files <n>.json (used when the dossier has no display object)")
    rd.add_argument("--rank", type=Path, help="rank stage output dir; when present, rows use its bands and order")

    args = ap.parse_args(argv)
    if not args.config:
        ap.error("--config is required (or set PRIO_CONFIG)")
    cfg = load_config(args.config)

    if args.cmd == "extract":
        from . import extract

        only = parse_only(args.only)
        res = extract.run(cfg, args.backup, args.out, only=only, include_closed=args.include_closed,
                          refs_index=args.refs_index, git_dir=args.git)
    elif args.cmd == "dossier" and args.dcmd == "submit":
        from . import dossier

        only = parse_only(args.only)
        res = dossier.cmd_submit(cfg, args.extract, args.out, only, args.model, args.effort,
                                 args.budget_tokens, args.max_tokens, args.dry_run, args.sync, args.force,
                                 args.git, args.patch_chars, args.max_cost, agreement_reads=args.agreement_reads)
    elif args.cmd == "dossier" and args.dcmd == "collect":
        from . import dossier

        res = dossier.cmd_collect(args.out, args.batch, args.wait)
    elif args.cmd == "dossier" and args.dcmd == "status":
        from . import dossier

        res = dossier.cmd_status(args.out, args.all)
    elif args.cmd == "git":
        from . import gitdata

        only = parse_only(args.only)
        res = gitdata.run(args.repo, args.url, args.reference, args.extract, args.out, only, args.branch,
                          args.budget_chars, args.pull_ref, args.branch_ref, args.git_config)
    elif args.cmd == "display" and args.pcmd == "submit":
        from . import display

        only = parse_only(args.only)
        res = display.cmd_submit(cfg, args.extract, args.dossier, args.out, only, args.model, args.dry_run, args.sync, args.force, data_dir=args.data)
    elif args.cmd == "display" and args.pcmd == "collect":
        from . import dossier

        res = dossier.cmd_collect(args.out, args.batch, args.wait)
    elif args.cmd == "display" and args.pcmd == "status":
        from . import dossier

        res = dossier.cmd_status(args.out, args.all)
    elif args.cmd == "select":
        from . import select

        split = lambda v: set(v.split(",")) if v else None  # noqa: E731
        select.run(cfg, args.extract, args.dossier, args.rank, top=args.top, bands=split(args.band),
                   agreement=split(args.agreement), reviewability=split(args.reviewability),
                   confidence=split(args.confidence), flagged=args.flagged, missing=args.missing,
                   failed=args.failed, categories=set(args.category) if args.category else None,
                   if_stale=args.if_stale, model=args.model, fmt=args.format, agreement_reads=args.agreement_reads)
        return 0
    elif args.cmd == "ledger" and args.lcmd == "update":
        from . import ledgerrun

        res = ledgerrun.cmd_update(cfg, args.extract, args.data, parse_only(args.only), args.model, args.effort, args.dry_run, args.prior,
                                   force=args.force, as_of=args.as_of, run_kind=args.run_kind, reads=args.reads)
    elif args.cmd == "ledger" and args.lcmd == "assess":
        from . import stages

        res = stages.cmd_assess(cfg, args.extract, args.data, parse_only(args.only), args.model, args.effort, args.git, args.patch_chars,
                                args.dry_run, force=args.force, what=args.what, prior_dir=args.prior)
    elif args.cmd == "ledger" and args.lcmd == "show":
        from . import ledgerrun

        sys.stdout.write(ledgerrun.cmd_show(args.data, args.repo or cfg.repos[0].full_name, args.number))
        return 0
    elif args.cmd == "status-page":
        from . import status

        res = status.render(args.data_dir, args.site_dir, args.next_runs, not args.no_lookup, ledger_dir=args.ledger)
    elif args.cmd == "rank":
        from . import rank

        only = set(args.category) if args.category else None
        res = rank.run(cfg, args.extract, args.dossier, args.display, args.out, only, args.model, args.effort, args.dry_run, args.force, data_dir=args.data)
    elif args.cmd == "render":
        from . import render

        res = render.render(cfg, args.extract, args.dossier, args.out, args.display, args.rank, data_dir=args.data)
    elif args.cmd == "report":
        from . import report

        sys.stdout.write(report.render(args.extract, args.dossier, args.category, not args.no_expand))
        return 0
    else:
        return 1
    json.dump(res, sys.stdout)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
