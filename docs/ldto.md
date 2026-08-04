<!--
SPDX-License-Identifier: MIT
-->
# ldto — device-tree overlay tool

Apply Libre Computer device-tree overlays at runtime (configfs) or merge
them into the EFI/boot DTB for the next boot. Resolves `dt.map` aliases
and auto-applies providers from `dt.deps`.

Package: `libretech-dtoverlay` (depends on `device-tree-compiler`).  
Data: `libre-computer/<board>/dt/*.dtbo`, `dt.map`, `dt.deps`, `dt.config`.

## Board detection

Same DMI / `VENDOR` / `BOARD` as [lgpio](lgpio.md). Host-side (no configfs):

```bash
export VENDOR=libre-computer BOARD=aml-s905x-cc
./ldto list
./ldto info spi-cc-1cs
./ldto enable --dry-run spi-cc-1cs-ili9341
./ldto conflicts spi-cc-1cs-enc28j60 spi-cc-1cs-ili9341
```

Commands that **do not** require configfs: `help`, `list`, `info`,
`conflicts`, `enable --dry-run`, `merge` / `merge --dry-run` (needs
firmware DTB / EFI for real merge).  
Commands that **need configfs**: `enable` (apply), `disable`, `status`,
`active`.  
Commands that need firmware/EFI DTB (not configfs): `merge`, `show`,
`diff`, `reset`, `current`.

## Commands

```text
ldto list
ldto status
ldto active [OVERLAY]
ldto enable [--dry-run|-n] OVERLAY [OVERLAY...]
ldto disable OVERLAY...
ldto info OVERLAY|ALIAS...
ldto conflicts [OVERLAY|ALIAS]...
ldto current
ldto merge OVERLAY...
ldto show
ldto diff
ldto reset
```

### list

Prints available overlays (`.dtbo`, or `.dts` if not built):

```text
OVERLAY                        ALIAS                    SUMMARY
spi-cc-1cs                     H40P_SPI_0_1CS           SPICC on Header 7J1
i2c-ao                         H40P_I2C_0               I2C_AO on Header 7J1
```

`SUMMARY` comes from the overlay DTS header (`Summary:` field).

### info

Description, requires / required-by (`dt.deps`), map aliases, GPIO
connections (DTS pads × `gpio.map`), and header pin notes.

```bash
ldto info spi-cc-1cs-enc28j60
ldto info H40P_SPI_0_1CS
```

### enable / disable

```bash
# Temporary (until reboot) via configfs
sudo ldto enable spi-cc-1cs-ili9341
# Providers from dt.deps applied first (e.g. spi-cc-1cs)

ldto enable --dry-run spi-cc-1cs-ili9341   # plan + pins + optional fdtoverlay chain check
ldto enable -n H40P_SPI_0_2CS_LCD_35
sudo ldto enable --no-preflight …          # skip fdtoverlay (not recommended)

sudo ldto disable spi-cc-1cs-ili9341
```

**Autoload + clean apply:** `enable` expands `dt.deps`, then **preflights the
entire chain** with `fdtoverlay` against `/sys/firmware/fdt`. If any
**intermediary** step fails, it prints `WARNING: apply not clean at overlay
'…'` (plan + steps that would have succeeded) and **applies nothing** to
configfs. If configfs fails mid-chain after preflight, overlays applied in
*this* command are rolled back.

Hardware overlays can wedge the system if removed while in use — disable
carefully.

### conflicts

Pin occupancy for the named overlays (deps expanded) plus any **active**
overlays when configfs is present.

```bash
ldto conflicts spi-cc-1cs-enc28j60 spi-cc-1cs-ili9341
```

- **Occupancy** — every resolved header pin and which overlays claim it  
- **Conflicts** — same pin claimed by overlays that are **not** in a
  provider→consumer relationship (shared SPI bus pins between a bus
  overlay and its device are OK; two independent devices on the same pins
  are not)

Exit status `2` if conflicts are reported.

### merge / show / diff / reset / current

Permanent path: merge overlays into the EFI DTB override (see board
`dt.config` for `DT_OVERRIDE` path). Effective after reboot.

```bash
sudo ldto merge spi-cc-1cs-ili9341
ldto merge --dry-run spi-cc-1cs-ili9341   # chain preflight only (no ESP write)
ldto show          # next-boot DTB as DTS
sudo ldto diff     # running vs next-boot
sudo ldto reset    # remove override DTB
sudo ldto current  # running firmware DTB as DTS
```

**Autoload + atomic merge:** expands `dt.deps` (providers first), then applies
the full chain to a **temp** DTB starting from the existing override (if any)
or the running firmware DTB. Only if **every** step succeeds is the result
installed to the ESP. An intermediate `fdtoverlay` failure prints
`WARNING: apply not clean at overlay '…'` / `WARNING: merge aborted — ESP
override not modified` and leaves the previous override untouched (no
half-merged next-boot DTB).

A kernel package upgrade may overwrite the ESP DTB — re-merge after
upgrades if you rely on permanent overlays.

## Aliases (dt.map)

Board-agnostic names for common 40-pin functions (values are **canonical**
overlay basenames):

```text
H40P_I2C_0              I2C on pins 3, 5
H40P_I2C_1              I2C on pins 27, 28
H40P_SPI_0_1CS          SPI + CS on pin 24
H40P_SPI_0_2CS          SPI + CS on pins 24, 26
H40P_SPI_0_*_DEV        … + spidev
H40P_UART_0             UART on pins 8, 10
H40P_PWM_P*             PWM on pin *
```

Use `ldto list` / `ldto info <alias>` for the board’s actual mapping.
Some PWM controllers expose two outputs via different overlays — only
enable one unless you know the board’s map.

## Dependencies (dt.deps)

Auto-generated (`make deps` / `scripts/overlay-deps.py`). `enable` and
`merge` expand consumers so bus overlays apply before devices.

## Related

- [overlays.md](overlays.md) — source layout, naming, headers  
- [gpio-map.md](gpio-map.md) — pinout cross-ref used by `info` / `conflicts`  
- [README.md](../README.md) — index  
