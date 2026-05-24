# nix/overlays.nix — Expose fork-native and compatibility package aliases
{ inputs, ... }:
{
  flake.overlays.default = final: _:
    let
      superforecastingAgent = final.callPackage ./hermes-agent.nix {
        inherit (inputs) uv2nix pyproject-nix pyproject-build-systems;
        npm-lockfile-fix = inputs.npm-lockfile-fix.packages.${final.stdenv.hostPlatform.system}.default;
        rev = inputs.self.rev or null;
      };
    in {
      "superforecasting-agent" = superforecastingAgent;
      "hermes-agent" = superforecastingAgent;
    };
}
