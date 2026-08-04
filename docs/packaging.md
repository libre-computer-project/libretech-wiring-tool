<!--
SPDX-License-Identifier: MIT
-->
# Packaging and install layout

## Debian packages

| Package | Contents |
|---------|----------|
| **libretech-gpio** | `lgpio`, per-board `gpio.map` |
| **libretech-dtoverlay** | `ldto`, `scripts/overlay-deps.py`, `dt/*.dtbo`, `dt.map`, `dt.deps`, `dt.config` |

Source package: `libretech-wiring-tool` (`debian/control`).

Build (example):

```bash
dpkg-buildpackage -us -uc -b
```

Depends:

- `libretech-gpio` → `gpiod`  
- `libretech-dtoverlay` → `device-tree-compiler`  

## Install prefix

Default: `/opt/librecomputer/libretech-wiring-tool/`

```text
/opt/librecomputer/libretech-wiring-tool/
  lgpio
  ldto
  scripts/overlay-deps.py
  libre-computer/<board>/
    gpio.map
    dt.map
    dt.deps
    dt.config
    dt/*.dtbo
```

`update-alternatives` (via package `.alternatives`) typically installs
`/usr/local/bin/lgpio` and `/usr/local/bin/ldto` pointing at this prefix.

From the git tree:

```bash
sudo make install              # install-lgpio + install-ldto
sudo make install-lgpio
sudo make install-ldto
# PREFIX=/opt/... DESTDIR=... optional
```

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
