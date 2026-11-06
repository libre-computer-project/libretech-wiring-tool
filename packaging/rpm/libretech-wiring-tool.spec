# SPDX-License-Identifier: GPL-2.0-only
# Fedora packages of libretech-wiring-tool: the same two packages, files and commands as the .deb (debian/control).
# Built by build-rpm.sh from a staged tree (lc_stage) and its per-package file lists (lc_lists); nothing is built
# here. Defines: lc_version, lc_stage, lc_lists.
%global debug_package %{nil}
%global __os_install_post %{nil}
%define _build_id_links none
%global lc_prefix /opt/librecomputer/libretech-wiring-tool

Name: libretech-wiring-tool
Version: %{lc_version}
# a package fix on the same source: a served file name never changes, so the fix is a new release
Release: %{?lc_release}%{!?lc_release:1}
Summary: Libre Computer header GPIO and device-tree overlay tools
License: GPL-2.0-only
URL: https://github.com/libre-computer-project/libretech-wiring-tool
BuildArch: noarch
AutoReqProv: no

%description
Libre Computer header GPIO lookup (lgpio) and device-tree overlays with the ldto tool.

%package -n libretech-gpio
Summary: Libre Computer header GPIO lookup and control (lgpio)
Requires: libgpiod-utils
Requires(post): /usr/sbin/alternatives
Requires(preun): /usr/sbin/alternatives

%description -n libretech-gpio
Translates 40-pin header pin numbers and BCM (RPi) GPIO numbers to chip/line, sysfs, pad, and schematic names for
Libre Computer boards. Includes get/set helpers for interactive use (not a high-performance API).

Board data lives under /opt/librecomputer/libretech-wiring-tool/libre-computer/.

%package -n libretech-dtoverlay
Summary: Libre Computer device-tree overlays and ldto tool
Requires: dtc
Requires: libretech-gpio = %{version}-%{release}
Recommends: i2c-tools
Recommends: spi-tools
Requires(post): /usr/sbin/alternatives
Requires(preun): /usr/sbin/alternatives

%description -n libretech-dtoverlay
Compiles and installs per-board device-tree overlays (.dtbo) for header buses and accessories (I2C, SPI, UART, PWM,
displays, etc.), plus the ldto CLI to apply overlays at runtime (configfs) or merge them into the EFI/boot DTB for the
next boot.

Board overlays and H40P_* alias maps live under /opt/librecomputer/libretech-wiring-tool/libre-computer/.

%install
cp -a %{lc_stage}/. %{buildroot}/

%post -n libretech-gpio
/usr/sbin/alternatives --install /usr/bin/lgpio lgpio %{lc_prefix}/lgpio 50 || :

%preun -n libretech-gpio
if [ "$1" -eq 0 ]; then /usr/sbin/alternatives --remove lgpio %{lc_prefix}/lgpio || :; fi

%post -n libretech-dtoverlay
/usr/sbin/alternatives --install /usr/bin/ldto ldto %{lc_prefix}/ldto 50 || :

%preun -n libretech-dtoverlay
if [ "$1" -eq 0 ]; then /usr/sbin/alternatives --remove ldto %{lc_prefix}/ldto || :; fi

%files -n libretech-gpio -f %{lc_lists}/libretech-gpio.files

%files -n libretech-dtoverlay -f %{lc_lists}/libretech-dtoverlay.files
