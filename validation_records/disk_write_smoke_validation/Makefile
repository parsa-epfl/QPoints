CC ?= gcc

CFLAGS := -O2 -std=c11 -Wall -Wextra -Werror

UBENCH := guest_disk_trace_ubench
UBENCH_AARCH64 := guest_disk_trace_ubench.arm64
ARMCC := aarch64-linux-gnu-gcc
ARM_CFLAGS := -O0 -g -std=c11 -Wall -Wextra -Werror -fno-pie -no-pie -static

.PHONY: all guest clean

all: $(UBENCH) $(UBENCH_AARCH64)

guest: $(UBENCH_AARCH64)

$(UBENCH): guest_disk_trace_ubench.c
	$(CC) $(CFLAGS) -o $@ $<

$(UBENCH_AARCH64): guest_disk_trace_ubench.c
	$(ARMCC) $(ARM_CFLAGS) -o $@ $<

clean:
	rm -f $(UBENCH) $(UBENCH_AARCH64)
