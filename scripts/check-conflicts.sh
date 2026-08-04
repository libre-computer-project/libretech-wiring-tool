#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Da Xue <da@libre.computer>
#
# Host-side regression matrix for ldto conflicts (pins + Resource-* + derived
# aliases). No board/configfs required.
#
# Exit 0 if every case matches the expected status; 1 on mismatch.
# make check runs this with || true (WARN model); make check-strict / CI
# should invoke without swallowing the status.
#
# Usage:
#   scripts/check-conflicts.sh
#   scripts/check-conflicts.sh --board aml-s905x-cc
#   VENDOR=libre-computer BOARD=aml-s905x-cc scripts/check-conflicts.sh

set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
LDTO="$ROOT/ldto"
BOARD="${BOARD:-aml-s905x-cc}"
VENDOR="${VENDOR:-libre-computer}"

while [ $# -gt 0 ]; do
	case "$1" in
		--board)
			BOARD="$2"
			shift 2
			;;
		-h|--help)
			echo "Usage: $0 [--board BOARD]" >&2
			exit 0
			;;
		*)
			echo "unknown option: $1" >&2
			exit 1
			;;
	esac
done

export VENDOR BOARD
export PATH="${PATH:-/usr/bin:/bin}"

if [ ! -x "$LDTO" ]; then
	echo "WARNING: check-conflicts: ldto not executable at $LDTO" >&2
	exit 1
fi

if [ ! -d "$ROOT/libre-computer/$BOARD/dt" ]; then
	echo "WARNING: check-conflicts: no dt/ for board $BOARD" >&2
	exit 1
fi

# name | expected_exit | arg1 [arg2 ...]
# expected: 0 = clean, 2 = conflicts reported (ldto conflicts exit 2)
CASES_s905x_cc=(
	"spi_bus_only|0|spi-cc-1cs"
	"spi_bus_device|0|spi-cc-1cs|spi-cc-1cs-ili9341"
	"spi_two_devices|2|spi-cc-1cs-ili9341|spi-cc-1cs-enc28j60"
	"map_alias|0|H40P_SPI_0_1CS"
	"uart_sdio_alias|2|uart-a|sdio"
	"sdio_pwm_e_ok|0|sdio|pwm-e"
	"rtc_addr_clash|2|i2c-ao-ds3231|i2c-ao-pcf8523"
	"fan_related|0|pwm-a|pwm-a-fan"
	"emc_stack|0|i2c-ao-emc2301|i2c-ao-emc2301-auto"
	"i2c_uart_ok|0|i2c-ao|uart-a"
	"cvbs_usb_ok|0|cvbs-disable|usb-device-mode"
)

CASES_s805x_ac=(
	"uart_sdio_alias|2|uart-a|sdio"
)

case "$BOARD" in
	aml-s905x-cc|aml-s905x-cc-v2)
		CASES=("${CASES_s905x_cc[@]}")
		# v2 shares dt/ with s905x-cc
		BOARD=aml-s905x-cc
		export BOARD
		;;
	aml-s805x-ac|aml-s805x-ac-v2)
		CASES=("${CASES_s805x_ac[@]}")
		BOARD=aml-s805x-ac
		export BOARD
		;;
	*)
		echo "SKIP: check-conflicts: no matrix for board $BOARD" >&2
		exit 0
		;;
esac

fail=0
pass=0
for spec in "${CASES[@]}"; do
	IFS='|' read -r name expect a1 a2 a3 <<<"$spec"
	args=("$a1")
	[ -n "${a2:-}" ] && args+=("$a2")
	[ -n "${a3:-}" ] && args+=("$a3")

	set +e
	"$LDTO" conflicts "${args[@]}" >/tmp/lwt-conflicts-$$.out 2>&1
	got=$?
	set -e

	# ldto conflicts: 0 clean, 2 conflict, 1 usage/error
	if [ "$got" -eq "$expect" ]; then
		echo "OK  $name (exit $got) — ${args[*]}"
		pass=$((pass + 1))
	else
		echo "WARNING: check-conflicts FAIL $name: expected exit $expect got $got — ${args[*]}" >&2
		sed -n '1,20p' /tmp/lwt-conflicts-$$.out >&2 || true
		fail=$((fail + 1))
	fi
	rm -f /tmp/lwt-conflicts-$$.out
done

echo "check-conflicts: $pass ok, $fail fail (board=$BOARD)" >&2
if [ "$fail" -gt 0 ]; then
	exit 1
fi
exit 0
