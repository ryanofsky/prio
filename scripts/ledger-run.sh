#!/usr/bin/env bash
# One ledger pipeline run on the host: extract, thread reads, code and
# judgments, display lines, render, commit to the data repo. Used for the
# shadow runs (renders to $SITE_OUT, e.g. the live site's staging/ dir) and
# later as the daily run.
#
#   sudo -u prio scripts/ledger-run.sh
#
# Environment (defaults match the NixOS module): PRIO_DATA_ROOT=/var/lib/prio
# (extract/, git/, src/, venv/), PRIO_LEDGER=$PRIO_DATA_ROOT/data (the data
# repo checkout; created with git init if missing), PRIO_SITE_OUT=
# $PRIO_DATA_ROOT/site/staging, PRIO_MODEL, PRIO_RANK_DIR=$PRIO_LEDGER/rank,
# PRIO_READS=2 (seed reads), PRIO_MAX_COST (informational), PRIO_SKIP_EXTRACT=1
# to reuse the daily run's extract, PRIO_ONLY=@file or list to restrict.
set -euo pipefail
D=${PRIO_DATA_ROOT:-/var/lib/prio}; L=${PRIO_LEDGER:-$D/data}; OUT=${PRIO_SITE_OUT:-$D/site/staging}
MODEL=${PRIO_MODEL:-openrouter/google/gemini-3.8-flash}; RANK=${PRIO_RANK_DIR:-$L/rank}
cd "$D"
# One run at a time: a second start while a run holds the lock exits at once.
exec 9>"$D/ledger-run.lock"
if ! flock -n 9; then echo "another ledger run holds $D/ledger-run.lock; exiting" >&2; exit 75; fi
export HOME=$D PYTHONPATH=$D/src/engine PRIO_OPENROUTER_WORKERS=${PRIO_OPENROUTER_WORKERS:-4}
[ -r "$D/api-key" ] && export ANTHROPIC_API_KEY="$(cat "$D/api-key")"
[ -r "$D/openrouter-key" ] && export OPENROUTER_API_KEY="$(cat "$D/openrouter-key")"
mkdir -p "$D/logs" "$L"
exec > >(tee -a "$D/logs/ledger-$(date -u +%Y%m%d-%H%M).log") 2>&1
prio() { "$D/venv/bin/python" -m prio.cli --config "$D/src/config" "$@"; }
SCHED=${PRIO_SCHEDULE_TEXT:-Daily ledger run at 01:00 UTC; weekly ranking pass on Sundays at 04:00 UTC.}
LIVE_SITE=${PRIO_LIVE_SITE:-$D/site}
mark() { mkdir -p "$D/status"; echo "$(date -u +%FT%TZ) $*" >> "$D/status/current.log"; prio status-page --data-dir "$D" --site-dir "$LIVE_SITE" --next-runs "$SCHED" >/dev/null 2>&1 || true; }
log() { echo "[$(date -u +%FT%TZ)] $*"; }
trap 'mark "FAILED at line $LINENO"' ERR
: > "$D/status/current.log" 2>/dev/null || mkdir -p "$D/status"; mark "ledger run started"
only=(); [ -n "${PRIO_ONLY:-}" ] && only=(--only "$PRIO_ONLY")

if [ ! -d "$L/.git" ]; then
  log "initializing the data repo at $L"
  git -C "$L" init --quiet -b main
  git -C "$L" config user.name "prio pipeline"; git -C "$L" config user.email "prio@$(hostname)"
  if [ -d "$D/dossier" ] && [ ! -d "$L/archive" ]; then
    log "archiving the old pipeline's outputs"
    mkdir -p "$L/archive"; cp -r "$D/dossier" "$D/display" "$D/rank" "$L/archive/" 2>/dev/null || true
    git -C "$L" add archive && git -C "$L" commit --quiet -m "archive: dossier, display, and rank files from the per-input-hash pipeline" || true
  fi
fi
for name in engine config; do git -C "$D/src/$name" pull --quiet --ff-only || true; done
log "engine $(git -C "$D/src/engine" rev-parse --short HEAD), config $(git -C "$D/src/config" rev-parse --short HEAD)"

if [ -z "${PRIO_SKIP_EXTRACT:-}" ]; then
  log "extract"
  prio git --repo "$D/bitcoin.git" --url "${PRIO_PROJECT_REPO:-https://github.com/bitcoin/bitcoin.git}" --extract "$D/extract" --out "$D/git" --budget-chars "${PRIO_PATCH_CHARS:-40000}" >/dev/null 2>>"$D/git.log" || true
  bash "$D/src/engine/scripts/refs-index.sh" "${PRIO_BACKUP:-/var/lib/github-metadata-backup/data/bitcoin/bitcoin}" > "$D/refs-index.tsv"
  prio extract --backup "${PRIO_BACKUP:-/var/lib/github-metadata-backup/data/bitcoin/bitcoin}" --out "$D/extract" --refs-index "$D/refs-index.tsv" --git "$D/git" >/dev/null
  mark "extract done"
fi

log "thread reads"
prior=(); [ -d "$D/dossier" ] && prior=(--prior "$D/dossier")
prio ledger update --extract "$D/extract" --data "$L" --model "$MODEL" --reads "${PRIO_READS:-2}" "${prior[@]}" "${only[@]}" 2>&1 | grep -E "PRs,|total|ERROR" || true
mark "thread reads done"
log "code assessments and judgments"
prio ledger assess --extract "$D/extract" --data "$L" --git "$D/git" --model "$MODEL" --patch-chars "${PRIO_PATCH_CHARS:-40000}" "${prior[@]}" "${only[@]}" 2>&1 | grep -E "PRs:|total|ERROR" || true
mark "code assessments and judgments done"
log "display lines"
prio display submit --extract "$D/extract" --data "$L" --out "$L/display" --model "${PRIO_DISPLAY_MODEL:-$MODEL}" "${only[@]}" 2>&1 | grep -E "dossiers|total|ERROR" || true
log "render to $OUT"
prio render --extract "$D/extract" --data "$L" --display "$L/display" --rank "$RANK" --out "$L/site.new" >/dev/null
mkdir -p "$OUT"; rsync -a --delete --exclude status.html --exclude status.json --exclude status/ --exclude staging/ --exclude preview/ --exclude local/ "$L/site.new/" "$OUT/"; rm -rf "$L/site.new"
log "commit"
git -C "$L" add -A
git -C "$L" commit --quiet -m "run $(date -u +%F): $(git -C "$L" diff --cached --stat | tail -1)" || log "nothing to commit"
if git -C "$L" remote get-url origin >/dev/null 2>&1; then
  # Keep the WHOLE message. This was `| tail -1`, which of git's three-line failure
  #   ERROR: … / fatal: Could not read from remote repository. /
  #   Please make sure you have the correct access rights / and the repository exists.
  # kept only the last line — the one that names no cause and reads almost reassuring —
  # while "see above" pointed at output tail had already discarded. A missing `ssh` on
  # PATH hid behind that for as long as the pipeline had been running.
  if ! push_out=$(git -C "$L" push --quiet origin HEAD 2>&1); then
    log "push to origin failed; the commit is local. git said:"
    printf '%s\n' "$push_out" | sed 's/^/    /'
  fi
fi
mark "done: site published"
log "done"
