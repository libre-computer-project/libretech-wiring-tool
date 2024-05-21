#!/bin/bash

dateymd=$(date +%Y.%m.%d.%H-%M-%S)
commit=$(git rev-parse HEAD)
dateutc=$(date -Ru)
cat <<EOF > debian/changelog
libretech-wiring-tool ($dateymd) linux; urgency=medium

  * $commit

 -- Da Xue <da@libre.computer>  $dateutc
EOF
dpkg-buildpackage -uc --no-sign --build=all
