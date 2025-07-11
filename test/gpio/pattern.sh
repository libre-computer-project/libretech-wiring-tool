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

pattern=toggle
if [ ! -z "$2" ]; then
	pattern="$2"
fi

cd $(readlink -f $(dirname ${BASH_SOURCE[0]}))

GPIO_MAP_PATH="../../$VENDOR/$BOARD/gpio.map"

if [ ! -f "$GPIO_MAP_PATH" ]; then
	echo "GPIO map not available for this board." >&2
	exit 1
fi

function PATTERN_getMainHeader(){
	local header_map=$(grep -v "^#" "$GPIO_MAP_PATH" | cut -f 1,2,3,4,5 -d "	")
	local main_header=$(echo "$header_map" | head -n 1 | cut -f 1 -d "	")
	echo "$header_map" | grep "^$main_header"
}

function PATTERN_displayToggle(){
	while true; do
		while read line; do
			arr=($line)
			if [ "${arr[1]}" -eq "${arr[1]}" -a "${arr[2]}" -eq "${arr[2]}" ] 2> /dev/null; then
				#echo "Testing Header	${arr[0]}	Pin ${arr[1]}	Chip ${arr[2]}	Line ${arr[3]}"
				gpioset "${arr[2]}" "${arr[3]}"=$((i % 2))
			fi
		done < <(PATTERN_getMainHeader)
		i=$((i+1))
	done
}

function PATTERN_displaySeq(){
	while true; do
		while read line; do
			arr=($line)
			if [ "${arr[1]}" -eq "${arr[1]}" -a "${arr[2]}" -eq "${arr[2]}" ] 2> /dev/null; then
				#echo "Testing Header	${arr[0]}	Pin ${arr[1]}	Chip ${arr[2]}	Line ${arr[3]}"
				#if [ $((${arr[1]} % 2)) -ne $((i % 2)) ]; then
				#	continue
				#fi
				gpioset "${arr[2]}" "${arr[3]}"=0
				sleep 0.1
				if [ ! -z "$p_chip" ]; then
					gpioset "$p_chip" "$p_line"=1
				fi
				local p_chip=${arr[2]}
				local p_line=${arr[3]}
			fi
		done < <(PATTERN_getMainHeader)
		i=$((i+1))
	done
}

function PATTERN_displayBias(){
	while true; do
		local value=$(((i >> 2) % 2))
		local bias=$((i % 4))
		if [ $bias -eq 0 ]; then
			local pin_bias="as-is"
		elif [ $bias -eq 1 ]; then
			local pin_bias="disable"
		elif [ $bias -eq 2 ]; then
			local pin_bias="pull-down"
		elif [ $bias -eq 3 ]; then
			local pin_bias="pull-up"
		else
			echo "${FUNCNAME} unexpected bias state" >&2
			exit 1
		fi
		while read line; do
			arr=($line)
			if [ "${arr[1]}" -eq "${arr[1]}" -a "${arr[2]}" -eq "${arr[2]}" ] 2> /dev/null; then
				#echo "Testing Header	${arr[0]}	Pin ${arr[1]}	Chip ${arr[2]}	Line ${arr[3]}"
				if [ $bias -eq 0 ]; then
					gpioset -B $pin_bias "${arr[2]}" "${arr[3]}"=$value
				else
					gpioget -B $pin_bias "${arr[2]}" "${arr[3]}" > /dev/null
				fi
			fi
		done < <(PATTERN_getMainHeader)
		i=$((i+1))
	done
}

i=0
if [ "$mode" = "gpiod" ]; then
	case "$pattern" in
		"toggle")
			PATTERN_displayToggle
			break
			;;
		"seq")
			PATTERN_displaySeq
			break
			;;
		"bias")
			PATTERN_displayBias
			break
			;;
		*)
			echo "Unsupported pattern $pattern." >&2
			exit 1
	esac
else
	while true; do
		while read line; do
			arr=($line)
			if [ "${arr[1]}" -eq "${arr[1]}" -a "${arr[4]}" -eq "${arr[4]}" ] 2> /dev/null; then
				#echo "Testing Header	${arr[0]}	Pin ${arr[1]}	sysfs ${arr[4]}"
				sysfs=${arr[4]}
				if [ ! -d $SYSFS_PATH/gpio$sysfs ]; then
					echo -n "$sysfs" > $SYSFS_PATH/export
				fi
				echo -n out > $SYSFS_PATH/gpio$sysfs/direction
				echo -n $((i % 2)) > $SYSFS_PATH/gpio$sysfs/value
				echo -n "$sysfs" > $SYSFS_PATH/unexport
			fi
		done < <(PATTERN_getMainHeader)
		i=$((i+1))
	done
fi
