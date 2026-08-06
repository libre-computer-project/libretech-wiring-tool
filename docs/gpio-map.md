<!--
SPDX-License-Identifier: MIT
-->
# gpio.map — header pinout tables

Per-board TSV used by **lgpio** and **ldto** for pinout cross-references.

Path: `libre-computer/<board>/gpio.map`  
(Installed under `/opt/librecomputer/libretech-wiring-tool/…`.)

## Format

Tab-separated; comment lines start with `#`. Header row:

```text
#Header  Pin  Chip  Line  sysfs  Name  Pad  Ref  Desc
```

| Column | Meaning |
|--------|---------|
| Header | Connector silk (e.g. `7J1`, `2J3`, `J1`) |
| Pin | Pin number on that header |
| Chip | Linux gpiochip index, or `3.3V` / `5V` / `GND` / `ADC` |
| Line | Line offset on that chip (matches SoC `dt-bindings` for GPIO names) |
| sysfs | Legacy global sysfs number (deprecated) |
| Name | SoC pad / signal name (`GPIOX_8`, `GPIOAO_5`, …) |
| Pad | Package ball / pin |
| Ref | Schematic / primary function label |
| Desc | Alternate mux functions (space-separated) |

Example (Le Potato SPI MOSI):

```text
7J1  19  1  87  488  GPIOX_8  B4  BTPCM_DOUT  PCM_OUT_A UART_TX_C SPI_MOSI
```

## Pins with two SoC lines

A header pin is normally one row. When the board wires **two SoC lines to the
same physical pin** — each through its own series resistor — that pin gets
**one row per line**, in wiring order:

```text
J1  33  2  16  80  GPIO2_C0  V15  GPIO2_C0_U/I2S1_LRCK_RX  I2S1_LRCK_RX/…
J1  33  2  17  81  GPIO2_C1  P18  GPIO2_C1_U/I2S1_LRCK_TX  I2S1_LRCK_TX/…
```

- **The first row is authoritative for operations.** `lgpio get` / `set` /
  `watch` / `bcm` resolve a pin to its first row, so adding a second row never
  changes what an existing command does.
- **`lgpio info PIN` (or `… all`) lists every row**, keeping both lines
  discoverable; `lgpio info PIN COLUMN` returns the first row only.
- **Never drive two rows of one pin at once.** They share a net through their
  series resistors, so opposite values contend. `test/gpio/pattern.sh` drives
  only the first row of each pin for exactly this reason.
- **`Name` must hold a single pad per row.** A combined cell such as
  `GPIO2_C0/GPIO2_C1` is unmatchable: `ldto`'s pad lookup compares the whole
  `Name` field, so a combined cell resolves *neither* pad.

Extra rows mean physically distinct SoC lines only — alternate *functions* of
one line belong in `Desc`.

## Sharing and variants

| Pattern | Example |
|---------|---------|
| Whole-board symlink | `aml-s905x-cc-v2/gpio.map` → `../aml-s905x-cc/gpio.map` |
| Shared cottonwood pinout | `aml-s905d3-cc` → `aml-a311d-cc` |
| Rev-specific maps | `aml-a311d-cc-v01` differs from main cottonwood |

Different boards (e.g. Potato vs La Frite) intentionally use different SoC
pads on the same 40-pin positions.

## Accuracy checks

`make` / `make check` runs `scripts/check-lwt.py`, which for Amlogic boards
verifies:

- `Name` exists in the SoC gpio header (`meson-gxl` / `meson-g12a`)
- `Line` matches the binding value for that name
- `Chip` matches the board family’s AO vs EE gpiochip index  
  (GXL: AO=0 EE=1; G12B/SM1: EE=0 AO=1)

Non-GPIO rows (`LOLN`, `CVBS_IOUT`, power rails) are skipped.  
H3 / Rockchip maps are format-checked only (no meson binding table).

```bash
make check
make check-strict          # exit 1 on any WARNING
python3 scripts/check-lwt.py --board aml-s905x-cc
```

### Desc completeness (`make check-pinmux`)

`check-lwt.py` validates the *offsets*; `scripts/check-pinmux.py` validates the
**mux inventory** — does `Desc` list every function the SoC can put on that
pad? It reads the pinctrl driver for the board's SoC and reports each function
the driver places on the pad that `Desc` does not mention:

| SoC | Authority | Coverage |
|-----|-----------|----------|
| meson GXL / G12A | `pinctrl-meson-{gxl,g12a}.c` `<group>_pins[]` | every muxable group |
| sunxi H3 / H5 | `pinctrl-sun{8i-h3,50i-h5}.c` `SUNXI_PIN(...)` | all four muxes per pad |
| rockchip RK3328 | none | **unaudited** — the kernel encodes mux *indices*, not names, so `Desc` here rests on the schematic and the (absent) TRM |

The driver is a proxy for the datasheet, not the datasheet: mainline omits
functions nobody upstreamed. Treat a report as a candidate list — confirm
against the SoC datasheet before editing a map.

```bash
make check-pinmux                                   # needs a kernel tree
python3 scripts/check-pinmux.py --linux ~/git/linux-worktree/linux-6.18.y-lc
python3 scripts/check-pinmux.py --board aml-s905x-cc --verbose
```

It is deliberately **not** part of `make` / `make check`: it walks a kernel
source tree, which is slow over NFS and absent on most build hosts.

## Consumers

| Tool | Use |
|------|-----|
| `lgpio info` / `pinmux` / `get` / `set` / `watch` / `bcm` | Lookup and control |
| `ldto info` / `conflicts` / `enable --dry-run` | Overlay pin cross-ref |
| Overlay DTS headers | `Pins:` rows must match this map |

## Related

- [lgpio.md](lgpio.md)  
- [ldto.md](ldto.md)  
- [overlays.md](overlays.md)  
