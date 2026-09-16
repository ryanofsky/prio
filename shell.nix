# Development shell for the prio engine.
#
#   nix-shell            # from this directory
#   prio --help          # the CLI, run from the checkout (no install needed)
#
# Provides Python with the Anthropic SDK plus jq, puts this checkout on
# PYTHONPATH so `python3 -m prio.cli` works from any directory, and defines
# a `prio` shell function for it. If ~/.config/prio/api-key exists it is
# exported as ANTHROPIC_API_KEY for the shell session. Set PRIO_CONFIG to a
# config repo checkout to omit --config on every command.
{ pkgs ? import <nixpkgs> { } }:

pkgs.mkShell {
  packages = [
    (pkgs.python3.withPackages (ps: [ ps.anthropic ]))
    pkgs.jq
  ];

  shellHook = ''
    export PYTHONPATH="${toString ./.}''${PYTHONPATH:+:$PYTHONPATH}"
    prio() { python3 -m prio.cli "$@"; }
    export -f prio
    if [ -z "''${ANTHROPIC_API_KEY:-}" ] && [ -r "$HOME/.config/prio/api-key" ]; then
      export ANTHROPIC_API_KEY="$(cat "$HOME/.config/prio/api-key")"
    fi
  '';
}
