#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Insert lc,provides / lc,requires / lc,revokes into overlay .dts roots.

Idempotent: skips files that already declare any of the three properties.
Does not rewrite existing annotations.

Token grammar (R15 / overlay-dependencies.md):
  bus:<label>           — bus enable (provider)
  pwm_<chip>.chN@<pin>  — exclusive PWM channel on header pin
  label:<name>          — created node (e.g. fan0)
  pin:<Header>-<N>      — exclusive header pin claim
  alias:<key>           — /aliases key (exclusive among writers)
  i2c:<bus>@0xNN        — exclusive I2C address on bus
  excl:<resource>       — exclusive non-pin resource (usb.dr_mode, …)
  display:<name>        — display resource (for revokes)

Usage:
  python3 scripts/annotate-resources.py              # aml-s905x-cc defaults
  python3 scripts/annotate-resources.py --board X
  python3 scripts/annotate-resources.py --dry-run
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LC = ROOT / "libre-computer"

# board -> basename -> {provides, requires, revokes}
# Only real (non-symlink) files under that board's dt/ are written; v2 boards
# that symlink dt/ pick up aml-s905x-cc annotations automatically.
BOARD_ANNOTATIONS: dict[str, dict[str, dict[str, list[str]]]] = {
    "aml-s905x-cc": {
        # --- buses ---
        "i2c-ao": {
            "provides": ["bus:i2c_AO"],
        },
        "i2c-b": {
            "provides": ["bus:i2c_B"],
        },
        # --- I2C devices (address exclusivity) ---
        "i2c-ao-ds3231": {
            "requires": ["bus:i2c_AO"],
            "provides": ["i2c:i2c_AO@0x68"],
        },
        "i2c-ao-pcf8523": {
            "requires": ["bus:i2c_AO"],
            "provides": ["i2c:i2c_AO@0x68"],
        },
        "i2c-ao-rv3028": {
            "requires": ["bus:i2c_AO"],
            "provides": ["i2c:i2c_AO@0x52"],
        },
        "i2c-ao-at24c32": {
            "requires": ["bus:i2c_AO"],
            "provides": ["i2c:i2c_AO@0x50"],
        },
        "i2c-ao-ssd1306-128x64": {
            "requires": ["bus:i2c_AO"],
            "provides": ["i2c:i2c_AO@0x3c"],
        },
        "i2c-ao-rpi-sense": {
            "requires": ["bus:i2c_AO"],
            "provides": ["i2c:i2c_AO@0x46"],
        },
        # emc2301 already annotated by hand — skip
        # --- PWM providers (migration step 1) ---
        "pwm-a": {
            "provides": ["pwm_ab.ch0@7J1-33"],
        },
        "pwm-e": {
            "provides": ["pwm_ef.ch0@7J1-32"],
        },
        "pwm-f": {
            "provides": ["pwm_ef.ch1@7J1-35"],
        },
        "pwm-ef": {
            "provides": ["pwm_ef.ch0@7J1-32", "pwm_ef.ch1@7J1-35"],
        },
        "pwm-ao-a": {
            "provides": ["pwm_AO_ab.ch0@7J1-11"],
            "revokes": ["cec_AO"],
        },
        "pwm-ao-b-6": {
            "provides": ["pwm_AO_ab.ch1@7J1-12"],
        },
        "pwm-ao-b-9": {
            "provides": ["pwm_AO_ab.ch1@7J1-13"],
        },
        "pwm-ao-6": {
            "provides": ["pwm_AO_ab.ch0@7J1-11", "pwm_AO_ab.ch1@7J1-12"],
            "revokes": ["cec_AO"],
        },
        "pwm-ao-9": {
            "provides": ["pwm_AO_ab.ch0@7J1-11", "pwm_AO_ab.ch1@7J1-13"],
            "revokes": ["cec_AO"],
        },
        # --- fans: create label:fan0, need PWM + tach pin ---
        "pwm-a-fan": {
            "requires": ["pwm_ab.ch0@7J1-33"],
            "provides": ["label:fan0", "pin:9J1-2"],
        },
        "pwm-a-fan-auto": {
            "requires": ["label:fan0"],
        },
        "pwm-ao-a-fan": {
            "requires": ["pwm_AO_ab.ch0@7J1-11"],
            "provides": ["label:fan0", "pin:9J1-2"],
        },
        "pwm-ao-b-6-fan": {
            "requires": ["pwm_AO_ab.ch1@7J1-12"],
            "provides": ["label:fan0", "pin:9J1-2"],
        },
        "pwm-ao-b-9-fan": {
            "requires": ["pwm_AO_ab.ch1@7J1-13"],
            "provides": ["label:fan0", "pin:9J1-2"],
        },
        "pwm-e-fan": {
            "requires": ["pwm_ef.ch0@7J1-32"],
            "provides": ["label:fan0", "pin:9J1-2"],
        },
        "pwm-f-fan": {
            "requires": ["pwm_ef.ch1@7J1-35"],
            "provides": ["label:fan0", "pin:9J1-2"],
        },
        # --- pinless / alias exclusives ---
        "usb-device-mode": {
            "provides": ["excl:usb.dr_mode"],
        },
        "cvbs-disable": {
            "revokes": ["display:cvbs"],
            "provides": ["excl:display.cvbs"],
        },
        # alias:<key> is NOT hand-coded — ldto derives from target-path="/aliases"
        "uart-a": {
            "provides": ["bus:uart_A"],
        },
        "uart-a-clk81": {
            "provides": ["bus:uart_A"],
        },
        "uart-a-rts-cts": {
            "provides": ["bus:uart_A"],
        },
        "uart-a-rts-cts-clk81": {
            "provides": ["bus:uart_A"],
        },
        "sdio": {
            # serial1 exclusivity: derived from /aliases fragment (not hand-coded).
            # Do NOT claim pwm_ef.ch0 here — false-conflicts with pwm-e.
            "provides": ["bus:uart_C"],
        },
        "spdif": {
            # fans claim 9J1.2 (GPIOH_4) for tach; spdif uses same pad family
            "provides": ["pin:9J1-2"],
        },
        "uart-ao-b": {
            "provides": ["bus:uart_AO_B"],
            # shares pins with i2c-ao on some mux configs — pin gate covers that
        },
    },
    # Separate copies on s805x-ac (not symlinked from s905x)
    "aml-s805x-ac": {
        "usb-device-mode": {
            "provides": ["excl:usb.dr_mode"],
        },
        "uart-a": {
            "provides": ["bus:uart_A"],
        },
        "uart-a-clk81": {
            "provides": ["bus:uart_A"],
        },
        # sdio / sdio-rtl8822cs: no hand lc,provides — alias keys derived in ldto
    },
}


def format_lc_block(
    provides: list[str] | None = None,
    requires: list[str] | None = None,
    revokes: list[str] | None = None,
) -> str:
    lines: list[str] = []
    lines.append("\t/* resource-set tokens for deps/conflicts (see overlay-dependencies.md) */")
    if provides:
        vals = ", ".join(f'"{t}"' for t in provides)
        lines.append(f"\tlc,provides = {vals};")
    if requires:
        vals = ", ".join(f'"{t}"' for t in requires)
        lines.append(f"\tlc,requires = {vals};")
    if revokes:
        vals = ", ".join(f'"{t}"' for t in revokes)
        lines.append(f"\tlc,revokes = {vals};")
    lines.append("")
    return "\n".join(lines)


def already_annotated(text: str) -> bool:
    return bool(re.search(r"\blc,(provides|requires|revokes)\s*=", text))


def insert_after_compatible(text: str, block: str) -> str | None:
    """Insert block after the root compatible = ...; property."""
    # Match root-level compatible (first in file after / {)
    m = re.search(
        r"(compatible\s*=\s*(?:\"[^\"]*\"\s*,\s*)*\"[^\"]*\"\s*;)",
        text,
        re.MULTILINE,
    )
    if not m:
        return None
    end = m.end()
    # avoid double insert
    rest = text[end : end + 200]
    if re.search(r"\blc,(provides|requires|revokes)\s*=", rest):
        return text
    return text[:end] + "\n\n" + block + text[end:]


def annotate_file(path: Path, meta: dict[str, list[str]], dry_run: bool) -> str:
    if path.is_symlink():
        return "skip-symlink"
    text = path.read_text(errors="replace")
    if already_annotated(text):
        return "skip-exists"
    block = format_lc_block(
        provides=meta.get("provides"),
        requires=meta.get("requires"),
        revokes=meta.get("revokes"),
    )
    new = insert_after_compatible(text, block)
    if new is None:
        return "skip-no-compatible"
    if new == text:
        return "skip-unchanged"
    if not dry_run:
        path.write_text(new)
    return "ok"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--board", action="append", help="Board dir name (default: all in table)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    boards = args.board or list(BOARD_ANNOTATIONS.keys())
    counts: dict[str, int] = {}
    for board in boards:
        table = BOARD_ANNOTATIONS.get(board)
        if not table:
            print(f"WARNING: no annotation table for {board}", file=sys.stderr)
            continue
        dt = LC / board / "dt"
        if not dt.is_dir():
            print(f"WARNING: missing {dt}", file=sys.stderr)
            continue
        for base, meta in sorted(table.items()):
            path = dt / f"{base}.dts"
            if not path.exists():
                print(f"MISSING {path}")
                counts["missing"] = counts.get("missing", 0) + 1
                continue
            status = annotate_file(path, meta, args.dry_run)
            counts[status] = counts.get(status, 0) + 1
            print(f"{status:18} {board}/dt/{base}.dts")
    print("summary:", counts, file=sys.stderr)
    return 0 if counts.get("missing", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
