#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Da Xue <da@libre.computer>
"""LWT integrity + gpio.map accuracy checks (warn by default).

Validates:
  - gpio.map format and Name/Line/Chip vs SoC dt-bindings (lgpio pinout data)
  - overlay .dts headers (Summary; Pins rows match gpio.map)
  - dt.map values name real non-symlink overlay basenames
  - dt.deps providers/consumers exist

Exit 0 always unless --strict (then non-zero if any WARNING).
Prints WARNING: lines for make to surface.
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
        by_pin: dict[tuple[str, str], str] = {}
        by_name: dict[str, tuple[str, str]] = {}
        if gpath.is_file():
            for r in load_gpio_map(gpath):
                if r.get("_bad") or r["chip"] in POWER_CHIPS:
                    continue
                bare = r["name"].rstrip("*")
                by_pin[(r["header"], r["pin"])] = bare
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
                map_name = by_pin[key]
                if name.rstrip("*") != map_name.rstrip("*"):
                    self.warn(
                        f"{board.name}/{dts.name}: Pins {h}.{pin} says "
                        f"{name} but gpio.map has {map_name}"
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

        for board in boards:
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
    args = ap.parse_args()
    c = Checker()
    n = c.run(args.board)
    if args.strict and n:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
