CC := gcc
CXX := g++

CFLAGS := -O2 -std=c11 -Wall -Wextra -Werror -fno-tree-vectorize -fno-unroll-loops -fno-if-conversion
CXXFLAGS := -O2 -std=c++17 -Wall -Wextra -Werror

UBENCH := tage_history_probe
UBENCH_AARCH64 := tage_history_probe.aarch64
GENERATOR := generate_expected_sequence
SIMULATOR := simulate_wormcache_tage
ARMCC := aarch64-linux-gnu-gcc
ARMOBJDUMP := aarch64-linux-gnu-objdump

.PHONY: all clean

all: $(UBENCH) $(UBENCH_AARCH64) $(GENERATOR) $(SIMULATOR)

$(UBENCH): tage_history_probe.c
	$(CC) $(CFLAGS) -o $@ $<

$(UBENCH_AARCH64): tage_history_probe.c
	$(ARMCC) $(CFLAGS) -o $@ $<

$(GENERATOR): generate_expected_sequence.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

$(SIMULATOR): simulate_wormcache_tage.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

clean:
	rm -f $(UBENCH) $(UBENCH_AARCH64) $(GENERATOR) $(SIMULATOR)
