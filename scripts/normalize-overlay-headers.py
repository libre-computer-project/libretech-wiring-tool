#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Da Xue <da@libre.computer>
"""Normalize LWT overlay DTS headers to the standard comment policy.

Header shape (after SPDX):
  /* Copyright / Author */
  /*
   * Summary: <one line>
   *
   * Pins (Header.Pin  Name  Pad  Ref — from gpio.map):
   *   7J1.19  GPIOX_8   B4  BTPCM_DOUT
   *   ...
   *
   * Requires: <dt.deps providers>   # omitted if none
   *
   * Notes: <optional free-form>
   */

Cross-references SoC pad names and comment pin numbers against the board
gpio.map. Skips symlink .dts files. Use --dry-run to preview.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LC = ROOT / "libre-computer"

SKIP_PAD = re.compile(
    r"^(GPIO_ACTIVE_|GPIO_OPEN_|GPIO_PULL_|GPIO_PERSISTENT)"
)
PAD_TOKEN = re.compile(
    r"\b(GPIO[A-Z][A-Z0-9_]*|GPIODV_[0-9]+|TEST_N|RK_P[A-Z0-9_]+)\b"
)
SPDX_RE = re.compile(r"^//\s*SPDX-License-Identifier:\s*(.+)$", re.M)


def load_gpio_map(board_dir: Path) -> list[dict]:
    path = board_dir / "gpio.map"
    if not path.is_file():
        # walk up for shared maps (rare)
        return []
    rows = []
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 9:
            # pad missing columns
            parts = parts + [""] * (9 - len(parts))
        rows.append(
            {
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


def load_deps(board_dir: Path) -> dict[str, str]:
    path = board_dir / "dt.deps"
    deps: dict[str, str] = {}
    if not path.is_file():
        return deps
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            deps[parts[0]] = parts[1].strip()
    return deps


def name_index(rows: list[dict]) -> dict[str, dict]:
    idx = {}
    for r in rows:
        bare = r["name"].rstrip("*")
        if bare and bare not in ("GND", "5V", "3.3V", "ADC"):
            idx[bare] = r
        # also index raw
        if r["name"]:
            idx[r["name"]] = r
    return idx


def pin_index(rows: list[dict]) -> dict[tuple[str, str], dict]:
    return {(r["header"], r["pin"]): r for r in rows}


def split_header_body(text: str) -> tuple[str, str]:
    m = re.search(r"^/dts-v1/;", text, re.M)
    if not m:
        return text, ""
    return text[: m.start()], text[m.start() :]


def extract_blocks(header: str) -> tuple[str, list[str], list[str]]:
    """Return (spdx, copyright_lines, prose_lines)."""
    spdx = "(GPL-2.0-or-later OR MIT)"
    m = SPDX_RE.search(header)
    if m:
        spdx = m.group(1).strip()

    copyright: list[str] = []
    prose: list[str] = []
    # strip SPDX line for block parse
    rest = SPDX_RE.sub("", header)

    # block comments
    for m in re.finditer(r"/\*(.*?)\*/", rest, re.S):
        raw = m.group(1)
        lines = []
        for line in raw.splitlines():
            line = re.sub(r"^\s*\*\s?", "", line)
            lines.append(line.rstrip())
        # drop leading/trailing empty
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        blob = "\n".join(lines)
        if re.search(r"Copyright|Author:", blob, re.I):
            for ln in lines:
                if ln.strip():
                    copyright.append(ln.strip())
        else:
            for ln in lines:
                prose.append(ln)

    # // comments (non-SPDX)
    for line in rest.splitlines():
        if line.strip().startswith("//") and "SPDX" not in line:
            prose.append(line.strip().lstrip("/").strip())

    return spdx, copyright, prose


def extract_pads_from_body(body: str) -> list[str]:
    found = []
    seen = set()
    for m in PAD_TOKEN.finditer(body):
        tok = m.group(1)
        if SKIP_PAD.match(tok):
            continue
        if tok not in seen:
            seen.add(tok)
            found.append(tok)
    return found


def extract_pins_from_prose(
    prose: list[str], default_header: str
) -> list[tuple[str, str]]:
    text = "\n".join(prose)
    out: list[tuple[str, str]] = []
    seen = set()

    def emit(h: str, p: str) -> None:
        try:
            pi = int(p)
        except ValueError:
            return
        if pi < 1 or pi > 99:
            return
        key = (h, str(pi))
        if key in seen:
            return
        seen.add(key)
        out.append(key)

    # Header.Pin
    for m in re.finditer(r"\b(\d+[Jj]\d+)\.(\d+)\b", text):
        emit(m.group(1), m.group(2))
    # 7J1 pin 22
    for m in re.finditer(
        r"\b(\d+[Jj]\d+)\s+pin\s*(\d+)\b", text, re.I
    ):
        emit(m.group(1), m.group(2))
    # bare pin 22
    for m in re.finditer(r"\bpin\s+(\d+)\b", text, re.I):
        emit(default_header, m.group(1))
    # Pins 19 (MOSI), 21 ... or pins (7J1 19/21/23/24)
    for m in re.finditer(r"\bpins\s+(.+)", text, re.I):
        rest = m.group(1)
        if rest.startswith("("):
            end = rest.find(")")
            inner = rest[1:end] if end > 0 else rest
            inner = re.sub(r"\d+[Jj]\d+", " ", inner)
            for n in re.findall(r"\d+", inner):
                emit(default_header, n)
        else:
            # strip role parens
            rest2 = re.sub(r"\([^)]*\)", " ", rest)
            rest2 = re.split(
                r"\s+(?:come|from|with|using)\b", rest2, maxsplit=1, flags=re.I
            )[0]
            for n in re.findall(r"\d+", rest2):
                emit(default_header, n)
    # slash lists 19/21/23/24
    for m in re.finditer(r"\b(\d+)(?:/\d+)+\b", text):
        for n in m.group(0).split("/"):
            emit(default_header, n)

    return out


def detect_header_in_prose(prose: list[str], rows: list[dict]) -> str:
    text = "\n".join(prose)
    m = re.search(r"\b(\d+[Jj]\d+)\b", text)
    if m:
        return m.group(1)
    if rows:
        return rows[0]["header"]
    return "7J1"


def build_summary(prose: list[str], stem: str) -> tuple[str, list[str]]:
    """Return (summary, remaining notes lines)."""
    dual = []
    other = []
    for ln in prose:
        low = ln.lower()
        if "tinydrm" in low or "fbtft" in low or "display stack" in low:
            dual.append(ln)
        else:
            other.append(ln)

    # Prefer first non-empty non-bullet descriptive line as summary seed
    summary = ""
    rest = []
    pin_row_re = re.compile(
        r"^\d+[Jj]\d+\.\d+\s+\S+"  # 7J1.19  GPIOX_8 ...
    )
    skip_prefix = re.compile(
        r"^(Summary|Pins|Requires|Notes)\s*:", re.I
    )
    for i, ln in enumerate(other):
        s = ln.strip()
        if not s:
            continue
        # drop structured rows from a previous normalize pass
        if pin_row_re.match(s):
            continue
        if re.match(r"^Pins\s*\(Header", s, re.I):
            continue
        if s.startswith("-") or s.startswith("*"):
            rest.extend(other[i:])
            break
        if skip_prefix.match(s):
            # Summary: foo  / Requires: bar  on re-run
            if s.lower().startswith("summary:"):
                while s.lower().startswith("summary:"):
                    s = s.split(":", 1)[1].strip()
                if not summary and s:
                    summary = s
                continue
            if s.lower().startswith("requires:"):
                continue
            if s.lower().startswith("notes:"):
                continue
            if s.lower().startswith("pins:"):
                continue
        if not summary:
            s2 = re.sub(
                r"^Overlay aimed to\s+", "", s, flags=re.I
            ).rstrip(" :")
            s2 = re.sub(r"^Enables?\s+", "", s2, flags=re.I)
            while re.match(r"^Summary:\s*", s2, re.I):
                s2 = re.sub(r"^Summary:\s*", "", s2, flags=re.I).strip()
            summary = s2[0].upper() + s2[1:] if s2 else s2
            continue
        rest.append(ln)

    if not summary:
        summary = stem

    notes = []
    for ln in dual + rest:
        s = ln.strip()
        if not s:
            continue
        # Pin lists / table rows absorbed into Pins: block
        if re.match(r"^Pins?\b", s, re.I):
            continue
        if re.match(r"^Header\s+\d", s, re.I) and "pin" in s.lower():
            continue
        if re.match(r"^\d+[Jj]\d+\.\d+\s+\S+", s):
            continue
        if re.match(r"^(Summary|Requires|Notes)\s*:", s, re.I):
            continue
        notes.append(ln)
    return summary, notes


def format_header(
    spdx: str,
    copyright: list[str],
    summary: str,
    pin_rows: list[dict],
    requires: str,
    notes: list[str],
) -> str:
    lines = [f"// SPDX-License-Identifier: {spdx}", "/*"]
    if copyright:
        for c in copyright:
            lines.append(f" * {c}" if c else " *")
    else:
        lines.append(" * Copyright (c) Libre Computer Project")
    lines.append(" */")
    lines.append("/*")
    lines.append(f" * Summary: {summary}")

    if pin_rows:
        lines.append(" *")
        lines.append(
            " * Pins (Header.Pin  Name  Pad  Ref — cross-ref gpio.map):"
        )
        for r in pin_rows:
            ref = r.get("ref") or r.get("desc") or ""
            lines.append(
                f" *   {r['header']}.{r['pin']:<3}  {r['name']:<12}  "
                f"{r['pad']:<6}  {ref}"
            )

    if requires:
        lines.append(" *")
        lines.append(f" * Requires: {requires}")

    if notes:
        lines.append(" *")
        lines.append(" * Notes:")
        for ln in notes:
            s = ln.rstrip()
            if not s:
                lines.append(" *")
                continue
            # avoid double "Notes:"
            if re.match(r"^Notes?:\s*$", s, re.I):
                continue
            lines.append(f" *   {s}" if not s.startswith(" ") else f" *{s}")

    lines.append(" */")
    lines.append("")
    return "\n".join(lines)


def process_file(
    dts: Path, board_dir: Path, deps: dict[str, str], dry_run: bool
) -> bool:
    text = dts.read_text(errors="replace")
    header, body = split_header_body(text)
    if not body:
        return False

    rows = load_gpio_map(board_dir)
    nidx = name_index(rows)
    pidx = pin_index(rows)
    default_hdr = rows[0]["header"] if rows else "7J1"

    spdx, copyright, prose = extract_blocks(header)
    default_hdr = detect_header_in_prose(prose, rows)

    stem = dts.stem
    # resolve symlink target stem for deps? use this stem
    requires = deps.get(stem, "")

    summary, notes = build_summary(prose, stem)

    # Collect pins from DTS pads + comment pin numbers
    pin_rows: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()

    def add_row(r: dict) -> None:
        key = (r["header"], r["pin"])
        if key in seen_keys:
            return
        # skip pure power rails unless explicitly the only claim
        if r["name"] in ("GND", "5V", "3.3V") and r["chip"] in (
            "GND",
            "5V",
            "3.3V",
        ):
            return
        seen_keys.add(key)
        pin_rows.append(r)

    for pad in extract_pads_from_body(body):
        r = nidx.get(pad) or nidx.get(pad.rstrip("*"))
        if r:
            add_row(r)
        else:
            pin_rows.append(
                {
                    "header": "?",
                    "pin": "?",
                    "name": pad,
                    "pad": "?",
                    "ref": "(not in gpio.map)",
                }
            )

    for h, p in extract_pins_from_prose(prose, default_hdr):
        r = pidx.get((h, p))
        if not r:
            # Silk name may differ from gpio.map header (7J2 vs 7J1)
            for (hh, pp), row in pidx.items():
                if pp == p and row["name"] not in ("GND", "5V", "3.3V"):
                    # prefer map default header
                    if hh == (rows[0]["header"] if rows else h):
                        r = row
                        break
                    if r is None:
                        r = row
        if r:
            add_row(r)

    # stable sort by header then pin number
    def sort_key(r: dict):
        try:
            pin_n = int(r["pin"])
        except ValueError:
            pin_n = 999
        return (r.get("header") or "", pin_n, r.get("name") or "")

    pin_rows_sorted = sorted(
        [r for r in pin_rows if r.get("header") != "?"], key=sort_key
    )
    # keep unmapped pads at end
    pin_rows_sorted += [r for r in pin_rows if r.get("header") == "?"]

    new_header = format_header(
        spdx, copyright, summary, pin_rows_sorted, requires, notes
    )
    new_text = new_header + body
    if new_text == text:
        return False
    if dry_run:
        print(f"--- would update {dts.relative_to(ROOT)}")
        return True
    dts.write_text(new_text)
    print(f"updated {dts.relative_to(ROOT)}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dry-run", action="store_true", help="print files that would change"
    )
    ap.add_argument(
        "--board",
        action="append",
        default=[],
        help="limit to board dir name (repeatable)",
    )
    ap.add_argument(
        "paths",
        nargs="*",
        help="optional specific .dts paths; default = all real files",
    )
    args = ap.parse_args()

    if args.paths:
        files = [Path(p).resolve() for p in args.paths]
    else:
        files = []
        for board in sorted(LC.iterdir()):
            if not board.is_dir():
                continue
            if args.board and board.name not in args.board:
                continue
            dt = board / "dt"
            if not dt.is_dir() or dt.is_symlink():
                continue
            for dts in sorted(dt.glob("*.dts")):
                if dts.is_symlink():
                    continue
                if not dts.is_file():
                    continue
                files.append(dts)

    changed = 0
    for dts in files:
        # board_dir = .../libre-computer/<board>
        try:
            board_dir = dts.parents[1]
        except IndexError:
            continue
        deps = load_deps(board_dir)
        if process_file(dts, board_dir, deps, args.dry_run):
            changed += 1
    print(f"{'would change' if args.dry_run else 'changed'}: {changed}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
