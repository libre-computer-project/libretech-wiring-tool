#!/bin/bash

if [ "$USER" != "root" ]; then
	echo "Please run this as root." >&2
	exit 1
fi

VENDOR=libre-computer BOARD=aml-s905x-cc ./ldto enable spicc-cs1
VENDOR=libre-computer BOARD=aml-s905x-cc ./ldto enable spidev-spicc-cs1
sleep 1
echo spidev > /sys/bus/spi/devices/spi0.0/driver_override
echo spidev > /sys/bus/spi/devices/spi0.1/driver_override
sleep 1
echo spi0.0 > /sys/bus/spi/drivers/spidev/bind
echo spi0.1 > /sys/bus/spi/drivers/spidev/bind

