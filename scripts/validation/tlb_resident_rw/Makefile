CC ?= gcc

CFLAGS := -O2 -std=c11 -Wall -Wextra -fno-tree-vectorize \
	-fno-unroll-loops -fno-aggressive-loop-optimizations -fno-builtin

TARGET := tlb_resident_rw
SRC := tlb_resident_rw.c

.PHONY: all clean

all: $(TARGET)

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f $(TARGET)
