#!/usr/bin/env bash
# Targeted re-assessment on the pipeline host: re-run the dossier stage for
# the PRs 'prio select' picks (see 'prio select --help'), regenerate their
# display lines, and republish the site. The weekly ranking pass is not
# re-run; the renderer slots re-assessed PRs among the ranked ones by score
# until the next pass. Refuses to spend more than PRIO_MAX_COST (USD).
#
#   sudo -u prio scripts/reassess.sh --top 10 --flagged --if-stale
#   sudo -u prio PRIO_MAX_COST=3 scripts/reassess.sh --agreement Strong,Positive --category p2p
#
# Environment (defaults match the NixOS module): PRIO_DATA=/var/lib/prio,
# PRIO_SITE=$PRIO_DATA/site, PRIO_MODEL=openrouter/google/gemini-3.8-flash,
# PRIO_DISPLAY_MODEL=$PRIO_MODEL, PRIO_PATCH_CHARS=40000, PRIO_MAX_COST=8.
set -euo pipefail
D=${PRIO_DATA:-/var/lib/prio}; SITE=${PRIO_SITE:-$D/site}
MODEL=${PRIO_MODEL:-openrouter/google/gemini-3.8-flash}; DMODEL=${PRIO_DISPLAY_MODEL:-$MODEL}
PATCH=${PRIO_PATCH_CHARS:-40000}; MAX=${PRIO_MAX_COST:-8}
cd "$D"
export HOME=$D PYTHONPATH=$D/src/engine PRIO_OPENROUTER_WORKERS=${PRIO_OPENROUTER_WORKERS:-6}
[ -r "$D/api-key" ] && export ANTHROPIC_API_KEY="$(cat "$D/api-key")"
[ -r "$D/openrouter-key" ] && export OPENROUTER_API_KEY="$(cat "$D/openrouter-key")"
mkdir -p "$D/logs" "$D/status"
exec > >(tee -a "$D/logs/reassess-$(date -u +%Y%m%d-%H%M).log") 2>&1
prio() { "$D/venv/bin/python" -m prio.cli --config "$D/src/config" "$@"; }
mark() { echo "$(date -u +%FT%TZ) $*" >> "$D/status/current.log"; prio status-page --data-dir "$D" --site-dir "$SITE" --next-runs "${PRIO_SCHEDULE_TEXT:-Daily 01:00 UTC; weekly ranking Sundays 04:00 UTC.}" >/dev/null 2>&1 || true; echo "[$(date -u +%FT%TZ)] $*"; }
trap 'mark "FAILED at line $LINENO"' ERR
for name in engine config; do git -C "$D/src/$name" pull --quiet --ff-only; echo "$name at $(git -C "$D/src/$name" rev-parse --short HEAD)"; done
: > "$D/status/current.log"; mark "targeted re-assessment started: $*"
LIST=$D/status/reassess-prs.txt
prio select --extract "$D/extract" --dossier "$D/dossier" --rank "$D/rank" "$@" > "$LIST"
if [ ! -s "$LIST" ]; then mark "done: nothing selected"; exit 0; fi
echo "selected: $(tr '\n' ' ' < "$LIST")"
git_arg=(); [ -d "$D/git" ] && git_arg=(--git "$D/git")
prio dossier submit --extract "$D/extract" --out "$D/dossier" "${git_arg[@]}" --only "@$LIST" --force \
  --model "$MODEL" --patch-chars "$PATCH" --max-cost "$MAX" 2>&1 | grep -E 'total|failed|ERROR|estimated|need' || true
mark "dossiers re-assessed"
prio display submit --extract "$D/extract" --dossier "$D/dossier" --out "$D/display" --model "$DMODEL" 2>&1 | grep -E 'total|failed|ERROR|need' || true
mark "display lines regenerated"
prio render --extract "$D/extract" --dossier "$D/dossier" --display "$D/display" --rank "$D/rank" --out "$D/site.new" >/dev/null
rsync -a --delete --exclude status.html --exclude status.json --exclude status/ "$D/site.new/" "$SITE/"
mark "done: site published after re-assessment of $(wc -l < "$LIST") PRs"
