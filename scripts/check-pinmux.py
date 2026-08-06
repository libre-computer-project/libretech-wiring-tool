#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Cross-check gpio.map Desc (alt-mux column) against the SoC's mux table.

check-lwt.py validates the *offsets* (Chip/Line vs dt-bindings). This validates
the *mux inventory*: for every header pad, does Desc list the functions the SoC
can actually mux onto that pad, and does every Desc token correspond to a real
one?

Authority per SoC family (best available, in order of preference):

    meson GXL / G12A   drivers/pinctrl/meson/pinctrl-meson-{gxl,g12a}.c
                       <group>_pins[] = { PAD } enumerates every muxable
                       group, so pad -> {groups} is the driver's whole table.
    sunxi H3 / H5      drivers/pinctrl/sunxi/pinctrl-sun{8i-h3,50i-h5}.c
                       SUNXI_PIN(...) carries all four mux functions per pad,
                       transcribed from the datasheet pin-list.
    rockchip RK3328    NO per-pin enumeration exists in the kernel (DT encodes
                       mux indices, not names), and no RK3328 TRM is in the
                       tree -- reported as unaudited, never as clean.

The kernel driver is a *proxy* for the datasheet, not the datasheet: mainline
omits functions nobody upstreamed (GXL JTAG on GPIOH_6..9 is the known case).
So a Desc token with no kernel group is reported separately from a kernel group
missing from Desc -- the first is usually datasheet-only, the second is usually
a gap in the map.

Usage:
    scripts/check-pinmux.py [--board B] [--linux PATH] [--verbose] [--strict]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LC = ROOT / "libre-computer"
DEFAULT_LINUX = [
    Path.home() / "git" / "linux-worktree" / "linux-6.18.y-lc",
    Path.home() / "git" / "libretech-builder" / "linux",
]

POWER = {"3.3V", "5V", "GND", "ADC", "PHY"}

# Tokens that carry no function identity -- routing/variant suffixes, pad
# qualifiers, and the drive/pull decorations Rockchip hangs off a mux name.
NOISE = {
    "M0", "M1", "M2", "M3", "S0",
    "PINS", "PIN",
    "AO", "EE",          # domain markers: present in some names, not others
    # instance / bank / master-slave letters: which bus, not which function
    "A", "B", "C", "D", "E", "F", "H", "M", "S", "U", "W", "X", "Z",
}
# Digits stay significant: TDMB_D1 and tdm_b_dout2 are different lanes.

SOC_OF_BOARD = {
    "aml-s905x-cc": "gxl", "aml-s905x-cc-v2": "gxl", "aml-s905x-cc-v3": "gxl",
    "aml-s805x-ac": "gxl", "aml-s805x-ac-v2": "gxl",
    "aml-a311d-cc": "g12a", "aml-a311d-cc-v01": "g12a",
    "aml-s905d3-cc": "g12a", "aml-s905d3-cc-v01": "g12a",
    "all-h3-cc-h3": "h3", "all-h3-cc-h5": "h5",
    "roc-rk3328-cc": "rk3328", "roc-rk3328-cc-v2": "rk3328",
}

DRIVER = {
    "gxl": "drivers/pinctrl/meson/pinctrl-meson-gxl.c",
    "g12a": "drivers/pinctrl/meson/pinctrl-meson-g12a.c",
    "h3": "drivers/pinctrl/sunxi/pinctrl-sun8i-h3.c",
    "h5": "drivers/pinctrl/sunxi/pinctrl-sun50i-h5.c",
}


# Same function, different vocabulary. Datasheet/silk names on the left of each
# pair, kernel driver names on the right; both sides normalise to the first.
ALIAS = {
    "TWI": "I2C",          # Allwinner calls I2C "TWI"
    "SCL": "SCK",
    "SLAVE": "S",          # meson i2c_ao_slave_* == datasheet I2C_AO_S0_*
    "MASTER": "M",
    "SYNC": "FS",          # I2S/TDM frame sync
    "LRCK": "FS",
    "SCLK": "CLK",
    # A data lane is one pad; the driver splits it per direction, the
    # datasheet names the lane. TDMB_D1 == tdm_b_dout1 == tdm_b_din1.
    "DOUT": "D",
    "DIN": "D",
    "SDO": "D",
    "SDI": "D",
    # meson TSIN groups fold the controller letter into the signal
    "ASOP": "SOP",
    "ACLK": "CLK",
    "ADIN": "D",
    "AVALID": "VALID",
    "AFAIL": "FAIL",
    "EINT": "INT",
    "MMC": "SDC",          # sunxi driver "mmc2" == datasheet SDC2
    "PCM": "I2S",          # sunxi: one block, datasheet says PCM, driver I2S
}


def squash(name: str) -> str:
    """Separator-insensitive form: I2SOUT_CH45 == i2s_out_ch45."""
    return re.sub(r"[^A-Z0-9]", "", name.upper())


def tokens(name: str) -> frozenset[str]:
    """Comparable token set: case/underscore/instance-suffix insensitive."""
    parts = re.split(r"[^A-Za-z0-9]+", name.upper())
    out = set()
    for p in parts:
        if not p:
            continue
        # split a trailing instance number so UART2 and UART_2 agree, and so
        # I2C0 splits to I2C+0 (the leading 2 is part of the block name)
        m = re.match(r"^(.*[A-Z])(\d+)$", p)
        if m:
            p, num = m.group(1), m.group(2)
            out.add(num)
        # split a trailing instance letter: TDMB == tdm_b
        m = re.match(r"^([A-Z]{3,})([A-C])$", p)
        if m:
            out.add(m.group(2))
            p = m.group(1)
        out.add(ALIAS.get(p, p))
    return frozenset(t for t in out if t not in NOISE) or frozenset(out)


def same_function(a: str, b: str) -> bool:
    """Do two names from different vocabularies denote the same function?"""
    sa, sb = squash(a), squash(b)
    if sa and sb and (sa in sb or sb in sa):
        return True
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    return ta <= tb or tb <= ta


# ---------------------------------------------------------------- authorities


def meson_pad_muxes(driver: Path) -> dict[str, set[str]]:
    """pad name -> {group names} from <group>_pins[] = { PAD, ... };"""
    text = driver.read_text(errors="replace")
    pads: dict[str, set[str]] = {}
    for m in re.finditer(
        r"static const unsigned int (\w+)_pins\[\]\s*=\s*\{([^}]*)\}", text
    ):
        group, body = m.group(1), m.group(2)
        for pad in re.findall(r"\b([A-Z][A-Z0-9_]+)\b", body):
            pads.setdefault(pad, set()).add(group)
    return pads


def sunxi_pad_muxes(driver: Path) -> dict[str, set[str]]:
    """pad name (PA0) -> {FUNC_SIGNAL} from SUNXI_PIN(...) blocks."""
    text = driver.read_text(errors="replace")
    pads: dict[str, set[str]] = {}
    blocks = re.split(r"SUNXI_PIN\(SUNXI_PINCTRL_PIN\(", text)[1:]
    for block in blocks:
        head = re.match(r"([A-Z]),\s*(\d+)\)", block)
        if not head:
            continue
        pad = f"P{head.group(1)}{head.group(2)}"
        body = block.split("SUNXI_PIN(")[0]
        funcs: set[str] = set()
        for fm in re.finditer(
            r'SUNXI_FUNCTION(?:_VARIANT)?\(0x[0-9a-fA-F]+,\s*"([^"]+)"\)'
            r"(?:,)?[ \t]*(?:/\*\s*([^*]*?)\s*\*/)?",
            body,
        ):
            func, sig = fm.group(1), (fm.group(2) or "").strip()
            if func in ("gpio_in", "gpio_out", "io_disabled"):
                continue
            funcs.add(f"{func}_{sig}".upper() if sig else func.upper())
        for im in re.finditer(r"SUNXI_FUNCTION_IRQ_BANK\(0x[0-9a-fA-F]+,\s*(\d+),\s*(\d+)\)", body):
            funcs.add(f"P{head.group(1)}_EINT{im.group(2)}")
        if funcs:
            pads[pad] = funcs
    return pads


def load_authority(soc: str, linux: Path) -> tuple[dict[str, set[str]] | None, str]:
    rel = DRIVER.get(soc)
    if rel is None:
        return None, f"{soc}: no per-pin mux authority available"
    path = linux / rel
    if not path.is_file():
        return None, f"{soc}: driver not found ({path})"
    if soc in ("gxl", "g12a"):
        return meson_pad_muxes(path), rel
    return sunxi_pad_muxes(path), rel


# ------------------------------------------------------------------ gpio.map


def load_map(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        f = line.split("\t")
        if len(f) < 9:
            continue
        rows.append({
            "header": f[0], "pin": f[1], "chip": f[2], "line": f[3],
            "name": f[5], "pad": f[6], "ref": f[7], "desc": f[8].strip(),
        })
    return rows


def desc_tokens(desc: str) -> list[str]:
    return [t for t in re.split(r"[\s/]+", desc) if t]


# --------------------------------------------------------------------- check


def check_board(board: Path, linux: Path, verbose: bool) -> tuple[int, int, int]:
    soc = SOC_OF_BOARD.get(board.name)
    gmap = board / "gpio.map"
    if soc is None or not gmap.is_file():
        return 0, 0, 0
    pads, src = load_authority(soc, linux)
    if pads is None:
        print(f"UNAUDITED: {board.name}: {src}")
        return 0, 0, 1

    missing = extra = 0
    for row in load_map(gmap):
        if row["chip"] in POWER or row["name"] in POWER:
            continue
        known = pads.get(row["name"])
        if known is None:
            continue          # pad carries no muxable function in the driver
        listed = desc_tokens(row["desc"])
        for group in sorted(known):
            if not any(same_function(group, tok) for tok in listed):
                missing += 1
                print(f"WARNING: {board.name} {row['header']}.{row['pin']} "
                      f"{row['name']}: Desc omits '{group}' "
                      f"[Desc: {row['desc']}]")
        if verbose:
            for tok in listed:
                if not any(same_function(group, tok) for group in known):
                    extra += 1
                    print(f"NOTE: {board.name} {row['header']}.{row['pin']} "
                          f"{row['name']}: '{tok}' has no {soc} driver group "
                          f"(datasheet-only or misspelt)")
    return missing, extra, 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", help="single board directory name")
    ap.add_argument("--linux", help="kernel source tree (pinctrl drivers)")
    ap.add_argument("--verbose", action="store_true",
                    help="also report Desc tokens with no driver group")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when Desc omits a function")
    args = ap.parse_args()

    if args.linux:
        linux = Path(args.linux)
    else:
        linux = next((p for p in DEFAULT_LINUX if (p / "drivers").is_dir()), None)
    if linux is None or not (linux / "drivers").is_dir():
        print("SKIP: no kernel tree found (--linux PATH); pinmux check not run")
        return 0

    boards = ([LC / args.board] if args.board
              else sorted(p for p in LC.iterdir() if p.is_dir()))
    missing = extra = unaudited = 0
    for board in boards:
        m, e, u = check_board(board, linux, args.verbose)
        missing += m
        extra += e
        unaudited += u

    print(f"check-pinmux: {missing} omitted function(s), {extra} unmatched Desc "
          f"token(s), {unaudited} unaudited SoC(s) [authority: {linux}]")
    return 1 if (args.strict and missing) else 0


if __name__ == "__main__":
    sys.exit(main())
