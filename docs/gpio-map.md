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
