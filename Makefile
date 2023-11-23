DTC	?= dtc
DTC_OPTIONS	?= -@ -q
PREFIX ?= $(DESTDIR)/opt/librecomputer/libretech-wiring-tool

DESTGPIOMAPS	:= $(patsubst %,$(PREFIX)/%,$(wildcard libre-computer/*/gpio.map))
DESTDTMAPS	:= $(patsubst %,$(PREFIX)/%,$(wildcard libre-computer/*/dt.map))
DTOS	:= $(patsubst %.dts,%.dtbo,$(wildcard libre-computer/*/dt/*.dts))
DESTDTOCFG	:= $(patsubst %,$(PREFIX)/%,$(wildcard libre-computer/*/dt.config))
DESTDTBOS	:= $(patsubst %,$(PREFIX)/%,$(wildcard libre-computer/*/dt/*.dtbo))

.PHONY : clean install-lgpio install-ldto install

all: $(DTOS)

%.pre.dts: %.dts
	@if [ -L $(@D) ]; then \
		exit; \
	fi
	@echo "CC	$^"
	@$(CC) -E -nostdinc -Iinclude -x assembler-with-cpp -undef -o $@ $^

%.dtbo: %.pre.dts
	@if [ -L $(@D) ]; then \
		exit; \
	fi
	@echo "DTC	$^"
	@$(DTC) $(DTC_OPTIONS) -I dts -O dtb -o $@ $^

clean:
	rm -f $(DTOS)

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
	else \
		install -p -m 644 $(patsubst $(PREFIX)/%,%,$@) $@; \
	fi

install-ldto: boarddirs $(DESTDTOCFG) $(DESTDTMAPS) $(DESTDTBOS)
	install -p -m 755 ldto $(PREFIX)

install: install-lgpio install-ldto

