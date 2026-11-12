{
  description = "coupled-tags-lint: check the COUPLED:<key>:[<relation>] tags in a repository, and that their relations hold";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
  # COUPLED:cli-kit-version:[=; @/cli-kit/(v[0-9.]+)/]
  inputs.cli-kit = { url = "github:ianflanagan1/cli-kit/v0.1.0"; flake = false; };

  outputs = { self, nixpkgs, cli-kit }:
    let
      systems = [ "aarch64-darwin" "x86_64-darwin" "aarch64-linux" "x86_64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      packages = forAllSystems (pkgs: rec {
        # Python and the tools the lint calls are pinned, so it behaves the same on macOS, Linux and CI.
        # cli-kit uses only the standard library, so its source on the path is all it needs.
        coupled-tags-lint = pkgs.writeShellApplication {
          name = "coupled-tags-lint";
          runtimeInputs = [ pkgs.git pkgs.gnugrep ];
          text = ''
            PYTHONPATH=${./src}:${cli-kit}/src exec ${pkgs.python313}/bin/python3 -s -P -m coupled_tags_lint "$@"
          '';
        };
        default = coupled-tags-lint;
      });
    };
}
