# nix/packages.nix — Superforecasting Agent package built with uv2nix
{ inputs, ... }:
{
  perSystem =
    { pkgs, inputs', ... }:
    let
      superforecastingAgent = pkgs.callPackage ./superforecasting-agent.nix {
        inherit (inputs) uv2nix pyproject-nix pyproject-build-systems;
        npm-lockfile-fix = inputs'.npm-lockfile-fix.packages.default;
        # Only embed clean revs — dirtyRev doesn't represent any upstream
        # commit, so comparing it would always claim "update available".
        rev = inputs.self.rev or null;
      };
    in
    {
      packages = {
        default = superforecastingAgent;
        "superforecasting-agent" = superforecastingAgent;
        "hermes-agent" = superforecastingAgent;
        tui = superforecastingAgent.superforecastingAgentTui;
        web = superforecastingAgent.superforecastingAgentWeb;

        fix-lockfiles = superforecastingAgent.superforecastingAgentNpmLib.mkFixLockfiles {
          packages = [ superforecastingAgent.superforecastingAgentTui superforecastingAgent.superforecastingAgentWeb ];
        };
      };

      # Runnable entrypoints. `packages.tui` is just the built JS bundle (a
      # build input), not an executable — so launching the TUI goes through the
      # fully-wrapped `superforecasting-agent` binary (it already sets
      # *_TUI_DIR / *_PYTHON / *_NODE) with --tui:
      #     nix run github:teddyjfpender/superforecasting-agent#tui
      apps = {
        default = {
          type = "app";
          program = "${superforecastingAgent}/bin/superforecasting-agent";
        };
        tui = {
          type = "app";
          program = toString (pkgs.writeShellScript "superforecasting-agent-tui" ''
            exec ${superforecastingAgent}/bin/superforecasting-agent --tui "$@"
          '');
        };
      };
    };
}
