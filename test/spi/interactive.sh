#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2021 Da Xue <da@libre.computer>

# PURPOSE: testing SPI chip select, modes, and frequency   

if [ "$USER" != "root" ]; then
	echo "Please run this as root." >&2
	exit 1
fi

if [ -z "$1" ]; then
	echo "$0 SPIDEVNUM" >&2
	exit 1
fi

if ! which spi-config > /dev/null; then
	echo "$0 requires spi-config from spi-tools." >&2
	exit 1
fi

SPIDEVNUM="$1"
SPICSMAX="0"
while true; do
	if [ ! -e "/dev/spidev${SPIDEVNUM}.${SPICSMAX}" ]; then
		if [ "$SPICSMAX" -eq 0 ]; then
			echo "SPIDEV $SPIDEVNUM does not exist." >&2
			exit 1
		fi
		break
	fi
	((SPICSMAX++))
done
echo "SPIDEV $SPIDEVNUM has $SPICSMAX chip enable(s)." >&2

freq=500000
chip=0
mode=0
data='S'
bpw=8
block=1024
stop=0

function TEST_SPI_help(){
	echo "Press q to quit, m to change mode, c to change chip select, b to change ascii byte." >&2
	echo "Press w and s to double/half freq, a and d to half/double word size." >&2
}

TEST_SPI_help

while [ $stop -eq 0 ]; do
	echo "Testing SPI ${SPIDEVNUM} CS ${chip} MODE ${mode} @ ${freq}Hz / $bpw BPW." >&2
	dev=/dev/spidev$SPIDEVNUM.$chip
	spi-config -d $dev -m $mode -s $freq -b $bpw -w &
	spi_config_pid=$!
	sleep 0.1
	if kill -0 $spi_config_pid 2> /dev/null; then
		tr '\0' "$data" < /dev/zero | dd bs=$block of=$dev &
		dd_pid=$!
		read -n 1 ctrl_char
		kill $dd_pid
		kill $spi_config_pid
	else
		echo 'Configuration failed!' >&2
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
			*)
				read -n 1 ctrl_char
				;;
		esac
	fi
	case "$ctrl_char" in
		q)
			stop=1
			break
			;;
		m)
			mode=$((++mode % 4))
			;;
		c)
			chip=$((++chip % SPICSMAX))
			;;
		b)
			echo >&2
			read -n 1 -p "Change ASCII byte '$data' to: " data >&2
			echo >&2
			;;
		w)
			if [ $freq -gt 200000000 ]; then
				echo "Frequency is already at maximum." >&2
			else
				freq=$((freq << 1))
			fi
			;;
		s)
			if [ $freq -lt 10000 ]; then
				echo "Frequency is already at minimum." >&2
			else
				freq=$((freq >> 1))
			fi
			;;
		a)
			if [ $bpw -eq 7 ]; then
				echo "Bits-per-word is already at minimum." >&2
			elif [ $bpw -le 8 ]; then
				bpw=$((bpw - 1))
			else
				bpw=$((bpw >> 1))
			fi
			;;
		d)
			if [ $bpw -ge 128 ]; then
				echo "Bits-per-word is already at maximum." >&2
			elif [ $bpw -lt 8 ]; then
				bpw=$((bpw + 1))
			else
				bpw=$((bpw << 1))
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

