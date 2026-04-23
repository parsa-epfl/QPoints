#include <stdint.h>
#include <stddef.h>

#define CACHE_LINE_BYTES 64
#define ARRAY_BYTES (512 * 1024)
#define ARRAY_WORDS (ARRAY_BYTES / sizeof(uint64_t))
#define STRIDE_WORDS (CACHE_LINE_BYTES / sizeof(uint64_t))

static uint64_t array[ARRAY_WORDS] __attribute__((aligned(CACHE_LINE_BYTES)));
static volatile uint64_t sink;

static void __attribute__((noinline)) init_array(void)
{
    size_t i;

    for (i = 0; i < ARRAY_WORDS; ++i) {
        array[i] = (uint64_t)i;
    }
}

int main(void)
{
    init_array();

    while (1) {
        uint64_t checksum = 0;
        size_t i;

        for (i = 0; i < ARRAY_WORDS; i += STRIDE_WORDS) {
            uint64_t value = array[i];
            value += 1;
            array[i] = value;
            checksum ^= value;
        }

        sink = checksum;
    }

    return 0;
}
