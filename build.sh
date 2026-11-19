#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Build .deb packages into the parent directory (dpkg-buildpackage default).
#
#   build.sh [--version YYYYMMDD.HHMMSS.g<sha8> --commit <sha>]
#
# The version is the commit's date and the commit (packaging/lib.sh check_version), the one version every format
# takes. A release passes both: it builds an exported commit (git archive), which has no .git. Without them the
# tree's HEAD gives them, and the build is the working tree as it stands.
set -euo pipefail

cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
. packaging/lib.sh

version="" commit=""
while (($#)); do
  case $1 in
    --version) version=${2:?}; shift 2 ;;
    --commit) commit=${2:?}; shift 2 ;;
    *) die "usage: build.sh [--version YYYYMMDD.HHMMSS.g<sha8> --commit <sha>]" ;;
  esac
done
if [[ -z $version ]]; then
  [[ -z $commit ]] || die "--commit needs --version"
  commit=$(git rev-parse HEAD) || die "no --version given and no git HEAD to take it from"
  version=$(TZ=UTC git log -1 --format=%cd --date=format-local:%Y%m%d.%H%M%S "$commit").g${commit:0:8}
fi
[[ -n $commit ]] || die "--version needs --commit"
check_version "$version"
dateutc=$(date -Ru)

# Stamp a changelog entry for this build only (native package, single entry is fine), and put the tracked changelog
# back afterwards so a build never leaves the tree dirty.
cp -p debian/changelog debian/changelog.build-orig
trap 'mv -f debian/changelog.build-orig debian/changelog' EXIT
cat > debian/changelog <<EOF
libretech-wiring-tool ($version) unstable; urgency=medium

  * Build $commit

 -- Da Xue <da@libre.computer>  $dateutc
EOF

dpkg-buildpackage -uc -us --build=all
