#!/bin/bash

set -e

cd $(dirname $(readlink -f "${BASH_SOURCE[0]}"))

update-alternatives --install /usr/local/bin/lgpio lgpio $PWD/lgpio 40
update-alternatives --install /usr/local/bin/ldto ldtbo $PWD/ldto 40

packages=()

if ! which dtc > /dev/null; then
	packages+=(device-tree-compiler)
fi

if ! which make > /dev/null; then
	packages+=(make)
fi

if ! which gcc > /dev/null; then
	packages+=(gcc)
fi

if [ "${#packages[@]}" -gt 0 ]; then
	apt install -y ${packages[@]}
fi

make

echo "Libre Computer Wiring Tool installed!"
