#!/bin/bash
# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2021 Da Xue <da@libre.computer>

if [ "$USER" != "root" ]; then
	echo "Please run this as root." >&2
	exit 1
fi

set -e

if [ -z "$VENDOR" ]; then
	if [ ! -e /sys/class/dmi/id/board_vendor ]; then
		echo "No vendor found!" >&2
		exit 1
	fi
	VENDOR=$(tr -d '\0' < /sys/class/dmi/id/board_vendor)
fi


if [ -z "$BOARD" ]; then
	if [ ! -e /sys/class/dmi/id/board_name ]; then
		echo "No boardname found!" >&2
		exit 1
	fi
	BOARD=$(tr -d '\0' < /sys/class/dmi/id/board_name)
fi

mode=gpiod
if [ ! -z "$1" ]; then
	case "$1" in
		gpiod)
			if ! which gpioset > /dev/null; then
				echo "$0 requires gpioset from gpiod." >&2
				exit 1
			fi
			;;
		sysfs)
			SYSFS_PATH=/sys/class/gpio
			if [ ! -d $SYSFS_PATH ]; then
				echo "$0 sysfs mode requires kernel CONFIG_GPIO_SYSFS." >&2
				exit 1
			fi
			mode=sysfs
			;;
		*)
			echo "$0 {gpiod,sysfs}" >&2
			exit 1
			;;
	esac
fi

cd $(readlink -f $(dirname ${BASH_SOURCE[0]}))

if [ ! -f "$VENDOR/$BOARD/gpio.map" ]; then
	echo "GPIO map not available for this board." >&2
	exit 1
fi

i=0
if [ "$mode" = "gpiod" ]; then
	while true; do
		while read line; do
			arr=($line)
			if [ "${arr[1]}" -eq "${arr[1]}" -a "${arr[2]}" -eq "${arr[2]}" ] 2> /dev/null; then
				#echo "Testing Header	${arr[0]}	Pin ${arr[1]}	Chip ${arr[2]}	Line ${arr[3]}"
				gpioset "${arr[2]}" "${arr[3]}"=$((i % 2))
			fi
		done < <(grep -v "^#" $VENDOR/$BOARD/gpio.map | cut -f 1,2,3,4 -d "	")
		i=$((i+1))
	done
else
	
	while true; do
		while read line; do
			arr=($line)
			if [ "${arr[1]}" -eq "${arr[1]}" -a "${arr[2]}" -eq "${arr[2]}" ] 2> /dev/null; then
				#echo "Testing Header	${arr[0]}	Pin ${arr[1]}	sysfs ${arr[2]}"
				sysfs=${arr[2]}
				if [ ! -d $SYSFS_PATH/gpio$sysfs ]; then
					echo -n "$sysfs" > $SYSFS_PATH/export
				fi
				echo -n out > $SYSFS_PATH/gpio$sysfs/direction
				echo -n $((i % 2)) > $SYSFS_PATH/gpio$sysfs/value
				echo -n "$sysfs" > $SYSFS_PATH/unexport
			fi
		done < <(grep -v "^#" $VENDOR/$BOARD/gpio.map | cut -f 1,2,5 -d "	")
		i=$((i+1))
	done
fi