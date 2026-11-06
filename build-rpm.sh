#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# build-rpm.sh -- build libretech-gpio and libretech-dtoverlay for Fedora (noarch RPMs), the same files as the .deb.
#
#   build-rpm.sh --src <exported source tree> --version YYYY.MM.DD [--out DIR]
#
# --src is an exported commit (git archive), never a working tree: an untracked overlay must not reach a package.
# Needs make, cpp, dtc, python3 and rpmbuild. The packages are unsigned: they are signed with the repository key when
# published. Output: the .rpm files in DIR [./out/<version>]; their paths are the last lines on stdout.

set -euo pipefail
IFS=$'\n\t'
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/packaging/lib.sh"

src="" version="" out=""
while (($#)); do
  case $1 in
    --src) src=${2:?}; shift 2 ;;
    --version) version=${2:?}; shift 2 ;;
    --out) out=${2:?}; shift 2 ;;
    *) die "usage: build-rpm.sh --src <tree> --version YYYY.MM.DD [--out DIR]" ;;
  esac
done
[[ -n $src && -n $version ]] || die "usage: build-rpm.sh --src <tree> --version YYYY.MM.DD [--out DIR]"
check_version "$version"
out=${out:-$PWD/out/$version}
command -v rpmbuild >/dev/null || die "rpmbuild not found (the rpm package)"

T=$(mktemp -d /var/tmp/lwt-rpm.XXXXXX)
trap 'rm -rf "$T"' EXIT
stage_tree "$src" "$T"
split_tree "$T"

# rpm's file lists: every path absolute, plus the directories above it from /opt/librecomputer down, so each
# package owns the directories it fills (a directory two packages own is allowed)
for p in "${PACKAGES[@]}"; do
  {
    while IFS= read -r rel; do
      d=$(dirname "$rel")
      while [[ $d == opt/librecomputer* ]]; do printf '%%dir /%s\n' "$d"; d=$(dirname "$d"); done
    done <"$T/$p.list" | sort -u
    sed 's#^#/#' "$T/$p.list"
  } >"$T/$p.files"
done

mkdir -p "$T/rpm/SPECS" "$out"
cp "$PKG_ROOT/packaging/rpm/libretech-wiring-tool.spec" "$T/rpm/SPECS/"
log "building libretech-gpio, libretech-dtoverlay $version"
rpmbuild --define "_topdir $T/rpm" --define "_buildhost $BUILD_HOST" --define "lc_version $version" \
  --define "lc_stage $T/root" --define "lc_lists $T" -bb "$T/rpm/SPECS/libretech-wiring-tool.spec" \
  >"$T/rpmbuild.log" 2>&1 || { tail -20 "$T/rpmbuild.log" >&2; die "rpmbuild failed"; }
for p in "${PACKAGES[@]}"; do
  cp "$T/rpm/RPMS/noarch/$p-$version-1.noarch.rpm" "$out/"
  echo "$out/$p-$version-1.noarch.rpm"
done
