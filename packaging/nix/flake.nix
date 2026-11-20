# SPDX-FileCopyrightText: 2021-2026 Libre Computer Project contributors
# SPDX-License-Identifier: GPL-2.0-only
# libretech-wiring-tool as a Nix flake (infra multi-distro plan, NixOS row of the wiring tool): lgpio and ldto with
# every board's maps and overlays, built from the same source as the .deb, .rpm and pacman packages. Cut per release
# by the release process (Libre Computer's pkg-mkflake.sh, --src embed), which puts the commit's tree in ./src.tar
# and the version in ./version.nix; this
# directory alone is not a flake. nixpkgs is the newest NixOS stable channel, pinned by flake.lock (the same pin as
# the kernel, Mesa and gaema-desktop flakes), so a host following it takes the build from packages.libre.computer's
# Nix cache.
#
# The other formats ship two packages into one install root; ldto reads lgpio's gpio.map from its own root, so here
# they are one store path, offered under both names (installing both is one path, never a collision).
{
  description = "Libre Computer wiring tool: lgpio, ldto and the board device-tree overlays";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      version = import ./version.nix;
      forAll = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
      lwt = pkgs: pkgs.callPackage ./package.nix { src = ./src.tar; inherit version; };
    in
    {
      packages = forAll (pkgs: rec {
        libretech-wiring-tool = lwt pkgs;
        libre-computer-gpio = libretech-wiring-tool;
        libre-computer-dtoverlay = libretech-wiring-tool;
        default = libretech-wiring-tool;
      });
      overlays.default = final: _prev: { libretech-wiring-tool = lwt final; };
    };
}
