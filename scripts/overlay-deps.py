#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Resolve LWT overlay dependencies for a board dt/ directory.

Reads each .dts (follows content; records every basename including aliases).
Builds a provider map from:
  - explicit root properties: lc,provides / lc,provides-n / lc,requires / lc,requires-n
  - structural inference (SPI/I2C bus enable vs device-only consumers)

Writes a dt.deps file:
  # consumer<TAB>provider [provider...]
  spi-cc1-2cs-mhs3528	spi-cc1-2cs

Also prints the same edges on stdout when --print is set.

Used by: Makefile (generate dt.deps), LBS FIT packaging, ldto enable/merge.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


def read_text(path: Path) -> str:
    return path.read_text(errors="replace")


def parse_lc_strings(text: str, prop: str) -> list[str]:
    """Parse lc,prop = "a", "b"; from overlay source."""
    # allow multi-line
    m = re.search(rf'{re.escape(prop)}\s*=\s*([^;]+);', text)
    if not m:
        return []
    return re.findall(r'"([^"]+)"', m.group(1))


def parse_lc_u32(text: str, prop: str) -> int | None:
    m = re.search(rf'{re.escape(prop)}\s*=\s*<(\d+)>', text)
    return int(m.group(1)) if m else None


def _extract_braced(text: str, open_idx: int) -> tuple[str, int]:
    """Given index of '{', return (inside, index_after_closing_brace)."""
    assert text[open_idx] == "{"
    depth = 0
    i = open_idx
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1 : i], i + 1
        i += 1
    return text[open_idx + 1 :], len(text)


def fragment_bodies(text: str) -> list[tuple[str, str]]:
    """Return list of (target_label_or_path, overlay_body)."""
    out: list[tuple[str, str]] = []
    for m in re.finditer(r"fragment@\d+\s*\{", text):
        body, _ = _extract_braced(text, m.end() - 1)
        tm = re.search(r"target\s*=\s*<&([A-Za-z0-9_]+)\s*>", body)
        if tm:
            target = tm.group(1)
        else:
            pm = re.search(r'target-path\s*=\s*"([^"]+)"', body)
            target = pm.group(1) if pm else ""
        om = re.search(r"__overlay__\s*\{", body)
        if om:
            ob, _ = _extract_braced(body, om.end() - 1)
        else:
            ob = body
        out.append((target, ob))
    return out


def overlay_root_status_okay(overlay_body: str) -> bool:
    """status=okay at overlay root (not only inside child nodes)."""
    depth = 0
    top: list[str] = []
    for c in overlay_body:
        if c == "{":
            depth += 1
        elif c == "}":
            depth = max(0, depth - 1)
        elif depth == 0:
            top.append(c)
    return bool(re.search(r'status\s*=\s*"okay"', "".join(top)))


def has_device_children(overlay_body: str) -> bool:
    if re.search(
        r"(display|touchscreen|spidev|ethernet|can|adc|sensor|eeprom|rtc)@\d+",
        overlay_body,
    ):
        return True
    if re.search(
        r'compatible\s*=\s*"[^"]*(spidev|ili9486|ili9341|ads7846|mcp2515|'
        r"enc28j60|ssd1306|st7789|st7735|mcp3008|at24|ds3231|pcf8523|"
        r'rv3028|emc2301|waveshare)',
        overlay_body,
    ):
        return True
    return False


def max_reg(overlay_body: str) -> int:
    regs = [int(x) for x in re.findall(r"reg\s*=\s*<(\d+)>", overlay_body)]
    return max(regs) if regs else 0


def cs_count_from_name(name: str) -> int | None:
    n = name.lower()
    if re.search(r"2cs|cs1|dual", n):
        return 2
    if re.search(r"1cs|[^0-9]1cs", n) or re.search(r"-1cs", n):
        return 1
    return None


def is_bus_label(label: str) -> bool:
    l = label.lower()
    return bool(
        re.match(r"^(spicc\d*|spi\d*|i2c[_\w]*|i2c\d*)$", l)
        or l.startswith("spicc")
        or l.startswith("spi")
        and "gpio" not in l
        or l.startswith("i2c")
    )


def analyze_source(name: str, text: str) -> dict:
    """Return {provides: [(cap, n)], requires: [(cap, n)]}."""
    provides: list[tuple[str, int]] = []
    requires: list[tuple[str, int]] = []

    expl_p = parse_lc_strings(text, "lc,provides")
    expl_r = parse_lc_strings(text, "lc,requires")
    pn = parse_lc_u32(text, "lc,provides-n")
    rn = parse_lc_u32(text, "lc,requires-n")

    if expl_p:
        n = pn if pn is not None else (cs_count_from_name(name) or 1)
        for cap in expl_p:
            provides.append((cap, n))
    if expl_r:
        n = rn if rn is not None else (cs_count_from_name(name) or 1)
        for cap in expl_r:
            requires.append((cap, n))

    if expl_p or expl_r:
        return {"provides": provides, "requires": requires}

    # Structural inference
    for target, ob in fragment_bodies(text):
        if not target or target.startswith("/"):
            continue
        if not is_bus_label(target):
            continue
        cap = f"bus:{target}"
        root_ok = overlay_root_status_okay(ob)
        kids = has_device_children(ob)
        if root_ok and not kids:
            n = cs_count_from_name(name) or 1
            # count cs-gpios cells roughly
            csg = re.search(r"cs-gpios\s*=\s*<([^>]+)>", ob)
            if csg:
                # each phandle+flags is typically 3 cells; count phandles as &ref
                n = max(n, len(re.findall(r"&", csg.group(1))) or n)
            provides.append((cap, n))
        elif kids and not root_ok:
            n = max(max_reg(ob) + 1, cs_count_from_name(name) or 1)
            requires.append((cap, n))
        elif kids and root_ok:
            # combo bus+device: provides the bus, no external require
            n = max(max_reg(ob) + 1, cs_count_from_name(name) or 1)
            provides.append((cap, n))

    return {"provides": provides, "requires": requires}


_PURE_BUS = re.compile(
    r"^(spi-cc\d*-[12]cs|spicc(-cs1)?|spi-[01]-[12]cs|spi-gpio-[12]cs|"
    r"spigpio|i2c-[a-z0-9-]+|i2c_ao|i2c_ee.*)$",
    re.I,
)
_COMBO = re.compile(
    r"spidev|ili|mhs|mpi|pitft|st7|ssd|enc28|mcp|ads|display|fan|"
    r"at24|ds3231|pcf|rv3028|emc2301|sense|ov5647|waveshare|dn9488",
    re.I,
)


def provider_score(
    name: str, provides_n: int, need_n: int, *, is_alias: bool = False
) -> tuple:
    """Higher is better. Prefer pure bus overlays with enough CS, exact match."""
    enough = 1 if provides_n >= need_n else 0
    pure = 1 if _PURE_BUS.match(name) else 0
    combo = 0 if _COMBO.search(name) else 1
    hw = 0 if re.search(r"gpio|spigpio", name, re.I) else 1
    canon = 0 if is_alias else 1
    tight = -abs(provides_n - need_n)
    return (enough, pure, combo, hw, canon, tight, name)


def resolve_board(dt_dir: Path) -> dict[str, list[str]]:
    """Map consumer basename (no .dts) -> [provider basenames]."""
    # Collect by real path content analysis; attach all names (aliases)
    entries: list[dict] = []  # name, provides, requires, is_alias

    for dts in sorted(dt_dir.glob("*.dts")):
        name = dts.stem
        real = Path(os.path.realpath(dts))
        text = read_text(real)
        # Alias names: re-score CS heuristics from the alias basename
        info = analyze_source(name, text)
        entries.append(
            {
                "name": name,
                "provides": info["provides"],
                "requires": info["requires"],
                "is_alias": dts.is_symlink(),
            }
        )

    # Build capability -> list of (name, n, is_alias)
    cap_providers: dict[str, list[tuple[str, int, bool]]] = {}
    for e in entries:
        for cap, n in e["provides"]:
            cap_providers.setdefault(cap, []).append(
                (e["name"], n, e["is_alias"])
            )

    edges: dict[str, list[str]] = {}
    for e in entries:
        if not e["requires"]:
            continue
        needs: list[str] = []
        for cap, need_n in e["requires"]:
            cands = [
                (n, pn, al)
                for n, pn, al in cap_providers.get(cap, [])
                if n != e["name"]
            ]
            if not cands:
                continue
            enough = [(n, pn, al) for n, pn, al in cands if pn >= need_n]
            pool = enough or cands
            pool.sort(
                key=lambda t: provider_score(
                    t[0], t[1], need_n, is_alias=t[2]
                ),
                reverse=True,
            )
            best = pool[0][0]
            if best not in needs:
                needs.append(best)
        if needs:
            edges[e["name"]] = needs
    return edges


def write_deps(edges: dict[str, list[str]], out: Path) -> None:
    # REUSE-IgnoreStart
    spdx_line = "# SPDX-License-Identifier: MIT"
    # REUSE-IgnoreEnd
    lines = [
        spdx_line,
        "# Auto-generated by scripts/overlay-deps.py - do not edit.",
        "# consumer<TAB>provider [provider...]",
        "# Applied automatically by ldto enable/merge and U-Boot nor-config",
        "# when the provider is not already in the request list.",
        "",
    ]
    for consumer in sorted(edges):
        lines.append(f"{consumer}\t{' '.join(edges[consumer])}")
    out.write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "dt_dir",
        type=Path,
        help="Board dt/ directory (e.g. libre-computer/aml-s905d3-cc/dt)",
    )
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write dt.deps here (default: <board>/dt.deps next to dt/)",
    )
    ap.add_argument("--print", action="store_true", help="Print edges to stdout")
    args = ap.parse_args()

    dt_dir = args.dt_dir
    if not dt_dir.is_dir():
        print(f"error: not a directory: {dt_dir}", file=sys.stderr)
        return 1

    edges = resolve_board(dt_dir)
    out = args.output
    if out is None:
        out = dt_dir.parent / "dt.deps"
    write_deps(edges, out)

    print(f"# {dt_dir}: {len(edges)} consumers with auto-deps -> {out}", file=sys.stderr)
    if args.print:
        for c, ps in sorted(edges.items()):
            print(f"{c}\t{' '.join(ps)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
