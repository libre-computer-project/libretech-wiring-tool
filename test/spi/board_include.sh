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
			spi_devnum=1
			board_clocks="c1108d80.spi#pow2_div,c1108d80.spi#pow2_fixed_div,gxbb_spi,gxbb_spicc"
			spi_speed_max=41666666
			;;
		aml-a311d-cc | aml-s905d3-cc)
			spi_devnum=1
			board_clocks=spicc1_sclk,spicc1_sclk_div,spicc1_sclk_sel,g12a_spicc_1
			spi_speed_max=166666664
			;;
		*)
			spi_devnum=$(find $DEV_PATH -maxdepth 1 -iname $SPI_DEV_NAME\*.0 | head -n 1)
			if [ -z $spi_devnum ]; then
				echo "Unable to find $SPI_DEV_NAME in $DEV_PATH!" >&2
				exit 1
			else
				spi_devnum=${spi_devnum#$SPI_DEV_PATH}
				spi_devnum=${spi_devnum%\.*}
			fi
			spi_speed_max=0
			;;
	esac
fi

spi_device="$SPI_DEV_PATH${spi_devnum}.0"
if [ "$spi_speed_max" -eq 0 ]; then
	spi_speeds=(${SPI_SPEEDS[@]})
else
	spi_speeds=()
	for i in "${SPI_SPEEDS[@]}"; do
		if [ "$i" -le "$spi_speed_max" ]; then
			spi_speeds+=($i)
		fi
	done
fi

if [ ! -c "$spi_device" ]; then
	echo "spi_device $spi_device does not exist" >&2
	exit 1
fi

if [ ! -w "$spi_device" ]; then
        echo "spi_device $spi_device is not writable. sudo?" >&2
        exit 1
fi
