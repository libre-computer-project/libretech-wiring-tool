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
# Rockchip has no per-pin mux names in the kernel, so its authority is the
# datasheet's Function IO Description table, extracted to JSON by
# tools/gpio_extract.py in the claude doc repo.
DEFAULT_RK_PINMUX = [
    Path.home() / "git" / "claude" / "rockchip" / "rk3328" / "gpio_pinmux.json",
]

# The pinctrl driver is a SUBSET of the datasheet -- mainline models no JTAG,
# PCM or CLK24 group on GXL -- so checking Desc against the driver alone
# answers a weaker question than it appears to. These are the vendor's own
# multiplexing tables, extracted by tools/gpio_ocr_extract.py in the claude doc
# repo, with every name verified against the PDF text layer.
#
# Keyed by BOARD, not by the SoC name below: SOC_OF_BOARD collapses S905X and
# S805X to "gxl" and A311D and S905D3 to "g12a" because they share a pinctrl
# driver, but they do NOT share a datasheet. S905D3 documents TDMB_D4..D7 on
# six GPIOA pads and A311D documents none of them, which is precisely the
# difference a driver-keyed lookup would erase.
CLAUDE = Path.home() / "git" / "claude"
DATASHEET_JSON = {
    "aml-s905x-cc": CLAUDE / "amlogic/gxl/s905x/gpio_pinmux.json",
    "aml-s905x-cc-v2": CLAUDE / "amlogic/gxl/s905x/gpio_pinmux.json",
    "aml-s905x-cc-v3": CLAUDE / "amlogic/gxl/s905x/gpio_pinmux.json",
    "aml-s805x-ac": CLAUDE / "amlogic/gxl/s805x/gpio_pinmux.json",
    "aml-s805x-ac-v2": CLAUDE / "amlogic/gxl/s805x/gpio_pinmux.json",
    "aml-a311d-cc": CLAUDE / "amlogic/g12sm1/a311d/gpio_pinmux.json",
    "aml-a311d-cc-v01": CLAUDE / "amlogic/g12sm1/a311d/gpio_pinmux.json",
    "aml-s905d3-cc": CLAUDE / "amlogic/g12sm1/s905d3/gpio_pinmux.json",
    "aml-s905d3-cc-v01": CLAUDE / "amlogic/g12sm1/s905d3/gpio_pinmux.json",
    "all-h3-cc-h3": CLAUDE / "allwinner/h3/gpio_pinmux.json",
    # H5 is deliberately absent. Its datasheet states mux options as a
    # row-per-function pin list (Ball / Pin Name / Signal Name / Function)
    # rather than the column-per-function table every other book here uses, so
    # gpio_ocr_extract.py reads it as a ball description and produces nothing
    # usable. H5 keeps pinctrl-sun50i-h5.c as its authority until that shape is
    # handled -- an absent extract is checked as "no datasheet", a wrong one
    # would be checked as fact.
}

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
    "OWA": "SPDIF",        # Allwinner calls S/PDIF "OWA" (One Wire Audio)
    "MMC": "SDC",          # sunxi driver "mmc2" == datasheet SDC2
    "PCM": "I2S",          # sunxi: one block, datasheet says PCM, driver I2S
    "DATA": "D",           # rockchip TRM cif_data5m1 == datasheet cif_d5m1
}


def squash(name: str) -> str:
    """Separator-insensitive form: I2SOUT_CH45 == i2s_out_ch45."""
    return re.sub(r"[^A-Z0-9]", "", name.upper())


def canon(name: str) -> str:
    """Squash plus the decorations that ride along with a Rockchip mux name.

    `cif_data5m1` (TRM) and `CIF_D5_M1_u` (map) are one function wearing three
    differences: DATA vs D, a glued vs separated M-route marker, and a reset-
    pull suffix. Length guards keep the strippers off short names -- PWM1 must
    not lose its M1 and become PW.
    """
    s = squash(name).replace("DBG", "")
    m = re.match(r"^(.*\d)[UDZ]$", s)       # reset pull: _u / _d / _z (outermost)
    if m and len(m.group(1)) >= 4:
        s = m.group(1)
    m = re.match(r"^(.*?)M\d$", s)          # route marker: …M0 / …M1
    if m and len(m.group(1)) >= 4:
        s = m.group(1)
    return s.replace("DATA", "D")


def tokens(name: str) -> frozenset[str]:
    """Comparable token set: case/underscore/instance-suffix insensitive."""
    parts = re.split(r"[^A-Za-z0-9]+", name.upper())
    out = set()
    for p in parts:
        if not p:
            continue
        # rockchip names the debug UART instance uart2dbg; the map calls the
        # same pad UART2_TX_M1
        p = re.sub(r"DBG$", "", p)
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


def match_score(a: str, b: str) -> int:
    """How well two names from different vocabularies agree. 0 means not at all.

    Graded rather than boolean because the loose rules are ambiguous on their
    own: {i2c,sck,ao} is a subset of {i2c,slave,sck,ao}, so a Desc listing
    I2C_SCK_AO would otherwise be read as covering the pad's *separate*
    i2c_slave_sck_ao function. The caller resolves that by giving each Desc
    token to its best-matching function only.
    """
    sa, sb = squash(a), squash(b)
    if sa and sb and sa == sb:
        return 4
    ca, cb = canon(a), canon(b)
    if ca and cb and ca == cb:
        return 3
    if sa and sb and (sa in sb or sb in sa):
        return 2
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0
    if ta <= tb or tb <= ta:
        return 1
    return 0


def same_function(a: str, b: str) -> bool:
    """Do two names from different vocabularies denote the same function?"""
    return match_score(a, b) > 0


def covered(known: set[str], listed: list[str]) -> set[str]:
    """Which known functions does this Desc actually account for?

    Each Desc token is spent on the single function it matches best, so a
    less specific token cannot stand in for a more specific function that the
    same pad also has.
    """
    pairs = sorted(
        ((match_score(g, t), g, t) for g in known for t in listed),
        key=lambda p: (-p[0], p[1], p[2]))
    used_g, used_t = set(), set()
    for score, group, tok in pairs:
        if score == 0 or group in used_g or tok in used_t:
            continue
        used_g.add(group)
        used_t.add(tok)
    return used_g


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
            # the last function of a pin closes SUNXI_PIN too, so allow any
            # run of ) and , before the signal comment
            r"[),]*[ \t]*(?:/\*\s*([^*]*?)\s*\*/)?",
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


def rk_pad_muxes(path: Path) -> dict[str, set[str]]:
    """pad name (GPIO2_D1) -> {function names} from a gpio_extract.py JSON.

    Entry 0 of each ball's mux list is the pad's own GPIO function; the rest
    are the datasheet's Func 2..6.
    """
    import json

    doc = json.loads(path.read_text())
    pads: dict[str, set[str]] = {}
    for ball in doc.get("balls", []):
        m = re.match(r"^(gpio\d_[a-d]\d)", ball.get("reset_function", ""), re.I)
        if not m:
            continue
        funcs = {x["signal_name"].upper() for x in ball.get("mux", [])[1:]}
        if funcs:
            pads[m.group(1).upper()] = funcs
    return pads


def load_authority(soc: str, linux: Path,
                   rk_json: Path | None) -> tuple[dict[str, set[str]] | None, str]:
    if soc == "rk3328":
        if rk_json is None or not rk_json.is_file():
            return None, (f"{soc}: no datasheet pinmux extract "
                          f"(tools/gpio_extract.py --soc rk3328 in the claude repo)")
        return rk_pad_muxes(rk_json), str(rk_json)
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
            # Trailing '*' / '**' are footnote markers on the map's own name
            # column, not part of the pad name, and leaving them attached makes
            # every lookup against the driver miss.
            "name": f[5].rstrip("*"), "pad": f[6], "ref": f[7],
            "desc": f[8].strip(),
        })
    return rows


def desc_tokens(desc: str) -> list[str]:
    return [t for t in re.split(r"[\s/]+", desc) if t and t != "-"]


# --------------------------------------------------------------------- check


def check_board(board: Path, linux: Path, rk_json: Path | None,
                verbose: bool) -> tuple[int, int, int, int]:
    soc = SOC_OF_BOARD.get(board.name)
    gmap = board / "gpio.map"
    if soc is None or not gmap.is_file():
        return 0, 0, 0, 0
    pads, src = load_authority(soc, linux, rk_json)
    if pads is None:
        print(f"UNAUDITED: {board.name}: {src}")
        return 0, 0, 0, 1

    missing = extra = bare = 0
    for row in load_map(gmap):
        if row["chip"] in POWER or row["name"] in POWER:
            continue
        known = pads.get(row["name"])
        listed = desc_tokens(row["desc"])
        if known is None:
            # The driver gives this pad no alternate function at all. Skipping
            # the row here is what let net names (BT_EN, BT_WAKE_HOST) sit in
            # the mux column unnoticed, so report instead: whatever is in Desc
            # is either a datasheet function mainline lacks, or not a function.
            for tok in listed:
                bare += 1
                print(f"NOTE: {board.name} {row['header']}.{row['pin']} "
                      f"{row['name']}: '{tok}' listed on a pad the {soc} "
                      f"driver treats as GPIO-only -- confirm against the "
                      f"datasheet that it is a mux and not a net name")
            continue
        accounted = covered(known, listed)
        for group in sorted(known):
            if group not in accounted:
                missing += 1
                print(f"WARNING: {board.name} {row['header']}.{row['pin']} "
                      f"{row['name']}: Desc omits '{group}' "
                      f"[Desc: {row['desc']}]")
        if verbose:
            for tok in listed:
                if not any(same_function(group, tok) for group in known):
                    extra += 1
                    print(f"NOTE: {board.name} {row['header']}.{row['pin']} "
                          f"{row['name']}: '{tok}' has no {soc} entry "
                          f"(datasheet-only, board-level name, or misspelt)")

    missing += check_datasheet(board, linux, verbose)
    return missing, extra, bare, 0


def load_datasheet(board: Path) -> tuple[dict[str, set[str]] | None, str]:
    """pad -> {function names} from the vendor's own multiplexing tables."""
    path = DATASHEET_JSON.get(board.name)
    if path is None:
        return None, "no datasheet extract mapped for this board"
    if not path.is_file():
        return None, f"{path} not present"
    import json
    data = json.loads(path.read_text())
    return {p: set(f) for p, f in data.get("pads", {}).items()}, str(path)


def check_datasheet(board: Path, linux: Path, verbose: bool) -> int:
    """Report functions the DATASHEET gives a pad that Desc does not list.

    Separate from the driver check because the two authorities disagree in both
    directions: mainline has TSIN_B_CLK on GPIOH_6 where the datasheet shows
    only JTAG_TCK and I2S_AM_CLK, and the datasheet has I2C_SLAVE_SCK_AO where
    Desc had nothing. A pad is only fully described when both are satisfied.
    """
    pads, src = load_datasheet(board)
    if pads is None:
        if verbose:
            print(f"NOTE: {board.name}: datasheet check skipped -- {src}")
        return 0

    # Which pad does the DRIVER put each function on? OCR occasionally slips a
    # row, and a shifted row is invisible to name verification because the name
    # itself is real -- TSIN_B_DIN0 read against GPIOX_11 when it belongs to
    # GPIOX_10. If the driver places a function on some other pad and not this
    # one, the extraction is the likelier suspect, so say so rather than
    # inviting a wrong function into the map.
    soc = SOC_OF_BOARD.get(board.name)
    driver_pads, _ = load_authority(soc, linux, None) if soc else (None, "")
    def driver_owners(name: str) -> set[str]:
        """Pads the driver puts this function on, matched by vocabulary."""
        return {pad for pad, groups in (driver_pads or {}).items()
                if any(same_function(g, name) for g in groups)}

    missing = 0
    for row in load_map(board / "gpio.map"):
        if row["chip"] in POWER or row["name"] in POWER:
            continue
        known = pads.get(row["name"])
        if not known:
            continue
        listed = desc_tokens(row["desc"])
        for group in sorted(known - covered(known, listed)):
            owners = driver_owners(group)
            if owners and row["name"] not in owners:
                print(f"SUSPECT: {board.name} {row['header']}.{row['pin']} "
                      f"{row['name']}: datasheet extract claims '{group}', but "
                      f"the driver puts it on {sorted(owners)} -- likely a "
                      f"shifted OCR row, not a missing function")
                continue
            missing += 1
            print(f"WARNING: {board.name} {row['header']}.{row['pin']} "
                  f"{row['name']}: Desc omits '{group}' (datasheet) "
                  f"[Desc: {row['desc']}]")
    return missing


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", help="single board directory name")
    ap.add_argument("--linux", help="kernel source tree (pinctrl drivers)")
    ap.add_argument("--rk-pinmux",
                    help="RK3328 gpio_pinmux.json from tools/gpio_extract.py")
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

    rk_json = (Path(args.rk_pinmux) if args.rk_pinmux
               else next((p for p in DEFAULT_RK_PINMUX if p.is_file()), None))

    boards = ([LC / args.board] if args.board
              else sorted(p for p in LC.iterdir() if p.is_dir()))
    missing = extra = bare = unaudited = 0
    for board in boards:
        m, e, b, u = check_board(board, linux, rk_json, args.verbose)
        missing += m
        extra += e
        bare += b
        unaudited += u

    print(f"check-pinmux: {missing} omitted function(s), {extra} unmatched Desc "
          f"token(s), {bare} token(s) on GPIO-only pads, {unaudited} unaudited "
          f"SoC(s) [authority: {linux}]")
    return 1 if (args.strict and missing) else 0


if __name__ == "__main__":
    sys.exit(main())
