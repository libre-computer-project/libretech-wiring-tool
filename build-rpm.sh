#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# build-rpm.sh -- build libre-computer-gpio and libre-computer-dtoverlay for Fedora (noarch RPMs), the same files as the .deb.
#
#   build-rpm.sh --src <exported source tree> --version YYYY.MM.DD [--release N] [--dist .tw|.lp<NNN>] [--out DIR]
#
# --release [1]: a packaging fix on the same source gets a new release -- a published file name never changes.
# --dist: an openSUSE copy, the same files with the release tagged for one openSUSE release (.tw Tumbleweed,
#   .lp160 Leap 16.0): the publisher places an openSUSE package by that tag, and an untagged build goes to Fedora.
#   The spec's dependencies resolve on both (libgpiod-utils, dtc, /usr/sbin/alternatives: openSUSE's
#   update-alternatives provides it).
#
# --src is an exported commit (git archive), never a working tree: an untracked overlay must not reach a package.
# Needs make, cpp, dtc, python3 and rpmbuild. The packages are unsigned: they are signed with the repository key when
# published. Output: the .rpm files in DIR [./out/<version>]; their paths are the last lines on stdout.

set -euo pipefail
IFS=$'\n\t'
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/packaging/lib.sh"

src="" version="" release=1 dist="" out=""
usage="usage: build-rpm.sh --src <tree> --version YYYY.MM.DD [--release N] [--dist .tw|.lp<NNN>] [--out DIR]"
while (($#)); do
  case $1 in
    --src) src=${2:?}; shift 2 ;;
    --version) version=${2:?}; shift 2 ;;
    --release) release=${2:?}; shift 2 ;;
    --dist) dist=${2:?}; shift 2 ;;
    --out) out=${2:?}; shift 2 ;;
    *) die "$usage" ;;
  esac
done
[[ -n $src && -n $version ]] || die "$usage"
check_version "$version"
[[ $release =~ ^[1-9][0-9]{0,2}$ ]] || die "--release $release is not 1-999"
[[ -z $dist || $dist =~ ^\.(tw|lp[0-9]{3})$ ]] || die "--dist $dist is not .tw or .lp<NNN>"
release+=$dist
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
log "building libre-computer-gpio, libre-computer-dtoverlay $version"
# vendor: the vendor zypper keeps an installed package with (the spec has no Vendor tag, so rpm takes the macro)
rpmbuild --define "_topdir $T/rpm" --define "_buildhost $BUILD_HOST" --define "vendor Libre Computer" \
  --define "lc_version $version" --define "lc_release $release" \
  --define "lc_stage $T/root" --define "lc_lists $T" -bb "$T/rpm/SPECS/libretech-wiring-tool.spec" \
  >"$T/rpmbuild.log" 2>&1 || { tail -20 "$T/rpmbuild.log" >&2; die "rpmbuild failed"; }
for p in "${PACKAGES[@]}"; do
  cp "$T/rpm/RPMS/noarch/$p-$version-$release.noarch.rpm" "$out/"
  echo "$out/$p-$version-$release.noarch.rpm"
done
