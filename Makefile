# SPDX-License-Identifier: GPL-2.0-only
DTC	?= dtc
DTC_OPTIONS	?= -@ -q
PREFIX ?= $(DESTDIR)/opt/librecomputer/libretech-wiring-tool

# LBS invokes: make BOARD_NAME=<lwt-board>
# Accept BOARD= as an alias (historical LBS comment; same meaning).
BOARD_FILTER := $(or $(BOARD_NAME),$(BOARD))

ifneq ($(BOARD_FILTER),)
  BOARD_DT := libre-computer/$(BOARD_FILTER)/dt
  ifeq ($(wildcard $(BOARD_DT)/.),)
    $(error LWT: no dt/ directory for BOARD_NAME=$(BOARD_FILTER) (expected $(BOARD_DT)))
  endif
  # Whole-dir symlink boards (e.g. aml-s905x-cc-v2/dt -> ../aml-s905x-cc/dt)
  # must compile the real tree: the pattern rules no-op when $(@D) is a
  # symlink, and LBS copies .dtbo via the symlink path either way.
  BOARD_DT_REAL := $(shell if [ -L "$(BOARD_DT)" ]; then readlink -f "$(BOARD_DT)"; else echo "$(BOARD_DT)"; fi)
  DT_DTS := $(wildcard $(BOARD_DT_REAL)/*.dts)
  ifeq ($(DT_DTS),)
    $(error LWT: no .dts overlays under $(BOARD_DT_REAL) (BOARD_NAME=$(BOARD_FILTER)))
  endif
else
  DT_DTS := $(wildcard libre-computer/*/dt/*.dts)
endif

# Same-dir alias .dts → .dtbo symlinks. Cross-dir .dts symlinks compile locally.
# Avoid `case`/`;;` inside $(shell) — make/sh mangles them into the recipe.
DT_DTS_REAL := $(shell for f in $(DT_DTS); do if [ ! -L "$$f" ]; then echo "$$f"; elif echo "$$(readlink "$$f")" | grep -q /; then echo "$$f"; fi; done)
DT_DTS_SYM  := $(shell for f in $(DT_DTS); do if [ -L "$$f" ] && ! echo "$$(readlink "$$f")" | grep -q /; then echo "$$f"; fi; done)
DTOS_REAL   := $(patsubst %.dts,%.dtbo,$(DT_DTS_REAL))
DTOS_SYM    := $(patsubst %.dts,%.dtbo,$(DT_DTS_SYM))
DTOS        := $(DTOS_REAL) $(DTOS_SYM)

DESTGPIOMAPS	:= $(patsubst %,$(PREFIX)/%,$(wildcard libre-computer/*/gpio.map))
DESTDTMAPS	:= $(patsubst %,$(PREFIX)/%,$(wildcard libre-computer/*/dt.map))
DESTDTOCFG	:= $(patsubst %,$(PREFIX)/%,$(wildcard libre-computer/*/dt.config))
DESTDTBOS	:= $(patsubst %,$(PREFIX)/%,$(wildcard libre-computer/*/dt/*.dtbo))
# Per-board auto-dependency tables (consumer -> provider).
ifneq ($(BOARD_FILTER),)
  DEPS_FILES := libre-computer/$(BOARD_FILTER)/dt.deps
else
  DEPS_BOARDS := $(sort $(foreach d,$(DT_DTS),$(word 2,$(subst /, ,$(d)))))
  DEPS_FILES := $(addprefix libre-computer/,$(addsuffix /dt.deps,$(DEPS_BOARDS)))
endif

.PHONY : clean install-lgpio install-ldto install deps

all: $(DTOS_REAL) $(DTOS_SYM) $(DEPS_FILES)

deps: $(DEPS_FILES)

# dt.deps is generated from .dts (not .dtbo); rebuild when sources change.
libre-computer/%/dt.deps: scripts/overlay-deps.py
	@dt=libre-computer/$*/dt; 	if [ -L "$$dt" ]; then dt=$$(readlink -f "$$dt"); fi; 	python3 scripts/overlay-deps.py "$$dt" -o $@

ifneq ($(strip $(DTOS_SYM)),)
$(DTOS_SYM): $(DTOS_REAL)
endif

# Real / cross-dir sources: cpp + dtc. Same-dir symlink .dts: .dtbo symlink only.
%.dtbo: %.dts
	@if [ -L $(@D) ]; then \
		exit 0; \
	fi
	@if [ -L "$<" ]; then \
		target=$$(readlink "$<"); \
		case "$$target" in \
		*/*) \
			echo "CC	$< (via $$target)"; \
			$(CC) -E -nostdinc -Iinclude -x assembler-with-cpp -undef -o $*.pre.dts $<; \
			echo "DTC	$*.pre.dts"; \
			$(DTC) $(DTC_OPTIONS) -I dts -O dtb -o $@ $*.pre.dts; \
			rm -f $*.pre.dts; \
			;; \
		*) \
			ln -fns "$${target%.dts}.dtbo" $@; \
			echo "LN	$@ -> $${target%.dts}.dtbo"; \
			;; \
		esac; \
	else \
		echo "CC	$<"; \
		$(CC) -E -nostdinc -Iinclude -x assembler-with-cpp -undef -o $*.pre.dts $<; \
		echo "DTC	$*.pre.dts"; \
		$(DTC) $(DTC_OPTIONS) -I dts -O dtb -o $@ $*.pre.dts; \
		rm -f $*.pre.dts; \
	fi

clean:
	rm -f $(DTOS) $(patsubst %.dtbo,%.pre.dts,$(DTOS)) $(DEPS_FILES)

boarddirs:
	mkdir -p $(PREFIX) $(patsubst %,$(PREFIX)/%,$(wildcard libre-computer/*))

dtodirs: boarddirs
	@for dtodir in $(wildcard libre-computer/*/dt); do \
		if [ -L $$dtodir ]; then \
			ln -fns $$(readlink $$dtodir) $(PREFIX)/$$dtodir; \
		else \
			mkdir -p $(PREFIX)/$$dtodir; \
		fi \
	done

$(PREFIX)/libre-computer/%/gpio.map: boarddirs
	@if [ -L $(patsubst $(PREFIX)/%,%,$@) ]; then \
		ln -fns $$(readlink $(patsubst $(PREFIX)/%,%,$@)) $@; \
	else \
		install -p -m 644 $(patsubst $(PREFIX)/%,%,$@) $@; \
	fi

install-lgpio: boarddirs $(DESTGPIOMAPS)
	install -p -m 755 lgpio $(PREFIX)

$(PREFIX)/libre-computer/%/dt.map: boarddirs
	@if [ -L $(patsubst $(PREFIX)/%,%,$@) ]; then \
		ln -fns $$(readlink $(patsubst $(PREFIX)/%,%,$@)) $@; \
	else \
		install -p -m 644 $(patsubst $(PREFIX)/%,%,$@) $@; \
	fi

$(PREFIX)/libre-computer/%/dt.config: boarddirs
	install -p -m 644 $(patsubst $(PREFIX)/%,%,$@) $@

$(PREFIX)/libre-computer/%.dtbo: boarddirs dtodirs
	@if [ -L $(@D) ]; then \
		exit; \
	fi
	@src=$(patsubst $(PREFIX)/%,%,$@); \
	srcdts=$${src%.dtbo}.dts; \
	if [ -L "$$srcdts" ]; then \
		target=$$(readlink "$$srcdts"); \
		case "$$target" in \
		*/*) install -p -m 644 "$$src" $@ ;; \
		*) ln -fns "$${target%.dts}.dtbo" $@ ;; \
		esac; \
	elif [ -L "$$src" ]; then \
		ln -fns $$(readlink "$$src") $@; \
	else \
		install -p -m 644 "$$src" $@; \
	fi

install-ldto: boarddirs $(DESTDTOCFG) $(DESTDTMAPS) $(DESTDTBOS) $(DEPS_FILES)
	install -p -m 755 ldto $(PREFIX)
	install -d -m 755 $(PREFIX)/scripts
	install -p -m 755 scripts/overlay-deps.py $(PREFIX)/scripts/overlay-deps.py
	@for f in $(DEPS_FILES); do 		if [ -f "$$f" ]; then 			install -p -m 644 "$$f" $(PREFIX)/$$f; 		fi; 	done

install: install-lgpio install-ldto

# --- SBOM / REUSE (optional; needs `reuse` from https://reuse.software/) ---
# Install: pipx install reuse   OR   python3 -m venv .venv && .venv/bin/pip install reuse
REUSE ?= reuse

.PHONY: reuse-lint sbom

reuse-lint:
	$(REUSE) lint

sbom:
	$(REUSE) spdx -o sbom.spdx
	@echo "Wrote sbom.spdx (SPDX SBOM). Re-run after license changes."

