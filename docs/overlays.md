<!--
SPDX-License-Identifier: MIT
-->
# Device-tree overlays (sources)

Overlay sources and board metadata under `libre-computer/<board>/`.

```text
libre-computer/<board>/
  dt/                 # *.dts → *.dtbo (make)
  dt.map              # H40P_* / product alias → overlay basename
  dt.deps             # consumer → provider (generated)
  dt.config           # DT_OVERRIDE path for EFI merge
  gpio.map            # header pinout (see gpio-map.md)
```

## Build

```bash
make BOARD_NAME=aml-s905x-cc
make BOARD_NAME=aml-s905d3-cc
make                    # all boards
make deps               # regenerate dt.deps only
make check              # maps/headers + fdtoverlay smoke (warnings)
make check-fdtoverlay   # only apply smoke
make check-strict       # same checks; exit 1 on WARNING
```

Build rule: `cpp` preprocess → `dtc -@ -q` → `.dtbo`. Same-dir `.dts`
symlinks produce matching `.dtbo` symlinks (legacy aliases).

Whole-dir `dt/` symlinks (e.g. `aml-s905x-cc-v2/dt` → `../aml-s905x-cc/dt`)
compile the real tree.

### fdtoverlay smoke (`scripts/check-fdtoverlay.py`)

Applies each unique overlay **with `dt.deps` providers first** onto the
board base DTB named by `dt.config` `DT_OVERRIDE`:

```bash
# base DTBs from a kernel O= tree (fleet default auto-search also tries this)
export LWT_DTB_DIR=$HOME/build/lc618/x86_64-arm64/arch/arm64/boot/dts
make check-fdtoverlay
# or
python3 scripts/check-fdtoverlay.py --board aml-s905x-cc -v
python3 scripts/check-fdtoverlay.py --strict --require-base   # CI
```

| Result | Meaning |
|--------|---------|
| **OK** | `fdtoverlay -i base … providers consumer` succeeded |
| **WARNING** | apply failed, missing `.dtbo`, or base lacks `__symbols__` |
| **SKIP** | no base DTB found for this board (not a failure unless `--require-base`) |

Base DTB must include `/__symbols__` (kernel `DTC_FLAGS=-@`). Without a
DTB tree, smoke is skipped so map-only hosts stay green.

## Overlay header policy

Every real (non-symlink) `.dts` should start with SPDX, copyright, and:

```dts
/*
 * Summary: one-line purpose
 *
 * Pins (Header.Pin  Name  Pad  Ref — cross-ref gpio.map):
 *   7J1.19  GPIOX_8  B4  BTPCM_DOUT
 *
 * Requires: spi-cc-1cs          /* if dt.deps lists providers */
 *
 * Notes: optional free-form
 */
```

`gpio.map` is the pinout authority for `Pins:` rows.  
Bulk refresh: `scripts/normalize-overlay-headers.py`.

## SPI chip-select naming

Linux DT vocabulary only: **`cs`**. Do not use RPi `ce` / `1cs2` in new
basenames (legacy names remain as same-dir symlinks).

```text
spi-<ctrl>-<n>cs                    # bus: n chip-selects
spi-<ctrl>-<n>cs-<device>           # device on reg=0
spi-<ctrl>-<n>cs-cs<i>-<device>     # device on reg=i
spi-<ctrl>-1cs-cs1                  # sole CS on second header CS pin
```

`<n>cs` is the **count** of chip-selects, not “chip select number n”.

## Root compatible

Order: `libre-computer,<board>`, `libretech,<board>`, SoC fallbacks.  
Include every board/variant that may apply the source.

## Dual-driver displays (tinydrm + fbtft)

Product / tinydrm id first, binding fallback next, fbtft-only id last if
different. Tag fbtft-only properties `/* fbtft/legacy */`.

## dt.map / dt.deps

- **dt.map** values must be **canonical** non-symlink basenames  
- **dt.deps** providers must exist; regenerate with `make deps`  
- `ldto enable` / `merge` expand deps automatically  

## Integrity

`scripts/check-lwt.py` (via `make check`) warns on:

- gpio.map Name/Line/Chip vs SoC bindings  
- overlay headers missing `Summary:` or Pins rows that disagree with gpio.map  
- dt.map targets that do not exist  
- dt.deps consumers/providers without a `.dts`  

## Related

- [ldto.md](ldto.md) — runtime / merge CLI  
- [gpio-map.md](gpio-map.md) — pinout tables  
- [packaging.md](packaging.md) — shipping `.dtbo`  
