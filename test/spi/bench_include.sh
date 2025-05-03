# Copyright (c) 2025 Da Xue <da@libre.computer>
# SPDX-License-Identifier: MIT

BENCH_BIN=./bench

if [ ! -f $BENCH_BIN ]; then
	gcc $BENCH_BIN.c -o $BENCH_BIN
fi

SPI_BPWS="8 16 24 32 64"
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
