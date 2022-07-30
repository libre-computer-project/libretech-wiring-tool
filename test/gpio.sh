#!/bin/bash

if [ "$USER" != "root" ]; then
	echo "Please run this as root." >&2
	exit 1
fi

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

cd $(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)/..

if [ ! -f "$VENDOR/$BOARD/gpio.map" ]; then
	echo "GPIO map not available for this board." >&2
	exit 1
fi

i=0
while true; do
	while read line; do
		arr=($line)
		if [ "${arr[1]}" -eq "${arr[1]}" -a "${arr[2]}" -eq "${arr[2]}" ] 2> /dev/null; then
			#echo "Testing Header	${arr[0]}	Chip ${arr[1]}	Line ${arr[2]}	sysfs ${arr[3]}"
			gpioset "${arr[2]}" "${arr[3]}"=$((i % 2))
		fi
	done < <(grep -v "^#" $VENDOR/$BOARD/gpio.map | cut -f 1,2,3,4 -d "	")
	((i++))
done