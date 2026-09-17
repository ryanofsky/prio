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
    log() { echo "[$(date -u +%FT%TZ)] $*"; }

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
    prio() { "$D/venv/bin/python" -m prio.cli --config "$D/src/config" "$@"; }

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

    # --- model stages (batch; wait for results)
    log "dossier submit (max cost ${toString cfg.maxCost})"
    prio dossier submit --extract "$D/extract" --out "$D/dossier" ${lib.optionalString (cfg.projectRepo != null) ''--git "$D/git"''} \
      --model ${cfg.model} --effort ${cfg.effort} --patch-chars ${toString cfg.patchChars} --max-cost ${toString cfg.maxCost}
    prio dossier collect --out "$D/dossier" --wait
    log "display submit"
    prio display submit --extract "$D/extract" --dossier "$D/dossier" --out "$D/display" --model ${cfg.displayModel}
    prio display collect --out "$D/display" --wait

    # --- site
    log "render"
    prio render --extract "$D/extract" --dossier "$D/dossier" --display "$D/display" --out "$D/site.new"
    rsync -a --delete "$D/site.new/" ${lib.escapeShellArg cfg.siteDir}/
    log "done"
  '';
in
{
  options.services.prio = {
    enable = lib.mkEnableOption "the prio review-priority pipeline";
    dataDir = lib.mkOption { type = lib.types.str; default = "/var/lib/prio"; };
    siteDir = lib.mkOption { type = lib.types.str; default = "/var/lib/prio/site"; description = "where the rendered site goes (nginx root)"; };
    engineRepo = lib.mkOption { type = lib.types.str; default = "https://github.com/ryanofsky/prio.git"; };
    configRepo = lib.mkOption { type = lib.types.str; description = "config repo URL (project.toml, categories/)"; };
    projectRepo = lib.mkOption { type = lib.types.nullOr lib.types.str; default = null; description = "git URL of the project being ranked, for diffs; null disables the sidecar"; };
    backupDir = lib.mkOption { type = lib.types.str; description = "github-metadata-backup dir with pulls/ and issues/"; };
    apiKeyFile = lib.mkOption { type = lib.types.str; default = "/var/lib/prio/api-key"; };
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
  };
}
