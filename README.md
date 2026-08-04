<!--
SPDX-License-Identifier: MIT
-->
# Libre Computer Wiring Tool

Utilities for Libre Computer OS images: header GPIO (`lgpio`) and device-tree
overlays (`ldto`). Board pinout tables and overlay sources live under
`libre-computer/<board>/`.

## Install

On a Libre Computer image (or any Debian system with the packages):

```bash
# GPIO tool + gpio.map data
sudo apt install libretech-gpio

# Overlay tool + .dtbo / dt.map / dt.deps
sudo apt install libretech-dtoverlay
```

From this tree:

```bash
make BOARD_NAME=aml-s905x-cc    # build overlays for one board
make check                      # integrity + gpio.map accuracy (warnings)
sudo make install               # → /opt/librecomputer/libretech-wiring-tool/
```

Installed tools are typically linked as `lgpio` / `ldto` via alternatives, or
run from `/opt/librecomputer/libretech-wiring-tool/`.

## Prerequisites

- Libre Computer board (DMI `board_vendor` / `board_name`)
- Libre Computer [OS image](http://distro.libre.computer/ci/) or Raspbian
  adapted with [libretech-raspbian-portability](https://github.com/libre-computer-project/libretech-raspbian-portability.git)
- Android, Armbian, CoreELEC, LibreELEC, Lakka are not supported

Host-side `ldto list` / `info` / `conflicts` / `enable --dry-run` work with:

```bash
export VENDOR=libre-computer BOARD=aml-s905x-cc
```

## Which tool?

| Need | Tool | Doc |
|------|------|-----|
| Header pin → chip/line, pad, mux | `lgpio` | [docs/lgpio.md](docs/lgpio.md) |
| Enable SPI/I2C/display overlays | `ldto` | [docs/ldto.md](docs/ldto.md) |
| Pinout table format / accuracy | `gpio.map` | [docs/gpio-map.md](docs/gpio-map.md) |
| Overlay naming, deps, headers | sources | [docs/overlays.md](docs/overlays.md) |
| Debian packages, install paths | packaging | [docs/packaging.md](docs/packaging.md) |

## Quick start

```bash
# Pinout
lgpio headers
lgpio pinmux 7J1 19          # MOSI pad + alt functions
lgpio info 24 name           # CE0 / SPI_SS0 on many boards
lgpio bcm check              # BCM (RPi) coverage vs gpio.map

# Overlays (runtime — needs configfs)
ldto list
ldto info spi-cc-1cs
ldto enable --dry-run spi-cc-1cs-ili9341
sudo ldto enable spi-cc-1cs-ili9341    # auto-applies bus deps
ldto conflicts spi-cc-1cs-enc28j60 spi-cc-1cs-ili9341
```

## Documentation

| Document | Contents |
|----------|----------|
| [docs/lgpio.md](docs/lgpio.md) | GPIO lookup, pinmux, get/set/watch, BCM |
| [docs/ldto.md](docs/ldto.md) | Overlay list/info/enable/conflicts/merge |
| [docs/gpio-map.md](docs/gpio-map.md) | `gpio.map` columns and checks |
| [docs/overlays.md](docs/overlays.md) | Overlay sources, naming, deps, headers |
| [docs/packaging.md](docs/packaging.md) | Packages, paths, build/install |

## Support

- [Libre Computer Hub](https://hub.libre.computer/t/libre-computer-wiring-tool/40)
- [Libera Chat IRC #librecomputer](https://web.libera.chat/#librecomputer)
- Guides: [GPIO](https://youtu.be/MDji4Yn_i8Q?t=720), [overlays](https://youtu.be/MDji4Yn_i8Q?t=600)

## License / SBOM

This project follows the [REUSE Specification](https://reuse.software/):

- Per-file `SPDX-License-Identifier` (or `REUSE.toml` annotations)
- Full texts under `LICENSES/`
- Debian: `debian/copyright` (DEP-5)

```bash
make reuse-lint          # requires: pipx install reuse
make sbom                # writes sbom.spdx
```
