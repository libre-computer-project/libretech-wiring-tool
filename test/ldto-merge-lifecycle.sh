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
# boot ignore-override: a bootloader that does not read the override.
boot() {
	local src=$BASE p v
	if [ -f "$OVR" ] && [ "${1:-}" != ignore-override ]; then
		src=$OVR
	fi
	mkdir -p "$S/sys/firmware" "$S/proc/sys/kernel/random"
	cp -f "$src" "$S/sys/firmware/fdt"
	fdtput -p -ts "$S/sys/firmware/fdt" /chosen u-boot,version "2026.07-test"
	fdtput -p -tx "$S/sys/firmware/fdt" /chosen kaslr-seed 12345678 9abcdef0
	fdtput -p -tx "$S/sys/firmware/fdt" /chosen linux,elfcorehdr 0 1000
	rm -rf "$S/proc/device-tree" "$S/run"
	mkdir -p "$S/proc/device-tree/chosen"
	for p in libretech,ldto-id libretech,ldto-merged libretech,ldto-u-boot; do
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

# --- U-Boot version note ---------------------------------------------------
run reset
boot
run merge pwm-a
check "override records the U-Boot version it was built on" [ "$(chosen libretech,ldto-u-boot)" = "2026.07-test" ]
boot
check "same U-Boot: no note" bash -c "! printf '%s' \"\$(\"$LDTO\" status 2>&1)\" | grep -q 'U-Boot is now'"
fdtput -ts "$S/sys/firmware/fdt" /chosen u-boot,version "2027.01-test"
printf '%s\0' "2027.01-test" > "$S/proc/device-tree/chosen/u-boot,version"
run status
check "newer U-Boot than the override's base: note" says "U-Boot is now 2027.01-test"

# --- after-check: crafted overlays in a scratch copy of the board ----------
run reset
boot
V=$S/vendor
mkdir -p "$V"
cp -a libre-computer/aml-s905x-cc "$V/"
mkov() { # mkov NAME BODY -- overlay with one root fragment
	cat > "$V/aml-s905x-cc/dt/$1.dts" <<-EOF
	/dts-v1/;
	/plugin/;
	/ {
		compatible = "libre-computer,aml-s905x-cc";
		fragment@0 {
			target-path = "/";
			__overlay__ {
	$2
			};
		};
	};
	EOF
	dtc -q -@ -I dts -O dtb -o "$V/aml-s905x-cc/dt/$1.dtbo" "$V/aml-s905x-cc/dt/$1.dts"
}
mkov test-dup-gpio '			test-a { gpios = <&gpio_ao 4 0>; };
			test-b { gpios = <&gpio_ao 4 0>; };'
mkov test-led-gpio '			test-c { gpios = <&gpio_ao 2 0>; };'
mkov test-uart-pins '			test-d { pinctrl-names = "default"; pinctrl-0 = <&uart_ao_a_pins>; };'
mkov test-rewrite '			chosen { stdout-path = "serial9:115200n8"; };'
mkov test-disabled-dup '			test-e { status = "disabled"; gpios = <&gpio_ao 2 0>; };'
VENDOR=$V run merge --dry-run test-dup-gpio
check "two new nodes on one GPIO: refused" rc_is 1
check "...after-check names the line" says "after-check: GPIO .*bank@14 4 is held by two enabled nodes"
VENDOR=$V run merge --dry-run test-led-gpio
check "new node on the blue LED's GPIO: refused" says "held by two enabled nodes: /leds/led-blue /test-c"
VENDOR=$V run merge --dry-run test-uart-pins
check "new node taking the console UART's pinctrl group: refused" says "pinctrl group .*uart_ao_a is held by two enabled nodes"
VENDOR=$V run merge --dry-run test-rewrite
check "overlay rewriting /chosen stdout-path: refused" says "rewrites existing node /chosen (stdout-path)"
VENDOR=$V run merge --dry-run test-disabled-dup
check "a disabled node claims nothing" rc_is 0
VENDOR=$V run merge --dry-run --no-check test-dup-gpio
check "--no-check skips the after-check" rc_is 0

# --- after-check, pad level: pinctrl debugfs of the AO controller ----------
# uart_ao_b_0_1 muxes the console's pads GPIOAO_0/1 through other groups,
# which only the pads (debugfs) show.
mkov test-uart-b01 '			test-f { pinctrl-names = "default"; pinctrl-0 = <&uart_ao_b_0_1_pins>; };'
mkov test-gpio-console '			test-g { gpios = <&gpio_ao 0 0>; };'
VENDOR=$V run merge --dry-run test-uart-b01
check "no debugfs: a different group on the console pads is not seen" rc_is 0
AO=/soc/bus@c8100000/pinctrl@14
D=$S/sys/kernel/debug/pinctrl/c8100000.bus:pinctrl@14-pinctrl-meson
mkdir -p "$D" "$S/sys/bus/platform/devices/c8100000.bus:pinctrl@14"
printf 'name [pinmux] [pinconf]\npinctrl-meson yes yes\n' > "$S/sys/kernel/debug/pinctrl/pinctrl-devices"
ln -s "../../../../firmware/devicetree/base$AO" "$S/sys/bus/platform/devices/c8100000.bus:pinctrl@14/of_node"
{
	echo "registered pins: 10"
	for i in 0 1 2 3 4 5 6 7 8 9; do echo "pin $i (GPIOAO_$i) $i:aobus-banks  c8100000.bus:pinctrl@14"; done
} > "$D/pins"
{
	echo "registered pin groups:"
	for g in uart_tx_ao_a:0 uart_rx_ao_a:1 uart_tx_ao_b_0:0 uart_rx_ao_b_1:1 GPIOAO_2:2; do
		printf 'group: %s\npin %s (GPIOAO_%s)\n\n' "${g%%:*}" "${g#*:}" "${g#*:}"
	done
} > "$D/pingroups"
VENDOR=$V run merge --dry-run test-uart-b01
check "debugfs: another group on the console pads is refused" says "pad GPIOAO_0 on $AO is held by two enabled nodes: /soc/bus@c8100000/serial@4c0 /test-f"
VENDOR=$V run merge --dry-run test-gpio-console
check "debugfs: a GPIO on a console pad is refused" says "pad GPIOAO_0 on $AO is held by two enabled nodes: /soc/bus@c8100000/serial@4c0 /test-g"
VENDOR=$V run merge --dry-run test-uart-pins
check "debugfs: the same group is reported once, not again per pad" bash -c "printf '%s' \"\$1\" | grep -q 'pinctrl group' && ! printf '%s' \"\$1\" | grep -q 'pad GPIOAO'" _ "$OUT"
VENDOR=$V run merge --dry-run pwm-e
check "debugfs: a clean overlay still merges" rc_is 0

# --- runtime (configfs) against what this boot's DT already holds ----------
CFG=$S/sys/kernel/config/device-tree/overlays
fake_active() { mkdir -p "$CFG/$1"; echo applied > "$CFG/$1/status"; }
run reset
boot
run merge spi-cc-1cs-ili9341
boot
mkdir -p "$CFG"
run enable --dry-run spi-cc-1cs-ili9341
check "enable of an overlay merged in this boot's DT: not applied again" says "spi-cc-1cs-ili9341: already merged in this boot's DT"
run enable --dry-run spi-cc-1cs-enc28j60
check "enable conflicting with an overlay merged in this boot's DT: refused" rc_is 1
run disable spi-cc-1cs-ili9341
check "disable of a merged overlay: refused with the reason" says "merged into this boot's DT, not a runtime overlay"
run reset
boot
fake_active spi-cc-1cs
fake_active spi-cc-1cs-enc28j60
run disable spi-cc-1cs
check "disable of a provider an active overlay needs: refused" says "'spi-cc-1cs' is required by active overlay 'spi-cc-1cs-enc28j60'"
check "...and nothing removed" [ -d "$CFG/spi-cc-1cs" ]
rm -rf "$CFG"

# --- the bootloader does not load the override -----------------------------
run merge pwm-a
boot ignore-override
check "override written in an earlier boot and not loaded: ignored" state_is ignored
check "...naming the cause" says "the bootloader does not read this override"
boot

# --- one changing command at a time ----------------------------------------
mkdir -p "$S/run/ldto"
flock "$S/run/ldto/lock" sleep 5 &
lockpid=$!
sleep 1
LDTO_LOCK_WAIT=0 run merge pwm-e
check "a second changing command while one runs: refused" says "another ldto command is still running"
wait "$lockpid"
check "...and the override is unchanged" [ "$(chosen libretech,ldto-merged)" = "pwm-a" ]

# --- a failed ESP write leaves the override as it was ----------------------
if [ "$(id -u)" -ne 0 ]; then
	cp -f "$OVR" "$S/ovr-before.dtb"
	chmod a-w "${OVR%/*}"
	run merge pwm-e
	chmod u+w "${OVR%/*}"
	check "ESP not writable: merge fails" rc_is 1
	check "...saying the override was not modified" says "ESP override not modified"
	check "...and it is byte-identical" cmp -s "$OVR" "$S/ovr-before.dtb"
	check "...with no staging file left behind" bash -c "! ls -A '${OVR%/*}' | grep -q '^\.ldto-new'"
fi

# --- --help never acts ------------------------------------------------------
run reset --help
check "reset --help: only prints usage" [ -f "$OVR" ]
EDITOR="sed -i s/pwm/PWM/" run edit -h
check "edit -h: only prints usage" [ "$(chosen libretech,ldto-merged)" = "pwm-a" ]
run reset bogus
check "reset with an unknown argument: refused, nothing removed" bash -c "[ $RC -eq 1 ] && [ -f '$OVR' ]"

# --- two merges from the built-in DT in one boot, then reset ----------------
run reset
boot
run merge pwm-a
run merge pwm-e
check "second merge keeps the built-in origin" [ "$(chosen libretech,ldto-u-boot)" = "2026.07-test" ]
run reset
check "...reset: no marker (this boot's DT is the built-in one)" [ ! -f "$S/run/ldto/reset-pending" ]
check "...state builtin" state_is builtin
run merge pwm-a
check "...and merge is allowed" rc_is 0

# --- a pending merge overwritten before the reboot ------------------------
run reset
boot
run merge pwm-e
cp -f "$BASE" "$OVR"
check "pending merge overwritten by another tool: replaced, not legacy" state_is replaced
check "...naming what was lost" says "pwm-e"

# --- merge --force after reset keeps what the tree already holds ------------
run reset
boot
run merge pwm-a
boot
run reset
run merge --force pwm-e
check "merge --force: record starts from the booted one" [ "$(chosen libretech,ldto-merged)" = "pwm-a pwm-e" ]
check "...and keeps the U-Boot origin" [ "$(chosen libretech,ldto-u-boot)" = "2026.07-test" ]

# --- reset that cannot record itself removes nothing -----------------------
run reset
cp -f "$BASE" "$OVR"
fdtput -ts "$OVR" / model "legacy override"
boot
mkdir -p "$S/run/ldto/reset-pending"
run reset
check "reset of a legacy override with no way to record it: refused" says "reset refused"
check "...and the override is still there" [ -f "$OVR" ]
rmdir "$S/run/ldto/reset-pending"

# --- no lock, no change -----------------------------------------------------
rm -rf "$S/run"
touch "$S/run"
run reset
check "lock directory unusable: refused" says "cannot take the ldto lock"
check "...and the override is still there" [ -f "$OVR" ]
rm -f "$S/run"

echo "ldto merge lifecycle: $pass pass, $fail fail"
[ "$fail" -eq 0 ]
