#!/usr/bin/env bash
# Build a site from (engine, config, data) into a directory. The live site,
# a preview, and a private view are all this with different arguments.
#
#   site-build.sh --name rows                       # render the live data with the checked-out engine and config
#   site-build.sh --name wallet --config-ref topic  # config repo at a branch, worktree under $D/preview/wallet/config
#   site-build.sh --name p2 --engine-ref topic --stages judge,display --only 123,456 --max-cost 2
#   site-build.sh --config /var/lib/prio/src/local --out /var/lib/prio/local/site   # a private view
#   site-build.sh --remove rows
#
# --name NAME writes to $SITE/preview/NAME/ (public, under the live site) and
# adds the preview to $SITE/preview/index.html; --out DIR writes anywhere.
# With --stages, the data is a git worktree of the data repo on branch
# preview/NAME (the live data is never touched) and the named stages run
# there first, restricted to --only, before the render. Without --stages
# the build is a render only: seconds, no model call, reads the live data.
#
# Environment (defaults match the NixOS module): PRIO_DATA_ROOT=/var/lib/prio,
# PRIO_SITE=$PRIO_DATA_ROOT/site, PRIO_MODEL for the stages.
set -euo pipefail
D=${PRIO_DATA_ROOT:-/var/lib/prio}; SITE=${PRIO_SITE:-$D/site}
MODEL=${PRIO_MODEL:-openrouter/google/gemini-3.8-flash}
name=""; out=""; engine="$D/src/engine"; config="$D/src/config"; data="$D/data"
engine_ref=""; config_ref=""; stages=""; only=""; max_cost=""; remove=""; note=""
while [ $# -gt 0 ]; do
  case "$1" in
    --name) name=$2; shift 2;;
    --out) out=$2; shift 2;;
    --engine) engine=$2; shift 2;;
    --engine-ref) engine_ref=$2; shift 2;;
    --config) config=$2; shift 2;;
    --config-ref) config_ref=$2; shift 2;;
    --data) data=$2; shift 2;;
    --stages) stages=$2; shift 2;;
    --only) only=$2; shift 2;;
    --max-cost) max_cost=$2; shift 2;;
    --note) note=$2; shift 2;;
    --remove) remove=$2; shift 2;;
    *) echo "unknown argument $1" >&2; exit 2;;
  esac
done

index() {  # rewrite $SITE/preview/index.html from each preview's meta.json
  "$D/venv/bin/python" - "$SITE/preview" <<'PY'
import json, sys, glob, os, html
root = sys.argv[1]
rows = []
for m in sorted(glob.glob(os.path.join(root, "*", "meta.json"))):
    d = json.load(open(m)); n = os.path.basename(os.path.dirname(m))
    rows.append(f'<tr><td><a href="{html.escape(n)}/index.html">{html.escape(n)}</a></td><td>{html.escape(d.get("built",""))}</td>'
                f'<td>{html.escape(d.get("engine",""))}</td><td>{html.escape(d.get("config",""))}</td><td>{html.escape(d.get("stages") or "render only")}</td>'
                f'<td>{html.escape(d.get("only") or "")}</td><td>{html.escape(d.get("note") or "")}</td></tr>')
body = ("<!doctype html><meta charset=utf-8><title>previews</title><style>body{font-family:system-ui,sans-serif;margin:1.5rem}table{border-collapse:collapse}"
        "td,th{border:1px solid #ddd;padding:.3rem .6rem;text-align:left;font-size:.9rem}</style><h1>Previews</h1>"
        "<p>Builds of the site from a branch or a changed file, against the live data or a copy of it. Not the live site: <a href=\"../index.html\">home</a>.</p>"
        "<table><tr><th>name</th><th>built</th><th>engine</th><th>config</th><th>stages</th><th>PRs</th><th>note</th></tr>" + "".join(rows) + "</table>")
open(os.path.join(root, "index.html"), "w").write(body)
PY
}

if [ -n "$remove" ]; then
  rm -rf "$SITE/preview/$remove" "$D/preview/$remove"
  git -C "$data" worktree prune 2>/dev/null || true
  index; echo "removed preview $remove"; exit 0
fi
[ -n "$name" ] || [ -n "$out" ] || { echo "need --name NAME or --out DIR" >&2; exit 2; }
[ -n "$out" ] || out="$SITE/preview/$name"
work="$D/preview/${name:-adhoc}"; mkdir -p "$work"

checkout() {  # $1 label, $2 repo dir, $3 ref -> prints a worktree path at that ref
  local repo=$2 ref=$3 dir="$work/$1"
  git -C "$repo" fetch --quiet origin "+refs/heads/*:refs/remotes/origin/*" 2>/dev/null || true
  if [ -d "$dir/.git" ] || [ -f "$dir/.git" ]; then git -C "$dir" checkout --quiet --detach "$ref"; else git -C "$repo" worktree add --quiet --detach "$dir" "$ref"; fi
  echo "$dir"
}
[ -z "$engine_ref" ] || engine=$(checkout engine "$D/src/engine" "$engine_ref")
[ -z "$config_ref" ] || config=$(checkout config "$D/src/config" "$config_ref")
export HOME=$D PYTHONPATH=$engine PRIO_OPENROUTER_WORKERS=${PRIO_OPENROUTER_WORKERS:-4}
[ -r "$D/api-key" ] && export ANTHROPIC_API_KEY="$(cat "$D/api-key")"
[ -r "$D/openrouter-key" ] && export OPENROUTER_API_KEY="$(cat "$D/openrouter-key")"
prio() { "$D/venv/bin/python" -m prio.cli --config "$config" "$@"; }
log() { echo "[$(date -u +%FT%TZ)] $*"; }
log "engine $(git -C "$engine" rev-parse --short HEAD 2>/dev/null || echo "$engine"), config $(git -C "$config" rev-parse --short HEAD 2>/dev/null || echo "$config")"

if [ -n "$stages" ]; then
  [ -n "$name" ] || { echo "--stages needs --name (the data copy is named after it)" >&2; exit 2; }
  copy="$work/data"
  if [ ! -e "$copy/.git" ]; then
    git -C "$data" worktree add --quiet -B "preview/$name" "$copy" HEAD
  fi
  data=$copy
  onlyarg=(); [ -z "$only" ] || onlyarg=(--only "$only")
  case ",$stages," in *,judge,*)
    log "judgments on the copy (category and priority hashes decide what is stale)"
    prio ledger assess --extract "$D/extract" --data "$data" --git "$D/git" --model "$MODEL" --what judge "${onlyarg[@]}" 2>&1 | grep -E "PRs:|total|ERROR" || true;;
  esac
  case ",$stages," in *,display,*)
    log "display lines on the copy"
    prio display submit --extract "$D/extract" --data "$data" --out "$data/display" --model "${PRIO_DISPLAY_MODEL:-$MODEL}" "${onlyarg[@]}" 2>&1 | grep -E "dossiers|total|ERROR" || true;;
  esac
  git -C "$data" add -A && git -C "$data" commit --quiet -m "preview $name: $stages" || true
fi

log "render to $out"
prio render --extract "$D/extract" --data "$data" --display "$data/display" --rank "$data/rank" --out "$work/site.new" >/dev/null
mkdir -p "$out"; rsync -a --delete "$work/site.new/" "$out/"; rm -rf "$work/site.new"
if [ -n "$name" ] && [ "$out" = "$SITE/preview/$name" ]; then
  printf '{"built":"%s","engine":"%s","config":"%s","stages":"%s","only":"%s","note":"%s"}\n' "$(date -u +%FT%TZ)" \
    "$(git -C "$engine" rev-parse --short HEAD 2>/dev/null || true)${engine_ref:+ ($engine_ref)}" \
    "$(git -C "$config" rev-parse --short HEAD 2>/dev/null || basename "$config")${config_ref:+ ($config_ref)}" "$stages" "$only" "$note" > "$out/meta.json"
  index
  log "preview at ${PRIO_SITE_URL:-https://prio.ofsky.org}/preview/$name/"
fi
log "done"
