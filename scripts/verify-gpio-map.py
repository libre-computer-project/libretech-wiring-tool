#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Da Xue <da@libre.computer>
"""Verify a board's gpio.map against the RUNNING kernel.  Run on the board, as
root (it reads debugfs).

check-lwt.py checks the file against itself, the dt-bindings and the Raspberry
Pi skeleton; none of that can see what the kernel actually built.  This reads
the live gpiochips and checks every GPIO row of the map against them:

  chip    the row's Chip index exists and its Line is < that chip's line count
  pad     the pinctrl driver's own pin table names the pad behind (Chip, Line);
          it must be the row's Name.  Catches a wrong Chip index (the AO/EE
          probe order), a wrong Line, and a pad copied from the wrong row.
          Every family registers its pins this way, so this covers every row.
  header  where the device tree names lines by header position
          ("7J1 Header Pin19", gpio-line-names), the name must be the row's
          own Header.Pin -- the only check anywhere that verifies HEADER
          POSITION against an authority other than the map.  Only boards whose
          DT carries such names get it.
  base    gaps between the map's legacy sysfs bases match the kernel's
          (2026-08: AO published 15 above EE where the kernel puts it 85 above)

Sources, all plain files, so no libgpiod and no ioctls:
  /sys/kernel/debug/gpio                      gpiochip index, label, lines
  /sys/kernel/debug/pinctrl/*/pins            "pin N (PAD) <offset>:<chip>"
  /sys/kernel/debug/pinctrl/*/gpio-ranges     each chip's legacy base
  /sys/bus/gpio/devices/gpiochipN/of_node/gpio-line-names

The gpio drivers on our SoCs (meson, sunxi, rockchip) set no line names of
their own, so the line names in debugfs are blank unless the DT supplies them;
the pad check reads pinctrl for exactly that reason.

Usage:
    scripts/verify-gpio-map.py --map path/to/gpio.map
    scripts/verify-gpio-map.py --board roc-rk3328-cc
    scripts/verify-gpio-map.py                       # map from DMI
    scripts/verify-gpio-map.py --root DIR ...        # replay a captured tree
    scripts/verify-gpio-map.py --self-test           # no hardware needed

Exit: 0 all checked rows agree, 1 any disagreement, 2 nothing could be read.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHIP_RE = re.compile(r"^gpiochip(\d+):\s+(\d+)\s+GPIOs?,\s+parent:\s+[^,]+,\s+"
                     r"([^,:]+)")
PIN_RE = re.compile(r"^pin\s+\d+\s+\(([^)]*)\)\s+(\d+):(\S+)")
RANGE_RE = re.compile(r"^\d+:\s+(\S+)\s+GPIOS\s+\[(\d+)\s*-\s*\d+\]")
HEADER_NAME = re.compile(r"^(\S+)\s+Header\s+Pin\s*(\d+)$", re.I)
RK_PIN = re.compile(r"^gpio(\d+)-(\d+)$")


def parse_chips(text: str) -> dict[int, dict]:
    """debugfs gpio: 'gpiochip0: 85 GPIOs, parent: platform/..., LABEL, ...'"""
    chips = {}
    for line in text.splitlines():
        m = CHIP_RE.match(line)
        if m:
            chips[int(m.group(1))] = {"label": m.group(3).strip(),
                                      "ngpio": int(m.group(2))}
    return chips


def pad_name(raw: str) -> str:
    """Normalise a pinctrl pin name to gpio.map's spelling.

    meson and sunxi pins already carry the datasheet name (GPIOX_8, PA0);
    rockchip names them '<bank>-<n>' (gpio2-25), which is GPIO2_D1.
    """
    m = RK_PIN.match(raw)
    if m:
        bank, n = int(m.group(1)), int(m.group(2))
        return f"GPIO{bank}_{chr(ord('A') + n // 8)}{n % 8}"
    return raw


def parse_pins(text: str) -> dict[tuple[str, int], str]:
    """pinctrl pins: 'pin 0 (GPIOZ_0) 0:periphs-banks  ...' -> (label, off)."""
    pads = {}
    for line in text.splitlines():
        m = PIN_RE.match(line.strip())
        if m and m.group(3) != "?":
            pads[(m.group(3), int(m.group(2)))] = pad_name(m.group(1))
    return pads


def parse_ranges(text: str) -> dict[str, int]:
    """pinctrl gpio-ranges: '0: periphs-banks GPIOS [512 - 596] PINS [...]'"""
    bases: dict[str, int] = {}
    for line in text.splitlines():
        m = RANGE_RE.match(line.strip())
        if m:
            label, base = m.group(1), int(m.group(2))
            bases[label] = min(base, bases.get(label, base))
    return bases


def parse_line_names(blob: bytes) -> dict[int, str]:
    """DT gpio-line-names: NUL-separated, one entry per line, '' = unnamed."""
    return {i: n for i, n in enumerate(blob.decode(errors="replace")
                                       .split("\0")) if n}


def load_map(path: Path) -> list[dict]:
    cols = ("header", "pin", "chip", "line", "sysfs", "name", "pad", "ref",
            "desc")
    rows = []
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 9:
            rows.append(dict(zip(cols, parts)))
    return rows


def verify(rows: list[dict], chips: dict[int, dict],
           pads: dict[tuple[str, int], str], bases: dict[str, int],
           dtnames: dict[int, dict[int, str]]) -> tuple[list[str], dict]:
    """Pure: map rows x live kernel tables -> (findings, coverage counts)."""
    out: list[str] = []
    cov = {"rows": 0, "pad": 0, "header": 0, "unverified": 0}
    gpio = [r for r in rows if r["chip"].isdigit() and r["line"].isdigit()]
    for r in gpio:
        cov["rows"] += 1
        where = f"{r['header']}.{r['pin']} {r['name']}"
        c, ln = int(r["chip"]), int(r["line"])
        if c not in chips:
            out.append(f"{where}: gpiochip{c} does not exist on this kernel "
                       f"(have {', '.join(f'gpiochip{i}' for i in sorted(chips))})")
            continue
        label = chips[c]["label"]
        if ln >= chips[c]["ngpio"]:
            out.append(f"{where}: line {ln} is past the end of gpiochip{c} "
                       f"[{label}], which has {chips[c]['ngpio']} lines")
            continue
        checked = False
        live = pads.get((label, ln))
        if live is not None:
            checked = True
            cov["pad"] += 1
            if live != r["name"].rstrip("*"):
                out.append(f"{where}: pinctrl puts pad {live} on gpiochip{c} "
                           f"[{label}] line {ln}, not {r['name']}")
        dt = dtnames.get(c, {}).get(ln, "")
        hm = HEADER_NAME.match(dt)
        if hm:
            checked = True
            cov["header"] += 1
            if (hm.group(1).lower(), hm.group(2)) != (r["header"].lower(),
                                                       r["pin"]):
                out.append(f"{where}: the device tree names gpiochip{c} line "
                           f"{ln} {dt!r}, but the map puts it on "
                           f"{r['header']}.{r['pin']}")
        if not checked:
            cov["unverified"] += 1

    # legacy sysfs: the map's per-chip base gaps must match the kernel's
    mbase: dict[int, int] = {}
    for r in gpio:
        if r["sysfs"].isdigit():
            mbase.setdefault(int(r["chip"]), int(r["sysfs"]) - int(r["line"]))
    live = {c: bases[chips[c]["label"]] for c in mbase
            if c in chips and chips[c]["label"] in bases}
    used = sorted(live)
    cov["base"] = len(used) > 1
    for a, b in zip(used, used[1:]):
        want, got = live[b] - live[a], mbase[b] - mbase[a]
        if want != got:
            out.append(f"sysfs: the map puts gpiochip{b} {got} above "
                       f"gpiochip{a}; the kernel puts it {want} above")
    return out, cov


def read_live(root: Path) -> tuple[dict, dict, dict, dict]:
    def rd(p: Path) -> str:
        try:
            return p.read_text(errors="replace")
        except OSError:
            return ""
    chips = parse_chips(rd(root / "sys/kernel/debug/gpio"))
    pads: dict = {}
    bases: dict = {}
    for d in sorted((root / "sys/kernel/debug/pinctrl").glob("*")):
        if d.is_dir():
            pads.update(parse_pins(rd(d / "pins")))
            bases.update(parse_ranges(rd(d / "gpio-ranges")))
    dtnames: dict = {}
    for c in chips:
        f = root / f"sys/bus/gpio/devices/gpiochip{c}/of_node/gpio-line-names"
        try:
            dtnames[c] = parse_line_names(f.read_bytes())
        except OSError:
            pass
    return chips, pads, bases, dtnames


def dmi_map() -> Path | None:
    try:
        v = Path("/sys/class/dmi/id/board_vendor").read_text().strip("\0\n ")
        b = Path("/sys/class/dmi/id/board_name").read_text().strip("\0\n ")
    except OSError:
        return None
    p = ROOT / v / b / "gpio.map"
    return p if p.exists() else None


# ---------------------------------------------------------------- self-test
# Fixture text copied from a live aml-a311d-cc (kernel 6.18), 2026-10-05.
_DBG_GPIO = (
    "gpiochip0: 85 GPIOs, parent: platform/ff634400.bus:pinctrl@40, "
    "periphs-banks, can sleep:\n"
    " gpio-15  (                    |PHY reset           ) out hi ACTIVE LOW\n"
    "gpiochip1: 15 GPIOs, parent: platform/ff800000.bus:pinctrl@14, "
    "aobus-banks, can sleep:\n")
_PINS = ("registered pins: 100\n"
         "pin 0 (GPIOZ_0) 0:periphs-banks  ff634400.bus:pinctrl@40\n"
         "pin 5 (GPIOZ_5) 5:periphs-banks  ff634400.bus:pinctrl@40\n"
         "pin 20 (GPIOX_8) 20:periphs-banks  ff634400.bus:pinctrl@40\n"
         "pin 21 (GPIOX_9) 21:periphs-banks  ff634400.bus:pinctrl@40\n"
         "pin 99 (NOGPIO) 0:? \n"
         "pin 5 (GPIOAO_5) 5:aobus-banks  ff800000.bus:pinctrl@14\n")
_RANGES = ("GPIO ranges handled:\n"
           "0: periphs-banks GPIOS [512 - 596] PINS [0 - 84]\n"
           "0: aobus-banks GPIOS [597 - 611] PINS [0 - 14]\n")


def _rows(*raw: str) -> list[dict]:
    cols = ("header", "pin", "chip", "line", "sysfs", "name", "pad", "ref",
            "desc")
    return [dict(zip(cols, r.split("\t"))) for r in raw]


def self_test() -> int:
    failed = 0
    chips = parse_chips(_DBG_GPIO)
    pads = parse_pins(_PINS)
    bases = parse_ranges(_RANGES)
    rk = parse_pins("pin 89 (gpio2-25) 25:gpio2  ff100000.pinctrl\n")
    names = parse_line_names(b"\0\x007J1 Header Pin19\0\0")
    parsers = {
        "chips": chips == {0: {"label": "periphs-banks", "ngpio": 85},
                           1: {"label": "aobus-banks", "ngpio": 15}},
        "pins": pads.get(("periphs-banks", 20)) == "GPIOX_8"
                and ("?", 0) not in pads,
        "ranges": bases == {"periphs-banks": 512, "aobus-banks": 597},
        "rockchip pin names": rk == {("gpio2", 25): "GPIO2_D1"},
        "dt line names": names == {2: "7J1 Header Pin19"},
    }
    for what, ok in parsers.items():
        if not ok:
            failed += 1
            print(f"FAIL [parser: {what}]", file=sys.stderr)

    dt = {0: {20: "7J1 Header Pin19"}}
    cases = [
        # (label, rows, dtnames, substring that must appear | None)
        ("rows that match the kernel", _rows(
            "7J1\t19\t0\t20\t20\tGPIOX_8\tB4\tx\tx",
            "7J1\t3\t1\t5\t90\tGPIOAO_5\tD13\tx\tx"), dt, None),
        ("pad copied from the next row", _rows(
            "7J1\t19\t0\t20\t20\tGPIOX_9\tB4\tx\tx"), {},
         "pinctrl puts pad GPIOX_8 on gpiochip0 [periphs-banks] line 20, not GPIOX_9"),
        # the AO/EE probe-order class: an AO pad given the EE chip index
        ("AO pad on the EE chip index", _rows(
            "7J1\t3\t0\t5\t5\tGPIOAO_5\tD13\tx\tx"), {},
         "not GPIOAO_5"),
        ("header position disagrees with the device tree", _rows(
            "7J1\t21\t0\t20\t20\tGPIOX_8\tB4\tx\tx"), dt,
         "'7J1 Header Pin19', but the map puts it on 7J1.21"),
        ("chip that does not exist", _rows(
            "7J1\t5\t4\t1\t129\tGPIO4_A1\tA1\tx\tx"), {},
         "gpiochip4 does not exist"),
        ("line past the end of its chip", _rows(
            "7J1\t5\t1\t20\t105\tGPIOAO_20\tA1\tx\tx"), {},
         "line 20 is past the end of gpiochip1"),
        # 2026-08: AO published at base 15 while the kernel puts it at 85
        ("legacy bases one chip off", _rows(
            "7J1\t19\t0\t20\t20\tGPIOX_8\tB4\tx\tx",
            "7J1\t3\t1\t5\t20\tGPIOAO_5\tD13\tx\tx"), {},
         "puts gpiochip1 15 above gpiochip0; the kernel puts it 85 above"),
        ("line with no pin entry is unverified, not a finding", _rows(
            "7J1\t7\t0\t30\t30\tGPIOX_18\tA2\tx\tx"), {}, None),
    ]
    for label, rows, dtn, expect in cases:
        got, _ = verify(rows, chips, pads, bases, dtn)
        if expect is None and got:
            failed += 1
            print(f"FAIL [{label}]: expected nothing, got {got}", file=sys.stderr)
        elif expect is not None and not any(expect in g for g in got):
            failed += 1
            print(f"FAIL [{label}]: no finding contained {expect!r}; got "
                  f"{got or 'nothing'}", file=sys.stderr)
    total = len(parsers) + len(cases)
    print(f"verify-gpio-map --self-test: {total - failed}/{total} cases pass",
          file=sys.stderr)
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", help="libre-computer/<board>/gpio.map")
    ap.add_argument("--map", type=Path, help="explicit gpio.map path")
    ap.add_argument("--root", type=Path, default=Path("/"),
                    help="filesystem root to read the kernel tables from "
                         "(default /; point at a captured tree to replay)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    path = a.map or (ROOT / "libre-computer" / a.board / "gpio.map"
                     if a.board else dmi_map())
    if not path or not path.exists():
        print("verify-gpio-map: no gpio.map (give --board or --map)",
              file=sys.stderr)
        return 2
    chips, pads, bases, dtnames = read_live(a.root)
    if not chips or not pads:
        print(f"verify-gpio-map: read {len(chips)} gpiochip(s) and "
              f"{len(pads)} pinctrl pin(s) under {a.root} -- needs root and "
              f"debugfs mounted at /sys/kernel/debug", file=sys.stderr)
        return 2
    found, cov = verify(load_map(path), chips, pads, bases, dtnames)

    for i in sorted(chips):
        lab = chips[i]["label"]
        print(f"gpiochip{i} [{lab}] {chips[i]['ngpio']} lines"
              + (f", legacy base {bases[lab]}" if lab in bases else "")
              + (f", {len(dtnames[i])} DT line names" if dtnames.get(i) else ""))
    for f in found:
        print(f"MISMATCH: {f}")
    print(f"verify-gpio-map: {path}: {cov['rows']} GPIO rows -- "
          f"{cov['pad']} checked against pinctrl, {cov['header']} against DT "
          f"header names, {cov['unverified']} unverified; base check "
          f"{'ran' if cov['base'] else 'not applicable'}; "
          f"{len(found)} mismatch(es)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
