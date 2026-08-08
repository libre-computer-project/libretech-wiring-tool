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
PIN_ROW_RE = re.compile(
    r"^\s*\*?\s*(\d+[Jj]\d+)\.(\d+)\s+(\S+)\s+"
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


def self_test() -> int:
    cols = ("header", "pin", "chip", "line", "sysfs", "name", "pad", "ref",
            "desc")
    failed = 0
    for label, raw, expect in SELF_TEST_CASES:
        rows = []
        for i, ln in enumerate(raw, 1):
            parts = ln.split("\t")
            r = {"_bad": False, "_line": i}
            r.update(dict(zip(cols, parts)))
            rows.append(r)
        got = map_identity_warnings("case", rows)
        if expect is None:
            if got:
                failed += 1
                print(f"FAIL [{label}]: expected no warning, got:",
                      file=sys.stderr)
                for g in got:
                    print(f"       {g}", file=sys.stderr)
        elif not any(expect in g for g in got):
            failed += 1
            print(f"FAIL [{label}]: no warning contained {expect!r}; got "
                  f"{got or 'nothing'}", file=sys.stderr)
    total = len(SELF_TEST_CASES)
    print(f"check-lwt --self-test: {total - failed}/{total} identity cases pass",
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

        gpath = board / "gpio.map"
        by_pin: dict[tuple[str, str], list[str]] = {}
        by_name: dict[str, tuple[str, str]] = {}
        if gpath.is_file():
            for r in load_gpio_map(gpath):
                if r.get("_bad") or r["chip"] in POWER_CHIPS:
                    continue
                bare = r["name"].rstrip("*")
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
            for line in header.splitlines():
                m = PIN_ROW_RE.match(line.replace("—", "-"))
                if not m:
                    continue
                h, pin, name = m.group(1), m.group(2), m.group(3)
                if name in ("Name", "Pad", "cross-ref", "Ref"):
                    continue
                if not by_pin:
                    continue
                key = (h, pin)
                if key not in by_pin:
                    self.warn(
                        f"{board.name}/{dts.name}: Pins {h}.{pin} {name} "
                        f"not in gpio.map"
                    )
                    continue
                map_names = by_pin[key]
                if name.rstrip("*") not in [m.rstrip("*") for m in map_names]:
                    self.warn(
                        f"{board.name}/{dts.name}: Pins {h}.{pin} says "
                        f"{name} but gpio.map has {' / '.join(map_names)}"
                    )

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
