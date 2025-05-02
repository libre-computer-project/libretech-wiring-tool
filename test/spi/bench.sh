#!/bin/bash
# Copyright (c) 2025 Da Xue <da@libre.computer>
# SPDX-License-Identifier: MIT

cd $(dirname $(readlink -f "${BASH_SOURCE[0]}"))

. bench_include.sh
. board_include.sh

./$BENCH_BIN "$spi_device" & # 10000000 8 0 $((1024 * 1024)) 4096
pid=$!
sleep 0.1
eval "sudo grep .\\* /sys/kernel/debug/clk/{$board_clocks}/clk_rate"
wait $pid
