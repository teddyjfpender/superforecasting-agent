# nix/tui.nix — Superforecasting Agent TUI (Ink/React) compiled with tsc and bundled
{ pkgs, superforecastingAgentNpmLib, ... }:
let
  src = ../ui-tui;
  npmDeps = pkgs.fetchNpmDeps {
    inherit src;
    hash = "sha256-dNL/J4tyQQ7Ji3xfIE5b5Jdi6rQyCFjqYpzLYftJVdc=";
  };

  npm = superforecastingAgentNpmLib.mkNpmPassthru { folder = "ui-tui"; attr = "tui"; pname = "superforecasting-agent-tui"; };

  packageJson = builtins.fromJSON (builtins.readFile (src + "/package.json"));
  version = packageJson.version;
in
pkgs.buildNpmPackage (npm // {
  pname = "superforecasting-agent-tui";
  inherit src npmDeps version;

  doCheck = false;
  npmFlags = [ "--legacy-peer-deps" ];

  installPhase = ''
    runHook preInstall

    mkdir -p $out/lib/superforecasting-agent-tui

    # Single self-contained bundle built by scripts/build.mjs (esbuild).
    cp -r dist $out/lib/superforecasting-agent-tui/dist

    # package.json kept for "type": "module" resolution on `node dist/entry.js`.
    cp package.json $out/lib/superforecasting-agent-tui/

    runHook postInstall
  '';
})
