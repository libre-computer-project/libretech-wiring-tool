# Copyright (c) 2025 Da Xue <da@libre.computer>
# SPDX-License-Identifier: MIT

BENCH_C=./bench.c
BENCH_BIN=./bench-`uname -m`

if [ ! -f $BENCH_BIN ]; then
	gcc $BENCH_C -o $BENCH_BIN
fi

SPI_BPWS="$(seq 8 8 64)"
SPI_MODES="0 1 2 3"
SPI_SPEEDS=()
for i in $(seq 1 1 20); do
	SPI_SPEEDS+=($((i * 50000)))
done
for i in $(seq 1 1 200); do
	SPI_SPEEDS+=($((i * 1000000)))
done

SPI_SPEED_DEFAULT=10000000 # 10MHz default

MAX_CHUNK_SIZE=$((4*1024*1024)) # require kernel cmdline spidev.bufsiz=4194304

CLK_PREFIX=/sys/kernel/debug/clk

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

spi_clock_monitor_clk(){
	cat "$CLK_PREFIX/$1/clk_rate"
}

spi_clock_monitor_clk_tree(){
	for clk in $@; do
		echo "========"
		while true; do
			clk_rate_path="$CLK_PREFIX/$clk/clk_rate"
			echo "$clk	$(cat ${clk_rate_path})"
			clk_parent_path="$CLK_PREFIX/$clk/clk_parent"
			if [ ! -e "$clk_parent_path" ]; then
				break
			fi
			clk=$(cat "$clk_parent_path")
		done
	done
	echo "========"
}

spi_clock_monitor_child(){
	if [ ! -z "$board_clock" ]; then
		output=$(spi_clock_monitor_clk_tree $board_clock)
		echo "$output"
		i=0
		while true; do
			output_new=$(spi_clock_monitor_clk_tree $board_clock)
			if [ "$output" != "$output_new" ]; then
				echo "Clocks after ${i}ms" >&2
				echo "$output_new" >&2
				output=$output_new
			fi
			if [ $i -eq 30 ]; then
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
