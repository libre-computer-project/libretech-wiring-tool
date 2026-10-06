#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Da Xue <da@libre.computer>
#
# ldto merge / reset / edit lifecycle, run against a scratch system root:
# boots are simulated by copying the DT U-Boot would hand over (the override
# DTB if present, else the built-in one) to sys/firmware/fdt, adding the
# per-boot /chosen values the bootloader writes, exposing /chosen under
# proc/device-tree, and giving every boot a new boot_id and an empty /run.
#
# Needs: built overlays for aml-s905x-cc (make BOARD_NAME=aml-s905x-cc) and the
# board's base DTB (LWT_BASE_DTB, default: the lc618 kernel build tree).
# Exit 0 = every case passed, 1 = a case failed, 0 with SKIP = no base DTB.

set -u

cd "$(readlink -f "$(dirname "${BASH_SOURCE[0]}")")/.."
LDTO=$PWD/ldto
BASE=${LWT_BASE_DTB:-$HOME/build/lc618/x86_64-arm64/arch/arm64/boot/dts/amlogic/meson-gxl-s905x-libretech-cc.dtb}
if [ ! -f "$BASE" ]; then
	echo "SKIP: no base DTB at $BASE (set LWT_BASE_DTB)"
	exit 0
fi
for o in spi-cc-1cs spi-cc-1cs-ili9341 spi-cc-1cs-enc28j60 pwm-a pwm-e; do
	if [ ! -f "libre-computer/aml-s905x-cc/dt/$o.dtbo" ]; then
		echo "SKIP: $o.dtbo not built (make BOARD_NAME=aml-s905x-cc)"
		exit 0
	fi
done

S=$(mktemp -d /tmp/ldto-lifecycle.XXXXXX)
trap 'rm -rf "$S"' EXIT
export VENDOR=libre-computer BOARD=aml-s905x-cc LDTO_SYSROOT=$S LDTO_EFI_DTB=$S/esp/dtb
OVR=$S/esp/dtb/amlogic/meson-gxl-s905x-libretech-cc.dtb
pass=0
fail=0
OUT=
RC=0

# boot: U-Boot loads the override if present, else its built-in DT.
boot() {
	local src=$BASE p v
	[ -f "$OVR" ] && src=$OVR
	mkdir -p "$S/sys/firmware" "$S/proc/sys/kernel/random"
	cp -f "$src" "$S/sys/firmware/fdt"
	fdtput -p -ts "$S/sys/firmware/fdt" /chosen u-boot,version "2026.07-test"
	fdtput -p -tx "$S/sys/firmware/fdt" /chosen kaslr-seed 12345678 9abcdef0
	fdtput -p -tx "$S/sys/firmware/fdt" /chosen linux,elfcorehdr 0 1000
	rm -rf "$S/proc/device-tree" "$S/run"
	mkdir -p "$S/proc/device-tree/chosen"
	for p in libretech,ldto-id libretech,ldto-merged; do
		if v=$(fdtget -ts "$S/sys/firmware/fdt" /chosen "$p" 2>/dev/null); then
			# shellcheck disable=SC2086 # one word per string
			printf '%s\0' $v > "$S/proc/device-tree/chosen/$p"
		fi
	done
	cat /proc/sys/kernel/random/uuid > "$S/proc/sys/kernel/random/boot_id"
}

run() {
	OUT=$("$LDTO" "$@" 2>&1)
	RC=$?
}

check() {
	local what=$1
	shift
	if "$@"; then
		pass=$((pass + 1))
	else
		fail=$((fail + 1))
		echo "FAIL: $what"
		echo "      rc=$RC"
		printf '%s\n' "$OUT" | sed 's/^/      | /'
	fi
}

rc_is() { [ "$RC" -eq "$1" ]; }
same_nonempty() { [ -n "$1" ] && [ "$1" = "$2" ]; }
says() { printf '%s\n' "$OUT" | grep -q -- "$1"; }
state_is() { run status; says "#Next boot DT: $1"; }
chosen() { fdtget -ts "$OVR" /chosen "$1" 2>/dev/null; }

# --- built-in boot, first merge -------------------------------------------
boot
check "fresh boot: next boot is the built-in DT" state_is builtin
run merge spi-cc-1cs-ili9341
check "first merge succeeds" rc_is 0
check "record lists provider and device" [ "$(chosen libretech,ldto-merged)" = "spi-cc-1cs spi-cc-1cs-ili9341" ]
check "base kind names the U-Boot version" [ "$(chosen libretech,ldto-base)" = "builtin:2026.07-test" ]
check "per-boot kaslr-seed not frozen into the override" bash -c "! fdtget '$OVR' /chosen kaslr-seed >/dev/null 2>&1"
check "per-boot u-boot,version not frozen into the override" bash -c "! fdtget '$OVR' /chosen u-boot,version >/dev/null 2>&1"
check "kexec linux,elfcorehdr not frozen into the override" bash -c "! fdtget '$OVR' /chosen linux,elfcorehdr >/dev/null 2>&1"
check "merged, not rebooted: pending-merge" state_is pending-merge
run merge spi-cc-1cs-ili9341
check "re-merge: nothing to do" says "nothing to do"
run merge spi-cc-1cs-enc28j60
check "merge conflicting with the recorded ili9341 is refused" rc_is 1
check "...and the override is unchanged" [ "$(chosen libretech,ldto-merged)" = "spi-cc-1cs spi-cc-1cs-ili9341" ]

# --- boot the override, merge more ----------------------------------------
boot
check "booted the override: sync" state_is sync
run merge pwm-a
check "second merge succeeds" rc_is 0
check "record appended" [ "$(chosen libretech,ldto-merged)" = "spi-cc-1cs spi-cc-1cs-ili9341 pwm-a" ]
check "merged since boot: changed" state_is changed

# --- reset without reboot -------------------------------------------------
boot
run reset
check "reset succeeds" rc_is 0
check "reset tells the user to reboot" says "reboot before the next 'ldto merge'"
check "reset, not rebooted: removed" state_is removed
check "...and status names what this boot still runs" says "merged: spi-cc-1cs spi-cc-1cs-ili9341 pwm-a"
run merge pwm-e
check "merge refused while the removed override still runs" rc_is 1
check "...with the reason" says "merge refused"
check "...and no override written" [ ! -f "$OVR" ]
run enable --dry-run pwm-e
check "enable warns that the next boot differs" says "reboot to apply"
run merge --force pwm-e
check "--force merges anyway" rc_is 0
run reset

# --- reboot to built-in, merge, then tamper / replace ---------------------
boot
check "rebooted after reset: built-in" state_is builtin
run merge pwm-e
check "merge after reboot succeeds" rc_is 0
fdtput -ts "$OVR" / model "edited by hand"
check "override changed outside ldto: tampered" state_is tampered
run reset
boot
run merge pwm-e
boot
check "booted the new override: sync" state_is sync
cp -f "$BASE" "$OVR"
check "override overwritten by another tool: replaced" state_is replaced
check "...naming the lost overlays" says "pwm-e"

# --- edit ------------------------------------------------------------------
run reset
boot
run merge pwm-a
boot
rec_before=$(chosen libretech,ldto-merged)
EDITOR=true run edit
check "edit succeeds" rc_is 0
check "edit keeps the record" same_nonempty "$rec_before" "$(chosen libretech,ldto-merged)"
check "edit marks the record advisory" [ "$(chosen libretech,ldto-edited)" = "1" ]
check "edited since boot: changed" state_is changed

# --- legacy override (no stamp): /run fallback ----------------------------
run reset
cp -f "$BASE" "$OVR"
fdtput -ts "$OVR" / model "legacy override"
boot
check "booted an unstamped override: legacy" state_is legacy
run reset
check "reset of an unstamped override leaves the per-boot marker" [ -f "$S/run/ldto/reset-pending" ]
check "...so the state is removed" state_is removed
run merge pwm-a
check "...and merge is refused" rc_is 1
echo "00000000-0000-0000-0000-000000000000" > "$S/proc/sys/kernel/random/boot_id"
check "a marker from another boot is ignored" state_is builtin
boot
run merge pwm-a
check "after reboot, merge succeeds" rc_is 0

# --- reset of an override merged onto the built-in DT in this boot --------
run reset
boot
run merge pwm-e
run reset
check "same-boot merge from built-in, then reset: no marker" [ ! -f "$S/run/ldto/reset-pending" ]
check "...state builtin" state_is builtin
run merge pwm-a
check "...merge allowed" rc_is 0

echo "ldto merge lifecycle: $pass pass, $fail fail"
[ "$fail" -eq 0 ]
