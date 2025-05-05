# Copyright (c) 2025 Da Xue <da@libre.computer>
# SPDX-License-Identifier: MIT

BENCH_BIN=./bench

if [ ! -f $BENCH_BIN ]; then
	gcc $BENCH_BIN.c -o $BENCH_BIN
fi

SPI_BPWS="$(seq 1 1 64)"
SPI_MODES="0 1 2 3"
SPI_SPEEDS=()
for i in $(seq 1 1 10); do
	SPI_SPEEDS+=($((i * 1000000)))
done
for i in $(seq 15 5 120); do
	SPI_SPEEDS+=($((i * 1000000)))
done
SPI_SPEED=10000000 # 10MHz default

MAX_CHUNK_SIZE=$((1024*1024)) # require kernel cmdline spidev.bufsiz=1048576

spi_bpw_get(){
	local bpw_tar=$1
	local bpw_dir=$2
	local bpw_last=${SPI_BPWS%% *}
	local bpw_next=0
	for bpw in $SPI_BPWS; do
		if [ $bpw_next -eq 1 ]; then
			echo -n "$bpw"
			break
		elif [ $bpw -eq $bpw_tar ]; then
			if [ $bpw_dir -eq 0 ]; then
				echo -n $bpw_last
				break
			else
				local bpw_next=1
			fi
		fi
		local bpw_last=$bpw
	done
}

spi_clock_monitor_child(){
	if [ ! -z "$board_clocks" ]; then
		clock_cmd="grep .\\* /sys/kernel/debug/clk/{$board_clocks}/clk_rate | tr -s : \"\\t\""
		output_old=$(eval $clock_cmd)
		i=0
		while true; do
			output=$(eval $clock_cmd)
			if [ "$output_old" != "$output" ]; then
				echo "Clocks after ${i}ms" >&2
				echo "$output" >&2
				output_old=$output
			fi
			if [ $i -eq 15 ]; then
				kill -s INT $$
				break
			fi
			((i++))
			sleep 0.001
		done
	fi
}

spi_clock_monitor(){
	spi_clock_monitor_child &
	scm_pid=$!
	trap "scm_pid=; trap - SIGINT;" SIGINT
	sleep 0.1 # time for spi_clock_monitor_child to read initial clock
}

spi_clock_monitor_wait(){
	while [ ! -z $scm_pid ]; do
		:
	done
}
