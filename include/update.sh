#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Refresh include/dt-bindings/*.h from a Linux source tree.

set -e

if [ -z "$1" ]; then
	echo "$0 LINUX_DIR" >&2
	exit 1
fi

linux=$(readlink -f "$1")
if [ ! -d "$linux/include/dt-bindings" ]; then
	echo "$linux/include/dt-bindings not found" >&2
	exit 1
fi

cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"

for i in $(find dt-bindings -iname "*.h"); do
	echo $i
	if [ -f "$linux/include/$i" ]; then
		cp "$linux/include/$i" $i
	else
		echo "$i not found..."
	fi
done
