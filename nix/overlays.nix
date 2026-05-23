# nix/overlays.nix — Expose the inherited pkgs.hermes-agent overlay
{ inputs, ... }:
{
  flake.overlays.default = final: _: {
    hermes-agent = final.callPackage ./hermes-agent.nix {
      inherit (inputs) uv2nix pyproject-nix pyproject-build-systems;
      npm-lockfile-fix = inputs.npm-lockfile-fix.packages.${final.stdenv.hostPlatform.system}.default;
      rev = inputs.self.rev or null;
    };
  };
}
