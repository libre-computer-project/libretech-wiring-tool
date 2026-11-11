#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# deb-rename.sh -- the .deb rename libretech-gpio / libretech-dtoverlay -> libre-computer-gpio /
# libre-computer-dtoverlay (package-naming policy rule 6.5), in copies of a Debian image that has the
# old packages installed (an os-factory image does). Both ways a board takes the new names:
#   T  transitional: the four packages together, as `apt upgrade` does while the transitional
#      packages are in the repository
#   B  Breaks: the two new packages alone, as libre-computer-archive-keyring's migration does once
#      they are not; apt removes the old names
# Each must leave lgpio and ldto working (their alternatives survive the old package's removal
# script) and the files owned by the new names.
#
#   sudo test/deb-rename.sh <image.img> <dir with the four built .debs>

set -uo pipefail
img=${1:?usage: sudo test/deb-rename.sh <image.img> <debs-dir>}
debs=$(realpath -e "${2:?usage: sudo test/deb-rename.sh <image.img> <debs-dir>}")
[[ $EUID -eq 0 ]] || { echo "needs root" >&2; exit 1; }
W=$(mktemp -d)
PASS=0 FAIL=0
check() { local what=$1; shift; if "$@" >/dev/null 2>&1; then PASS=$((PASS + 1)); echo "PASS  $what"; else FAIL=$((FAIL + 1)); echo "FAIL  $what"; fi; }
mnt="" loop=""
cleanup() {
	[[ -z "$mnt" ]] || { umount -R "$mnt" 2>/dev/null || true; rmdir "$mnt" 2>/dev/null || true; }
	[[ -z "$loop" ]] || losetup -d "$loop" 2>/dev/null || true
	mnt="" loop=""
	rm -f "$W/t.img"
}
trap 'cleanup; rm -rf "$W"' EXIT
deb() { find "$debs" -maxdepth 1 -name "$1_*_all.deb" -print -quit; }
for p in libre-computer-gpio libre-computer-dtoverlay libretech-gpio libretech-dtoverlay; do
	[[ -n "$(deb "$p")" ]] || { echo "no $p .deb in $debs" >&2; exit 1; }
done
# a package that Depends on an old name keeps it satisfied once the transitional package is gone (rule 6.5)
for p in gpio dtoverlay; do
	check "P: libre-computer-$p Provides libretech-$p at its own version" bash -c "[[ \$(dpkg-deb -f '$(deb libre-computer-$p)' Provides) == *'libretech-$p (= '\$(dpkg-deb -f '$(deb libre-computer-$p)' Version)')'* ]]"
done
setup() {
	cp --reflink=auto "$img" "$W/t.img"
	loop=$(losetup -fP --show "$W/t.img")
	udevadm settle
	mnt=$(mktemp -d)
	mount "${loop}p2" "$mnt"
	local m
	for m in dev dev/pts proc sys; do mount --bind "/$m" "$mnt/$m"; done
	mount -t tmpfs tmpfs "$mnt/run"
	mount -t tmpfs tmpfs "$mnt/tmp"
	cp "$debs"/*.deb "$mnt/tmp/"
}
installed() { [[ "$(chroot "$mnt" dpkg-query -W -f '${db:Status-Status}' "$1" 2>/dev/null)" == installed ]]; }
apt_local() { # local .debs through apt, which orders the swap as a board's upgrade does
	local a=() p
	for p in "$@"; do a+=("/tmp/$(basename "$(deb "$p")")"); done
	chroot "$mnt" env DEBIAN_FRONTEND=noninteractive apt-get -y -q install "${a[@]}" > "$W/apt.log" 2>&1 ||
		{ echo "-- apt failed:"; tail -n 12 "$W/apt.log"; }
}
works() { # the commands, through their alternatives, and the files' owner
	local tag=$1
	check "$tag: /usr/bin/lgpio leads to the installed lgpio" bash -c "[[ \$(chroot '$mnt' readlink -f /usr/bin/lgpio) == /opt/librecomputer/libretech-wiring-tool/lgpio ]] && test -x '$mnt/opt/librecomputer/libretech-wiring-tool/lgpio'"
	check "$tag: /usr/bin/ldto leads to the installed ldto" bash -c "[[ \$(chroot '$mnt' readlink -f /usr/bin/ldto) == /opt/librecomputer/libretech-wiring-tool/ldto ]] && test -x '$mnt/opt/librecomputer/libretech-wiring-tool/ldto'"
	check "$tag: lgpio's file belongs to libre-computer-gpio" bash -c "chroot '$mnt' dpkg -S /opt/librecomputer/libretech-wiring-tool/lgpio | grep -q '^libre-computer-gpio:'"
	check "$tag: ldto's file belongs to libre-computer-dtoverlay" bash -c "chroot '$mnt' dpkg -S /opt/librecomputer/libretech-wiring-tool/ldto | grep -q '^libre-computer-dtoverlay:'"
	check "$tag: dpkg's database is consistent (dpkg --audit says nothing)" bash -c "[[ -z \$(chroot '$mnt' dpkg --audit) ]]"
}

echo "== T: the transitional packages with the new ones"
setup
check "T: the image has the old names installed (precondition)" bash -c "$(declare -f installed); mnt='$mnt'; installed libretech-gpio && installed libretech-dtoverlay"
apt_local libre-computer-gpio libre-computer-dtoverlay libretech-gpio libretech-dtoverlay
check "T: the new names installed, the old ones now transitional" bash -c "$(declare -f installed); mnt='$mnt'; installed libre-computer-gpio && installed libre-computer-dtoverlay && [[ \$(chroot '$mnt' dpkg-query -W -f '\${Section}' libretech-gpio) == oldlibs ]]"
works T
chroot "$mnt" env DEBIAN_FRONTEND=noninteractive apt-get -y -q remove libretech-gpio libretech-dtoverlay > "$W/rm.log" 2>&1
check "T: the transitional packages removed, the new ones kept" bash -c "$(declare -f installed); mnt='$mnt'; ! installed libretech-gpio && ! installed libretech-dtoverlay && installed libre-computer-gpio && installed libre-computer-dtoverlay"
works T-after-removal
cleanup

echo "== B: the new packages alone (the old names gone from the repository)"
setup
apt_local libre-computer-gpio libre-computer-dtoverlay
check "B: the new names installed, the old ones removed by Breaks" bash -c "$(declare -f installed); mnt='$mnt'; installed libre-computer-gpio && installed libre-computer-dtoverlay && ! installed libretech-gpio && ! installed libretech-dtoverlay"
works B
cleanup

echo "deb-rename: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
