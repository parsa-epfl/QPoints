CC ?= gcc

CFLAGS := -O2 -std=c11 -Wall -Wextra -fno-tree-vectorize \
	-fno-unroll-loops -fno-aggressive-loop-optimizations -fno-builtin \
	-fno-if-conversion -fno-if-conversion2

TARGET := l1d_frontend_mix
SRC := l1d_frontend_mix.c

.PHONY: all clean

all: $(TARGET)

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f $(TARGET)
