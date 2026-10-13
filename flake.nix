{
  description = "Atticus: macOS voice and AI assistant";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    nixpkgs-darwin-legacy.url = "github:NixOS/nixpkgs/nixpkgs-26.05-darwin";
  };

  outputs =
    {
      self,
      nixpkgs,
      nixpkgs-darwin-legacy,
    }:
    let
      version = "1.0";
      targetSystems = [
        "aarch64-darwin"
        "x86_64-darwin"
      ];
      forEachSystem =
        f:
        builtins.listToAttrs (
          map (system: {
            name = system;
            value = f system;
          }) targetSystems
        );
      pkgsFor =
        system:
        if system == "x86_64-darwin" then
          nixpkgs-darwin-legacy.legacyPackages.${system}
        else
          nixpkgs.legacyPackages.${system};
      packageFor =
        system:
        let
          pkgs = pkgsFor system;
        in
        pkgs.writeShellApplication {
          name = "atticus";
          runtimeInputs = [ pkgs.python313 ];
          text = ''
            set -euo pipefail
            src=${./.}
            case "''${1:-}" in
              ""|install|--install|build|--build)
                exec bash "$src/install.sh"
                ;;
              --check)
                python3 -c 'import pathlib, sys; compile(pathlib.Path(sys.argv[1]).read_text(), sys.argv[1], "exec")' "$src/atticus.py"
                bash -n "$src/build.sh"
                bash -n "$src/install.sh"
                printf '%s\n' 'atticus source checks passed'
                ;;
              --version)
                printf '%s\n' "atticus ${version}"
                ;;
              --help|-h|help)
                cat <<'EOF'
            Atticus launcher for macOS.

            Usage:
              atticus              Install or update Atticus.app
              atticus --install    Install or update Atticus.app
              atticus --check      Run packaged source checks
              atticus --version    Print the packaged version
              atticus --help       Show this help

            Building requires macOS 26 or later and Apple's command line tools.
            Full use also requires a paid Claude plan and Claude Code.
            EOF
                ;;
              *)
                printf 'Unknown option: %s\n\n' "$1" >&2
                exec "$0" --help
                ;;
            esac
          '';
          meta = with pkgs.lib; {
            description = "Atticus macOS app launcher";
            homepage = "https://github.com/SaarthurR/atticus-mac";
            license = licenses.mit;
            mainProgram = "atticus";
            platforms = targetSystems;
          };
        };
    in
    {
      packages = forEachSystem (
        system:
        let
          atticus = packageFor system;
        in
        {
          inherit atticus;
          atticus-mac = atticus;
          source = atticus;
          default = atticus;
        }
      );

      apps = forEachSystem (
        system:
        let
          atticus = self.packages.${system}.default;
          program = "${atticus}/bin/atticus";
          app = {
            type = "app";
            inherit program;
            inherit (atticus) meta;
          };
        in
        {
          atticus = app;
          atticus-mac = app;
          default = app;
        }
      );

      checks = forEachSystem (system: {
        package = self.packages.${system}.default;
      });

      devShells = forEachSystem (system: {
        default =
          let
            pkgs = pkgsFor system;
          in
          pkgs.mkShell {
            packages = [
              pkgs.python313
              pkgs.act
            ];
            shellHook = ''
              echo "Atticus development shell. Building the app requires Apple's command line tools."
            '';
          };
      });

      formatter = forEachSystem (system: (pkgsFor system).nixfmt);
    };
}
