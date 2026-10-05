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
| **WARNING** | apply failed, missing `.dtbo`, base lacks `__symbols__`, or an alias the overlay adds names no node in the merged tree |
| **not-for-board** | the overlay's board-level `compatible` entries leave this board out; it reaches the board only through a shared `dt/` symlink (counted, never silent) |
| **SKIP** | no base DTB found for this board (not a failure unless `--require-base`) |

An apply that succeeds can still be wrong: an `/aliases` entry is a path
string, and a path that names no node is dropped by the kernel without a word,
so `serial1` silently becomes the next free number. The check reads each alias
an overlay adds from the merged tree. Pre-mainline node names (`cbus@`,
`aobus@`, `/soc/spi@01c68000`, a `/soc` prefix on RK3328) were the whole
population when it first ran.

The root `compatible` is otherwise informational -- neither `ldto` nor U-Boot
matches it before applying -- so listing a board that cannot take the overlay
is invisible except here.

Base DTB must include `/__symbols__` (kernel `DTC_FLAGS=-@`). Without a
DTB tree, smoke is skipped so map-only hosts stay green.

### What an overlay muxes (`scripts/check-overlay-pins.py`)

`check-lwt` compares each `Pins:` row with `gpio.map`, but nothing compared
`Pins:` with the overlay body. This applies each overlay with its providers,
resolves every node it touches to SoC pads, and keeps those on a header:

| Source in the merged tree | Resolved through |
|---|---|
| `pinctrl-N` | meson `groups` via the pinctrl driver's `<group>_pins[]`; sunxi `pins`; rockchip `rockchip,pins` cells |
| `*-gpios` | the controller node: rockchip `gpioN`, sunxi `pio`/`r_pio` bank+pin, meson AO/EE line via `dt-bindings` |
| `interrupts` / `interrupts-extended` | GPIO lines used as interrupts: meson `gpio-intc` hwirq via `IRQID_*`, rockchip/sunxi GPIO controllers |

| Finding | Meaning |
|---|---|
| UNDOCUMENTED | a header pad the overlay itself newly muxes, absent from `Pins:` (bus pins a provider already muxed are the provider's to list) |
| STALE | a `Pins:` pad nothing in the overlay chain muxes |
| NO-SUCH-PAD | a pad the SoC package does not bond out (from the claude repo's ball extracts) -- an overlay copied from a sibling board |
| RESIDUE | `?.?` rows, repeats of `Pins:`, or unmuxed pads left under `Notes:` by an older header generator |

```bash
make check-overlay-pins                                    # needs base DTBs + a kernel tree
python3 scripts/check-overlay-pins.py --explain --board aml-s905x-cc
python3 scripts/check-overlay-pins.py --fix   # rewrite flagged Pins: blocks from gpio.map
```

It needs a kernel tree (Amlogic group tables) like `check-pinmux`, so it is not
in `make check`; its `--self-test` is.

Two pinctrl rules matter to that resolution. The core applies a state by name
at probe, taking the first `pinctrl-N` named `default` (or `init`); a second
`default`, or a node with no `pinctrl-names`, applies nothing. And a node
under a disabled ancestor never probes. COLLIDE adds one more finding: a pad
the overlay newly muxes that an enabled node it does not touch already holds.
Amlogic and Rockchip pinctrl are not strict, so the loser just stops working.
The first instance was a gpio-leds status LED whose pin became PWM_D.

### Binding schema (`scripts/check-overlay-schema.py`)

`dt-validate` on each overlay's merged tree against the kernel's bindings,
minus the errors the base and providers already had:

```bash
dt-mk-schema -j <linux>/Documentation/devicetree/bindings > processed-schema.json
make check-overlay-schema SCHEMA=processed-schema.json
```

It reports and does not gate: legacy fbtft properties on tinydrm panels and
node names make up much of the output. The defects it found first were a
`pinctrl-o` typo, a `pinctrl-names` with two `default`s, a missing
`vref-supply`, and PWM clocks overridden with a legacy `clkin0` list that the
v2 binding reads by index.

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
