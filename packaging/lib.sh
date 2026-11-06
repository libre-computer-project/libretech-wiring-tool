# SPDX-License-Identifier: GPL-2.0-only
# packaging/lib.sh -- shared by build-rpm.sh and build-arch.sh: build the tree once, as the .deb does, and split it.
#
# The Fedora and Arch packages carry exactly what the .deb packages carry: the tree `make install` stages, split by
# the same debian/<package>.install lists, so the three formats cannot drift apart. Every staged file must be
# claimed by exactly one package (as dh_missing enforces for the .deb).

PKG_ROOT=$(dirname "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")")
readonly PKG_ROOT
readonly PREFIX_REL=opt/librecomputer/libretech-wiring-tool
readonly PACKAGES=(libretech-gpio libretech-dtoverlay)
readonly BUILD_HOST=deb.libre.computer      # what a package header names, never the machine that built it

log() { printf '%s: %s\n' "$(basename "$0")" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

# <src tree> <scratch>: `make` and `make install` in a copy of the source (an exported commit: an untracked file in
# a working tree must never reach a package), staged under <scratch>/root
stage_tree() {
  local src=$1 t=$2
  [[ -f $src/Makefile && -d $src/debian ]] || die "$src is not a libretech-wiring-tool source tree"
  mkdir -p "$t/src" "$t/root"
  cp -a "$src/." "$t/src/"
  make -C "$t/src" -j"$(nproc)" >"$t/make.log" 2>&1 || { tail -20 "$t/make.log" >&2; die "make failed"; }
  make -C "$t/src" install DESTDIR="$t/root" >"$t/install.log" 2>&1 ||
    { tail -20 "$t/install.log" >&2; die "make install failed"; }
}

# <scratch>: write <scratch>/<package>.list for each package -- the paths its debian/<package>.install names, as
# found under <scratch>/root (a directory entry carries everything under it) -- and refuse a staged file that no
# package or two packages claim
split_tree() {
  local t=$1 p pat m rel
  shopt -s nullglob
  for p in "${PACKAGES[@]}"; do
    : >"$t/$p.list"
    while IFS= read -r pat; do
      [[ -z $pat || $pat == \#* ]] && continue
      local hits=0
      for m in "$t/root/"$pat; do
        printf '%s\n' "${m#"$t/root/"}" >>"$t/$p.list"
        hits=$((hits + 1))
      done
      ((hits > 0)) || die "debian/$p.install: '$pat' matches nothing staged"
    done <"$t/src/debian/$p.install"
  done
  shopt -u nullglob
  # every staged file or link, claimed by exactly one package
  local unclaimed=0 twice=0 n
  while IFS= read -r rel; do
    n=0
    for p in "${PACKAGES[@]}"; do
      while IFS= read -r m; do
        if [[ $rel == "$m" || $rel == "$m"/* ]]; then n=$((n + 1)); break; fi
      done <"$t/$p.list"
    done
    ((n == 0)) && { log "unclaimed: $rel"; unclaimed=$((unclaimed + 1)); }
    ((n > 1)) && { log "claimed twice: $rel"; twice=$((twice + 1)); }
  done < <(cd "$t/root" && find . \( -type f -o -type l \) -printf '%P\n' | sort)
  ((unclaimed == 0 && twice == 0)) || die "$unclaimed staged file(s) in no package, $twice in two"
}

# <version>: YYYY.MM.DD, the .deb's version scheme
check_version() {
  [[ $1 =~ ^[0-9]{4}\.[0-9]{2}\.[0-9]{2}$ ]] || die "version $1 is not YYYY.MM.DD"
}
