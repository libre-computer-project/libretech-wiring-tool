#!/bin/bash
# Copyright (c) 2025 Da Xue <da@libre.computer>
# SPDX-License-Identifier: MIT

cd $(dirname $(readlink -f "${BASH_SOURCE[0]}"))

. bench_include.sh

if [ ! -z "$1" ]; then
	if [ "$1" = "--help" ]; then
		echo "$0 \"spi_bpws\" spi_speed" >&2
		exit 1
	fi
	spi_bpws=$1
else
	spi_bpws=$SPI_BPWS
fi

if [ ! -z "$2" ]; then
	spi_speed=$2
else
	spi_speed=$SPI_SPEED_DEFAULT
fi

. board_include.sh

spi_mode=32
ret=0

ts_start=64
ts_incre=8

echo "Target Speed:	$spi_speed" >&2
spi_clock_monitor

for spi_bpw in $spi_bpws; do
	spi_bpw_fail=0
	spi_Bpw=$((spi_bpw >> 3))
	ts_start=$spi_bpw #$(((spi_bpw << 3) >> 3))
	ts_incre=$((spi_bpw >> 3))
	for transfer_size in $(seq $ts_start $ts_incre $MAX_CHUNK_SIZE); do
		spi_chunk_size=$((transfer_size < MAX_CHUNK_SIZE ? transfer_size : MAX_CHUNK_SIZE))
		cmd="$BENCH_BIN $spi_device $spi_speed $spi_bpw $spi_mode $transfer_size $spi_chunk_size"
		output=$($cmd 2>&1)
		if [ $? -ne 0 ]; then
			echo
			echo -e "$cmd #"
			echo -e "\r${transfer_size}B @ ${spi_bpw}b/w failed"
			echo "$output" >&2
			spi_bpw_fail=1
			if [ ! -z "$EXIT_ON_FAIL" ] && [ "$EXIT_ON_FAIL" -eq 1 ]; then
				exit 1
			fi
		else
			spi_clock_monitor_wait
			throughput=$(echo "$output" | grep "Throughput:" | awk '{print $2}')
			echo -en "\r${transfer_size}B @ ${throughput}MHz ${spi_bpw}b/w"
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
