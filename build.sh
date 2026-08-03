#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Build .deb packages into the parent directory (dpkg-buildpackage default).
set -euo pipefail

cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"

dateymd=$(date +%Y.%m.%d.%H-%M-%S)
commit=$(git rev-parse HEAD 2>/dev/null || echo unknown)
dateutc=$(date -Ru)

# Refresh changelog for this build (native package, single entry is fine).
cat > debian/changelog <<EOF
libretech-wiring-tool ($dateymd) unstable; urgency=medium

  * Build $commit

 -- Da Xue <da@libre.computer>  $dateutc
EOF

dpkg-buildpackage -uc -us --build=all
