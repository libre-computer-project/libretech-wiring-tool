<!--
SPDX-License-Identifier: MIT
-->
# Packaging and install layout

## Debian packages

| Package | Contents |
|---------|----------|
| **libretech-gpio** | `lgpio`, per-board `gpio.map` and `gpio.config`, `vendor/*/*/gpio_debug` (`lgpio debug`) |
| **libretech-dtoverlay** | `ldto`, `scripts/overlay-deps.py`, `dt/*.dtbo` + their `dt/*.dts` sources, `dt.map`, `dt.deps`, `dt.config`, `boot.config` |

The `.dts` sources ship beside the `.dtbo`: `ldto list`, `info`, `conflicts`
and the `enable` preflight read `Summary:`, `Pins:` and `Resource-*` from them.

Source package: `libretech-wiring-tool` (`debian/control`).

Build: `./build.sh` (stamps a dated `debian/changelog` entry, then runs
`dpkg-buildpackage -uc -us --build=all`). Build-Depends include `python3`
(`dt.deps` generation and the build-time checks).

Depends:

- `libretech-gpio` → `gpiod`  
- `libretech-dtoverlay` → `device-tree-compiler`, `libretech-gpio` (ldto reads `gpio.map`)  

## Install prefix

Default: `/opt/librecomputer/libretech-wiring-tool/`

```text
/opt/librecomputer/libretech-wiring-tool/
  lgpio
  ldto
  scripts/overlay-deps.py
  libre-computer/<board>/
    gpio.map
    gpio.config          # GXL boards only (lgpio debug)
    dt.map
    dt.deps
    dt.config
    boot.config
    dt/*.dtbo
    dt/*.dts
  vendor/aml/gxl/gpio_debug
```

`boot.config` (in `libretech-dtoverlay`) says what the board's BootROM boots
from, for flashing tools; nothing in LWT itself reads it.
`EMMC_BOOT_PARTITIONS=yes` means the bootloader can live in the eMMC `boot0` /
`boot1` hardware partitions; `no` means the BootROM reads the eMMC user area
only, so the bootloader sits at the vendor boot sector before the first
partition; `unknown` means not shown and is treated as `no`. `SPI_NOR=yes`
means the board has SPI NOR, which holds its bootloader; `no` means none is
fitted; `unknown` means it varies by build or is not shown, and is treated as
`no`. On a board where both read `no`, a tool that writes a whole OS image
with no bootloader in it checks that the bootloader fits before the first
partition and writes it there, or warns that the board will not boot.
`make check` validates every board's file.

The packages register `/usr/bin/lgpio` and `/usr/bin/ldto` with
`update-alternatives`; `install.sh` (git checkout) registers
`/usr/local/bin/lgpio` and `/usr/local/bin/ldto` instead.

From the git tree:

```bash
sudo make install              # install-lgpio + install-ldto (builds first)
sudo make install-lgpio
sudo make install-ldto
# PREFIX=/opt/... DESTDIR=... optional
```

`lgpio debug` sources `gpio.config` and the `GPIO_DEBUG_PATH` it names,
relative to the install root.

## Runtime board paths

`lgpio` / `ldto` `cd` to the install (or repo) root and open:

```text
$VENDOR/$BOARD/gpio.map
$VENDOR/$BOARD/dt/
$VENDOR/$BOARD/dt.map
$VENDOR/$BOARD/dt.deps
$VENDOR/$BOARD/dt.config
```

`$VENDOR` / `$BOARD` from DMI, or set in the environment.

## LBS / SPI NOR

Libre Computer U-Boot SPI builds package LWT overlays into a FIT image
(`LBS_LWT_PATH`, `make BOARD_NAME=…`). Boot-time `overlays=` uses the FIT
copy — rebuild LBS after renaming overlays so NOR matches the tree.

## Related

- [README.md](../README.md)  
- [ldto.md](ldto.md)  
- [lgpio.md](lgpio.md)  
