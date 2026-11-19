#!/bin/bash
# SPDX-FileCopyrightText: 2021-2026 Libre Computer Project contributors
# SPDX-License-Identifier: GPL-2.0-only
# mkflake.sh -- cut the flake packages.libre.computer publishes for one commit.
#
#   packaging/nix/mkflake.sh --commit <sha> --version YYYYMMDD.HHMMSS.g<sha8> --out DIR [--repo PATH]
#
# Writes, under DIR:
#   flake/                          this directory's flake.nix, flake.lock and package.nix, the commit's tree as
#                                   src.tar (git archive: an untracked file never reaches it) and version.nix
#   libretech-wiring-tool.tar.gz    flake/ under one top directory (Nix's tarball flakes), to publish
# The source is open and travels inside the flake, so a host evaluates the derivation the builders built and takes
# its output from the cache. --version is the commit's date and the commit, as every format takes it. Runs
# git only to read the commit; writes nothing into the repository.
set -euo pipefail
IFS=$'\n\t'
die() { echo "mkflake: $*" >&2; exit 1; }
commit="" version="" out="" repo=""
while (($#)); do
  case $1 in
    --commit) commit=${2:?}; shift 2 ;;
    --version) version=${2:?}; shift 2 ;;
    --out) out=${2:?}; shift 2 ;;
    --repo) repo=${2:?}; shift 2 ;;
    *) die "usage: mkflake.sh --commit <sha> --version YYYYMMDD.HHMMSS.g<sha8> --out DIR [--repo PATH]" ;;
  esac
done
[[ -n $commit && -n $version && -n $out ]] || die "usage: mkflake.sh --commit <sha> --version YYYYMMDD.HHMMSS.g<sha8> --out DIR [--repo PATH]"
[[ $version =~ ^[0-9]{8}\.[0-9]{6}\.g([0-9a-f]{8})$ ]] || die "--version $version is not YYYYMMDD.HHMMSS.g<sha8>"
here=$(cd "$(dirname "$0")" && pwd)
repo=${repo:-$(cd "$here/../.." && pwd)}
commit=$(git -C "$repo" rev-parse --verify "$commit^{commit}") || die "no commit $commit"
[[ $version == *.g${commit:0:8} ]] || die "--version $version does not name commit ${commit:0:8}"
mkdir -p "$out"
rm -rf "$out/flake" "$out/libretech-wiring-tool.tar.gz"
mkdir -p "$out/flake"
for f in flake.nix flake.lock package.nix; do
  git -C "$repo" show "$commit:packaging/nix/$f" >"$out/flake/$f" || die "$commit has no packaging/nix/$f"
done
# the tree as one plain tar member: it has links (board aliases), and the signing box's nix-publish takes only plain
# files and directories in a flake tarball (it reads every file's bytes, so a tar is still scanned)
git -C "$repo" archive --format=tar --prefix=src/ "$commit" >"$out/flake/src.tar"
printf '"%s"\n' "$version" >"$out/flake/version.nix"
tar -C "$out" --transform="s|^flake|libretech-wiring-tool-$version|" --owner=0 --group=0 --numeric-owner \
  --mtime=@0 --sort=name -czf "$out/libretech-wiring-tool.tar.gz" flake
echo "mkflake: $version (${commit:0:12}): $out/flake, $out/libretech-wiring-tool.tar.gz (publish)" >&2
echo "$out/libretech-wiring-tool.tar.gz"
