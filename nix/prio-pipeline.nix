# NixOS module: run the prio pipeline on a schedule and serve nothing itself.
#
# Each run: pull the engine and config repos, fetch open PR heads into a
# local clone, extract, assess changed PRs (Batch API, capped by cost),
# write display lines, render the static site into `siteDir`. Serving is
# left to nginx (see the host config). The API key is read from
# `apiKeyFile`, provisioned out of band; the service is skipped until it
# exists.
#
# The engine's Python code needs a newer Anthropic SDK than nixpkgs may
# carry, so the service keeps a pinned venv under dataDir/venv (created on
# first run, reused after).
{ config, lib, pkgs, ... }:

let
  cfg = config.services.prio;
  py = pkgs.python3;
  runScript = pkgs.writeShellScript "prio-run" ''
    set -euo pipefail
    export PATH="${lib.makeBinPath [ pkgs.bash pkgs.git pkgs.coreutils pkgs.gawk pkgs.findutils pkgs.gnugrep pkgs.gnused pkgs.jq py pkgs.rsync pkgs.cacert ]}:$PATH"
    export SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt
    export HOME=${cfg.dataDir}
    D=${cfg.dataDir}
    mkdir -p "$D/logs" "$D/status"
    exec > >(tee -a "$D/logs/run-$(date -u +%Y%m%d-%H%M).log") 2>&1
    : > "$D/status/current.log"
    log() { echo "[$(date -u +%FT%TZ)] $*"; }
    mark() {
      echo "$(date -u +%FT%TZ) $*" >> "$D/status/current.log"
      if [ -x "$D/venv/bin/python" ]; then
        PYTHONPATH="$D/src/engine" "$D/venv/bin/python" -m prio.cli --config "$D/src/config" status-page \
          --data-dir "$D" --site-dir ${lib.escapeShellArg cfg.siteDir} --next-runs ${lib.escapeShellArg cfg.scheduleText} >/dev/null 2>&1 || true
      fi
    }
    trap 'mark "FAILED at line $LINENO"' ERR
    mark "run started"

    # --- code checkouts (pinned by branch; a run is reproducible from the two commits logged below)
    for pair in "engine=${cfg.engineRepo}" "config=${cfg.configRepo}"; do
      name=''${pair%%=*}; url=''${pair#*=}
      if [ ! -d "$D/src/$name/.git" ]; then git clone --quiet "$url" "$D/src/$name"; fi
      git -C "$D/src/$name" pull --quiet --ff-only
      log "$name at $(git -C "$D/src/$name" rev-parse --short HEAD)"
    done

    # --- python env with the pinned SDK
    if [ ! -x "$D/venv/bin/python" ]; then
      ${py}/bin/python3 -m venv "$D/venv"
      "$D/venv/bin/pip" install --quiet "anthropic==${cfg.sdkVersion}"
    fi
    export PYTHONPATH="$D/src/engine"
    export ANTHROPIC_API_KEY="$(cat ${cfg.apiKeyFile})"
    ${lib.optionalString (cfg.openrouterKeyFile != null) ''[ -r ${cfg.openrouterKeyFile} ] && export OPENROUTER_API_KEY="$(cat ${cfg.openrouterKeyFile})"''}
    export PRIO_OPENROUTER_WORKERS=${toString cfg.openrouterWorkers}
    prio() { "$D/venv/bin/python" -m prio.cli --config "$D/src/config" "$@"; }
    mark "code and environment ready"

    # --- data
    ${lib.optionalString (cfg.projectRepo != null) ''
      log "git sidecar"
      if ! prio git --repo "$D/bitcoin.git" --url ${lib.escapeShellArg cfg.projectRepo} \
          --extract "$D/extract" --out "$D/git" --budget-chars ${toString cfg.patchChars} >/dev/null 2>"$D/git.log"; then
        log "WARNING: git sidecar failed; continuing without diffs. Last lines of git.log:"; tail -5 "$D/git.log"
      fi
    ''}
    log "refs index"
    bash "$D/src/engine/scripts/refs-index.sh" ${lib.escapeShellArg cfg.backupDir} > "$D/refs-index.tsv"
    mark "git sidecar done"
    log "extract"
    prio extract --backup ${lib.escapeShellArg cfg.backupDir} --out "$D/extract" \
      --refs-index "$D/refs-index.tsv" ${lib.optionalString (cfg.projectRepo != null) ''--git "$D/git"''}
    ${lib.optionalString (cfg.projectRepo != null) ''
      # second sidecar pass now that extract knows the current heads (first pass may predate a new PR)
      prio git --repo "$D/bitcoin.git" --url ${lib.escapeShellArg cfg.projectRepo} \
        --extract "$D/extract" --out "$D/git" --budget-chars ${toString cfg.patchChars} >/dev/null 2>>"$D/git.log" \
        || { log "WARNING: second sidecar pass failed"; tail -3 "$D/git.log"; }
      prio extract --backup ${lib.escapeShellArg cfg.backupDir} --out "$D/extract" --refs-index "$D/refs-index.tsv" --git "$D/git"
    ''}

    mark "extract done"

    # --- model stages (batch; wait for results)
    log "dossier submit (max cost ${toString cfg.maxCost})"
    prio dossier submit --extract "$D/extract" --out "$D/dossier" ${lib.optionalString (cfg.projectRepo != null) ''--git "$D/git"''} \
      --model ${cfg.model} --effort ${cfg.effort} --patch-chars ${toString cfg.patchChars} --max-cost ${toString cfg.maxCost} \
      --agreement-reads ${toString cfg.agreementReads}
    mark "dossier batch submitted, waiting"
    prio dossier collect --out "$D/dossier" --wait
    mark "dossiers collected"
    log "display submit"
    prio display submit --extract "$D/extract" --dossier "$D/dossier" --out "$D/display" --model ${cfg.displayModel}
    mark "display batch submitted, waiting"
    prio display collect --out "$D/display" --wait
    mark "display collected"

    # --- site (rank output, if any, from the weekly prio-rank service)
    log "render"
    prio render --extract "$D/extract" --dossier "$D/dossier" --display "$D/display" --rank "$D/rank" --out "$D/site.new"
    rsync -a --delete --exclude status.html --exclude status.json --exclude status/ "$D/site.new/" ${lib.escapeShellArg cfg.siteDir}/
    log "done"
    mark "done: site published"
  '';
  rankScript = pkgs.writeShellScript "prio-rank" ''
    set -euo pipefail
    export PATH="${lib.makeBinPath [ pkgs.bash pkgs.git pkgs.coreutils pkgs.rsync pkgs.cacert ]}:$PATH"
    export SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt
    export HOME=${cfg.dataDir}
    D=${cfg.dataDir}
    export PYTHONPATH="$D/src/engine"
    export ANTHROPIC_API_KEY="$(cat ${cfg.apiKeyFile})"
    prio() { "$D/venv/bin/python" -m prio.cli --config "$D/src/config" "$@"; }
    mkdir -p "$D/logs" "$D/status"
    exec > >(tee -a "$D/logs/rank-$(date -u +%Y%m%d-%H%M).log") 2>&1
    mark() { echo "$(date -u +%FT%TZ) $*" >> "$D/status/current.log"; prio status-page --data-dir "$D" --site-dir ${lib.escapeShellArg cfg.siteDir} --next-runs ${lib.escapeShellArg cfg.scheduleText} >/dev/null 2>&1 || true; }
    : > "$D/status/current.log"; mark "ranking pass started"
    echo "[$(date -u +%FT%TZ)] rank (only categories changed since last pass)"
    prio rank --extract "$D/extract" --dossier "$D/dossier" --display "$D/display" --out "$D/rank" --model ${cfg.rankModel} --effort ${cfg.rankEffort}
    echo "[$(date -u +%FT%TZ)] render"
    prio render --extract "$D/extract" --dossier "$D/dossier" --display "$D/display" --rank "$D/rank" --out "$D/site.new"
    rsync -a --delete --exclude status.html --exclude status.json --exclude status/ "$D/site.new/" ${lib.escapeShellArg cfg.siteDir}/
    echo "[$(date -u +%FT%TZ)] done"
    mark "done: ranking published"
  '';
in
{
  options.services.prio = {
    agreementReads = lib.mkOption { type = lib.types.int; default = 1; description = "2 = a second, thread-only read of the agreement merged by union (catches omitted objections; ~40% more dossier cost)"; };
    rankModel = lib.mkOption { type = lib.types.str; default = "claude-opus-5"; };
    rankEffort = lib.mkOption { type = lib.types.str; default = "high"; };
    scheduleText = lib.mkOption { type = lib.types.str; default = "Daily run at 01:00 UTC; weekly ranking pass on Sundays at 04:00 UTC."; description = "shown on the status page"; };
    rankOnCalendar = lib.mkOption { type = lib.types.nullOr lib.types.str; default = null; description = "weekly ranking pass schedule, e.g. \"Sun *-*-* 03:00:00\"; null disables"; };
    enable = lib.mkEnableOption "the prio review-priority pipeline";
    dataDir = lib.mkOption { type = lib.types.str; default = "/var/lib/prio"; };
    siteDir = lib.mkOption { type = lib.types.str; default = "/var/lib/prio/site"; description = "where the rendered site goes (nginx root)"; };
    engineRepo = lib.mkOption { type = lib.types.str; default = "https://github.com/ryanofsky/prio.git"; };
    configRepo = lib.mkOption { type = lib.types.str; description = "config repo URL (project.toml, categories/)"; };
    projectRepo = lib.mkOption { type = lib.types.nullOr lib.types.str; default = null; description = "git URL of the project being ranked, for diffs; null disables the sidecar"; };
    backupDir = lib.mkOption { type = lib.types.str; description = "github-metadata-backup dir with pulls/ and issues/"; };
    apiKeyFile = lib.mkOption { type = lib.types.str; default = "/var/lib/prio/api-key"; };
    openrouterKeyFile = lib.mkOption { type = lib.types.nullOr lib.types.str; default = "/var/lib/prio/openrouter-key"; description = "for models named openrouter/<id>"; };
    openrouterWorkers = lib.mkOption { type = lib.types.int; default = 8; };
    model = lib.mkOption { type = lib.types.str; default = "claude-sonnet-5"; };
    displayModel = lib.mkOption { type = lib.types.str; default = "claude-sonnet-5"; };
    effort = lib.mkOption { type = lib.types.str; default = "medium"; };
    maxCost = lib.mkOption { type = lib.types.float; default = 1.5; description = "USD; a run whose estimate exceeds this submits nothing"; };
    patchChars = lib.mkOption { type = lib.types.int; default = 40000; };
    sdkVersion = lib.mkOption { type = lib.types.str; default = "0.97.0"; };
    onCalendar = lib.mkOption { type = lib.types.str; default = "*-*-* 01:00:00"; };
    user = lib.mkOption { type = lib.types.str; default = "prio"; };
    extraGroups = lib.mkOption { type = lib.types.listOf lib.types.str; default = [ ]; description = "e.g. the backup data's group, for read access"; };
  };

  config = lib.mkIf cfg.enable {
    users.users.${cfg.user} = { isSystemUser = true; group = cfg.user; home = cfg.dataDir; extraGroups = cfg.extraGroups; };
    users.groups.${cfg.user} = { };
    systemd.tmpfiles.rules = [
      "d ${cfg.dataDir} 0755 ${cfg.user} ${cfg.user} -"
      "d ${cfg.siteDir} 0755 ${cfg.user} ${cfg.user} -"
    ];
    systemd.services.prio = {
      description = "prio pipeline: extract, assess, render";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      unitConfig.ConditionPathExists = cfg.apiKeyFile;
      serviceConfig = {
        Type = "oneshot";
        User = cfg.user;
        Group = cfg.user;
        ExecStart = runScript;
        TimeoutStartSec = "8h";
        Nice = 10;
      };
    };
    systemd.timers.prio = {
      description = "daily prio pipeline";
      wantedBy = [ "timers.target" ];
      timerConfig = { OnCalendar = cfg.onCalendar; Persistent = true; RandomizedDelaySec = "10m"; };
    };
    systemd.services.prio-rank = lib.mkIf (cfg.rankOnCalendar != null) {
      description = "prio ranking pass: compare all PRs in each changed category";
      after = [ "network-online.target" "prio.service" ];
      wants = [ "network-online.target" ];
      unitConfig.ConditionPathExists = cfg.apiKeyFile;
      serviceConfig = { Type = "oneshot"; User = cfg.user; Group = cfg.user; ExecStart = rankScript; TimeoutStartSec = "3h"; Nice = 10; };
    };
    systemd.timers.prio-rank = lib.mkIf (cfg.rankOnCalendar != null) {
      description = "weekly prio ranking pass";
      wantedBy = [ "timers.target" ];
      timerConfig = { OnCalendar = cfg.rankOnCalendar; Persistent = true; RandomizedDelaySec = "10m"; };
    };
  };
}
