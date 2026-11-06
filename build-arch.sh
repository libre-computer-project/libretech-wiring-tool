#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# build-arch.sh -- build libretech-gpio and libretech-dtoverlay for Arch / Arch Linux ARM (`any` packages), the same
# files as the .deb.
#
#   build-arch.sh --src <exported source tree> --version YYYY.MM.DD [--out DIR]
#
# --src is an exported commit (git archive), never a working tree: an untracked overlay must not reach a package.
# Needs make, cpp, dtc, python3, makepkg and bsdtar. Built in /var/tmp: makepkg writes its directory into .BUILDINFO,
# and the publisher refuses a package naming a home directory. Unsigned: signed with the repository key when
# published. Output: the packages in DIR [./out/<version>]; their paths are the last lines on stdout.

set -euo pipefail
IFS=$'\n\t'
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/packaging/lib.sh"

src="" version="" out=""
while (($#)); do
  case $1 in
    --src) src=${2:?}; shift 2 ;;
    --version) version=${2:?}; shift 2 ;;
    --out) out=${2:?}; shift 2 ;;
    *) die "usage: build-arch.sh --src <tree> --version YYYY.MM.DD [--out DIR]" ;;
  esac
done
[[ -n $src && -n $version ]] || die "usage: build-arch.sh --src <tree> --version YYYY.MM.DD [--out DIR]"
check_version "$version"
out=${out:-$PWD/out/$version}
command -v makepkg >/dev/null || die "makepkg not found"

T=$(mktemp -d /var/tmp/lwt-arch.XXXXXX)
trap 'rm -rf "$T"' EXIT
stage_tree "$src" "$T"
split_tree "$T"
cp "$PKG_ROOT/packaging/arch/PKGBUILD" "$T/"
mkdir -p "$out"
log "building libretech-gpio, libretech-dtoverlay $version"
(cd "$T" && LC_VERSION=$version BUILDDIR=$T/b PKGDEST=$T/pkg PKGEXT=.pkg.tar.zst SRCDEST=$T \
  PACKAGER='autobuild <autobuild@deb.libre.computer>' makepkg --nodeps --noconfirm --force >"$T/makepkg.log" 2>&1) ||
  { tail -20 "$T/makepkg.log" >&2; die "makepkg failed"; }
for p in "${PACKAGES[@]}"; do
  f=$(find "$T/pkg" -maxdepth 1 -name "$p-$version-1-any.pkg.tar.zst")
  [[ -n $f ]] || die "makepkg made no $p-$version-1-any.pkg.tar.zst"
  cp "$f" "$out/"
  echo "$out/$(basename "$f")"
done
