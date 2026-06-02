#include <stddef.h>
#include <stdint.h>
#include <sys/mman.h>

#define CACHE_LINE_BYTES 64
#define PAGE_BYTES 4096
#define PAGE_COUNT 48
#define ARRAY_BYTES (PAGE_COUNT * PAGE_BYTES)
#define ARRAY_WORDS (ARRAY_BYTES / sizeof(uint64_t))
#define PAGE_STRIDE_WORDS (PAGE_BYTES / sizeof(uint64_t))

static uint64_t array[ARRAY_WORDS] __attribute__((aligned(PAGE_BYTES)));
static volatile uint64_t sink;

static void __attribute__((noinline)) init_array(void)
{
    size_t i;

    for (i = 0; i < ARRAY_WORDS; ++i) {
        array[i] = (uint64_t)i;
    }
}

static void __attribute__((noinline)) request_base_pages(void)
{
#ifdef MADV_NOHUGEPAGE
    (void)madvise((void *)array, ARRAY_BYTES, MADV_NOHUGEPAGE);
#endif
}

int main(void)
{
    init_array();
    request_base_pages();

    while (1) {
        uint64_t checksum = 0;
        size_t i;

        for (i = 0; i < ARRAY_WORDS; i += PAGE_STRIDE_WORDS) {
            uint64_t value = array[i];
            value += 1;
            array[i] = value;
            checksum ^= value;
        }

        sink = checksum;
    }

    return 0;
}
