#!/bin/bash
# Copyright (c) 2025 Da Xue <da@libre.computer>
# SPDX-License-Identifier: MIT

cd $(dirname $(readlink -f "${BASH_SOURCE[0]}"))

. bench_include.sh
. board_include.sh

if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
	echo "$0 SPEED BPW MODE SIZE CHUNK" >&2
	exit 1
fi

board_clock_display(){
	if [ ! -z "$board_clock" ]; then
		spi_clock_monitor_clk_tree $board_clock
	fi
	trap - SIGUSR1
	wait -f $pid
}

bench_kill(){
	if [ ! -z "$pid" ]; then
		kill -TERM $pid
	fi
}

trap board_clock_display SIGUSR1
trap bench_kill SIGINT
trap bench_kill SIGTERM

PARENT_USR1=1 $BENCH_BIN "$spi_device" $@ &
pid=$!
wait -f $pid
