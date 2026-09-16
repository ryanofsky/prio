"""Command line entry point: ``prio <stage> --config CONFIG_REPO ...``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="prio")
    ap.add_argument("--config", required=True, type=Path, help="path to a config repo checkout (contains project.toml)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ex = sub.add_parser("extract", help="stage 1: backup JSON -> compact per-PR facts")
    ex.add_argument("--backup", required=True, type=Path, help="github-metadata-backup dir containing pulls/ and issues/")
    ex.add_argument("--out", required=True, type=Path, help="output dir (writes prs/<n>.json and index.json)")
    ex.add_argument("--only", help="comma-separated PR numbers to extract")
    ex.add_argument("--include-closed", action="store_true")

    args = ap.parse_args(argv)
    cfg = load_config(args.config)

    if args.cmd == "extract":
        from . import extract

        only = {int(x) for x in args.only.split(",")} if args.only else None
        res = extract.run(cfg, args.backup, args.out, only=only, include_closed=args.include_closed)
        json.dump(res, sys.stdout)
        print()
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
