CC ?= gcc
CXX ?= g++

CFLAGS := -O2 -std=c11 -Wall -Wextra -Werror -fno-tree-vectorize -fno-unroll-loops -fno-if-conversion
CXXFLAGS := -O2 -std=c++17 -Wall -Wextra -Werror

UBENCH := tage_family_8x4
UBENCH_AARCH64 := tage_family_8x4.aarch64
GENERATOR := generate_expected_sequence
SIMULATOR := simulate_wormcache_tage
ARMCC := aarch64-linux-gnu-gcc
SIMULATOR_SRC := simulate_sequence_driver.cpp

.PHONY: all clean

all: $(UBENCH) $(UBENCH_AARCH64) $(GENERATOR) $(SIMULATOR)

$(UBENCH): tage_family_8x4.c
	$(CC) $(CFLAGS) -o $@ $<

$(UBENCH_AARCH64): tage_family_8x4.c
	$(ARMCC) $(CFLAGS) -o $@ $<

$(GENERATOR): generate_expected_sequence.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

$(SIMULATOR): $(SIMULATOR_SRC)
	$(CXX) $(CXXFLAGS) -o $@ $<

clean:
	rm -f $(UBENCH) $(UBENCH_AARCH64) $(GENERATOR) $(SIMULATOR)
