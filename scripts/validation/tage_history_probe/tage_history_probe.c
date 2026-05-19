#include <stdint.h>

static volatile uint64_t sink;

static inline uint64_t rotl64(uint64_t value, unsigned int shift)
{
    return (value << shift) | (value >> (64U - shift));
}

int main(void)
{
    uint64_t acc = 0x243f6a8885a308d3ULL;
    uint8_t state = 0x5U;

    while (1) {
        unsigned int next = ((state >> 2) ^ state) & 0x1U;

        if (next != 0U) {
            acc += 0x9e3779b97f4a7c15ULL;
            acc = rotl64(acc ^ (uint64_t)state, 7U);
        } else {
            acc ^= 0xbf58476d1ce4e5b9ULL;
            acc = rotl64(acc + (uint64_t)state, 11U);
        }

        acc ^= 0x0101010101010101ULL * (uint64_t)(next + 1U);
        state = (uint8_t)(((state << 1) | next) & 0x7U);
        sink = acc ^ (uint64_t)state;
    }

    return 0;
}
