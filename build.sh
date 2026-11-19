#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Build .deb packages into the parent directory (dpkg-buildpackage default).
set -euo pipefail

cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"

# the version: the build's date and time, without a hyphen (a native package's version has none; dpkg would read
# what follows the last hyphen as a Debian revision)
dateymd=$(date +%Y.%m.%d.%H%M%S)
commit=$(git rev-parse HEAD 2>/dev/null || echo unknown)
dateutc=$(date -Ru)

# Stamp a dated changelog entry for this build only (native package, single
# entry is fine), and put the tracked changelog back afterwards so a build
# never leaves the tree dirty.
cp -p debian/changelog debian/changelog.build-orig
trap 'mv -f debian/changelog.build-orig debian/changelog' EXIT
cat > debian/changelog <<EOF
libretech-wiring-tool ($dateymd) unstable; urgency=medium

  * Build $commit

 -- Da Xue <da@libre.computer>  $dateutc
EOF

dpkg-buildpackage -uc -us --build=all
