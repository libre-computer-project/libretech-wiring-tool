<!--
SPDX-License-Identifier: MIT
-->
# lgpio — header GPIO tool

Translates Libre Computer header pins (and RPi BCM numbers) to gpiod
chip/line, sysfs, SoC name, pad, schematic ref, and mux description.
Interactive get/set/watch for debugging — not a high-performance API
(lookup cost is non-trivial).

Package: `libretech-gpio` (depends on `gpiod`).  
Data: `libre-computer/<board>/gpio.map` (see [gpio-map.md](gpio-map.md)).

## Board detection

Uses DMI:

- `/sys/class/dmi/id/board_vendor` → `VENDOR` (e.g. `libre-computer`)
- `/sys/class/dmi/id/board_name` → `BOARD` (e.g. `aml-s905x-cc`)

Override for host-side use:

```bash
export VENDOR=libre-computer BOARD=aml-s905x-cc
./lgpio headers
```

## Commands

```text
lgpio headers
lgpio header [HEADER]
lgpio info [HEADER] PIN [type=all,gpiod,chip,line,sysfs,name,pad,ref,desc]
lgpio get [HEADER] PIN
lgpio set [options] [HEADER_]PIN={0,1} ...
lgpio pinmux [HEADER] [PIN]
lgpio watch [options] [HEADER] PIN
lgpio bcm [PIN] [type=...]
lgpio bcm check
lgpio debug [BANK][_NUM]    # board-specific, needs gpio.config + memtool
```

### headers / header

List header names, or dump all rows for one header (e.g. `7J1`).

### info

Default header is the first data row in `gpio.map` (usually the 40-pin
header). Types: `all`, `gpiod` (chip+line), `chip`, `line`, `sysfs`,
`name`, `pad`, `ref`, `desc`.

```bash
lgpio info 7J1 19
lgpio info 19 name
lgpio info 24 gpiod
```

### pinmux

Print pad + alternate functions from the `Ref` / `Desc` columns (mux
options as `A | B | C`).

```bash
lgpio pinmux 7J1 19
lgpio pinmux 7J1          # entire header
```

### get / set

```bash
lgpio get 7J1 11
lgpio set 7J1_11=1
lgpio set 11=0            # default header

# Bias / drive / active-low (libgpiod v1 and v2)
lgpio set -b pull-up 11=1
lgpio set -d open-drain -l 22=0
lgpio set --bias pull-down --drive push-pull 7J1_12=1
```

| Option | Values |
|--------|--------|
| `-l` / `--active-low` | treat line as active-low |
| `-b` / `--bias` | `pull-up`, `pull-down`, `disabled`, `as-is` |
| `-d` / `--drive` | `push-pull`, `open-drain`, `open-source` |

**Note:** On libgpiod v2, line state after `gpioset` exits is not guaranteed
unless held; `lgpio set` uses a short hold period for one-shot values.
Do not use get/set as a tight control loop.

### watch

Edge monitoring via `gpiomon` (install `gpiod`).

```bash
lgpio watch 22
lgpio watch -e falling -b pull-up 7J1 22
lgpio watch -n 10 11      # exit after 10 events
```

| Option | Meaning |
|--------|---------|
| `-e` / `--edges` | `rising`, `falling`, `both` (default) |
| `-b` / `--bias` | pull-up / pull-down / disabled |
| `-l` / `--active-low` | invert edge sense |
| `-n` / `--num-events` | exit after N events |

### bcm

RPi BCM GPIO number → physical pin on the default header, then `info`.

```bash
lgpio bcm 8 name          # BCM8 → pin 24 → SoC name
lgpio bcm 2 sysfs
lgpio bcm check           # full coverage table + WARNINGs if incomplete
```

`bcm check` flags: missing map rows, non-GPIO (power) pins, incomplete
alias coverage (`SDA0` / `SCL0` / `ID_SD` / `ID_SC`).

## Related

- [gpio-map.md](gpio-map.md) — table format and accuracy
- [ldto.md](ldto.md) — overlays that claim the same pins
- [README.md](../README.md) — index
