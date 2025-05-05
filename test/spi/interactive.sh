#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2021 Da Xue <da@libre.computer>

# PURPOSE: testing SPI speed, mode, bpw, chip-enable, chunk size

if ! which spi-config > /dev/null; then
	echo "$0 requires spi-config from spi-tools." >&2
	exit 1
fi

cd $(dirname $(readlink -f "${BASH_SOURCE[0]}"))

. bench_include.sh

if [ ! -z "$1" ]; then
	if [ "$1" = "--help" ]; then
		echo "$0" >&2
		echo "$0 spi_devnum" >&2
		exit 1
	fi
fi

if [ ! -z "$1" ]; then
	spi_devnum_user=$1
fi

. board_include.sh

spi_cs_max="0"
while true; do
	if [ ! -e "${spi_device%.*}.${spi_cs_max}" ]; then
		if [ "$spi_cs_max" -eq 0 ]; then
			echo "SPI bus $spi_devnum does not exist." >&2
			exit 1
		fi
		break
	fi
	((spi_cs_max++))
done
echo "SPI bus $spi_devnum has $spi_cs_max chip enable(s)." >&2

spi_speed=500000
spi_mode=0
spi_bpw=8
spi_chip=0
spi_chunk_size=1024
data='S' # S for 01010011, U for 01010101
end=0

function TEST_SPI_help(){
	echo "Press q to quit, m to change mode, c to change chip select, b to change ascii byte." >&2
	echo "Press w and s to double/half freq, a and d to half/double word size, j and k to decrease/increase chunk size." >&2
}

TEST_SPI_help

while [ $end -eq 0 ]; do
	spi_device=$SPI_DEV_PATH$spi_devnum.$spi_chip
	spi_clock_monitor
	spi-config -d $spi_device -m $spi_mode -s $spi_speed -b $spi_bpw -w &
	spi_config_pid=$!
	sleep 0.1
	if kill -0 $spi_config_pid 2> /dev/null; then
		tr '\0' "$data" < /dev/zero | dd bs=$spi_chunk_size of=$spi_device &
		dd_pid=$!
		spi_clock_monitor_wait
		echo "SPI bus ${spi_devnum} chip ${spi_chip} mode ${spi_mode} @ ${spi_speed}Hz $spi_bpw bpw $spi_chunk_size B/chunks." >&2
		read -n 1 ctrl_char
		read -e -t 1 &
		kill $dd_pid
		kill $spi_config_pid
	else
		echo "SPI bus ${spi_devnum} chip ${spi_chip} mode ${spi_mode} @ ${spi_speed}Hz $spi_bpw bpw $spi_chunk_size B/chunks FAILED!" >&2
		case "$ctrl_char" in
			w)
				ctrl_char="s"
				;;
			s)
				ctrl_char="w"
				;;
			a)
				ctrl_char="d"
				;;
			d)
				ctrl_char="a"
				;;
			j)
				ctrl_char="k"
				;;
			k)
				ctrl_char="j"
				;;
			*)
				read -n 1 ctrl_char
				read -e -t 1 &
				;;
		esac
	fi
	echo
	case "$ctrl_char" in
		q)
			stop=1
			break
			;;
		m)
			spi_mode=$((++spi_mode % 4))
			;;
		c)
			spi_chip=$((++spi_chip % spi_cs_max))
			;;
		b)
			echo >&2
			read -n 1 -p "Change ASCII byte '$data' to: " data >&2
			echo >&2
			;;
		w)
			if [ $spi_speed_max -ne 0 -a $spi_speed -gt $spi_speed_max ]; then
				echo "Speed is already at maximum." >&2
			else
				spi_speed=$((spi_speed << 1))
				if [ $spi_speed -gt $spi_speed_max ]; then
					spi_speed=$spi_speed_max
				fi
			fi
			;;
		s)
			if [ $spi_speed -lt $spi_speed_min ]; then
				echo "Speed is already at minimum." >&2
			else
				spi_speed=$((spi_speed >> 1))
				if [ $spi_speed -lt $spi_speed_min ]; then
					spi_speed=$spi_speed_min
				fi
			fi
			;;
		a)
			# spi-config does not support below 7 bpw
			if [ $spi_bpw -eq 7 ]; then
				echo "Bits-per-word is already at minimum." >&2
			else
				spi_bpw=$(spi_bpw_get $spi_bpw 0)
			fi
			;;
		d)
			if [ $spi_bpw -ge 64 ]; then
				echo "Bits-per-word is already at maximum." >&2
			else
				spi_bpw=$(spi_bpw_get $spi_bpw 1)
			fi
			;;
		j)
			if [ $spi_chunk_size -lt 2 ]; then
				echo "Chunk size is already at minimum." >&2
			else
				((spi_chunk_size >>= 1))
			fi
			;;
		k)
			if [ $spi_chunk_size -ge 1048576 ]; then
				echo "Chunk size is already at maximum." >&2
			else
				((spi_chunk_size <<= 1))
			fi
			;;
		h)
			TEST_SPI_help
			;;
		*)
			echo "Unrecognized command character $ctrl_char." >&2
			TEST_SPI_help
			;;
	esac
done

