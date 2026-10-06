<!--
SPDX-License-Identifier: MIT
-->
# ldto — device-tree overlay tool

Apply Libre Computer device-tree overlays at runtime (configfs) or merge
them into the EFI/boot DTB for the next boot. Resolves `dt.map` aliases
and auto-applies providers from `dt.deps`.

Package: `libretech-dtoverlay` (depends on `device-tree-compiler`).  
Data: `libre-computer/<board>/dt/*.dtbo`, `dt.map`, `dt.deps`, `dt.config`.

## Board detection

Same DMI / `VENDOR` / `BOARD` as [lgpio](lgpio.md). Host-side (no configfs):

```bash
export VENDOR=libre-computer BOARD=aml-s905x-cc
./ldto list
./ldto info spi-cc-1cs
./ldto enable --dry-run spi-cc-1cs-ili9341
./ldto conflicts spi-cc-1cs-enc28j60 spi-cc-1cs-ili9341
```

Commands that **do not** require configfs: `help`, `list`, `info`,
`conflicts`, `enable --dry-run`, `merge --dry-run`. On a host without
`/sys/firmware/fdt` both dry-runs print the plan and run the pin/resource
conflict check, then report the `fdtoverlay` chain check as `SKIPPED`.  
Commands that **need configfs**: `enable` (apply), `disable`, `active`.  
Commands that need firmware/EFI DTB (not configfs): `merge`, `show`,
`diff`, `edit`, `reset`, `current`, `status` (lists configfs actives when
configfs is present).  
Testing: `LDTO_SYSROOT` prefixes every system path and `LDTO_EFI_DTB` names
the ESP `dtb/` directory; `make check-ldto` runs the merge lifecycle in a
scratch root.

## Commands

```text
ldto list
ldto status
ldto active [OVERLAY]
ldto enable [--dry-run|-n] [--no-preflight] OVERLAY [OVERLAY...]
ldto disable OVERLAY...
ldto info OVERLAY|ALIAS...
ldto conflicts [OVERLAY|ALIAS]...
ldto current
ldto merge [--dry-run|-n] [--force] OVERLAY...
ldto show [OVERLAY]
ldto diff
ldto edit
ldto reset
```

### list

Prints available overlays (`.dtbo`, or `.dts` if not built):

```text
OVERLAY                        ALIAS                    SUMMARY
spi-cc-1cs                     H40P_SPI_0_1CS           SPICC on Header 7J1
i2c-ao                         H40P_I2C_0               I2C_AO on Header 7J1
```

`SUMMARY` comes from the overlay DTS header (`Summary:` field).

### info

Description, requires / required-by (`dt.deps`), map aliases, GPIO
connections (DTS pads × `gpio.map`), and header pin notes.

```bash
ldto info spi-cc-1cs-enc28j60
ldto info H40P_SPI_0_1CS
```

### enable / disable

```bash
# Temporary (until reboot) via configfs
sudo ldto enable spi-cc-1cs-ili9341
# Providers from dt.deps applied first (e.g. spi-cc-1cs)

ldto enable --dry-run spi-cc-1cs-ili9341   # plan + pins + optional fdtoverlay chain check
ldto enable -n H40P_SPI_0_2CS_LCD_35
sudo ldto enable --no-preflight …          # skip conflict gate AND chain check (not recommended)

sudo ldto disable spi-cc-1cs-ili9341
```

**Autoload + clean apply:** `enable` expands `dt.deps`, then runs two gates
before touching configfs:

1. **Conflicts** — the same check as `ldto conflicts` over the plan plus the
   currently applied overlays.
2. **Chain preflight** — `fdtoverlay` of the new steps onto a live base:
   `/sys/firmware/fdt` with the currently applied overlays re-applied in
   `dt.deps` order (providers first).

If either gate fails it prints a `WARNING` (for the chain: `apply not clean
at overlay '…'`, the plan, and the steps that would have succeeded) and
**applies nothing**. An unreadable `/sys/firmware/fdt` is a failed preflight
too. `--no-preflight` skips **both** gates. If configfs fails mid-chain after
preflight, overlays applied in *this* command are rolled back.

A cycle in `dt.deps`, or a provider chain deeper than 16, is reported as a
`WARNING` and the command fails.

Hardware overlays can wedge the system if removed while in use — disable
carefully.

### conflicts

Pin occupancy for the named overlays (deps expanded) plus any **active**
overlays (configfs `status` = `applied`; leftover unapplied directories are
ignored) when configfs is present.

```bash
ldto conflicts spi-cc-1cs-enc28j60 spi-cc-1cs-ili9341
```

- **Occupancy** — every resolved header pin and which overlays claim it  
- **Conflicts** — same pin claimed by overlays that are **not** in a
  provider→consumer relationship (shared SPI bus pins between a bus
  overlay and its device are OK; two independent devices on the same pins
  are not)

Exit status `2` if conflicts are reported.

### merge / show / diff / edit / reset / current

Permanent path: merge overlays into the EFI DTB override (see board
`dt.config` for `DT_OVERRIDE` path). Effective after reboot.

```bash
sudo ldto merge spi-cc-1cs-ili9341
ldto merge --dry-run spi-cc-1cs-ili9341   # conflicts + chain preflight (no ESP write)
ldto show          # next-boot DTB as DTS
ldto show OVERLAY  # one overlay's .dtbo as DTS
sudo ldto diff     # running vs next-boot
sudo ldto edit     # hand-edit the next-boot DTB in $EDITOR (default vim)
sudo ldto reset    # remove override DTB (reboot before the next merge)
ldto status        # configfs actives, merged set, next-boot state
sudo ldto current  # running firmware DTB as DTS
```

`edit` decompiles the existing override to DTS, opens it in `$EDITOR`, and
recompiles it. If the decompile, the editor, or the recompile fails, the
override is left unchanged; otherwise the recompiled DTB replaces it, with its
merge record kept and marked edited (advisory). It needs an override to exist
(run `merge` first).

**Which DT boots:** U-Boot loads the override DTB if it exists, else its own
built-in DT. The override is a self-contained copy; it does not follow later
changes to the built-in DT (or to the NOR overlays U-Boot applies to it).

**Merge record:** every override ldto writes carries `/chosen` properties:
`libretech,ldto-merged` (the overlays merged, in order),
`libretech,ldto-base` (`builtin:<u-boot version>`, `override:<id>`, or
`override-unstamped` when it was merged onto an override with no record --
then the list holds only what ldto added), `libretech,ldto-edited` after
`edit`, and `libretech,ldto-id`, a hash of the DTB that changes with every
write. U-Boot and the EFI stub keep them, so the running system shows the
record of the DT it booted under `/proc/device-tree/chosen`.

**Autoload + atomic merge:** expands `dt.deps` (providers first). Overlays
already in the override's record are skipped (`already merged`; nothing new =
nothing to do). The new steps are conflict-checked against each other **and
against the overlays already merged** (runtime-only overlays are reported as
"gone after reboot", not gated), then applied to a **temp** copy of the
existing override -- or, with none, of this boot's DT with its per-boot
`/chosen` values removed (`kaslr-seed`, `rng-seed`, `u-boot,version`, the EFI
`linux,uefi-*` and kexec entries). Only if **every** step succeeds is the
stamped result installed to the ESP; otherwise `WARNING: merge aborted — ESP
override not modified`.

**Next boot vs this boot:** `status`, `merge` and `enable` compare the booted
DT's `libretech,ldto-id` with the override file:

| State | Meaning |
|---|---|
| `builtin` | no override; this boot used the built-in DT too |
| `sync` | the next boot loads the override this boot used |
| `pending-merge` / `changed` | the override was written or edited after this boot -- reboot to apply |
| `removed` | this boot runs an override that has since been removed (`reset`, deleted) -- reboot to apply |
| `replaced` | the override was overwritten by another tool (e.g. a kernel deploy); the overlays merged in this boot's DT are not in it |
| `tampered` | the override changed outside ldto; its record is advisory |
| `legacy` | an override with no ldto record: cannot compare |

`merge` **refuses** in state `removed`: with no override file its base would be
this boot's DT, which still holds the removed overlays. Reboot first, or
`--force`. For an override without a record, `reset` leaves a marker in
`/run/ldto` that has the same effect until the next boot.

A kernel package or deploy that writes the ESP DTB path replaces the override
(state `replaced`); merge the overlays again afterwards.

## Aliases (dt.map)

Board-agnostic names for common 40-pin functions (values are **canonical**
overlay basenames). A key names a **position**, not a SoC controller: it
means the same header pins on every board that has it, so a HAT that works
with `H40P_SPI_0_1CS` on one board works with it on all of them.

| Slot | Header pins (Raspberry Pi numbering) |
|---|---|
| `H40P_I2C_0` | 3 (SDA), 5 (SCL) |
| `H40P_I2C_1` | 27 (SDA), 28 (SCL) |
| `H40P_SPI_0_1CS` | 19 (MOSI), 21 (MISO), 23 (SCLK), 24 (CS0) |
| `H40P_SPI_0_2CS` | as `_1CS`, plus 26 (CS1) |
| `H40P_SPI_1_1CS` | 38 (MOSI), 40 (MISO), 12 (SCLK), 35 (CS0) -- the Pi's SPI1 pins, but not its signal order (Pi: 35 MISO, 40 SCLK, 12 CE0); a Pi SPI1 HAT does not work here |
| `H40P_UART_0` | 8 (TX), 10 (RX) -- no flow control |
| `H40P_UART_P<tx>_P<rx>` | a UART on the two named pins |
| `H40P_PWM_P<n>` | PWM on pin n |

Grammar: `H40P_<SLOT>[_<DEVICE>]`, where `<SLOT>` is a row above and
`_<DEVICE>` names what sits on that slot (`_DEV` for spidev, a panel or
sensor). Three rules follow, and `make check` enforces all of them:

- **Shared by at least two boards, at identical pins.** A key exists only
  when two or more boards (two `dt/` trees -- revisions sharing one `dt/`
  count once) map it, and every one of them muxes the same header pin
  positions. An overlay only one board has is enabled by its name.

- **Position, not controller.** A board whose controller cannot reach a
  slot's pins does not get that key. Its overlay is still there under its own
  name. For example, H3's SPI1 is on pins 22/32/36/37, so it has no
  `H40P_SPI_1_1CS`; `ldto enable spi-1-1cs` still works.
- **Nothing outside the grammar.** CPU operating points, NOR flash, a carrier
  board, a debug UART, a camera bus or audio (I2S) are not 40-pin header
  slots. They are enabled by overlay name and never get a `dt.map` key.

Use `ldto list` / `ldto info <alias>` for the board’s actual mapping.
Some PWM controllers expose two outputs via different overlays — only
enable one unless you know the board’s map.

## Dependencies (dt.deps)

Auto-generated (`make deps` / `scripts/overlay-deps.py`). `enable` and
`merge` expand consumers so bus overlays apply before devices.

## Related

- [overlays.md](overlays.md) — source layout, naming, headers  
- [gpio-map.md](gpio-map.md) — pinout cross-ref used by `info` / `conflicts`  
- [README.md](../README.md) — index  
