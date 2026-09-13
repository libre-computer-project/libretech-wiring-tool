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
| Per-SoC maps for one PCB | `all-h3-cc-h3` and `all-h3-cc-h5` (de-symlinked 2026-08-06: same header, different SoC — H5's `PC1` can mux `SDC2_DS`, H3's cannot) |

**A shared map may only span boards whose pads are identical.** Two boards on
the same PCB but different SoCs are not that case: one differing mux makes the
file wrong for one of them either way.

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

### `Desc` mux inventory (`check-pinmux.py`)

`check-lwt.py` validates the *offsets*; `check-pinmux.py` validates the *mux
inventory* — does `Desc` list the functions the SoC can actually mux onto that
pad. It has two independent halves, and they take different routes to an
authority:

| Half | Authority route | Keyed by |
|---|---|---|
| primary mux check | `SOC_OF_BOARD` → `load_authority()` → e.g. `RK_PINMUX` | **SoC** |
| driver-vs-datasheet cross-check | `DATASHEET_JSON` → `load_datasheet()` | **board** |

> 🔴 **`NOTE: <board>: datasheet check skipped -- no datasheet extract mapped`
> does NOT mean the map is unvalidated.** It refers only to the second half. A
> Rockchip board reaching that note still had its `Desc` fully checked by the
> primary half via `RK_PINMUX`. Measured on `roc-rk3328-cc`: 29/29 rows match,
> 0 omitted functions, 0 unmatched tokens — while the note is printed.
>
> 🔴 **Do not silence that note by adding the board to `DATASHEET_JSON`.** The
> two readers expect different schemas: `load_datasheet()` reads
> `data.get("pads", {})`, which is the `gpio_ocr_extract.py` shape, while the
> Rockchip extracts are `gpio_extract.py` shape (`{"balls": [...]}`, no `pads`
> key). The lookup returns `{}`, which is not `None`, so the honest note
> **disappears while zero pads are compared** — turning a truthful "unaudited"
> into a false "clean". Wiring it up properly needs a schema adapter routing
> the RK JSON through `rk_pad_muxes()`, and even then it duplicates the primary
> check.

`--rails` runs the supply/ground half alone and needs no kernel tree: for a
power or ground row, `Chip` carries the rail class and `Ref` the board's net
name, and the two must describe the same net. Four boards published a 3.3 V
supply as ground on header pin 17 for years because nothing compared them.

```bash
python3 scripts/check-pinmux.py --self-test        # what a clean run is worth
python3 scripts/check-pinmux.py --rails --board roc-rk3328-cc
```

### Row identity (`check-lwt.py`, every board)

The binding / mux / rail checks each compare one cell against an **external**
authority. Nothing compared two **rows of the same file**, so a cell copied off
the wrong line of a datasheet or schematic stayed invisible for as long as the
file existed. `check-lwt.py` now also checks each map against itself, for every
board including the SoCs with no binding table:

| Rule | What it catches |
|------|-----------------|
| A package ball appears once | `all-h3-cc-h3/-h5` 7J1.16 `PG9` carried `D3`, which is `PG7`'s — and `PG7` is 7J1.10 of the same header |
| A legacy sysfs number appears once | the four G12B/SM1 maps put the 15-line AO gpiochip at base 15 while the 85-line EE chip sat at base 0, so four pairs of pins on each board shared one number |
| A `(Chip,Line)` appears once | two header positions claiming one SoC line |
| A `Name` appears once | one SoC pad placed on two positions |
| One sysfs base per gpiochip | a board where `sysfs - Line` holds for 39 rows and breaks on one |
| `Pad` looks like a ball | `BKH30` (`aml-*-cc-v01` `GPIOX_13`, really `BH30`), and `-` left on a routed line (`roc-rk3399-pc` J20.20) |
| Header pins run 1..N | a position silently skipped, which makes the reader miscount pads |
| No repeated `Desc` token | one signal spelled twice on a pad (`SPI2_RXD` / `SPI2TPM_RXD`) |
| No stray whitespace, no empty cell | `Desc` `"PWM_E "` on `aml-s905x-cc` 7J1.32 |

Rail, `NC` and other class rows carry no ball, line or sysfs number and repeat
freely; a pin with **two** rows (Renegade J1.33) is fine because its two rows
differ in every identifier.

`--self-test` drives these against a case table built from the real defects, so
the checks cannot silently stop firing:

```bash
python3 scripts/check-lwt.py --self-test    # also runs inside make check
```

**Limit:** self-consistency cannot see a wrong ball that collides with nothing.
Eleven of `roc-rk3399-pc`'s twelve off-by-one `Pad` cells were only found by
comparing against the RK3399 datasheet ball table; only the twelfth (the blank
one) trips a rule here. A `Pad`-vs-ballmap check would need the per-SoC ball
tables the way `check-pinmux --rk-pinmux` takes the mux table.

### Desc completeness (`make check-pinmux`)

`check-lwt.py` validates the *offsets*; `scripts/check-pinmux.py` validates the
**mux inventory** — does `Desc` list every function the SoC can put on that
pad? It reads the pinctrl driver for the board's SoC and reports each function
the driver places on the pad that `Desc` does not mention:

| SoC | Authority | Coverage |
|-----|-----------|----------|
| meson GXL / G12A | `pinctrl-meson-{gxl,g12a}.c` `<group>_pins[]` | every muxable group |
| sunxi H3 / H5 | `pinctrl-sun{8i-h3,50i-h5}.c` `SUNXI_PIN(...)` | all four muxes per pad |
| rockchip RK3328 | RK3328 TRM `GRF_GPIO<b><L>_IOMUX`, extracted to `rockchip/rk3328/gpio_pinmux.json` in the claude repo (`--rk-pinmux PATH`) | every mux value per pin. The kernel is no use here — Rockchip DT carries mux *indices*, not names — and the datasheet's Table 2-3 stops at Func 6, losing `usb3phy_debug1-8` and `power_state0/1` |

The driver is a proxy for the datasheet, not the datasheet: mainline omits
functions nobody upstreamed. Treat a report as a candidate list — confirm
against the SoC datasheet before editing a map.

```bash
make check-pinmux                                   # needs a kernel tree
python3 scripts/check-pinmux.py --linux ~/git/linux-worktree/linux-6.18.y-lc
python3 scripts/check-pinmux.py --board aml-s905x-cc --verbose
python3 scripts/check-pinmux.py --board roc-rk3328-cc \
        --rk-pinmux ~/git/claude/rockchip/rk3328/gpio_pinmux.json
```

Map and authority speak different vocabularies — the map is written in
datasheet names, the drivers in Linux ones — so names are compared after
normalisation (`TWI`≡`I2C`, sunxi `PCM`≡`I2S`, meson `tdm_b_dout1`≡`TDMB_D1`,
rockchip `cif_data5m1`≡`CIF_D5_M1_u`). Instance numbers stay significant:
`TDMB_D1` never matches `tdm_b_dout2`.

It is deliberately **not** part of `make` / `make check`: it walks a kernel
source tree, which is slow over NFS and absent on most build hosts.

### Rail consistency (`make check-rails`)

On a supply or ground row, `Chip` carries the rail class (`3.3V`, `5V`, `GND`,
and on Renegade Elite also `1.8V` / `3.0V`) and `Ref` carries the board's own
net name. The same script's `--rails` half checks that the two describe the
same net — the one thing no other checker looked at, because every mux and
offset check *skips* the non-GPIO rows:

```bash
make check-rails                       # also runs inside make / make check
python3 scripts/check-pinmux.py --rails --board roc-rk3328-cc
python3 scripts/check-pinmux.py --self-test
```

- Reads only the maps, so it needs **no kernel tree** and runs even for an SoC
  the mux check reports `UNAUDITED`.
- Exits **1** on a contradiction whether or not `--strict` is given: unlike the
  mux warnings, a row whose own two columns disagree is a defect, not a
  candidate list.
- A rail-ish *substring* is never enough. A row is in scope only when `Chip` is
  a rail class, or when `Ref` is **wholly** a rail name — a GPIO's net name may
  legitimately mention one (`TCPD_VBUS_BDIS_d`), and a name ending in a control
  suffix (`VCC5V_EN`) is a signal about a rail, not the rail.
- A supply name that states no voltage (`VCC_IO`, `VCC_SYS`) constrains only
  supply-vs-ground; `Chip=5V Ref=VCC_SYS` passes, `Chip=GND Ref=VCC_SYS` does
  not. Voltages that *are* spelled out compare as millivolts, so `VCC_1V8` and
  `VCCA3V0_CODEC` are checked as 1.8V and 3.0V rather than rounded into one of
  three classes.

This is what four boards needed and did not have: `all-h3-cc-h3`,
`all-h3-cc-h5`, `roc-rk3328-cc` and `roc-rk3328-cc-v2` published header pin 17
as `Chip=GND` while `Ref` said `VCC3V3-OUT` / `VCC_IO`, from each file's first
commit in 2022 until `0bff83d0a` — a 3.3V supply drawn as ground, in the
direction that damages hardware. `--self-test` keeps those four rows, and every
correct row they resemble, in a case table.

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
