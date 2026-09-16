"""Command line entry point: ``prio <stage> --config CONFIG_REPO ...``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import load_config


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

    do = sub.add_parser("dossier", help="stage 2: per-PR model assessment")
    dsub = do.add_subparsers(dest="dcmd", required=True)
    ds = dsub.add_parser("submit", help="build prompts and submit (batch by default)")
    ds.add_argument("--extract", required=True, type=Path, help="extract output dir (contains prs/)")
    ds.add_argument("--out", required=True, type=Path, help="dossier output dir")
    ds.add_argument("--only", help="comma-separated PR numbers")
    ds.add_argument("--model", default="claude-opus-5")
    ds.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ds.add_argument("--budget-tokens", type=int, default=40000, help="approximate cap on the PR content per request")
    ds.add_argument("--max-tokens", type=int, default=16000)
    ds.add_argument("--dry-run", action="store_true", help="count tokens, estimate cost, print one prompt; no model calls")
    ds.add_argument("--sync", action="store_true", help="call the API directly instead of the Batch API")
    ds.add_argument("--force", action="store_true", help="re-assess even if a dossier for this input hash exists")
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

    args = ap.parse_args(argv)
    if not args.config:
        ap.error("--config is required (or set PRIO_CONFIG)")
    cfg = load_config(args.config)

    if args.cmd == "extract":
        from . import extract

        only = {int(x) for x in args.only.split(",")} if args.only else None
        res = extract.run(cfg, args.backup, args.out, only=only, include_closed=args.include_closed)
    elif args.cmd == "dossier" and args.dcmd == "submit":
        from . import dossier

        only = {int(x) for x in args.only.split(",")} if args.only else None
        res = dossier.cmd_submit(cfg, args.extract, args.out, only, args.model, args.effort,
                                 args.budget_tokens, args.max_tokens, args.dry_run, args.sync, args.force)
    elif args.cmd == "dossier" and args.dcmd == "collect":
        from . import dossier

        res = dossier.cmd_collect(args.out, args.batch, args.wait)
    elif args.cmd == "dossier" and args.dcmd == "status":
        from . import dossier

        res = dossier.cmd_status(args.out, args.all)
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
