#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Migrate root lc,provides/requires/revokes DT properties to header comments.

Header fields (alongside Summary / Pins / Requires basenames):
  * Resource-provides: tok, tok
  * Resource-requires: tok
  * Resource-revokes: tok

Removes the DT properties and the temporary /* resource-set tokens ... */ block.
Idempotent if only comments remain.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse_lc(text: str, prop: str) -> list[str]:
    m = re.search(rf"lc,{re.escape(prop)}\s*=\s*([^;]+);", text)
    if not m:
        return []
    return re.findall(r'"([^"]+)"', m.group(1))


def strip_lc_props(text: str) -> str:
    text = re.sub(
        r"\n\s*/\*\s*resource-set tokens[^*]*\*/\s*\n",
        "\n",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\n\s*/\*\s*overlay-deps:[^*]*\*/\s*\n",
        "\n",
        text,
        flags=re.I,
    )
    text = re.sub(r"\n\s*lc,provides\s*=\s*[^;]+;\s*", "\n", text)
    text = re.sub(r"\n\s*lc,requires\s*=\s*[^;]+;\s*", "\n", text)
    text = re.sub(r"\n\s*lc,revokes\s*=\s*[^;]+;\s*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def insert_header_resources(
    text: str,
    provides: list[str],
    requires: list[str],
    revokes: list[str],
) -> str:
    if not (provides or requires or revokes):
        return text
    # Already have Resource-* fields
    if re.search(r"^\s*\*\s*Resource-(provides|requires|revokes)\s*:", text, re.M | re.I):
        return text

    lines: list[str] = []
    if provides:
        lines.append(f" * Resource-provides: {', '.join(provides)}")
    if requires:
        lines.append(f" * Resource-requires: {', '.join(requires)}")
    if revokes:
        lines.append(f" * Resource-revokes: {', '.join(revokes)}")
    block = "\n".join(lines) + "\n"

    # Prefer insert before closing of second /* ... */ header (after SPDX block)
    # Pattern: header comment containing Summary:
    m = re.search(
        r"(/\*[^*]*\*+(?:[^/*][^*]*\*+)*/\s*)\n(/dts-v1/)",
        text,
        re.S,
    )
    if m:
        hdr = m.group(1)
        # insert before final " */"
        if "Resource-provides" in hdr or "Resource-requires" in hdr:
            return text
        # place after Requires: line if present, else after Pins/Summary, else before */
        if re.search(r"^\s*\*\s*Requires\s*:", hdr, re.M | re.I):
            hdr2 = re.sub(
                r"(^\s*\*\s*Requires\s*:.*\n)",
                r"\1" + block,
                hdr,
                count=1,
                flags=re.M | re.I,
            )
        elif re.search(r"^\s*\*\s*Notes\s*:", hdr, re.M | re.I):
            hdr2 = re.sub(
                r"(^\s*\*\s*Notes\s*:)",
                block + r"\1",
                hdr,
                count=1,
                flags=re.M | re.I,
            )
        else:
            hdr2 = re.sub(r"\*/\s*$", block + " */", hdr, count=1)
        return text[: m.start(1)] + hdr2 + "\n" + text[m.start(2) :]

    # No structured header: inject a small block before /dts-v1/
    inj = "/*\n" + block + " */\n"
    return re.sub(r"(/dts-v1/;)", inj + r"\1", text, count=1)


def migrate_file(path: Path) -> str:
    text = path.read_text(errors="replace")
    provides = parse_lc(text, "provides")
    requires = parse_lc(text, "requires")
    revokes = parse_lc(text, "revokes")
    if not (provides or requires or revokes):
        if re.search(r"lc,(provides|requires|revokes)\s*=", text):
            return "skip-orphan-lc"
        return "skip-none"
    # Drop alias:* from provides (derived in ldto)
    provides = [t for t in provides if not t.startswith("alias:")]
    new = insert_header_resources(text, provides, requires, revokes)
    new = strip_lc_props(new)
    if new == text:
        return "skip-unchanged"
    path.write_text(new)
    return "ok"


def main() -> int:
    n = 0
    for path in sorted((ROOT / "libre-computer").rglob("*.dts")):
        if path.is_symlink():
            continue
        st = migrate_file(path)
        if st == "ok":
            n += 1
            print(f"ok {path.relative_to(ROOT)}")
        elif st.startswith("skip") and st != "skip-none":
            print(f"{st} {path.relative_to(ROOT)}")
    print(f"migrated {n}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
