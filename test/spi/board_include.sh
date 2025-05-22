# Copyright (c) 2025 Da Xue <da@libre.computer>
# SPDX-License-Identifier: MIT

DMI_BOARDNAME_PATH=/sys/class/dmi/id/board_name
DEV_PATH=/dev
SPI_DEV_NAME=spidev
SPI_DEV_PATH=$DEV_PATH/$SPI_DEV_NAME

if [ -e "$DMI_BOARDNAME_PATH" ]; then
	board=$(cat "$DMI_BOARDNAME_PATH")
	case $board in
		aml-s805x-ac | aml-s905x-cc | aml-s905x-cc-v2 | aml-s905d-pc)
			spi_devnum=0
			board_clock="c1108d80.spi#pow2_div"
			spi_speed_max=41666666
			spi_speed_min=325521
			spi_chunk_size_max=1024
			;;
		aml-a311d-cc | aml-s905d3-cc)
			spi_devnum=1
			board_clock="ffd15000.spi#sel"
			spi_speed_max=166666664
			spi_speed_min=50000
			spi_chunk_size_max=524280
			;;
		*)
			spi_devnum=$(find $DEV_PATH -maxdepth 1 -iname $SPI_DEV_NAME\*.0 | head -n 1)
			board_clock=
			if [ -z $spi_devnum ]; then
				echo "Unable to find $SPI_DEV_NAME in $DEV_PATH!" >&2
				exit 1
			else
				spi_devnum=${spi_devnum#$SPI_DEV_PATH}
				spi_devnum=${spi_devnum%\.*}
			fi
			spi_speed_max=0
			spi_speed_min=0
			;;
	esac
fi

if [ ! -z "$spi_devnum_user" ]; then
	spi_devnum=$spi_devnum_user
fi

spi_device="$SPI_DEV_PATH${spi_devnum}.0"
if [ "$spi_speed_max" -eq 0 ]; then
	spi_speeds=(${SPI_SPEEDS[@]})
else
	spi_speeds=()
	for i in "${SPI_SPEEDS[@]}"; do
		if [ "$i" -le "$spi_speed_max" ]; then
			spi_speeds+=($i)
			spi_speed_last=$i
		fi
	done
	if [ $spi_speed_last -lt $spi_speed_max ]; then
		spi_speeds+=($spi_speed_max)
	fi
fi

if [ ! -c "$spi_device" ]; then
	echo "spi_device $spi_device does not exist" >&2
	exit 1
fi

if [ ! -w "$spi_device" ]; then
        echo "spi_device $spi_device is not writable. sudo?" >&2
        exit 1
fi
