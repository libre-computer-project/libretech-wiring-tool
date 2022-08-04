#!/bin/bash

if [ "$USER" != "root" ]; then
	echo "Please run this as root." >&2
	exit 1
fi

if [ -z "$1" ]; then
	echo "$0 SPIDEVNUM" >&2
	exit 1
fi

SPIDEVNUM="$1"
SPICSMAX="0"
while true; do
	if [ ! -e "/dev/spidev${SPIDEVNUM}.${SPICSMAX}" ]; then
		if [ "$SPICSMAX" -eq 0 ]; then
			echo "SPIDEV $SPIDEV does not exist." >&2
			exit 1
		fi
		break
	fi
	((SPICSMAX++))
done
echo "SPIDEV $0 has $SPICSMAX chip enable(s)." >&2

freq=500000
chip=0
mode=0
data='S'
block=512
stop=0

echo "Press q to quit, m to change mode, c to change chip select, w and s to double/half freq." >&2

while [ $stop -eq 0 ]; do
	echo "Testing SPI ${SPIDEVNUM} CHIP ${chip} MODE ${mode} @ ${freq}Hz ." >&2
	dev=/dev/spidev$SPIDEVNUM.$chip
	spi-config -d $dev -m $mode -s $freq -w &
	spi_config_pid=$!
	tr '\0' "$data" < /dev/zero | dd bs=$block of=$dev &
	dd_pid=$!
	read -n 1 ctrl_char
	kill $dd_pid
	kill $spi_config_pid
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
		w)
			freq=$((freq << 1))
			;;
		s)
			if [ $freq -lt 31250 ]; then
				echo "Frequency is already at minimum." >&2
			else
				freq=$((freq >> 1))
			fi
			;;	
		*)
			echo "Unrecognized command character $ctrl_char." >&2
			;;
	esac
done

