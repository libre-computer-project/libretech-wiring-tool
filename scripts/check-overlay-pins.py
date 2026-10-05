#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Da Xue <da@libre.computer>
"""Check what each overlay actually muxes against what its header says.

check-lwt compares an overlay's `Pins:` comment with gpio.map. Nothing
compared the comment with the overlay BODY, so an overlay could document one
set of header pins and claim another. This applies each overlay (with its
dt.deps providers) to the board's base DTB, and for every node the overlay
touches resolves

  pinctrl-N   -> pinctrl group -> SoC pads
                 (meson "groups" via the pinctrl driver's <group>_pins[];
                  sunxi "pins"; rockchip "rockchip,pins" bank/pin cells)
  *-gpios     -> gpio controller + line -> SoC pad

then keeps the pads that sit on a header (gpio.map) and reports

  undocumented  a header pad the overlay itself muxes, missing from Pins:
  stale         a Pins: pad nothing in the overlay chain muxes
  no-such-pad   a pad the overlay uses that the SoC package does not bond out
                (an overlay copied from a sibling board: S805X has no GPIOX_17)
  collide       a pad the overlay newly muxes that an enabled node it does not
                touch already holds (pinctrl is not strict here: the loser just
                stops working)

Pads that are not on a header (on-board WiFi, regulators) are ignored. It
prints the overlays it could resolve beside the verdict.

    scripts/check-overlay-pins.py [--board B] [--linux PATH] [--dtb-dir DIR]
    scripts/check-overlay-pins.py --self-test
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LC = ROOT / "libre-computer"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fdt = _load("check-fdtoverlay")
lwt = _load("check-lwt")
pinmux = _load("check-pinmux")

# ------------------------------------------------------------------ tree


def parse_dts(text: str) -> dict[str, dict[str, str]]:
    """dtc -O dts output -> {node path: {prop: raw value}} (one prop a line)."""
    nodes: dict[str, dict[str, str]] = {}
    stack: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"^(?:[\w,-]+:\s*)*([\w,.@+-]+|/) \{$", s)
        if m:
            stack.append(m.group(1))
            nodes.setdefault(_path(stack), {})
            continue
        if s == "};":
            if stack:
                stack.pop()
            continue
        m = re.match(r"^([\w,.#?+-]+)(?: = (.*))?;$", s)
        if m and stack:
            nodes[_path(stack)][m.group(1)] = m.group(2) or ""
    return nodes


def _path(stack: list[str]) -> str:
    return "/" + "/".join(s for s in stack if s != "/")


def cells(raw: str) -> list[int]:
    out = []
    for grp in re.findall(r"<([^>]*)>", raw):
        out += [int(c, 0) for c in grp.split()]
    return out


def strings(raw: str) -> list[str]:
    return re.findall(r'"([^"]*)"', raw)


class Tree:
    def __init__(self, nodes: dict[str, dict[str, str]]):
        self.nodes = nodes
        self.by_phandle = {}
        for path, props in nodes.items():
            if "phandle" in props:
                self.by_phandle[cells(props["phandle"])[0]] = path
        syms = nodes.get("/__symbols__", {})
        self.label_of = {strings(v)[0]: k for k, v in syms.items() if strings(v)}
        self.symbols = {k: strings(v)[0] for k, v in syms.items() if strings(v)}

    def children(self, path: str) -> list[str]:
        pre = path.rstrip("/") + "/"
        return [p for p in self.nodes if p.startswith(pre)]

    def parent(self, path: str) -> str:
        return path.rsplit("/", 1)[0] or "/"


# ------------------------------------------------------------------ pads


def meson_bindings(header: Path) -> tuple[dict[int, str], dict[int, str]]:
    """(AO line -> pad, EE line -> pad) from include/dt-bindings meson-*-gpio.h."""
    ao, ee = {}, {}
    for name, num in re.findall(r"#define\s+(GPIO\w+)\s+(\d+)", header.read_text()):
        pad = "TEST_N" if name == "GPIO_TEST_N" else name
        (ao if name.startswith("GPIOAO_") or name == "GPIO_TEST_N" else ee)[int(num)] = pad
    return ao, ee


def meson_irqids(header: Path) -> dict[int, str]:
    """gpio-intc hwirq -> pad, from amlogic,meson-*-gpio-intc.h."""
    return {int(num): name for name, num in re.findall(
        r"#define\s+IRQID_(\w+)\s+(\d+)", header.read_text())}


class Resolver:
    def __init__(self, family: str, tree: Tree, groups: dict[str, list[str]],
                 bindings: tuple[dict[int, str], dict[int, str]] | None,
                 irqids: dict[int, str] | None = None):
        self.family, self.t, self.groups, self.bind = family, tree, groups, bindings
        self.irqids = irqids or {}

    def irq_pad(self, ctrl: str, args: list[int]) -> str | None:
        """A GPIO line used as an interrupt: rockchip gpioN <line flags>,
        sunxi pio <bank pin flags>, meson gpio-intc <hwirq flags>."""
        props = self.t.nodes.get(ctrl, {})
        compat = " ".join(strings(props.get("compatible", "")))
        if "gpio-intc" in compat:
            return self.irqids.get(args[0])
        if "gpio-controller" in props and self.family in ("rockchip", "sunxi"):
            return self.gpio_pad(ctrl, args)
        return None

    def irq_prop_pads(self, path: str, props: dict[str, str]) -> set[str]:
        pads: set[str] = set()
        if "interrupts-extended" in props:
            c, i = cells(props["interrupts-extended"]), 0
            while i < len(c):
                ctrl = self.t.by_phandle.get(c[i])
                if ctrl is None:
                    break
                n = cells(self.t.nodes[ctrl].get("#interrupt-cells", "<2>"))[0]
                pad = self.irq_pad(ctrl, c[i + 1:i + 1 + n])
                if pad:
                    pads.add(pad)
                i += 1 + n
        elif "interrupts" in props:
            p, parent = path, None
            while parent is None:
                parent = self.t.nodes.get(p, {}).get("interrupt-parent")
                if p == "/":
                    break
                p = self.t.parent(p)
            ctrl = self.t.by_phandle.get(cells(parent)[0]) if parent else None
            if ctrl:
                n = cells(self.t.nodes[ctrl].get("#interrupt-cells", "<2>"))[0]
                c = cells(props["interrupts"])
                for i in range(0, len(c) - n + 1, n):
                    pad = self.irq_pad(ctrl, c[i:i + n])
                    if pad:
                        pads.add(pad)
        return pads

    def pinctrl_pads(self, path: str) -> set[str]:
        pads: set[str] = set()
        for p in [path] + self.t.children(path):
            props = self.t.nodes.get(p, {})
            if "groups" in props:
                for g in strings(props["groups"]):
                    pads.update(self.groups.get(g, []))
            if "pins" in props:
                pads.update(strings(props["pins"]))
            if "rockchip,pins" in props:
                c = cells(props["rockchip,pins"])
                for i in range(0, len(c) - 3, 4):
                    pads.add(f"GPIO{c[i]}_{'ABCD'[c[i + 1] // 8]}{c[i + 1] % 8}")
        return pads

    def gpio_pad(self, ctrl: str, args: list[int]) -> str | None:
        props = self.t.nodes.get(ctrl, {})
        compat = " ".join(strings(props.get("compatible", "")))
        if self.family == "rockchip":
            label = self.t.label_of.get(ctrl, "")
            m = re.match(r"gpio(\d)$", label)
            if m:
                return f"GPIO{m.group(1)}_{'ABCD'[args[0] // 8]}{args[0] % 8}"
            return None
        if self.family == "sunxi":
            first = "L" if "-r-pinctrl" in compat else "A"
            return f"P{chr(ord(first) + args[0])}{args[1]}"
        if self.family == "meson" and self.bind:
            parent = self.t.nodes.get(self.t.parent(ctrl), {})
            pc = compat + " " + " ".join(strings(parent.get("compatible", "")))
            table = self.bind[0] if "aobus" in pc else self.bind[1]
            return table.get(args[0])
        return None

    def gpio_prop_pads(self, raw: str) -> set[str]:
        c = cells(raw)
        pads, i = set(), 0
        while i < len(c):
            if c[i] == 0:
                # a null phandle is a one-cell placeholder: `cs-gpios = <0>,
                # <&gpio GPIOA_9 ...>` keeps CS0 native and puts CS1 on a GPIO
                i += 1
                continue
            ctrl = self.t.by_phandle.get(c[i])
            if ctrl is None:
                break
            n = cells(self.t.nodes[ctrl].get("#gpio-cells", "<2>"))[0]
            pad = self.gpio_pad(ctrl, c[i + 1:i + 1 + n])
            if pad:
                pads.add(pad)
            i += 1 + n
        return pads

    def enabled(self, path: str) -> bool:
        """Neither the node nor any ancestor is disabled: a device under a
        disabled bus or controller never probes, so it muxes nothing."""
        p = path
        while True:
            if self.t.nodes.get(p, {}).get("status", '"okay"') == '"disabled"':
                return False
            if p == "/":
                return True
            p = self.t.parent(p)

    def node_pads(self, path: str) -> set[str]:
        pads: set[str] = set()
        props = self.t.nodes.get(path, {})
        if not self.enabled(path):
            return pads
        # The pinctrl core applies a state by NAME at probe ("default", or
        # "init" then "default"), taking the first pinctrl-N of that name. A
        # second "default", or a node with no pinctrl-names, applies nothing:
        # roc-rk3328-cc spi-0-2cs carried CS1's mux in such a pinctrl-1.
        names = strings(props.get("pinctrl-names", ""))
        live = {names.index(n) for n in ("default", "init") if n in names}
        for k, v in props.items():
            m = re.match(r"pinctrl-(\d+)$", k)
            if m and int(m.group(1)) in live:
                for ph in cells(v):
                    pc = self.t.by_phandle.get(ph)
                    if pc:
                        pads |= self.pinctrl_pads(pc)
            elif re.match(r"(.*-)?gpios?$", k) and k != "gpio-controller":
                pads |= self.gpio_prop_pads(v)
        return pads | self.irq_prop_pads(path, props)


def collisions(res: "Resolver", mine: list[str], own: set[str]) -> list[tuple[str, list]]:
    """Enabled nodes the overlay does not touch that hold a pad it newly
    muxes. pinctrl does not refuse this on Amlogic or Rockchip (not strict),
    so the loser just stops working: a gpio-leds LED whose pin became PWM_D."""
    out = []
    if not own:
        return out
    for path in res.t.nodes:
        if path.startswith(("/__", "/aliases", "/chosen")):
            continue
        if any(path == t or path.startswith(t.rstrip("/") + "/") for t in mine):
            continue
        hit = sorted(res.node_pads(path) & own)
        if hit:
            out.append((path, hit))
    return out


def overwrites(dtbo_tree: Tree, before: Tree) -> list[tuple[str, list[str]]]:
    """Nodes an overlay writes BELOW a fragment's target that already exist
    with different values for the same properties: the overlay meant to add a
    node and instead rewrote a live one. Adding properties or children to an
    existing node (a dai-link into the sound card, a pull-up into a pin group)
    is not reported. The defect behind it: fan-auto overlays named their
    cooling maps map1/map2, which the base DTB also has, and replaced the
    CPUs' hot-trip throttling (A311D) and a passive-trip map (S905X) with the
    fan."""
    out = []
    fixups = dtbo_tree.nodes.get("/__fixups__", {})
    for frag, props in dtbo_tree.nodes.items():
        if not re.match(r"^/fragment@\d+$", frag):
            continue
        if "target-path" in props:
            target = strings(props["target-path"])[0]
        else:
            target = next((before.symbols.get(l) for l, refs in fixups.items()
                           if f"{frag}:target:0" in strings(refs)), None)
        if not target:
            continue
        ov = f"{frag}/__overlay__"
        for p in dtbo_tree.children(ov):
            dest = target.rstrip("/") + p[len(ov):]
            old = before.nodes.get(dest)
            if old is None:
                continue
            new = dtbo_tree.nodes[p]
            changed = sorted(k for k in new if k != "phandle" and k in old and old[k] != new[k])
            if changed:
                out.append((dest, changed))
    return out


def slot_finding(key: str, pins: set[int]) -> str | None:
    """dt.map positional rule (docs/ldto.md 'Aliases'): a bare slot key muxes
    exactly the slot's pins; a device key muxes at least them."""
    s = lwt.h40p_slot(key)
    if s is None:
        return None  # grammar is check-lwt's job
    slot, want, device = s
    if device and not want <= pins:
        return f"needs {sorted(want)} (slot {slot}), muxes {sorted(pins)}"
    if not device and pins != want:
        return f"is slot {slot} = pins {sorted(want)}, muxes {sorted(pins)}"
    return None


def shared_findings(keypins: dict[str, dict[str, frozenset[int]]]) -> list[str]:
    """dt.map cross-board rule (docs/ldto.md 'Aliases'): every key is served
    by at least two boards, and they mux identical header pin positions.
    A board is one dt/ tree -- revisions and SKUs whose dt/ is a symlink are
    the same board here."""
    out = []
    for key in sorted(keypins):
        by = keypins[key]
        if len(by) < 2:
            out.append(f"{key}: only {', '.join(sorted(by))} has it")
            continue
        layouts: dict[frozenset[int], list[str]] = {}
        for b, pins in by.items():
            layouts.setdefault(pins, []).append(b)
        if len(layouts) > 1:
            out.append(f"{key}: pin positions differ: " + "; ".join(
                f"{sorted(p)} on {', '.join(sorted(bs))}"
                for p, bs in sorted(layouts.items(), key=lambda kv: sorted(kv[0]))))
    return out


def touched(dtbo_tree: Tree, base_symbols: dict[str, str]) -> list[str]:
    """Merged-tree paths of every node an overlay's fragments write."""
    out = []
    fixups = dtbo_tree.nodes.get("/__fixups__", {})
    for frag, props in dtbo_tree.nodes.items():
        if not re.match(r"^/fragment@\d+$", frag):
            continue
        if "target-path" in props:
            target = strings(props["target-path"])[0]
        else:
            target = None
            for label, refs in fixups.items():
                if f"{frag}:target:0" in strings(refs):
                    target = base_symbols.get(label)
            if target is None:
                continue
        ov = f"{frag}/__overlay__"
        for p in [ov] + dtbo_tree.children(ov):
            rel = p[len(ov):]
            out.append((target.rstrip("/") + rel) or "/")
    return out


# ------------------------------------------------------------------ check


def pin_findings(own: set[str], chain: set[str], documented: set[str],
                 header_pads: set[str]) -> tuple[list[str], list[str]]:
    undocumented = sorted((own & header_pads) - documented)
    stale = sorted((documented & header_pads) - chain)
    return undocumented, stale


def package_pads(board: Path, soc: str) -> set[str]:
    """Every pad the SoC package bonds out, from the ball extracts check-pinmux
    reads (Rockchip TRM + datasheet joins, Amlogic/Allwinner electrical)."""
    pads: set[str] = set()
    if soc in pinmux.RK_PINMUX:
        for path in pinmux.RK_PINMUX[soc] + [pinmux.RK_PINMUX[soc][0].with_name(
                "gpio_pinmux_datasheet.json")]:
            if path.is_file():
                pads |= set(pinmux.rk_pad_balls(path))
    elif board.name in pinmux.DATASHEET_JSON:
        path = pinmux.DATASHEET_JSON[board.name].with_name("gpio_electrical.json")
        if path.is_file():
            pads |= set(pinmux.electrical_pad_balls(path))
    return pads


def bank(pad: str) -> str:
    return re.sub(r"_?\d+$", "", pad)


def missing_pads(used: set[str], pkg: set[str]) -> list[str]:
    """Pads not bonded out by this package -- judged only within banks the
    extract covers, so a bank it leaves out (TEST_N) is not called missing."""
    banks = {bank(p) for p in pkg}
    return sorted(p for p in used if bank(p) in banks and p not in pkg)


PINS_HEAD = " * Pins (Header.Pin  Name  Pad  Ref — cross-ref gpio.map):"


def pins_rows(pads: set[str], rows: list[dict]) -> list[str]:
    """Pins: rows for these pads, in header/pin order, from gpio.map."""
    keyed = []
    for r in rows:
        name = r["name"].rstrip("*")
        if name in pads:
            hp = f"{r['header']}.{r['pin']}"
            keyed.append(((r["header"], int(r["pin"])),
                          f" *   {hp:<8} {name:<13} {r['pad']:<7} {r['ref']}".rstrip()))
    return [line for _, line in sorted(keyed)]


def rewrite_pins(text: str, new_rows: list[str]) -> str:
    """Replace the Pins: block (heading + its rows) of an overlay header;
    insert one after the Summary paragraph if there is none. Drops the block
    when there is nothing to list."""
    lines = text.split("\n")
    head = next((i for i, l in enumerate(lines) if l.startswith(" * Pins (")), None)
    if head is not None:
        end = head + 1
        # rows, plus the "?.?  PAD  ?  (not in gpio.map)" rows an older header
        # generator wrote for pads it could not place
        while end < len(lines) and (lwt.PIN_ROW_RE.match(lines[end]) or
                                    re.match(r"^\s*\*\s+\?\.\?", lines[end])):
            end += 1
        block = [PINS_HEAD] + new_rows if new_rows else []
        if not new_rows and end < len(lines) and lines[end].strip() == "*":
            end += 1  # take the separator with the block
        return "\n".join(lines[:head] + block + lines[end:])
    if not new_rows:
        return text
    summ = next((i for i, l in enumerate(lines) if "Summary:" in l), None)
    if summ is None:
        return text
    at = summ + 1
    while at < len(lines) and lines[at].strip() not in ("*", "*/"):
        at += 1
    return "\n".join(lines[:at] + [" *", PINS_HEAD] + new_rows + lines[at:])


NOTE_ROW = re.compile(r"^\s*\*\s+(?:\?\.\?\s+(\S+)|(\d*[Jj]\d+)\.(\d+)\s+(\S+))")


def notes_junk(text: str, pins_pads: set[str], chain: set[str]) -> list[int]:
    """Line numbers of pin rows under Notes: that are generator residue: a
    `?.?` row, a repeat of a pad already in Pins:, or a pad nothing in the
    chain muxes. A provider pad the chain does mux is kept -- the header
    policy lets device overlays note bus pins there "via Requires"."""
    lines = text.split("\n")
    start = next((i for i, l in enumerate(lines) if l.strip() == "* Notes:"), None)
    if start is None:
        return []
    out = []
    for i in range(start + 1, len(lines)):
        if lines[i].strip().startswith("*/"):
            break
        m = NOTE_ROW.match(lines[i])
        if not m:
            continue
        if m.group(1) is not None:
            out.append(i)
            continue
        pad = m.group(4).rstrip("*")
        if pad in pins_pads or pad not in chain:
            out.append(i)
    return out


def drop_lines(text: str, idx: list[int]) -> str:
    gone = set(idx)
    lines = [l for i, l in enumerate(text.split("\n")) if i not in gone]
    # a Notes: heading left with nothing under it goes too
    out = []
    for i, l in enumerate(lines):
        if l.strip() == "* Notes:" and i + 1 < len(lines) and \
                lines[i + 1].strip().startswith("*/"):
            if out and out[-1].strip() == "*":
                out.pop()
            continue
        out.append(l)
    return "\n".join(out)


def tracked(path: Path) -> bool:
    """--fix rewrites committed overlays only: an untracked .dts is somebody's
    work in progress, and its header is theirs to write."""
    return subprocess.run(["git", "-C", str(ROOT), "ls-files", "--error-unmatch",
                           str(path.relative_to(ROOT))],
                          capture_output=True).returncode == 0


def dts_of(path: Path) -> str:
    return subprocess.run(["dtc", "-q", "-I", "dtb", "-O", "dts", str(path)],
                          capture_output=True, text=True, timeout=60).stdout


def documented_pads(dts: Path) -> set[str]:
    header = dts.read_text(errors="replace").split("/dts-v1/")[0]
    out = set()
    for line in header.split("Notes:")[0].splitlines():
        m = lwt.PIN_ROW_RE.match(line.replace("—", "-"))
        if m and m.group(3) not in ("Name", "Pad", "cross-ref", "Ref"):
            out.add(m.group(3).rstrip("*"))
    return out


FAMILY = {"gxl": "meson", "g12a": "meson", "h3": "sunxi", "h5": "sunxi",
          "rk3328": "rockchip", "rk3399": "rockchip"}
BINDING = {"gxl": "meson-gxl-gpio.h", "g12a": "meson-g12a-gpio.h"}


def check_slots(board: Path, base: Path, family: str, groups, bindings, irqids,
                edges, stats: dict) -> None:
    """Every dt.map key (this board's, symlinked maps included) against the
    header pins its overlay chain muxes, in Raspberry Pi numbering."""
    gmap, mp = board / "gpio.map", board / "dt.map"
    hdr = lwt.read_rpi_header(gmap) if gmap.is_file() else None
    if not hdr or not mp.is_file():
        return
    pin_of = {}
    for r in lwt.load_gpio_map(gmap):
        if r["header"] == hdr and not r.get("_bad"):
            pin_of.setdefault(r["name"].rstrip("*"), int(r["pin"]))
    with tempfile.TemporaryDirectory(prefix=f"lwt-slots-{board.name}-") as tmp:
        for line in mp.read_text().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            key, ov = line.split()[:2]
            chain = [board / "dt" / f"{c}.dtbo" for c in fdt.expand_chain(ov, edges)]
            out = Path(tmp) / "a.dtb"
            if fdt.run_fdtoverlay("fdtoverlay", base, chain, out)[0] != 0:
                continue  # check-fdtoverlay reports apply failures
            t = Tree(parse_dts(dts_of(out)))
            res = Resolver(family, t, groups, bindings, irqids)
            pads: set[str] = set()
            for c in chain:
                for p in touched(Tree(parse_dts(dts_of(c))), t.symbols):
                    pads |= res.node_pads(p)
            stats["slots"] += 1
            pins = {pin_of[p] for p in pads if p in pin_of}
            stats["keypins"].setdefault(key, {})[board.name] = frozenset(pins)
            why = slot_finding(key, pins)
            if why:
                stats["slot_bad"] += 1
                print(f"SLOT: {board.name}: dt.map {key} -> {ov} {why}")


def check_board(board: Path, roots, linux: Path, stats: dict) -> None:
    soc = pinmux.SOC_OF_BOARD.get(board.name)
    family = FAMILY.get(soc or "")
    if (board / "dt").is_symlink():
        owner = (board / "dt").resolve().parent
        mine, theirs = board / "dt.map", owner / "dt.map"
        if (mine.is_file() and theirs.is_file()
                and mine.read_text() != theirs.read_text()):
            stats["slot_bad"] += 1
            print(f"SLOT: {board.name}: dt.map differs from {owner.name}'s, "
                  f"which owns its dt/ and is the map that gets checked")
        return  # checked under the board that owns the files
    if not family:
        return
    base = fdt.resolve_base(fdt.parse_dt_config(board / "dt.config") or "", roots)
    if base is None:
        stats["skip"] += 1
        print(f"SKIP: {board.name}: no base DTB")
        return
    groups: dict[str, list[str]] = {}
    if family == "meson":
        for pad, gs in pinmux.meson_pad_muxes(linux / pinmux.DRIVER[soc]).items():
            for g in gs:
                groups.setdefault(g, []).append(pad)
    bindings = (meson_bindings(ROOT / "include/dt-bindings/gpio" / BINDING[soc])
                if family == "meson" else None)
    irqids = (meson_irqids(ROOT / "include/dt-bindings/interrupt-controller" /
                           f"amlogic,meson-{soc}-gpio-intc.h")
              if family == "meson" else None)
    pkg = package_pads(board, soc)
    map_rows = [r for r in lwt.load_gpio_map(board / "gpio.map")
                if not r.get("_bad") and r["chip"] not in lwt.POWER_CHIPS]
    header_pads = {r["name"].rstrip("*") for r in map_rows}
    base_symbols = Tree(parse_dts(dts_of(base))).symbols
    base_compat = fdt.root_compatible(base)
    edges = fdt.load_deps(board / "dt.deps")
    dt_dir = board / "dt"
    check_slots(board, base, family, groups, bindings, irqids, edges, stats)
    with tempfile.TemporaryDirectory(prefix=f"lwt-pins-{board.name}-") as tmp:
        for stem, dtbo in fdt.unique_overlays(dt_dir):
            dts = dt_dir / f"{stem}.dts"
            if not dtbo.is_file() or not fdt.claims_board(fdt.root_compatible(dtbo),
                                                         base_compat):
                continue
            chain = [dt_dir / f"{c}.dtbo" for c in fdt.expand_chain(stem, edges)]
            out = Path(tmp) / f"{stem}.dtb"
            if fdt.run_fdtoverlay("fdtoverlay", base, chain, out)[0] != 0:
                continue
            res = Resolver(family, Tree(parse_dts(dts_of(out))), groups, bindings, irqids)
            # "Before" is the base with only the providers applied. A device
            # overlay that adds a child under its bus touches the bus node,
            # whose pins the provider set; those are the provider's to
            # document (/lwt header policy: bus pins may be left to Requires:).
            before_dtb = base
            if len(chain) > 1:
                before_dtb = Path(tmp) / f"{stem}.before.dtb"
                if fdt.run_fdtoverlay("fdtoverlay", base, chain[:-1], before_dtb)[0] != 0:
                    continue
            prev_tree = Tree(parse_dts(dts_of(before_dtb)))
            prev = Resolver(family, prev_tree, groups, bindings, irqids)
            own: set[str] = set()
            whole: set[str] = set()
            # Labels from base + providers: a device overlay may target a node
            # its provider created (spi-gpio-1cs defines &spigpio0).
            otree = Tree(parse_dts(dts_of(dtbo)))
            for dest, props in overwrites(otree, prev_tree):
                stats["merge"] += 1
                print(f"MERGE: {board.name}/{stem}: rewrites {props} of existing node "
                      f"{dest} -- a new node that collides with a base node's name")
            mine = touched(otree, prev_tree.symbols)
            for p in mine:
                own |= res.node_pads(p) - prev.node_pads(p)
                # "stale" asks whether anything muxes the pad once the chain
                # is applied -- including what the base already had enabled
                # on a node the overlay only adjusts (uart2 is the console).
                whole |= res.node_pads(p)
            for path, pads in collisions(res, mine, own):
                stats["collide"] += 1
                print(f"COLLIDE: {board.name}/{stem}: muxes {pads}, which {path} "
                      f"already holds")
            for prov in chain[:-1]:
                for p in touched(Tree(parse_dts(dts_of(prov))), base_symbols):
                    whole |= res.node_pads(p)
            doc = documented_pads(dts)
            undoc, stale = pin_findings(own, whole, doc, header_pads)
            if stats.get("explain") and (undoc or stale):
                print(f"EXPLAIN: {board.name}/{stem}: own={sorted(own & header_pads)} "
                      f"chain={sorted(whole & header_pads)} documented={sorted(doc)} "
                      f"requires={[c.stem for c in chain[:-1]]}")
            stats["overlays"] += 1
            stats["with_pads"] += bool(own & header_pads)
            for pad in undoc:
                stats["undocumented"] += 1
                print(f"UNDOCUMENTED: {board.name}/{stem}: muxes header pad {pad}, "
                      f"absent from its Pins:")
            if stats.get("fix") and not dts.is_symlink() and tracked(dts):
                text = dts.read_text()
                pins_pads = doc
                if undoc or stale:
                    pins_pads = (doc & whole & header_pads) | (own & header_pads)
                    text = rewrite_pins(text, pins_rows(pins_pads, map_rows))
                junk = notes_junk(text, pins_pads, whole)
                if junk:
                    text = drop_lines(text, junk)
                if undoc or stale or junk:
                    dts.write_text(text)
                    stats["fixed"] += 1
                    print(f"FIXED: {board.name}/{stem}: +{len(undoc)} undocumented, "
                          f"-{len(stale)} stale, -{len(junk)} Notes residue")
            elif notes_junk(dts.read_text(), doc, whole):
                stats["residue"] = stats.get("residue", 0) + 1
                print(f"RESIDUE: {board.name}/{stem}: Notes: carries generator "
                      f"pin rows ('?.?', repeats of Pins:, or unmuxed pads)")
            for pad in missing_pads(own, pkg):
                stats["missing"] += 1
                print(f"NO-SUCH-PAD: {board.name}/{stem}: uses {pad}, which the "
                      f"{soc} package does not bond out")
            for pad in stale:
                stats["stale"] += 1
                print(f"STALE: {board.name}/{stem}: Pins: lists {pad}, which "
                      f"nothing in the overlay chain muxes")


SELF_TEST_DTS = """/dts-v1/;
/ {
	compatible = "x";
	pinctrl {
		uart_a_pins: uart-a {
			mux {
				groups = "uart_tx_a", "uart_rx_a";
				function = "uart_a";
			};
		};
		bank {
			gpio-controller;
			#gpio-cells = <0x02>;
			phandle = <0x05>;
		};
	};
	serial@84c0 {
		pinctrl-0 = <0x07>;
		pinctrl-names = "default";
		cts-gpios = <0x05 0x0c 0x00>;
		status = "okay";
	};
	disabled-node {
		pinctrl-0 = <0x07>;
		pinctrl-names = "default";
		status = "disabled";
	};
	second-default {
		pinctrl-0 = <0x07>;
		pinctrl-1 = <0x07>;
		pinctrl-names = "sleep", "default", "default";
		status = "okay";
	};
	unnamed {
		pinctrl-0 = <0x07>;
		status = "okay";
	};
	__symbols__ {
		uart_A = "/serial@84c0";
	};
};
"""


def self_test() -> int:
    t = parse_dts(SELF_TEST_DTS.replace("uart-a {", "uart-a {\n\t\t\tphandle = <0x07>;"))
    tree = Tree(t)
    res = Resolver("meson", tree, {"uart_tx_a": ["GPIOX_12"], "uart_rx_a": ["GPIOX_13"]},
                   ({}, {12: "GPIOX_14"}))
    cases = [
        ("pinctrl group + gpio specifier resolve to pads",
         res.node_pads("/serial@84c0"), {"GPIOX_12", "GPIOX_13", "GPIOX_14"}),
        ("a disabled node muxes nothing", res.node_pads("/disabled-node"), set()),
        ("only the first state named default is applied (pinctrl-1 here)",
         res.node_pads("/second-default"), {"GPIOX_12", "GPIOX_13"}),
        ("no pinctrl-names: the core applies no state",
         res.node_pads("/unnamed"), set()),
        ("collision: another enabled node holds a newly muxed pad",
         set(p for p, _ in collisions(res, ["/unnamed"], {"GPIOX_14"})), {"/serial@84c0"}),
        ("no collision with a node under a disabled ancestor",
         collisions(Resolver("meson", Tree(parse_dts(
             '/ {\n\tbus {\n\t\tstatus = "disabled";\n\t\tdev {\n'
             '\t\t\tcs-gpios = <0x05 0x0c 0x00>;\n\t\t};\n\t};\n'
             '\tgpio {\n\t\tgpio-controller;\n\t\t#gpio-cells = <0x02>;\n'
             '\t\tphandle = <0x05>;\n\t};\n};\n')), {}, ({}, {12: "GPIOX_14"})),
             [], {"GPIOX_14"}), []),
        ("undocumented header pad fires",
         set(pin_findings({"GPIOX_12", "GPIOX_13"}, {"GPIOX_12", "GPIOX_13"},
                          {"GPIOX_12"}, {"GPIOX_12", "GPIOX_13"})[0]), {"GPIOX_13"}),
        ("stale Pins: pad fires",
         set(pin_findings({"GPIOX_12"}, {"GPIOX_12"}, {"GPIOX_12", "GPIOX_8"},
                          {"GPIOX_12", "GPIOX_8"})[1]), {"GPIOX_8"}),
        ("provider-owned pad is not stale",
         set(pin_findings({"GPIOX_12"}, {"GPIOX_12", "GPIOX_8"}, {"GPIOX_12", "GPIOX_8"},
                          {"GPIOX_12", "GPIOX_8"})[1]), set()),
        ("meson gpio-intc interrupt resolves to its pad (fan tach / gpio-keys)",
         Resolver("meson", Tree(parse_dts(
             '/ {\n\tintc {\n\t\tcompatible = "amlogic,meson-gpio-intc";\n'
             '\t\t#interrupt-cells = <0x02>;\n\t\tphandle = <0x09>;\n\t};\n'
             '\tfan {\n\t\tinterrupt-parent = <0x09>;\n'
             '\t\tinterrupts = <0x1e 0x02>;\n\t};\n};\n')),
             {}, None, {30: "GPIOH_4"}).node_pads("/fan"), {"GPIOH_4"}),
        ("null placeholder in cs-gpios does not end the list",
         Resolver("meson", tree, {}, ({}, {12: "GPIOX_14", 9: "GPIOA_9"}))
         .gpio_prop_pads("<0x00>, <0x05 0x09 0x01>"), {"GPIOA_9"}),
        ("pad the package lacks fires (S805X has no GPIOX_17/18)",
         set(missing_pads({"GPIOX_17", "GPIOX_8", "TEST_N"},
                          {"GPIOX_8", "GPIOX_16", "GPIOAO_2"})), {"GPIOX_17"}),
        ("Pins: block rewrite keeps the header, replaces rows, drops ?.? junk",
         set(rewrite_pins(" * Summary: x\n *\n" + PINS_HEAD + "\n"
                          " *   7J1.8    GPIOX_9       B1      OLD\n"
                          " *   ?.?    RK_PD4        ?       (not in gpio.map)\n"
                          " *\n * Notes:\n */",
                          [" *   7J1.19   GPIOX_8       A5      NEW"]).split("\n")),
         {" * Summary: x", " *", PINS_HEAD, " *   7J1.19   GPIOX_8       A5      NEW",
          " * Notes:", " */"}),
        ("Notes residue: ?.? row, a repeat of Pins:, an unmuxed pad go; a "
         "muxed provider pad stays",
         set(notes_junk(" * Notes:\n"
                        " *  ?.?    RK_PB0        ?       (not in gpio.map)\n"
                        " *  J1.19   GPIO3_A1      D2      SPI_TXD\n"
                        " *  J1.28   GPIO2_A5      N20     I2C1_SCL\n"
                        " *  J1.23   GPIO3_A0      E3      SPI_CLK\n */",
                        {"GPIO3_A1"}, {"GPIO3_A1", "GPIO3_A0"})), {1, 2, 3}),
        ("MERGE: a 'new' node whose name the base already uses is rewritten",
         overwrites(Tree(parse_dts(
             '/ {\n\tfragment@0 {\n\t\ttarget-path = "/maps";\n\t\t__overlay__ {\n'
             '\t\t\tmap1 {\n\t\t\t\ttrip = <0x09>;\n\t\t\t};\n'
             '\t\t\tmap-fan {\n\t\t\t\ttrip = <0x09>;\n\t\t\t};\n\t\t};\n\t};\n};\n')),
             Tree(parse_dts('/ {\n\tmaps {\n\t\tmap1 {\n\t\t\ttrip = <0x03>;\n'
                            '\t\t};\n\t};\n};\n'))), [("/maps/map1", ["trip"])]),
        ("SLOT: bare UART_0 that also takes RTS/CTS (16/18) fires",
         slot_finding("H40P_UART_0", {8, 10, 16, 18}) is not None, True),
        ("SLOT: H3-style SPI_1 on 22/32/36/37 fires",
         slot_finding("H40P_SPI_1_1CS", {22, 32, 36, 37}) is not None, True),
        ("SLOT: device key may add its own pins",
         slot_finding("H40P_SPI_0_2CS_LCD_35", {11, 18, 19, 21, 22, 23, 24, 26}), None),
        ("SHARED: a key only one board has fires",
         len(shared_findings({"H40P_PWM_P7": {"a": frozenset({7})}})), 1),
        ("SHARED: two boards at different pins fire",
         len(shared_findings({"H40P_I2C_0_X": {"a": frozenset({3, 5}),
                                               "b": frozenset({3, 5, 7})}})), 1),
        ("SHARED: two boards at identical pins pass",
         shared_findings({"H40P_I2C_0": {"a": frozenset({3, 5}),
                                         "b": frozenset({3, 5})}}), []),
        ("rockchip pins cells decode",
         Resolver("rockchip", Tree(parse_dts(
             '/ {\n\tp {\n\t\trockchip,pins = <0x03 0x19 0x01 0x08>;\n\t};\n};\n')),
             {}, None).pinctrl_pads("/p"), {"GPIO3_D1"}),
    ]
    fails = 0
    for what, got, want in cases:
        if got != want:
            fails += 1
            print(f"SELFTEST FAIL: {what}: expected {sorted(want)}, got {sorted(got)}")
    print(f"check-overlay-pins --self-test: {len(cases) - fails}/{len(cases)} cases pass")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board")
    ap.add_argument("--linux", help="kernel tree (meson pinctrl group tables)")
    ap.add_argument("--dtb-dir", action="append", default=[])
    ap.add_argument("--explain", action="store_true",
                    help="for each finding, print the pads resolved and documented")
    ap.add_argument("--fix", action="store_true",
                    help="rewrite each flagged overlay's Pins: block from gpio.map: "
                         "its own header pads plus documented pads the chain muxes")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    linux = Path(a.linux) if a.linux else next(
        (p for p in pinmux.DEFAULT_LINUX if (p / "drivers").is_dir()), None)
    if linux is None:
        print("SKIP: no kernel tree (--linux); meson group tables unavailable")
        return 0
    roots = [Path(d) for d in a.dtb_dir] + fdt.home_paths()
    stats = {"overlays": 0, "with_pads": 0, "undocumented": 0, "stale": 0, "skip": 0,
             "missing": 0, "collide": 0, "merge": 0, "explain": a.explain, "fix": a.fix,
             "fixed": 0, "slots": 0, "slot_bad": 0, "keypins": {}}
    for board in fdt.board_dirs(a.board):
        check_board(board, roots, linux, stats)
    shared = [] if a.board else shared_findings(stats["keypins"])
    for f in shared:
        print(f"SHARED: dt.map {f}")
    print(f"check-overlay-pins: {stats['overlays']} overlays resolved, "
          f"{stats['with_pads']} mux header pads; {stats['undocumented']} undocumented, "
          f"{stats['stale']} stale, {stats['missing']} on no package pad, "
          f"{stats['collide']} colliding with an enabled node, "
          f"{stats['merge']} rewriting an existing node, "
          f"{stats.get('residue', 0)} with Notes residue; "
          f"{stats['slots']} dt.map keys checked, {stats['slot_bad']} off their slot, "
          f"{len(shared)} not shared by 2+ boards at identical pins; "
          f"{stats['skip']} board(s) without a base DTB")
    return 1 if (stats["undocumented"] or stats["stale"] or stats["missing"]
                 or stats["collide"] or stats["merge"] or stats.get("residue")
                 or stats["slot_bad"] or shared) else 0


if __name__ == "__main__":
    sys.exit(main())
