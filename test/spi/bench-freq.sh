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
	echo "bpw	MHz	Mb/s	Data" >&2
else
	echo "bpw	MHz (Real)	Mb/s (% Real)	Data" >&2
fi
for spi_bpw in $spi_bpws; do
	for spi_speed in "${spi_speeds[@]}"; do
		spi_speed_mhz=$(echo "scale=0; $spi_speed / 1000000" | bc)
		transfer_size=$((spi_speed_mhz * TARGET_TIME * 1024 * 8 / (spi_bpw * 8) * (spi_bpw * 8)))
		spi_chunk_size=$((transfer_size < MAX_CHUNK_SIZE ? transfer_size: MAX_CHUNK_SIZE / (spi_bpw * 8) * (spi_bpw * 8)))
		if [ ! -z "$spi_chunk_size_max" ] && [ "$spi_chunk_size_max" -lt "$spi_chunk_size" ]; then
			spi_chunk_size=$spi_chunk_size_max
		fi
		data_ok=OK
		cmd="$BENCH_BIN $spi_device $spi_speed $spi_bpw $spi_mode $transfer_size $spi_chunk_size"
		output=$($cmd 2>&1)
		if [ $? -ne 0 ]; then
			if [ ! -z "$DEBUG_OUTPUT" ]; then
				echo "$cmd" >&2
				echo "$output" >&2
			fi
			data_miss=$(echo "$output" | grep "^Data" | grep -oE " [0-9]+ " | head -n 1 | cut -f 2 -d " ")
			data_miss_percent=$(echo "$output" | grep "^Data" | grep -oE "\([0-9]+%\)")
			data_ok="$data_miss $data_miss_percent"
		fi
		throughput=$(echo "$output" | grep "^Throughput:" | awk '{print $2}')
		if [ -z "$throughput" ]; then
			if [ ! -z "$data_ok" ] && [ ! -z "$DEBUG_OUTPUT" ]; then
				echo "$cmd" >&2
				echo "$output" >&2
			fi
		fi
		error_msg=$(echo "$output" | grep "^Word" | head -n 1)
		if [ ! -z "$board_clock" ]; then
			spi_speed_mhz_real=$(echo "scale=2; $(spi_clock_monitor_clk $board_clock) / 1000000" | bc)
			# TODO: fix detection by using PARENT_USR1=1 USR1 interrupt from bench
			if [ "$spi_speed_mhz_real" = "0" ]; then
				echo "Unable to detect real frequency at this moment." >&2
				spi_speed_mhz_real=$spi_speed_mhz
			fi
		fi
		if [ -z "$board_clock" ]; then
			echo "$spi_bpw	$spi_speed_mhz	$throughput	${data_ok:-FAIL}	${error_msg}"
		else
			throughput_efficiency=$(echo "scale=2; 100 * $throughput / $spi_speed_mhz_real" | bc)
			echo "$spi_bpw	$spi_speed_mhz ($spi_speed_mhz_real)	$throughput ($throughput_efficiency%)	${data_ok:-FAIL}	$error_msg"
		fi
	done
done
