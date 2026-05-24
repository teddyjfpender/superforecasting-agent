# nix/packages.nix — Superforecasting Agent package built with uv2nix
{ inputs, ... }:
{
  perSystem =
    { pkgs, inputs', ... }:
    let
      superforecastingAgent = pkgs.callPackage ./hermes-agent.nix {
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
        tui = superforecastingAgent.hermesTui;
        web = superforecastingAgent.hermesWeb;

        fix-lockfiles = superforecastingAgent.hermesNpmLib.mkFixLockfiles {
          packages = [ superforecastingAgent.hermesTui superforecastingAgent.hermesWeb ];
        };
      };
    };
}
