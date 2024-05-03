#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2021 Da Xue <da@libre.computer>

set -e

cd $(readlink -f $(dirname ${BASH_SOURCE[0]}))

dt_maps=../libre-computer/*/dt.map

for dt_map in $dt_maps; do
	dt_overlays=$(grep -v "^#" $dt_map | cut -f 2 -d "	")
	for dt_overlay in $dt_overlays; do
		dt_overlay_src="${dt_map%.map}/$dt_overlay.dts"
		if [ ! -f "$dt_overlay_src" ]; then
			echo "$dt_overlay_src Missing!"
		fi
	done
done
