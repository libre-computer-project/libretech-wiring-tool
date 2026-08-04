#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Da Xue <da@libre.computer>
"""Smoke-apply LWT overlay chains onto board base DTBs with fdtoverlay.

For each board under libre-computer/:
  1. Read DT_OVERRIDE from dt.config (EFI/base DTB path)
  2. Resolve a base .dtb from LWT_DTB_DIR / --dtb-dir / auto-search
  3. For each unique real .dtbo, expand providers from dt.deps and run:
       fdtoverlay -i base.dtb -o <tmp> <provider.dtbo>... <consumer.dtbo>

Default: print WARNING on apply failure; SKIP when base DTB is missing
(not a failure — CI hosts without a DTB tree stay green). Use --strict
to exit non-zero on WARNING (not on SKIP). Use --require-base to also
treat missing bases as WARNING.

Exit 0 always unless --strict (then 1 if any WARNING).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LC = ROOT / "libre-computer"

# Relative to a kernel build O=... or /usr/lib/linux-image-* layout.
DEFAULT_DTB_HINTS = (
    # arm64 kernel O= trees (common on fleet build hosts)
    "build/lc618/x86_64-arm64/arch/arm64/boot/dts",
    "build/lc618/x86_64-arm64/arch/arm64/boot/dts/amlogic",  # also try parent
    # armhf (H3)
    "build/lc618/x86_64-armhf-linux-6.18.y-lc/arch/arm/boot/dts",
)


def warn(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr)


def skip(msg: str) -> None:
    print(f"SKIP: {msg}", file=sys.stderr)


def info(msg: str) -> None:
    print(f"check-fdtoverlay: {msg}", file=sys.stderr)


def parse_dt_config(path: Path) -> str | None:
    """Return DT_OVERRIDE path relative fragment, or None."""
    if not path.is_file():
        return None
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # DT_OVERRIDE=path  or  DT_OVERRIDE=path # comment
        m = re.match(r"DT_OVERRIDE\s*=\s*(\S+)", line)
        if not m:
            continue
        val = m.group(1)
        # strip inline comments glued without space (unlikely) and quotes
        val = val.split("#", 1)[0].strip().strip("\"'")
        return val or None
    return None


def load_deps(path: Path) -> dict[str, list[str]]:
    """consumer -> [provider, ...] (immediate)."""
    edges: dict[str, list[str]] = {}
    if not path.is_file():
        return edges
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            consumer, rest = line.split("\t", 1)
        else:
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            consumer, rest = parts[0], parts[1]
        providers = rest.split()
        if consumer and providers:
            edges[consumer.strip()] = [p.strip() for p in providers if p.strip()]
    return edges


def expand_chain(consumer: str, edges: dict[str, list[str]]) -> list[str]:
    """Providers first (depth-first), then consumer. Dedupe, preserve order."""
    ordered: list[str] = []
    seen: set[str] = set()

    def add(name: str, depth: int = 0) -> None:
        if depth > 32:
            return
        if name in seen:
            return
        for p in edges.get(name, []):
            add(p, depth + 1)
        if name not in seen:
            seen.add(name)
            ordered.append(name)

    add(consumer)
    return ordered


def is_same_dir_symlink(path: Path) -> bool:
    if not path.is_symlink():
        return False
    target = os.readlink(path)
    return "/" not in target and "\\" not in target


def board_dirs(board_filter: str | None) -> list[Path]:
    if board_filter:
        p = LC / board_filter
        return [p] if p.is_dir() else []
    return sorted(p for p in LC.iterdir() if p.is_dir())


def home_paths() -> list[Path]:
    """Candidate DTB search roots (directories that contain vendor subdirs)."""
    roots: list[Path] = []
    seen: set[Path] = set()

    def add(p: Path) -> None:
        try:
            r = p.resolve()
        except OSError:
            return
        if not r.is_dir() or r in seen:
            return
        seen.add(r)
        roots.append(r)

    env = os.environ.get("LWT_DTB_DIR", "")
    for part in env.split(":"):
        part = part.strip()
        if part:
            add(Path(part))

    home = Path.home()
    for rel in DEFAULT_DTB_HINTS:
        add(home / rel)
        # if hint is .../boot/dts/amlogic, also parent .../boot/dts
        p = home / rel
        if p.name in ("amlogic", "allwinner", "rockchip"):
            add(p.parent)

    # Kernel package layouts (host may be multi-arch)
    for pattern in (
        "/usr/lib/linux-image-*",
        "/lib/modules/*/build/arch/arm64/boot/dts",
        "/lib/modules/*/build/arch/arm/boot/dts",
    ):
        # Avoid recursive walk — only glob depth we need
        import glob as _glob

        for g in sorted(_glob.glob(pattern)):
            add(Path(g))

    # Explicit LINUX_DIR / LB-style O=
    for key in ("LWT_LINUX_DTB_DIR", "LINUX_DTB_DIR"):
        v = os.environ.get(key)
        if v:
            add(Path(v))

    return roots


def resolve_base(override: str, roots: list[Path]) -> Path | None:
    """Find DT_OVERRIDE under search roots.

    DT_OVERRIDE may be:
      amlogic/meson-….dtb
      sun8i-h3-….dtb          (no vendor prefix)
      rockchip/rk3328-….dtb
    """
    override = override.lstrip("/")
    base_name = Path(override).name
    candidates: list[Path] = []
    for root in roots:
        candidates.append(root / override)
        candidates.append(root / base_name)
        # root is O=.../arch/arm64/boot/dts already
        # or root is O= build top
        candidates.append(root / "arch" / "arm64" / "boot" / "dts" / override)
        candidates.append(root / "arch" / "arm" / "boot" / "dts" / override)
        # vendor-less: try under common vendor dirs
        for vendor in ("amlogic", "allwinner", "rockchip"):
            candidates.append(root / vendor / base_name)
            candidates.append(
                root / "arch" / "arm64" / "boot" / "dts" / vendor / base_name
            )
            candidates.append(
                root / "arch" / "arm" / "boot" / "dts" / vendor / base_name
            )

    for c in candidates:
        if c.is_file():
            return c.resolve()
    return None


def has_symbols(dtb: Path) -> bool:
    try:
        data = dtb.read_bytes()
    except OSError:
        return False
    return b"__symbols__" in data


def run_fdtoverlay(
    fdtoverlay: str,
    base: Path,
    chain_dtbos: list[Path],
    out: Path,
) -> tuple[int, str]:
    cmd = [fdtoverlay, "-i", str(base), "-o", str(out), *[str(p) for p in chain_dtbos]]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return 124, "fdtoverlay timed out"
    except OSError as e:
        return 127, str(e)
    err = (r.stderr or r.stdout or "").strip()
    return r.returncode, err


def unique_overlays(dt_dir: Path) -> list[tuple[str, Path]]:
    """Return (canonical_stem, dtbo_path) unique by realpath of content.

    Prefer non-symlink basenames; same-dir aliases are skipped (same blob).
    Cross-dir symlink .dtbo (rare) is tested under this board's name.
    """
    by_real: dict[Path, tuple[str, Path]] = {}
    if not dt_dir.is_dir():
        return []

    # Prefer listing .dts so we know the intended basename set
    dts_files = sorted(dt_dir.glob("*.dts"))
    if not dts_files:
        # fall back to .dtbo only
        for dtbo in sorted(dt_dir.glob("*.dtbo")):
            if is_same_dir_symlink(dtbo):
                continue
            try:
                real = dtbo.resolve()
            except OSError:
                real = dtbo
            stem = dtbo.stem
            if real not in by_real or not dtbo.is_symlink():
                by_real[real] = (stem, dtbo)
        return list(by_real.values())

    for dts in dts_files:
        if is_same_dir_symlink(dts):
            continue
        dtbo = dts.with_suffix(".dtbo")
        stem = dts.stem
        # Resolve real content path for de-dupe (cross-board symlinks share)
        try:
            real_key = dts.resolve()
        except OSError:
            real_key = dts
        # Prefer keeping a non-symlink board-local name as the report stem
        prev = by_real.get(real_key)
        if prev is None or (dts.is_symlink() is False and Path(prev[1]).is_symlink()):
            by_real[real_key] = (stem, dtbo)

    return list(by_real.values())


class Stats:
    def __init__(self) -> None:
        self.ok = 0
        self.fail = 0
        self.skip_base = 0
        self.skip_nodtbo = 0
        self.skip_empty = 0
        self.missing_dtbo = 0
        self.no_symbols = 0
        self.warnings = 0


def check_board(
    board: Path,
    roots: list[Path],
    fdtoverlay: str,
    *,
    require_base: bool,
    verbose: bool,
    stats: Stats,
) -> None:
    name = board.name
    dt_dir = board / "dt"
    if dt_dir.is_symlink():
        try:
            dt_dir = dt_dir.resolve()
        except OSError:
            pass

    if not dt_dir.is_dir():
        stats.skip_empty += 1
        if verbose:
            skip(f"{name}: no dt/ directory")
        return

    override = parse_dt_config(board / "dt.config")
    if not override:
        stats.skip_empty += 1
        if verbose:
            skip(f"{name}: no DT_OVERRIDE in dt.config")
        return

    base = resolve_base(override, roots)
    if base is None:
        stats.skip_base += 1
        msg = f"{name}: no base DTB for {override} (set LWT_DTB_DIR or --dtb-dir)"
        if require_base:
            warn(msg)
            stats.warnings += 1
        else:
            skip(msg)
        return

    if not has_symbols(base):
        stats.no_symbols += 1
        warn(
            f"{name}: base {base} has no __symbols__ "
            f"(rebuild dtbs with DTC_FLAGS=-@); label overlays will fail"
        )
        stats.warnings += 1
        # still try — path-based fragments may work

    edges = load_deps(board / "dt.deps")
    overlays = unique_overlays(dt_dir)
    if not overlays:
        stats.skip_empty += 1
        if verbose:
            skip(f"{name}: no overlays under {dt_dir}")
        return

    with tempfile.TemporaryDirectory(prefix=f"lwt-fdt-{name}-") as tmp:
        tmp_path = Path(tmp)
        for stem, dtbo in overlays:
            if not dtbo.is_file():
                # try resolve via realpath of .dts sibling after make
                stats.missing_dtbo += 1
                try:
                    rel = dtbo.relative_to(ROOT)
                except ValueError:
                    rel = dtbo
                warn(f"{name}: missing {rel} (run make BOARD_NAME={name})")
                stats.warnings += 1
                continue

            chain_names = expand_chain(stem, edges)
            chain_paths: list[Path] = []
            missing = False
            for cn in chain_names:
                p = dt_dir / f"{cn}.dtbo"
                if not p.is_file():
                    # provider may live only as cross-dir content — resolve via .dts
                    dts = dt_dir / f"{cn}.dts"
                    if dts.is_file():
                        try:
                            p = dts.resolve().with_suffix(".dtbo")
                        except OSError:
                            p = dt_dir / f"{cn}.dtbo"
                if not p.is_file():
                    warn(
                        f"{name}: chain for {stem} missing provider/consumer "
                        f"dtbo {cn}.dtbo"
                    )
                    stats.warnings += 1
                    stats.missing_dtbo += 1
                    missing = True
                    break
                chain_paths.append(p)
            if missing:
                continue

            out = tmp_path / f"{stem}.dtb"
            rc, err = run_fdtoverlay(fdtoverlay, base, chain_paths, out)
            if rc == 0:
                stats.ok += 1
                if verbose:
                    print(f"OK {name}: {' + '.join(chain_names)}", file=sys.stderr)
            else:
                stats.fail += 1
                stats.warnings += 1
                err_one = err.replace("\n", " | ")[:400] if err else f"exit {rc}"
                warn(
                    f"{name}: fdtoverlay failed for {stem} "
                    f"(chain: {' '.join(chain_names)}): {err_one}"
                )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--board", default=None, help="limit to libre-computer/<board>")
    ap.add_argument(
        "--dtb-dir",
        action="append",
        default=[],
        metavar="DIR",
        help="directory containing vendor/*.dtb (repeatable); "
        "also LWT_DTB_DIR (colon-separated)",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 if any WARNING",
    )
    ap.add_argument(
        "--require-base",
        action="store_true",
        help="WARNING (not SKIP) when board base DTB is not found",
    )
    ap.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="print OK lines and empty-board skips",
    )
    ap.add_argument(
        "--fdtoverlay",
        default=os.environ.get("FDTOVERLAY", "fdtoverlay"),
        help="fdtoverlay binary (default: PATH or $FDTOVERLAY)",
    )
    args = ap.parse_args()

    if not shutil.which(args.fdtoverlay) and not Path(args.fdtoverlay).is_file():
        warn(f"fdtoverlay not found ({args.fdtoverlay!r}); install device-tree-compiler")
        return 1 if args.strict else 0

    roots = home_paths()
    for d in args.dtb_dir:
        p = Path(d)
        if p.is_dir():
            roots.insert(0, p.resolve())
        else:
            warn(f"--dtb-dir not a directory: {d}")

    if not roots:
        info("no DTB search roots (set LWT_DTB_DIR); all boards will SKIP")
    elif args.verbose:
        info("DTB roots: " + ", ".join(str(r) for r in roots[:8]))

    stats = Stats()
    boards = board_dirs(args.board)
    if not boards:
        warn(f"no board dirs for filter={args.board!r}")
        stats.warnings += 1
    for board in boards:
        check_board(
            board,
            roots,
            args.fdtoverlay,
            require_base=args.require_base,
            verbose=args.verbose,
            stats=stats,
        )

    info(
        f"{stats.ok} ok, {stats.fail} fail, "
        f"{stats.skip_base} skip(no-base), {stats.missing_dtbo} missing-dtbo, "
        f"{stats.warnings} warning(s)"
        + (f" (board={args.board})" if args.board else "")
    )

    if args.strict and stats.warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
