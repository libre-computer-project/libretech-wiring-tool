#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Da Xue <da@libre.computer>
"""LWT integrity + gpio.map accuracy checks (warn by default).

Validates:
  - gpio.map format and Name/Line/Chip vs SoC dt-bindings (lgpio pinout data)
  - gpio.map row IDENTITY: no two header positions may claim the same BGA
    ball, the same legacy sysfs number or the same (Chip,Line); sysfs must be
    one base per chip; Pad must look like a ball; no stray whitespace; header
    pin numbers run 1..N with no hole  (--self-test covers these)
  - overlay .dts headers (Summary; Pins rows match gpio.map)
  - dt.map values name real non-symlink overlay basenames
  - dt.deps providers/consumers exist

Exit 0 always unless --strict (then non-zero if any WARNING).
Prints WARNING: lines for make to surface.

Why the identity checks exist
-----------------------------
Every other checker validates a cell against an EXTERNAL authority -- Line
against dt-bindings, Desc against the pinctrl driver, Chip against Ref for the
rails.  Nothing compared two ROWS of the same file, so a cell copied off the
wrong line of a datasheet or schematic was invisible for as long as the file
existed.  Found by the 2026-08-08 data audit, all present from each file's
first commit:

  all-h3-cc-h3/-h5  7J1.16 PG9 carried ball D3, which is PG7's -- and PG7 is
                    7J1.10 of the same header, so one ball was published on two
                    pins (H3 datasheet V1.2 / H5 V1.0: PG9 is E3).  7J1.15 PA3
                    carried D13, which is PA9's; PA9 is not on the header, so
                    that one collided with nothing and only a datasheet
                    comparison could see it.
  roc-rk3399-pc     twelve Pad cells each held the ball of the NEXT pad in the
                    bank -- the schematic prints the ball one text row below
                    the pad name -- and the last of each run (J20.20 GPIO2_B4)
                    fell off the end and was left as '-'.
  aml-a311d-cc-v01  GPIOX_13 ball 'BKH30': no BGA ball has that shape.
  aml-s905d3-cc-v01
  aml-a311d-cc      the AO gpiochip was given base 15 while the EE chip at
  aml-s905d3-cc     base 0 has 85 lines, so four pairs of header pins on each
  aml-a311d-cc-v01  board shared one legacy number.  Measured 2026-08-08 on
  aml-s905d3-cc-v01 live boards: periphs base 512 ngpio 85, aobus base 597 --
                    AO starts 85 above EE, not 15.

A ball, a sysfs number and a (Chip,Line) are each an identifier: two header
positions holding the same one is a contradiction no authority is needed to
see.  These run for EVERY board, including the SoCs with no binding table.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LC = ROOT / "libre-computer"
INC = ROOT / "include" / "dt-bindings" / "gpio"

POWER_CHIPS = {"3.3V", "5V", "GND", "ADC"}
SKIP_NAMES = {
    "3.3V",
    "5V",
    "GND",
    "ADC",
    "LOLN",
    "LORN",
    "CVBS_IOUT",
}
# Header names are "7J1" on the Amlogic/Allwinner boards but plain "J1" /
# "J12" on the Rockchip ones; requiring a leading digit skipped every Pins row
# in every Rockchip overlay without a word. Group 4 is the row's Pad column.
PIN_ROW_RE = re.compile(
    r"^\s*\*?\s*(\d*[Jj]\d+)\.(\d+)\s+(\S+)(?:\s+(\S+))?"
)
PAD_TOKEN = re.compile(
    r"\b(GPIO[A-Z][A-Z0-9_]*|GPIODV_[0-9]+|TEST_N|RK_P[A-Z0-9_]+|"
    r"GPIO[0-9]_[A-Z][0-9]+|P[A-G][0-9]+)\b"
)
SKIP_PAD = re.compile(r"^(GPIO_ACTIVE_|GPIO_OPEN_|GPIO_PULL_|GPIO_PERSISTENT)")

# A package ball: one or two column letters then a row number.  Rockchip and
# Amlogic both use this shape; 'BKH30' (three letters) is how a typo shows up.
BALL_RE = re.compile(r"^[A-Z]{1,2}[0-9]{1,2}$")

# Chip values that are a rail/function class rather than a gpiochip index.
# Those rows carry no ball, no line and no sysfs number, so the identity
# checks skip them -- Chip-vs-Ref on them is check-pinmux.py --rails.
CLASS_CHIPS = {
    "3.3V", "3.0V", "1.8V", "5V", "12V", "GND", "ADC", "DAC", "PHY", "USB",
    "PCIE", "POE", "NC", "FLASH", "CLK", "I2C", "AUDIO", "CVBS",
}


def parse_defines(path: Path) -> dict[str, int]:
    d: dict[str, int] = {}
    if not path.is_file():
        return d
    for line in path.read_text(errors="replace").splitlines():
        m = re.match(r"#define\s+(\w+)\s+(\d+)", line)
        if m:
            d[m.group(1)] = int(m.group(2))
    return d


GXL = parse_defines(INC / "meson-gxl-gpio.h")
G12 = parse_defines(INC / "meson-g12a-gpio.h")

# board -> (family, defines, ao_linux_chip_index)
# GXL: AO chip0, EE chip1. G12B/SM1: periphs first → EE chip0, AO chip1.
BOARD_SOC: dict[str, tuple[str, dict[str, int], int]] = {
    "aml-s905x-cc": ("gxl", GXL, 0),
    "aml-s905x-cc-v2": ("gxl", GXL, 0),
    "aml-s905x-cc-v3": ("gxl", GXL, 0),
    "aml-s805x-ac": ("gxl", GXL, 0),
    "aml-s805x-ac-v2": ("gxl", GXL, 0),
    "aml-a311d-cc": ("g12", G12, 1),
    "aml-a311d-cc-v01": ("g12", G12, 1),
    "aml-s905d3-cc": ("g12", G12, 1),
    "aml-s905d3-cc-v01": ("g12", G12, 1),
}


def is_ao_name(name: str) -> bool:
    n = name.rstrip("*")
    return (
        n.startswith("GPIOAO_")
        or n.startswith("GPIOE_")
        or n in ("TEST_N", "GPIO_TEST_N")
    )


def load_gpio_map(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.is_file():
        return rows
    for i, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 9:
            rows.append(
                {
                    "_bad": True,
                    "_line": i,
                    "_raw": line,
                    "cols": len(parts),
                }
            )
            continue
        rows.append(
            {
                "_bad": False,
                "_line": i,
                "header": parts[0],
                "pin": parts[1],
                "chip": parts[2],
                "line": parts[3],
                "sysfs": parts[4],
                "name": parts[5],
                "pad": parts[6],
                "ref": parts[7],
                "desc": parts[8],
            }
        )
    return rows


def board_dirs(board_filter: str | None) -> list[Path]:
    if board_filter:
        p = LC / board_filter
        return [p] if p.is_dir() else []
    return sorted(p for p in LC.iterdir() if p.is_dir())


def real_dt_dir(board: Path) -> Path | None:
    dt = board / "dt"
    if not dt.exists():
        return None
    if dt.is_symlink():
        return dt.resolve()
    return dt


def map_identity_warnings(bname: str, rows: list[dict]) -> list[str]:
    """Every row-vs-row contradiction in one board's gpio.map.

    Pure function over parsed rows so --self-test can drive it directly.
    """
    out: list[str] = []
    where = lambda r: f"{r['header']}.{r['pin']}"

    # --- per-field hygiene -------------------------------------------------
    for r in rows:
        for col in ("header", "pin", "chip", "line", "sysfs", "name", "pad",
                    "ref", "desc"):
            v = r[col]
            if v != v.strip():
                out.append(
                    f"{bname}: {where(r)} {r['name']}: {col} is {v!r} "
                    f"-- leading/trailing whitespace"
                )
            elif v == "":
                out.append(f"{bname}: {where(r)}: {col} is empty")

    gpio = [r for r in rows if r["chip"] not in CLASS_CHIPS]
    for r in gpio:
        if not r["chip"].isdigit():
            out.append(
                f"{bname}: {where(r)} {r['name']}: Chip={r['chip']!r} is "
                f"neither a gpiochip index nor a known rail/function class"
            )
            continue
        if not r["line"].isdigit() or not r["sysfs"].isdigit():
            out.append(
                f"{bname}: {where(r)} {r['name']}: Chip is numeric but "
                f"Line={r['line']!r} sysfs={r['sysfs']!r} are not"
            )
            continue
        if not BALL_RE.match(r["pad"]):
            out.append(
                f"{bname}: {where(r)} {r['name']}: Pad={r['pad']!r} is not a "
                f"package ball (expected 1-2 letters then 1-2 digits)"
            )

    ok = [r for r in gpio
          if r["chip"].isdigit() and r["line"].isdigit() and r["sysfs"].isdigit()]

    # --- one base per gpiochip --------------------------------------------
    per_chip: dict[str, dict[int, list[dict]]] = {}
    for r in ok:
        per_chip.setdefault(r["chip"], {}).setdefault(
            int(r["sysfs"]) - int(r["line"]), []
        ).append(r)
    for chip, bases in sorted(per_chip.items()):
        if len(bases) < 2:
            continue
        major = max(bases, key=lambda b: len(bases[b]))
        for base, brs in sorted(bases.items()):
            if base == major:
                continue
            for r in brs:
                out.append(
                    f"{bname}: {where(r)} {r['name']}: sysfs {r['sysfs']} "
                    f"implies gpiochip{chip} base {base}, but "
                    f"{len(bases[major])} other row(s) on gpiochip{chip} use "
                    f"base {major} (expected {major + int(r['line'])})"
                )

    # --- identifiers that must be unique across the whole board ------------
    def collide(key, label, fmt):
        seen: dict = {}
        for r in ok:
            seen.setdefault(key(r), []).append(r)
        for k, rs in sorted(seen.items(), key=lambda kv: str(kv[0])):
            if len(rs) < 2:
                continue
            out.append(
                f"{bname}: {label} {fmt(k)} on {len(rs)} header positions: "
                + "; ".join(f"{where(r)} {r['name']}" for r in rs)
            )

    collide(lambda r: r["pad"], "package ball", str)
    collide(lambda r: int(r["sysfs"]), "legacy sysfs number", str)
    collide(lambda r: (int(r["chip"]), int(r["line"])),
            "gpiochip line", lambda k: f"gpiochip{k[0]} line {k[1]}")

    # A pad NAME may repeat only when it is the same SoC line reached twice,
    # which the (Chip,Line) check above already rejects -- so any repeat here
    # is a second row claiming a pad that is already placed elsewhere.
    byname: dict[str, list[dict]] = {}
    for r in ok:
        byname.setdefault(r["name"].rstrip("*"), []).append(r)
    for n, rs in sorted(byname.items()):
        if len(rs) > 1:
            out.append(
                f"{bname}: SoC pad {n} on {len(rs)} header positions: "
                + "; ".join(f"{where(r)} (ball {r['pad']})" for r in rs)
            )

    # --- every physical position 1..N present ------------------------------
    hdrs: dict[str, set] = {}
    for r in rows:
        if r["pin"].isdigit():
            hdrs.setdefault(r["header"], set()).add(int(r["pin"]))
    for h, pins in sorted(hdrs.items()):
        missing = sorted(set(range(1, max(pins) + 1)) - pins)
        if missing:
            out.append(
                f"{bname}: header {h} skips pin position(s) "
                f"{', '.join(map(str, missing))} (highest pin {max(pins)}) -- "
                f"a pinout that omits a position makes the reader miscount pads"
            )

    # --- a Desc token listed twice on one pad ------------------------------
    for r in rows:
        if r["desc"] in ("-", ""):
            continue
        toks = [t for t in re.split(r"[/ ]+", r["desc"]) if t]
        for t in sorted({t for t in toks if toks.count(t) > 1}):
            out.append(
                f"{bname}: {where(r)} {r['name']}: Desc lists {t!r} "
                f"{toks.count(t)} times: {r['desc']!r}"
            )
    return out


SELF_TEST_CASES: list[tuple[str, list[str], str | None]] = [
    # (label, gpio.map rows as raw TSV, substring that MUST appear in a
    #  warning -- None means the case must produce no warning at all)
    (
        "clean 6-pin board",
        [
            "7J1\t1\t3.3V\t3.3V\t3.3V\t3.3V\t3.3V\tVCC3.3V\t3.3V",
            "7J1\t2\t5V\t5V\t5V\t5V\t5V\tVCC5V\t5V",
            "7J1\t3\t0\t5\t506\tGPIOAO_5\tD13\tI2C_SDA_AO\tI2C_SDA_AO",
            "7J1\t4\tGND\tGND\tGND\tGND\tGND\tGND\tGND",
            "7J1\t5\t1\t87\t488\tGPIOX_8\tB4\tSPI_MOSI\tSPI_MOSI PCM_OUT_A",
            "7J1\t6\tNC\tNC\tNC\tNC\t-\tNC\t-",
        ],
        None,
    ),
    (
        # all-h3-cc-h3 7J1.10/7J1.16 as published 2022..2026-08-08
        "one ball on two pins (PG7/PG9 both D3)",
        [
            "7J1\t10\t1\t199\t199\tPG7\tD3\tAP-UART1-RX\tUART1_RX/PG_EINT7",
            "7J1\t16\t1\t201\t201\tPG9\tD3\tAP-UART1-CTS\tUART1_CTS/PG_EINT9",
        ],
        "package ball D3 on 2 header positions",
    ),
    (
        # aml-a311d-cc as published 2023-10-04..2026-08-08: AO base 15 while
        # the 85-line EE chip sits at base 0
        "AO and EE gpiochips overlapping in sysfs",
        [
            "7J1\t7\t1\t6\t21\tGPIOAO_6\tAV44\tJTAG_CLK\tJTAG_A_CLK",
            "7J1\t21\t0\t21\t21\tGPIOH_5\tW38\tSPI_B_MISO\tSPDIF_IN",
        ],
        "legacy sysfs number 21 on 2 header positions",
    ),
    (
        "one gpiochip with two bases",
        [
            "7J1\t3\t1\t2\t403\tGPIOAO_2\tB7\tPWR\tUART_CTS_AO_A",
            "7J1\t5\t1\t0\t501\tGPIOAO_0\tC9\tTX\tUART_TX_AO_A",
            "7J1\t7\t1\t1\t502\tGPIOAO_1\tC8\tRX\tUART_RX_AO_A",
        ],
        "implies gpiochip1 base 401",
    ),
    (
        # aml-s905d3-cc-v01 7J1.10 as published
        "malformed ball BKH30",
        ["7J1\t10\t0\t78\t78\tGPIOX_13\tBKH30\tUART_A_RX\tUART_EE_A_RX"],
        "Pad='BKH30' is not a package ball",
    ),
    (
        # roc-rk3399-pc J20.20 as published: the ball fell off the end of a
        # run of off-by-one reads and was left blank
        "blank ball on a routed SoC line",
        ["J20\t20\t2\t12\t76\tGPIO2_B4\t-\tSPI2_CSN0\tSPI2_CSn0_u"],
        "Pad='-' is not a package ball",
    ),
    (
        "two pins claiming one SoC line",
        [
            "J1\t7\t2\t20\t84\tGPIO2_C4\tV18\tI2S1_SDO1\tI2S1_SDIO1",
            "J1\t9\t2\t20\t85\tGPIO2_C4x\tV19\tI2S1_SDO1b\tI2S1_SDIO1",
        ],
        "gpiochip line gpiochip2 line 20 on 2 header positions",
    ),
    (
        # roc-rk3399-pc J12 published 30 physical positions as 12 rows
        "header with a hole in its numbering",
        [
            "J12\t1\t2\t1\t65\tGPIO2_A1\tH25\tI2C2_SCL\tVOP_D1",
            "J12\t4\t2\t0\t64\tGPIO2_A0\tG31\tI2C2_SDA\tVOP_D0",
        ],
        "skips pin position(s) 2, 3",
    ),
    (
        # roc-rk3399-pc J20.17 shipped SPI2_RXD and SPI2TPM_RXD together
        "one signal spelled twice in Desc",
        ["J20\t17\t2\t9\t73\tGPIO2_B1\tF30\tSPI2_RXD\tSPI2_RXD/CIF_HREF/SPI2_RXD"],
        "Desc lists 'SPI2_RXD' 2 times",
    ),
    (
        "trailing whitespace in Desc",
        ["7J1\t32\t1\t95\t496\tGPIOX_16\tA3\tWIFI_32K\tPWM_E "],
        "desc is 'PWM_E ' -- leading/trailing whitespace",
    ),
    (
        # Renegade J1.33: two SoC lines really are wired to one pin, each
        # through its own series resistor.  Distinct ball, line and sysfs on
        # both rows, so nothing here is a duplicate.  (Pin 1 in the fixture
        # only so the single-row header has no numbering hole.)
        "deliberate two-line pin is not a duplicate",
        [
            "J1\t1\t2\t16\t80\tGPIO2_C0\tV15\tI2S1_LRCK_RX\tI2S1_LRCK_RX",
            "J1\t1\t2\t17\t81\tGPIO2_C1\tP18\tI2S1_LRCK_TX\tI2S1_LRCK_TX",
        ],
        None,
    ),
    (
        # roc-rk3399-pc J1/J21: rail-only and NC positions carry no ball, no
        # line and no sysfs, and repeat freely
        "rail and NC rows repeat without warning",
        [
            "J21\t3\t12V\t12V\t12V\tSYS_12V\t-\tSYS_12V\tSYS_12V",
            "J21\t4\tGND\tGND\tGND\tGND\t-\tGND\tGND",
            "J21\t5\t12V\t12V\t12V\tSYS_12V\t-\tSYS_12V\tSYS_12V",
            "J21\t6\tGND\tGND\tGND\tGND\t-\tGND\tGND",
            "J21\t1\tNC\tNC\tNC\tNC\t-\tNC\t-",
            "J21\t2\tNC\tNC\tNC\tNC\t-\tNC\t-",
        ],
        None,
    ),
]


# --------------------------------------------------------------------------
# SoC formula: pad NAME -> (Chip, Line, sysfs), for SoCs whose pad names are
# their own coordinates.  meson boards are checked against the dt-bindings
# headers in check_gpio_map instead; until this existed, Rockchip and
# Allwinner rows had no Chip/Line check at all.
#
#   Rockchip  GPIO<b>_<X><n>  one gpiochip per bank, registered in bank
#                             order, so Chip = b and Line = (X-'A')*8 + n;
#                             the legacy number is 32 per bank, so
#                             sysfs = 32*b + Line.
#   Allwinner P<X><n>         two gpiochips: the main PIO (banks A..K) and
#                             R_PIO (L onwards); Line = (X-first)*32 + n
#                             inside its own chip.  Which INDEX each chip
#                             gets is probe order, invisible from this file,
#                             so only "one controller, one chip" is checked.
# --------------------------------------------------------------------------
RK_PAD = re.compile(r"^GPIO([0-9])_([A-D])([0-7])$")
SUNXI_PAD = re.compile(r"^P([A-Z])([0-9]{1,2})$")


def soc_family(bname: str) -> str | None:
    if bname.startswith("roc-rk"):
        return "rockchip"
    if bname.startswith("all-h"):
        return "sunxi"
    return None


def soc_formula_warnings(bname: str, rows: list[dict],
                         family: str | None) -> list[str]:
    """Every row whose Chip/Line/sysfs disagrees with its own pad name."""
    out: list[str] = []
    if family is None:
        return out
    where = lambda r: f"{r['header']}.{r['pin']}"
    gpio = [r for r in rows
            if not r.get("_bad") and r["chip"].isdigit()
            and r["line"].isdigit() and r["sysfs"].isdigit()]
    if family == "rockchip":
        for r in gpio:
            name = r["name"].rstrip("*")
            m = RK_PAD.match(name)
            if not m:
                out.append(f"{bname}: {where(r)}: Name={r['name']!r} is not a "
                           f"Rockchip pad name (GPIO<bank>_<A-D><0-7>)")
                continue
            bank = int(m.group(1))
            line = (ord(m.group(2)) - ord("A")) * 8 + int(m.group(3))
            if int(r["chip"]) != bank:
                out.append(f"{bname}: {where(r)} {name}: Chip={r['chip']} but "
                           f"{name} is bank {bank}, i.e. gpiochip{bank}")
            if int(r["line"]) != line:
                out.append(f"{bname}: {where(r)} {name}: Line={r['line']} but "
                           f"{name} is line {line} of its bank")
            if int(r["sysfs"]) != 32 * bank + line:
                out.append(f"{bname}: {where(r)} {name}: sysfs={r['sysfs']} "
                           f"but {name} is legacy number {32 * bank + line} "
                           f"(32 per bank)")
    elif family == "sunxi":
        chips: dict[str, set] = {"main PIO": set(), "R_PIO": set()}
        for r in gpio:
            name = r["name"].rstrip("*")
            m = SUNXI_PAD.match(name)
            if not m:
                out.append(f"{bname}: {where(r)}: Name={r['name']!r} is not an "
                           f"Allwinner pad name (P<bank><pin>)")
                continue
            bank, pin = m.group(1), int(m.group(2))
            ctl, first = ("R_PIO", "L") if bank >= "L" else ("main PIO", "A")
            line = (ord(bank) - ord(first)) * 32 + pin
            if int(r["line"]) != line:
                out.append(f"{bname}: {where(r)} {name}: Line={r['line']} but "
                           f"{name} is line {line} of the {ctl}")
            chips[ctl].add(r["chip"])
        for ctl, cs in chips.items():
            if len(cs) > 1:
                out.append(f"{bname}: {ctl} rows are split across gpiochips "
                           f"{', '.join(sorted(cs))} -- one controller is "
                           f"one chip")
        shared = chips["main PIO"] & chips["R_PIO"]
        if shared:
            out.append(f"{bname}: main PIO and R_PIO rows share gpiochip "
                       f"{', '.join(sorted(shared))} -- they are two "
                       f"controllers")
    return out


# --------------------------------------------------------------------------
# Raspberry Pi 40-pin header.  "BCM" is Broadcom's GPIO numbering, i.e. the
# Raspberry Pi pinout.  Nothing else in this file can see a HEADER POSITION
# error -- a map that swaps two pins passes every identity and binding check
# -- but a header declared Pi-compatible has a fixed skeleton: the power and
# ground rails sit on the same twelve pins of every such header, and every
# other pin is a GPIO position.  A map declares its Pi header with
#     #rpi-header: 7J1          (or  #rpi-header: none)
# as a comment line, so symlinked variant boards inherit it with the map.
# --------------------------------------------------------------------------
RPI_RAILS = {1: "3.3V", 17: "3.3V", 2: "5V", 4: "5V",
             6: "GND", 9: "GND", 14: "GND", 20: "GND",
             25: "GND", 30: "GND", 34: "GND", 39: "GND"}
# BCM GPIO number -> physical pin.  BCM0/BCM1 are the HAT ID EEPROM pair.
RPI_BCM = {0: 27, 1: 28, 2: 3, 3: 5, 4: 7, 5: 29, 6: 31, 7: 26, 8: 24,
           9: 21, 10: 19, 11: 23, 12: 32, 13: 33, 14: 8, 15: 10, 16: 36,
           17: 11, 18: 12, 19: 35, 20: 38, 21: 40, 22: 15, 23: 16, 24: 18,
           25: 22, 26: 37, 27: 13}
RAIL_CLASSES = {"3.3V", "5V", "GND"}
RPI_DIRECTIVE = re.compile(r"^#\s*rpi-header:\s*(\S+)\s*$")


def read_rpi_header(path: Path) -> str | None:
    for line in path.read_text(errors="replace").splitlines():
        m = RPI_DIRECTIVE.match(line)
        if m:
            return m.group(1)
    return None


def rpi_header_warnings(bname: str, rows: list[dict],
                        decl: str | None) -> list[str]:
    """Rails and GPIO positions of the declared Pi header vs the Pi's own."""
    out: list[str] = []
    pins: dict[str, dict[int, list[dict]]] = {}
    for r in rows:
        if r.get("_bad") or not r["pin"].isdigit():
            continue
        pins.setdefault(r["header"], {}).setdefault(int(r["pin"]), []).append(r)
    full = set(range(1, 41))
    if decl is None:
        for h in sorted(pins):
            if set(pins[h]) == full:
                out.append(
                    f"{bname}: header {h} has 40 positions but gpio.map has no "
                    f"'#rpi-header:' line -- declare it ('#rpi-header: {h}' or "
                    f"'#rpi-header: none') so lgpio bcm and this check know "
                    f"whether the Raspberry Pi pinout applies")
        return out
    if decl == "none":
        return out
    if decl not in pins:
        out.append(f"{bname}: '#rpi-header: {decl}' names a header that is "
                   f"not in gpio.map")
        return out
    if set(pins[decl]) != full:
        out.append(f"{bname}: '#rpi-header: {decl}' but {decl} has positions "
                   f"{min(pins[decl])}..{max(pins[decl])} "
                   f"({len(pins[decl])} distinct) -- a Raspberry Pi header is "
                   f"exactly 1..40")
        return out
    bcm_of = {p: b for b, p in RPI_BCM.items()}
    for p in sorted(full):
        classes = {r["chip"] for r in pins[decl][p]}
        want = RPI_RAILS.get(p)
        if want:
            if classes != {want}:
                out.append(f"{bname}: {decl}.{p} is "
                           f"{'/'.join(sorted(classes))} but every Raspberry "
                           f"Pi-compatible header has {want} on pin {p}")
        else:
            rails = classes & RAIL_CLASSES
            if rails:
                out.append(f"{bname}: {decl}.{p} is a "
                           f"{'/'.join(sorted(rails))} rail, but pin {p} is "
                           f"BCM{bcm_of[p]} -- a GPIO position on a Raspberry "
                           f"Pi header")
    return out


def rpi_table_warnings() -> list[str]:
    """RPI_RAILS and RPI_BCM must partition positions 1..40 exactly."""
    out: list[str] = []
    gp = list(RPI_BCM.values())
    if len(gp) != len(set(gp)):
        out.append("RPI_BCM maps two BCM numbers to one pin")
    both = set(gp) & set(RPI_RAILS)
    if both:
        out.append(f"RPI_BCM and RPI_RAILS overlap on pins {sorted(both)}")
    gap = set(range(1, 41)) - set(gp) - set(RPI_RAILS)
    if gap:
        out.append(f"RPI_BCM + RPI_RAILS leave pins {sorted(gap)} unassigned")
    return out


LGPIO_BCM_LINE = re.compile(r"^\s*BCM_GPIO2PIN\[(\w+)\]=(\d+)\s*$")
LGPIO_BCM_ALIASES = {"ID_SD": 0, "ID_SC": 1, "SDA0": 0, "SCL0": 1}


def lgpio_bcm_warnings(lgpio_text: str) -> list[str]:
    """lgpio's own BCM -> pin table, checked against the Pi pinout above."""
    out: list[str] = []
    numeric: set[int] = set()
    for line in lgpio_text.splitlines():
        m = LGPIO_BCM_LINE.match(line)
        if not m:
            continue
        key, pin = m.group(1), int(m.group(2))
        bcm = int(key) if key.isdigit() else LGPIO_BCM_ALIASES.get(key)
        if bcm is None:
            out.append(f"lgpio: BCM_GPIO2PIN[{key}] is not a BCM number or a "
                       f"known alias")
            continue
        if key.isdigit():
            numeric.add(bcm)
        if RPI_BCM.get(bcm) != pin:
            out.append(f"lgpio: BCM_GPIO2PIN[{key}]={pin} but BCM{bcm} is "
                       f"Raspberry Pi pin {RPI_BCM.get(bcm)}")
    if not numeric:
        out.append("lgpio: no BCM_GPIO2PIN entries found -- the table moved "
                   "or was renamed, so nothing checked it")
        return out
    missing = sorted(set(range(2, 28)) - numeric)
    if missing:
        out.append(f"lgpio: BCM_GPIO2PIN has no entry for BCM "
                   f"{', '.join(map(str, missing))}")
    return out


FORMULA_CASES: list[tuple[str, str, list[str], str | None]] = [
    # (label, board name -> SoC family, rows, substring that MUST appear;
    #  None = no warning)
    ("rockchip row as published (Renegade J1.3)", "roc-rk3328-cc",
     ["J1\t3\t2\t25\t89\tGPIO2_D1\tR17\tI2C0_SDA\tI2C0_SDA"], None),
    ("rockchip line off by one", "roc-rk3328-cc",
     ["J1\t3\t2\t24\t88\tGPIO2_D1\tR17\tI2C0_SDA\tI2C0_SDA"],
     "Line=24 but GPIO2_D1 is line 25"),
    ("rockchip row on the wrong bank's chip", "roc-rk3399-pc",
     ["J20\t25\t1\t1\t33\tGPIO0_A1\tR29\tGPIO0_A1\t-"],
     "Chip=1 but GPIO0_A1 is bank 0"),
    ("rockchip legacy number off", "roc-rk3328-cc",
     ["J1\t3\t2\t25\t90\tGPIO2_D1\tR17\tI2C0_SDA\tI2C0_SDA"],
     "sysfs=90 but GPIO2_D1 is legacy number 89"),
    ("rockchip name that is not a pad", "roc-rk3328-cc",
     ["J1\t3\t2\t25\t89\tGPIO2_E1\tR17\tI2C0_SDA\tI2C0_SDA"],
     "is not a Rockchip pad name"),
    ("allwinner rows as published (all-h3-cc 7J1.36/38)", "all-h3-cc-h3",
     ["7J1\t36\t1\t15\t15\tPA15\tF14\tUART3-RTS\tSPI1_MOSI",
      "7J1\t38\t1\t205\t205\tPG13\tB1\tBB-PCM-DIN\tPCM1_DIN"], None),
    ("allwinner line off by one", "all-h3-cc-h3",
     ["7J1\t38\t1\t204\t204\tPG13\tB1\tBB-PCM-DIN\tPCM1_DIN"],
     "Line=204 but PG13 is line 205"),
    ("allwinner main PIO split over two chips", "all-h3-cc-h3",
     ["7J1\t36\t0\t15\t15\tPA15\tF14\tUART3-RTS\tSPI1_MOSI",
      "7J1\t38\t1\t205\t205\tPG13\tB1\tBB-PCM-DIN\tPCM1_DIN"],
     "main PIO rows are split across gpiochips"),
    ("meson board is left to the binding check", "aml-s905x-cc",
     ["7J1\t3\t0\t5\t506\tGPIOAO_5\tD13\tI2C_SDA_AO\tI2C_SDA_AO"], None),
]


def _rpi_rows(hdr: str = "7J1", swap: dict | None = None) -> list[str]:
    """A clean Pi header; swap={pin: 'GND'|'3.3V'|'5V'|'gpio'} overrides."""
    bcm_of = {p: b for b, p in RPI_BCM.items()}
    rows = []
    for p in range(1, 41):
        c = (swap or {}).get(p) or RPI_RAILS.get(p)
        if c in RAIL_CLASSES:
            rows.append(f"{hdr}\t{p}\t{c}\t{c}\t{c}\t{c}\t-\t{c}\t{c}")
        else:
            rows.append(f"{hdr}\t{p}\t1\t{p}\t{p}\tGPIOX_{p}\tA{p}\t"
                        f"BCM{bcm_of.get(p, 'x')}\t-")
    return rows


RPI_CASES: list[tuple[str, str | None, list[str], str | None]] = [
    # (label, '#rpi-header:' value or None when absent, rows, expected)
    ("clean Raspberry Pi header", "7J1", _rpi_rows(), None),
    # four boards published this 2022..2026 (check-pinmux --rails history)
    ("3.3V published as ground on pin 17", "7J1", _rpi_rows(swap={17: "GND"}),
     "7J1.17 is GND but every Raspberry Pi-compatible header has 3.3V on "
     "pin 17"),
    ("signal on pin 39", "7J1", _rpi_rows(swap={39: "gpio"}),
     "has GND on pin 39"),
    ("ground on a GPIO position", "7J1", _rpi_rows(swap={7: "GND"}),
     "pin 7 is BCM4 -- a GPIO position"),
    ("40-pin header with no declaration", None, _rpi_rows(),
     "has no '#rpi-header:' line"),
    ("declared not a Pi header", "none", _rpi_rows(), None),
    ("declaration names a missing header", "J9", _rpi_rows(),
     "names a header that is not in gpio.map"),
    # Renegade J1.33: two SoC lines on one position is still one position
    ("two-line pin keeps the skeleton", "J1",
     _rpi_rows("J1") + ["J1\t33\t1\t99\t99\tGPIOX_99\tB9\tBCM13\t-"], None),
]


def _lgpio_table(override: dict | None = None) -> str:
    keys = {str(b): p for b, p in RPI_BCM.items() if b >= 2}
    keys.update({"SDA0": 27, "SCL0": 28, "ID_SD": 27, "ID_SC": 28})
    keys.update(override or {})
    return "\n".join(f"\tBCM_GPIO2PIN[{k}]={v}" for k, v in keys.items())


LGPIO_CASES: list[tuple[str, str, str | None]] = [
    ("lgpio table matches the Pi", _lgpio_table(), None),
    ("lgpio table with BCM19 on the wrong pin", _lgpio_table({"19": 37}),
     "BCM_GPIO2PIN[19]=37 but BCM19 is Raspberry Pi pin 35"),
    ("lgpio table missing an entry",
     "\n".join(l for l in _lgpio_table().splitlines() if "[26]" not in l),
     "has no entry for BCM 26"),
    ("lgpio table renamed away", "", "no BCM_GPIO2PIN entries found"),
]


def _parse_rows(raw: list[str]) -> list[dict]:
    cols = ("header", "pin", "chip", "line", "sysfs", "name", "pad", "ref",
            "desc")
    rows = []
    for i, ln in enumerate(raw, 1):
        r = {"_bad": False, "_line": i}
        r.update(dict(zip(cols, ln.split("\t"))))
        rows.append(r)
    return rows


def pins_row_warnings(where: str, header: str,
                      by_pin: dict[tuple[str, str], list[str]],
                      pad_of: dict[str, str]) -> list[str]:
    """An overlay header's Pins rows against gpio.map: the position must
    exist, carry the Name, and -- when the row gives one -- the Pad."""
    out = []
    for line in header.splitlines():
        m = PIN_ROW_RE.match(line.replace("—", "-"))
        if not m:
            continue
        h, pin, name, pad = m.group(1), m.group(2), m.group(3), m.group(4)
        if name in ("Name", "Pad", "cross-ref", "Ref"):
            continue
        key = (h, pin)
        if key not in by_pin:
            out.append(f"{where}: Pins {h}.{pin} {name} not in gpio.map")
            continue
        map_names = by_pin[key]
        bare = name.rstrip("*")
        if bare not in [n.rstrip("*") for n in map_names]:
            out.append(f"{where}: Pins {h}.{pin} says {name} but gpio.map has "
                       f"{' / '.join(map_names)}")
        elif pad and BALL_RE.match(pad) and pad != pad_of.get(bare, pad):
            out.append(f"{where}: Pins {h}.{pin} {name} says Pad {pad} but "
                       f"gpio.map has {pad_of[bare]}")
    return out


# dt.map slots: header pins in Raspberry Pi numbering. One code copy of the
# table in docs/ldto.md "Aliases (dt.map)"; check-overlay-pins.py imports it to
# check what each alias's overlay chain actually muxes.
H40P_SLOTS: dict[str, frozenset[int]] = {
    "I2C_0": frozenset({3, 5}),
    "I2C_1": frozenset({27, 28}),
    "SPI_0_1CS": frozenset({19, 21, 23, 24}),
    "SPI_0_2CS": frozenset({19, 21, 23, 24, 26}),
    "SPI_1_1CS": frozenset({38, 35, 40, 12}),
    "UART_0": frozenset({8, 10}),
}
_UART_PINS = re.compile(r"^UART_P(\d+)_P(\d+)$")
_PWM_PIN = re.compile(r"^PWM_P(\d+)$")


def h40p_slot(key: str) -> tuple[str, frozenset[int], bool] | None:
    """(slot, pins, has_device_suffix) for a dt.map key, or None when the key
    is outside the grammar H40P_<SLOT>[_<DEVICE>]."""
    if not key.startswith("H40P_"):
        return None
    rest = key[len("H40P_"):]
    for slot in sorted(H40P_SLOTS, key=len, reverse=True):
        if rest == slot or rest.startswith(slot + "_"):
            return slot, H40P_SLOTS[slot], rest != slot
    head = "_".join(rest.split("_")[:3])
    m = _UART_PINS.match(head)
    if m:
        return head, frozenset({int(m.group(1)), int(m.group(2))}), rest != head
    head = "_".join(rest.split("_")[:2])
    m = _PWM_PIN.match(head)
    if m:
        return head, frozenset({int(m.group(1))}), rest != head
    return None


SLOT_CASES = [
    # (key, expected slot or None)
    ("H40P_SPI_0_2CS_LCD_35_MHS3528", "SPI_0_2CS"),
    ("H40P_I2C_0", "I2C_0"),
    ("H40P_UART_P5_P3", "UART_P5_P3"),
    ("H40P_PWM_P38", "PWM_P38"),
    ("H40P_UART_DEBUG", None),
    ("SPIFC_NOR", None),
    ("CSI_0_I2C", None),
    ("H40P_I2S_1", None),
    ("H40P_I2S_0", None),   # audio is not a header slot (/lwt H40P policy rule 4)
]


def requires_warning(where: str, header: str, deps: list[str]) -> str | None:
    """An overlay header's Requires: line must name exactly the providers
    dt.deps applies -- it is what a reader sees, dt.deps is what ldto does.
    A fan-auto overlay whose header said nothing still pulled in its fan."""
    m = re.search(r"^\s*\*\s*Requires:\s*(.+)$", header, re.M)
    said = set(re.split(r"[,\s]+", m.group(1).strip())) - {""} if m else set()
    if said != set(deps):
        return (f"{where}: Requires: says {sorted(said) or 'nothing'}, dt.deps "
                f"applies {sorted(deps) or 'nothing'}")
    return None


REQUIRES_CASES = [
    ("matching Requires:", " * Requires: pwm-2\n", ["pwm-2"], None),
    ("dt.deps provider missing from the header",
     " * Summary: x\n", ["pwm-a-fan"], "dt.deps applies ['pwm-a-fan']"),
    ("header names a provider dt.deps lacks", " * Requires: spi-cc-1cs\n", [],
     "Requires: says ['spi-cc-1cs']"),
]


PINS_MAP = ({("7J1", "16"): ["PG9"], ("J1", "19"): ["GPIO3_A1"]},
            {"PG9": "E3", "GPIO3_A1": "D2"})
PINS_CASES = [
    # (label, header text, expected substring or None)
    ("7J1 row matching the map", " *   7J1.16   PG9           E3      AP-UART1-CTS", None),
    ("stale Pad fires (all-h3-cc-h5 uart-1-rts-cts PG9 D3)",
     " *   7J1.16   PG9           D3      AP-UART1-CTS", "says Pad D3"),
    ("Rockchip J1 row is read at all (was skipped by a 7J1-only regex)",
     " *   J1.19   GPIO3_A2      D2      SPI_TXD", "says GPIO3_A2"),
    ("Rockchip J1 row matching the map", " *   J1.19   GPIO3_A1      D2      SPI_TXD", None),
]


def self_test() -> int:
    """Every checker against cases that must fire and cases that must not."""
    failed = 0
    total = 0

    def judge(suite: str, label: str, got: list[str],
              expect: str | None) -> None:
        nonlocal failed, total
        total += 1
        if expect is None:
            if got:
                failed += 1
                print(f"FAIL [{suite}: {label}]: expected no warning, got:",
                      file=sys.stderr)
                for g in got:
                    print(f"       {g}", file=sys.stderr)
        elif not any(expect in g for g in got):
            failed += 1
            print(f"FAIL [{suite}: {label}]: no warning contained {expect!r}; "
                  f"got {got or 'nothing'}", file=sys.stderr)

    for label, raw, expect in SELF_TEST_CASES:
        judge("identity", label,
              map_identity_warnings("case", _parse_rows(raw)), expect)
    for label, bname, raw, expect in FORMULA_CASES:
        judge("formula", label,
              soc_formula_warnings(bname, _parse_rows(raw), soc_family(bname)),
              expect)
    for label, decl, raw, expect in RPI_CASES:
        judge("rpi-header", label,
              rpi_header_warnings("case", _parse_rows(raw), decl), expect)
    judge("rpi-header", "Pi tables partition pins 1..40",
          rpi_table_warnings(), None)
    for label, text, expect in LGPIO_CASES:
        judge("lgpio-bcm", label, lgpio_bcm_warnings(text), expect)
    for label, text, expect in PINS_CASES:
        judge("overlay-pins", label, pins_row_warnings("case", text, *PINS_MAP), expect)
    for label, text, deps, expect in REQUIRES_CASES:
        w = requires_warning("case", text, deps)
        judge("requires", label, [w] if w else [], expect)
    for key, want in SLOT_CASES:
        got = h40p_slot(key)
        got_slot = got[0] if got else None
        judge("dt.map-grammar", key,
              [] if got_slot == want else [f"slot {got_slot!r} != {want!r}"], None)

    print(f"check-lwt --self-test: {total - failed}/{total} cases pass "
          f"(identity, formula, rpi-header, lgpio-bcm, overlay-pins, requires, "
          f"dt.map-grammar)",
          file=sys.stderr)
    return 1 if failed else 0


class Checker:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.info: list[str] = []

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        print(f"WARNING: {msg}", file=sys.stderr)

    def note(self, msg: str) -> None:
        self.info.append(msg)

    def check_gpio_map(self, board: Path) -> None:
        bname = board.name
        gpath = board / "gpio.map"
        if not gpath.exists():
            # Only warn if board has overlays (pinout expected)
            dt = board / "dt"
            if dt.exists() and any(dt.glob("*.dts")):
                self.warn(f"{bname}: missing gpio.map (lgpio/ldto info pinout)")
            return

        rows = load_gpio_map(gpath)
        if not rows:
            self.warn(f"{bname}: gpio.map empty")
            return

        bad = [r for r in rows if r.get("_bad")]
        for r in bad:
            self.warn(
                f"{bname}: gpio.map L{r['_line']}: expected ≥9 tab fields, "
                f"got {r.get('cols')}"
            )

        soc = BOARD_SOC.get(bname)
        if not soc:
            self.note(f"{bname}: gpio.map present (no meson Line/Chip binding check)")
            return

        fam, defs, ao_chip = soc
        ee_chip = 0 if ao_chip == 1 else 1
        for r in rows:
            if r.get("_bad"):
                continue
            name = r["name"]
            bare = name.rstrip("*")
            if (
                bare in SKIP_NAMES
                or r["chip"] in POWER_CHIPS
                or bare.startswith("SARADC")
            ):
                continue
            key = (
                "GPIO_TEST_N"
                if bare == "TEST_N" and "GPIO_TEST_N" in defs
                else bare
            )
            if key not in defs:
                self.warn(
                    f"{bname}: {r['header']}.{r['pin']} Name={name} "
                    f"not in meson-{fam}-gpio.h"
                )
                continue
            exp_line = str(defs[key])
            if str(r["line"]) != exp_line:
                self.warn(
                    f"{bname}: {r['header']}.{r['pin']} {name}: "
                    f"Line={r['line']} but binding={exp_line}"
                )
            exp_chip = str(ao_chip if is_ao_name(name) else ee_chip)
            if str(r["chip"]) != exp_chip:
                self.warn(
                    f"{bname}: {r['header']}.{r['pin']} {name}: "
                    f"Chip={r['chip']} expected {exp_chip} "
                    f"(AO=chip{ao_chip} on this SoC family)"
                )

    def check_map_identity(self, board: Path) -> None:
        """Row-vs-row checks that need no external authority.

        Runs for every board with a gpio.map, including the SoCs with no
        binding table -- these compare the file against itself.
        """
        gpath = board / "gpio.map"
        if not gpath.exists():
            return
        rows = [r for r in load_gpio_map(gpath) if not r.get("_bad")]
        if not rows:
            return
        for w in map_identity_warnings(board.name, rows):
            self.warn(w)

    def check_soc_formula(self, board: Path) -> None:
        """Rockchip/Allwinner pad name vs Chip/Line/sysfs (meson: bindings)."""
        gpath = board / "gpio.map"
        if not gpath.exists():
            return
        rows = [r for r in load_gpio_map(gpath) if not r.get("_bad")]
        for w in soc_formula_warnings(board.name, rows,
                                      soc_family(board.name)):
            self.warn(w)

    def check_rpi_header(self, board: Path) -> None:
        """The declared Raspberry Pi header must have the Pi's rail layout."""
        gpath = board / "gpio.map"
        if not gpath.exists():
            return
        rows = [r for r in load_gpio_map(gpath) if not r.get("_bad")]
        for w in rpi_header_warnings(board.name, rows,
                                     read_rpi_header(gpath)):
            self.warn(w)

    def check_lgpio_bcm(self) -> None:
        """lgpio's BCM -> pin table vs the Raspberry Pi pinout."""
        lgpio = ROOT / "lgpio"
        if not lgpio.is_file():
            self.warn("lgpio not found -- its BCM table was not checked")
            return
        for w in lgpio_bcm_warnings(lgpio.read_text(errors="replace")):
            self.warn(w)

    def check_dt_map(self, board: Path) -> None:
        mpath = board / "dt.map"
        dt = real_dt_dir(board)
        if not mpath.is_file() or not dt:
            return
        basenames = {p.stem for p in dt.glob("*.dts")}
        for i, line in enumerate(mpath.read_text(errors="replace").splitlines(), 1):
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                self.warn(f"{board.name}: dt.map L{i}: not KEY\\tVALUE")
                continue
            alias, target = parts[0].strip(), parts[-1].strip()
            if not alias or not target:
                self.warn(f"{board.name}: dt.map L{i}: empty key/value")
                continue
            if h40p_slot(alias) is None:
                self.warn(
                    f"{board.name}: dt.map {alias} is not an H40P slot key "
                    f"(docs/ldto.md 'Aliases'); enable {target} by name instead"
                )
            if target not in basenames:
                self.warn(
                    f"{board.name}: dt.map {alias} → {target} "
                    f"(no {target}.dts under dt/)"
                )
                continue
            # Prefer non-symlink targets
            tpath = dt / f"{target}.dts"
            if tpath.is_symlink() and not tpath.readlink().as_posix().startswith(
                ".."
            ):
                # same-dir alias as map value — discouraged
                self.warn(
                    f"{board.name}: dt.map {alias} → {target} "
                    f"(value is a same-dir symlink; prefer canonical basename)"
                )

    def check_dt_deps(self, board: Path) -> None:
        dpath = board / "dt.deps"
        dt = real_dt_dir(board)
        if not dpath.is_file() or not dt:
            return
        basenames = {p.stem for p in dt.glob("*.dts")}
        for i, line in enumerate(dpath.read_text(errors="replace").splitlines(), 1):
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t")
            consumer = parts[0].strip()
            providers = " ".join(parts[1:]).split()
            if consumer not in basenames:
                self.warn(
                    f"{board.name}: dt.deps L{i}: consumer {consumer} "
                    f"has no .dts"
                )
            for p in providers:
                if p not in basenames:
                    self.warn(
                        f"{board.name}: dt.deps {consumer} needs {p} "
                        f"(no {p}.dts)"
                    )

    def check_overlay_headers(self, board: Path) -> None:
        dt = real_dt_dir(board)
        if not dt:
            return
        # Only check files that live under this board's dt/ as real files
        # (skip if board's dt is a symlink to another board — checked there)
        if (board / "dt").is_symlink():
            return

        deps: dict[str, list[str]] = {}
        if (board / "dt.deps").is_file():
            for line in (board / "dt.deps").read_text(errors="replace").splitlines():
                if line.strip() and not line.startswith("#"):
                    parts = line.split()
                    deps[parts[0]] = parts[1:]

        gpath = board / "gpio.map"
        by_pin: dict[tuple[str, str], list[str]] = {}
        by_name: dict[str, tuple[str, str]] = {}
        pad_of: dict[str, str] = {}
        if gpath.is_file():
            for r in load_gpio_map(gpath):
                if r.get("_bad") or r["chip"] in POWER_CHIPS:
                    continue
                bare = r["name"].rstrip("*")
                pad_of[bare] = r.get("pad", "")
                # One header pin may have several rows when two SoC lines are
                # wired to it, so keep every name; a Pins: row naming any of
                # them is correct. A plain dict would silently keep the last.
                by_pin.setdefault((r["header"], r["pin"]), []).append(bare)
                by_name[bare] = (r["header"], r["pin"])

        for dts in sorted(dt.glob("*.dts")):
            if dts.is_symlink():
                continue
            text = dts.read_text(errors="replace")
            if "/dts-v1/" not in text and "/dts-v1/;" not in text:
                self.warn(f"{board.name}/{dts.name}: missing /dts-v1/")
                continue
            header = text.split("/dts-v1/")[0]
            if "Summary:" not in header:
                self.warn(
                    f"{board.name}/{dts.name}: header missing Summary: "
                    f"(run scripts/normalize-overlay-headers.py)"
                )

            # Pins rows must match gpio.map
            if by_pin:
                for w in pins_row_warnings(f"{board.name}/{dts.name}", header,
                                           by_pin, pad_of):
                    self.warn(w)

            # Requires: is the human-readable copy of dt.deps
            w = requires_warning(f"{board.name}/{dts.name}", header,
                                 deps.get(dts.stem, []))
            if w:
                self.warn(w)

            # DTS body pad names: if known to map, OK; unknown meson pads warn lightly
            body = text.split("/dts-v1/", 1)[-1]
            if by_name and board.name in BOARD_SOC:
                for m in PAD_TOKEN.finditer(body):
                    tok = m.group(1)
                    if SKIP_PAD.match(tok):
                        continue
                    bare = tok.rstrip("*")
                    if bare in ("TEST_N",) or bare.startswith("GPIO"):
                        # only warn if looks like SoC pad but absent from map
                        # AND used in gpios/groups (already in body)
                        if bare not in by_name and bare != "GPIO_TEST_N":
                            # Many pads exist on SoC but not on header — OK
                            pass

    def run(self, board_filter: str | None) -> int:
        boards = board_dirs(board_filter)
        if not boards:
            self.warn(f"no board dirs for filter={board_filter!r}")
            return 1 if board_filter else 0

        self.check_lgpio_bcm()
        seen_maps: set = set()
        for board in boards:
            gpath = board / "gpio.map"
            # A whole-board symlink shares one file; check it once so the
            # aliases do not triple every warning.
            if gpath.exists():
                real = gpath.resolve()
                if real in seen_maps:
                    self.check_dt_map(board)
                    self.check_dt_deps(board)
                    self.check_overlay_headers(board)
                    continue
                seen_maps.add(real)
            self.check_map_identity(board)
            self.check_soc_formula(board)
            self.check_rpi_header(board)
            self.check_gpio_map(board)
            self.check_dt_map(board)
            self.check_dt_deps(board)
            self.check_overlay_headers(board)

        n = len(self.warnings)
        if n:
            print(
                f"check-lwt: {n} warning(s)"
                + (f" (board={board_filter})" if board_filter else ""),
                file=sys.stderr,
            )
        else:
            print(
                "check-lwt: OK"
                + (f" (board={board_filter})" if board_filter else ""),
                file=sys.stderr,
            )
        return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--board",
        default=None,
        help="limit to libre-computer/<board>",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 if any WARNING (default: always 0 for make)",
    )
    ap.add_argument(
        "--self-test",
        action="store_true",
        help="run the gpio.map identity checks against their case table",
    )
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    c = Checker()
    n = c.run(args.board)
    if args.strict and n:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
