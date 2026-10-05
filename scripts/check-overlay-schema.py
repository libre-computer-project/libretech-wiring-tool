#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Schema errors each overlay introduces, judged against the kernel's bindings.

dt-validate on the base DTB with the overlay's dt.deps providers applied, and
again with the overlay itself; the errors only the second run has are the
overlay's. A base board's own schema debt is not reported, so the output is
what an overlay change could fix.

    scripts/check-overlay-schema.py --schema processed-schema.json [--board B]
    scripts/check-overlay-schema.py --self-test

The processed schema is dt-mk-schema's output over the kernel tree's
Documentation/devicetree/bindings (the tree that built the base DTBs):

    dt-mk-schema -j <linux>/Documentation/devicetree/bindings > processed-schema.json

Several real defects first showed up here, such as a misspelt pinctrl-o, a
pinctrl state named "default" twice, and a mcp3008 without vref-supply. Much
of what it reports is binding hygiene, though (legacy fbtft properties on
tinydrm panels, node names), so it reports rather than gates.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fdt", ROOT / "scripts/check-fdtoverlay.py")
fdt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fdt)


def normalize(output: str) -> set[str]:
    """dt-validate output -> comparable error lines (file prefix and the
    'from schema $id' trailers dropped; overlay bookkeeping nodes ignored)."""
    out = set()
    for line in output.splitlines():
        line = re.sub(r"^\S+\.dtb: ", "", line.strip())
        line = re.sub(r"\s+from schema \$id:.*$", "", line)
        if line and not line.startswith(("Warning", "from schema")) and "/__" not in line:
            out.add(line)
    return out


def introduced(before: set[str], after: set[str]) -> list[str]:
    return sorted(after - before)


def self_test() -> int:
    base = ("/x/base.dtb: serial@84c0 (amlogic,meson-gx-uart): 'foo' is a required property\n"
            "\tfrom schema $id: http://devicetree.org/schemas/serial/amlogic,meson-uart.yaml\n")
    after = base + ("/x/a.dtb: pps-gpio (pps-gpio): 'pinctrl-0' is a dependency of "
                    "'pinctrl-names'\n")
    cases = [
        ("base debt is not the overlay's", introduced(normalize(base), normalize(base)), []),
        ("a new error is reported once, without file or schema trailer",
         introduced(normalize(base), normalize(after)),
         ["pps-gpio (pps-gpio): 'pinctrl-0' is a dependency of 'pinctrl-names'"]),
    ]
    fails = 0
    for what, got, want in cases:
        if got != want:
            fails += 1
            print(f"SELFTEST FAIL: {what}: {got!r}")
    print(f"check-overlay-schema --self-test: {len(cases) - fails}/{len(cases)} cases pass")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--schema", help="dt-mk-schema processed-schema.json")
    ap.add_argument("--board")
    ap.add_argument("--dtb-dir", action="append", default=[])
    ap.add_argument("--dt-validate", default=shutil.which("dt-validate") or
                    os.path.expanduser("~/.local/bin/dt-validate"))
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if not a.schema or not Path(a.dt_validate).is_file():
        print("SKIP: need --schema and dt-validate (pip dtschema)")
        return 0
    cache: dict[Path, set[str]] = {}

    def errors(dtb: Path) -> set[str]:
        if dtb not in cache:
            r = subprocess.run([a.dt_validate, "-s", a.schema, str(dtb)],
                               capture_output=True, text=True, timeout=600)
            cache[dtb] = normalize(r.stdout + r.stderr)
        return cache[dtb]

    roots = [Path(d) for d in a.dtb_dir] + fdt.home_paths()
    checked = new = 0
    for board in fdt.board_dirs(a.board):
        if (board / "dt").is_symlink():
            continue
        base = fdt.resolve_base(fdt.parse_dt_config(board / "dt.config") or "", roots)
        if base is None:
            print(f"SKIP: {board.name}: no base DTB")
            continue
        bc = fdt.root_compatible(base)
        edges = fdt.load_deps(board / "dt.deps")
        with tempfile.TemporaryDirectory() as tmp:
            for stem, dtbo in fdt.unique_overlays(board / "dt"):
                if not dtbo.is_file() or not fdt.claims_board(fdt.root_compatible(dtbo), bc):
                    continue
                chain = [board / "dt" / f"{c}.dtbo" for c in fdt.expand_chain(stem, edges)]
                before = base
                if len(chain) > 1:
                    before = Path(tmp) / f"{stem}.before.dtb"
                    if fdt.run_fdtoverlay("fdtoverlay", base, chain[:-1], before)[0]:
                        continue
                after = Path(tmp) / f"{stem}.dtb"
                if fdt.run_fdtoverlay("fdtoverlay", base, chain, after)[0]:
                    continue
                checked += 1
                for e in introduced(errors(before), errors(after)):
                    new += 1
                    print(f"SCHEMA: {board.name}/{stem}: {e}")
    print(f"check-overlay-schema: {checked} overlays validated, {new} error(s) introduced")
    return 0


if __name__ == "__main__":
    sys.exit(main())
