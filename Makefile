GCC?=gcc
DTC?=dtc
DTC_OPTIONS?=-@ -q

OBJECTS:= $(patsubst %.dts,%.dtbo,$(wildcard libre-computer/*/*.dts))

all: $(OBJECTS)

%.pre.dts: %.dts
	@echo "CC	$^"
	@$(GCC) -E -nostdinc -I$(CURDIR)/include -I$(CURDIR) -x assembler-with-cpp -undef -o $@ $^

%.dtbo: %.pre.dts
	@echo "DTC	$^"
	@$(DTC) $(DTC_OPTIONS) -I dts -O dtb -o $@ $^

clean:
	@echo "RM	$(OBJECTS)"
	@rm -f $(OBJECTS)
