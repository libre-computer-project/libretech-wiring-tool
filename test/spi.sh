#!/bin/bash

if [ "$USER" != "root" ]; then
	echo "Please run this as root." >&2
	exit 1
fi

if ! ./ldto isActive spicc-cs1; then
	./ldto enable spicc-cs1
	sleep 1
fi
if ./ldto isActive spidev-spicc-cs1; then
	./ldto disable spidev-spicc-cs1
	sleep 1
fi
if ! ./ldto isActive spidev-spicc-cs1; then
	./ldto enable spidev-spicc-cs1
	sleep 1
fi
echo spidev > /sys/bus/spi/devices/spi0.0/driver_override
echo spidev > /sys/bus/spi/devices/spi0.1/driver_override
sleep 1
echo spi0.0 > /sys/bus/spi/drivers/spidev/bind
echo spi0.1 > /sys/bus/spi/drivers/spidev/bind
sleep 1
for spic in 0 1; do
	for speed in 500000 1000000 2000000 4000000 8000000 16000000; do
		for mode in 0 1 2 3; do
			dev=/dev/spidev0.$spic
			count=$((speed * 2048 / 1000 / 1000))
			size=$((count >> 1))
			echo
			echo "Testing $dev in mode $mode at speed $speed Hz with $size KB"
			echo
			spi-config -d $dev -m $mode -s $speed -w &
			pid=$!
			tr '\0' '4' < /dev/zero | dd bs=512 count=$count of=$dev
			kill $pid
		done
	done
done

