#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
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

delay=0
if [ ! -z "$3" ]; then
	delay="$3"
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
	# Exact match on the Header column: J1 must not also select J12/J13/J16.
	# A header pin may have several rows when two SoC lines are wired to it.
	# Drive only the first: the rest share the same physical pin, and
	# toggling them together would contend through their series resistors.
	echo "$header_map" | awk -F'\t' -v h="$main_header" '$1 == h && !seen[$1 FS $2]++'
}

# libgpiod v1 vs v2, detected once (same probe as lgpio): v2's gpioset
# takes <line=value> with -c CHIP, v1's takes CHIP OFFSET=VALUE.
GPIOD_MAJOR=1
if [ "$mode" = "gpiod" ] && gpioset --help 2>&1 | grep -q 'line=value'; then
	GPIOD_MAJOR=2
fi

# PATTERN_bias BIAS -> option words for the installed libgpiod; none for as-is.
function PATTERN_bias(){
	case "$1" in
		as-is) ;;
		disable)
			if [ "$GPIOD_MAJOR" = 2 ]; then echo "-b disabled"; else echo "-B disable"; fi
			;;
		*)
			if [ "$GPIOD_MAJOR" = 2 ]; then echo "-b $1"; else echo "-B $1"; fi
			;;
	esac
}

# PATTERN_gpioset CHIP LINE VALUE [BIAS]
function PATTERN_gpioset(){
	local bias_opt=$(PATTERN_bias "${4:-as-is}")
	if [ "$GPIOD_MAJOR" = 2 ]; then
		gpioset -c "$1" $bias_opt -p 100ms -t 0 "$2=$3"
	else
		gpioset $bias_opt "$1" "$2=$3"
	fi
}

# PATTERN_gpioget CHIP LINE [BIAS]
function PATTERN_gpioget(){
	local bias_opt=$(PATTERN_bias "${3:-as-is}")
	if [ "$GPIOD_MAJOR" = 2 ]; then
		gpioget -c "$1" --numeric $bias_opt "$2"
	else
		gpioget $bias_opt "$1" "$2"
	fi
}

# Legacy sysfs number of CHIP LINE on the running kernel. The map's sysfs
# column is the old fixed numbering; current kernels allocate chip bases
# dynamically (from 512), so the base is read live: the sysfs gpiochip<base>
# whose parent device also parents /dev/gpiochip<CHIP>. Sets SYSFS_NUM;
# called in the current shell so SYSFS_BASE caches across iterations.
declare -A SYSFS_BASE
function PATTERN_sysfsNumber(){
	local chip="$1" line="$2" d base="" n=0
	if [ -z "${SYSFS_BASE[$chip]}" ]; then
		for d in $SYSFS_PATH/gpiochip*; do
			[ -r "$d/base" ] || continue
			if [ -e "$d/device/gpiochip$chip" ] || [ "$(basename "$(readlink -f "$d/device")")" = "gpiochip$chip" ]; then
				base=$(cat "$d/base")
				n=$((n + 1))
			fi
		done
		if [ "$n" -ne 1 ]; then
			echo "$0: cannot map gpiochip$chip to one sysfs base ($n candidates); use gpiod mode." >&2
			exit 1
		fi
		SYSFS_BASE[$chip]=$base
	fi
	SYSFS_NUM=$((SYSFS_BASE[$chip] + line))
}

function PATTERN_displayToggle(){
	while true; do
		while read line; do
			arr=($line)
			if [ "${arr[1]}" -eq "${arr[1]}" -a "${arr[2]}" -eq "${arr[2]}" ] 2> /dev/null; then
				#echo "Testing Header	${arr[0]}	Pin ${arr[1]}	Chip ${arr[2]}	Line ${arr[3]}"
				PATTERN_gpioset "${arr[2]}" "${arr[3]}" $((i % 2))
			fi
		done < <(PATTERN_getMainHeader)
		i=$((i+1))
		sleep $delay
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
				PATTERN_gpioset "${arr[2]}" "${arr[3]}" 0
				sleep 0.1
				if [ ! -z "$p_chip" ]; then
					PATTERN_gpioset "$p_chip" "$p_line" 1
				fi
				local p_chip=${arr[2]}
				local p_line=${arr[3]}
			fi
		done < <(PATTERN_getMainHeader)
		i=$((i+1))
		sleep $delay
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
					PATTERN_gpioset "${arr[2]}" "${arr[3]}" $value $pin_bias
				else
					PATTERN_gpioget "${arr[2]}" "${arr[3]}" $pin_bias > /dev/null
				fi
			fi
		done < <(PATTERN_getMainHeader)
		i=$((i+1))
		sleep $delay
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
			if [ "${arr[1]}" -eq "${arr[1]}" -a "${arr[2]}" -eq "${arr[2]}" -a "${arr[3]}" -eq "${arr[3]}" ] 2> /dev/null; then
				PATTERN_sysfsNumber "${arr[2]}" "${arr[3]}"
				sysfs=$SYSFS_NUM
				#echo "Testing Header	${arr[0]}	Pin ${arr[1]}	sysfs $sysfs"
				if [ ! -d $SYSFS_PATH/gpio$sysfs ]; then
					echo -n "$sysfs" > $SYSFS_PATH/export
				fi
				echo -n out > $SYSFS_PATH/gpio$sysfs/direction
				echo -n $((i % 2)) > $SYSFS_PATH/gpio$sysfs/value
				echo -n "$sysfs" > $SYSFS_PATH/unexport
			fi
		done < <(PATTERN_getMainHeader)
		i=$((i+1))
		sleep $delay
	done
fi
