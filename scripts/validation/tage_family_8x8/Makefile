CC ?= gcc

CFLAGS := -O2 -std=c11 -Wall -Wextra -Werror -fno-tree-vectorize -fno-unroll-loops -fno-if-conversion

UBENCH := tage_family_8x8
UBENCH_AARCH64 := tage_family_8x8.aarch64
ARMCC := aarch64-linux-gnu-gcc

.PHONY: all guest clean

all: $(UBENCH) $(UBENCH_AARCH64)

guest: $(UBENCH)

$(UBENCH): tage_family_8x8.c
	$(CC) $(CFLAGS) -o $@ $<

$(UBENCH_AARCH64): tage_family_8x8.c
	$(ARMCC) $(CFLAGS) -o $@ $<

clean:
	rm -f $(UBENCH) $(UBENCH_AARCH64)
