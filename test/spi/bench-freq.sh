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

TARGET_TIME=2

spi_mode=0

echo "bpw	MHz	Mb/s" >&2
for spi_bpw in $spi_bpws; do
	for spi_speed in "${spi_speeds[@]}"; do
		spi_speed_mhz=$(echo "scale=0; $spi_speed / 1000000" | bc)

		transfer_size=$((spi_speed * TARGET_TIME / 8))
		spi_chunk_size=$((transfer_size < MAX_CHUNK_SIZE ? transfer_size: MAX_CHUNK_SIZE))
		if [ ! -z "$spi_chunk_size_max" -a "$spi_chunk_size_max" -lt "$spi_chunk_size" ]; then
			spi_chunk_size=$spi_chunk_size_max
		fi
		output=$("$BENCH_BIN" "$spi_device" "$spi_speed" "$spi_bpw" "$spi_mode" "$transfer_size" "$spi_chunk_size" 2>&1)
		if [ $? -ne 0 ]; then
			echo "$spi_bpw	$spi_speed_mhz	DATA_FAIL"
			echo "$output" >&2
			continue
		fi
		throughput=$(echo "$output" | grep "Throughput:" | awk '{print $2}')
		if [ -z "$throughput" ]; then
			echo "$spi_bpw	$spi_speed_mhz	PARSE_FAIL"
			echo "$output" >&2
			continue
		fi
		echo "$spi_bpw	$spi_speed_mhz	$throughput"
	done
done
