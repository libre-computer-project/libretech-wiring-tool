#!/bin/bash
# Copyright (c) 2025 Da Xue <da@libre.computer>
# SPDX-License-Identifier: MIT

cd $(dirname $(readlink -f "${BASH_SOURCE[0]}"))

. bench_include.sh

if [ ! -z "$1" ]; then
	if [ "$1" = "--help" ]; then
		echo "$0 \"spi_bpws\" spi_speed"
		exit 1
	fi
	spi_bpws=$1
else
	spi_bpws=$SPI_BPWS
fi

if [ ! -z "$2" ]; then
	spi_speed=$2
else
	spi_speed=$SPI_SPEED
fi

. board_include.sh

spi_mode=0


ret=0

for spi_bpw in $SPI_BPWS; do
	spi_bpw_fail=0
	spi_Bpw=$((spi_bpw >> 3))
	for total_size in $(seq 8 8 $MAX_CHUNK_SIZE); do
		echo -en "\r${total_size}B @ ${spi_bpw}b/w"
		chunk_size=$((total_size < MAX_CHUNK_SIZE ? total_size : MAX_CHUNK_SIZE))
		output=$($BENCH_BIN $spi_device $spi_speed $spi_bpw $spi_mode $total_size $chunk_size 2>&1)
		if [ $? -ne 0 ]; then
			echo
			echo "$output"
			spi_bpw_fail=1
		fi
	done
	if [ $spi_bpw_fail -eq 0 ]; then
		echo -e "\r$spi_bpw b/w PASS"
	else
		echo -e "$spi_bpw b/w FAIL"
		ret=1
	fi
done

exit $ret
