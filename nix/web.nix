# nix/web.nix — Superforecasting Agent web dashboard (Vite/React) frontend build
{ pkgs, superforecastingAgentNpmLib, ... }:
let
  src = ../web;
  npmDeps = pkgs.fetchNpmDeps {
    inherit src;
    hash = "sha256-XDxoZ/FxienSOef3wywFrymgv5AYlKkjrOQpSe8mN/Y=";
  };

  npm = superforecastingAgentNpmLib.mkNpmPassthru { folder = "web"; attr = "web"; pname = "superforecasting-agent-web"; };

  packageJson = builtins.fromJSON (builtins.readFile (src + "/package.json"));
  version = packageJson.version;
in
pkgs.buildNpmPackage (npm // {
  pname = "superforecasting-agent-web";
  inherit src npmDeps version;

  doCheck = false;

  buildPhase = ''
    npx tsc -b
    npx vite build --outDir dist
  '';

  installPhase = ''
    runHook preInstall
    cp -r dist $out
    runHook postInstall
  '';
})
