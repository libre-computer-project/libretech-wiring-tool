#!/bin/bash
# Copyright (c) 2025 Da Xue <da@libre.computer>
# SPDX-License-Identifier: MIT

cd $(dirname $(readlink -f "${BASH_SOURCE[0]}"))

. bench_include.sh

if [ ! -z "$1" ]; then
	if [ "$1" = "--help" ]; then
		echo "$0 \"spi_bpws\"" >&2
		exit 1
	fi
	spi_bpws=$1
else
	spi_bpws=$SPI_BPWS
fi

. board_include.sh

if [ ! -z "$2" ]; then
	spi_speeds=($(($2 * 1000000)))
fi

TARGET_TIME=1

spi_mode=0
if [ -z "$board_clock" ]; then
	echo "bpw	MHz	Mb/s	Data	Parse" >&2
else
	echo "bpw	MHz (Real)	Mb/s (% Real)	Data	Parse" >&2
fi
for spi_bpw in $spi_bpws; do
	for spi_speed in "${spi_speeds[@]}"; do
		spi_speed_mhz=$(echo "scale=0; $spi_speed / 1000000" | bc)
		transfer_size=$((spi_speed_mhz * TARGET_TIME * 1024 * 128))
		spi_chunk_size=$((transfer_size < MAX_CHUNK_SIZE ? transfer_size: MAX_CHUNK_SIZE))
		if [ ! -z "$spi_chunk_size_max" ] && [ "$spi_chunk_size_max" -lt "$spi_chunk_size" ]; then
			spi_chunk_size=$spi_chunk_size_max
		fi
		data_ok=OK
		output=$("$BENCH_BIN" "$spi_device" "$spi_speed" "$spi_bpw" "$spi_mode" "$transfer_size" "$spi_chunk_size" 2>&1)
		if [ $? -ne 0 ]; then
			echo "$output" >&2
			data_ok=$(echo "$output" | grep "^Data" | grep -oE "\([0-9]*%\)")
		fi
		parse_ok=OK
		throughput=$(echo "$output" | grep "^Throughput:" | awk '{print $2}')
		if [ -z "$throughput" ]; then
			if [ ! -z "$data_ok" ]; then
				echo "$output" >&2
			fi
			parse_ok=
		fi
		if [ ! -z "$board_clock" ]; then
			spi_speed_mhz_real=$(echo "scale=2; $(spi_clock_monitor_clk $board_clock) / 1000000" | bc)
			# TODO: fix detection by using PARENT_USR1=1 USR1 interrupt from bench
			if [ "$spi_speed_mhz_real" = "0" ]; then
				echo "Unable to detect real frequency at this moment." >&2
				spi_speed_mhz_real=$spi_speed_mhz
			fi
		fi
		if [ -z "$board_clock" ]; then
			echo "$spi_bpw	$spi_speed_mhz	$throughput	${data_ok:-FAIL}	${parse_ok:-FAIL}"
		else
			throughput_efficiency=$(echo "scale=2; 100 * $throughput / $spi_speed_mhz_real" | bc)
			echo "$spi_bpw	$spi_speed_mhz ($spi_speed_mhz_real)	$throughput ($throughput_efficiency%)	${data_ok:-FAIL}	${parse_ok:-FAIL}"
		fi
	done
done
