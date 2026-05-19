CC ?= gcc

CFLAGS := -O2 -std=c11 -Wall -Wextra -fno-tree-vectorize \
	-fno-unroll-loops -fno-aggressive-loop-optimizations -fno-builtin

TARGET := l1d_resident_rw
SRC := l1d_resident_rw.c

.PHONY: all clean

all: $(TARGET)

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f $(TARGET)
