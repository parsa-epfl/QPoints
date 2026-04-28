#include <stddef.h>
#include <stdint.h>

#define CACHE_LINE_BYTES 64
#define DATA_BYTES (32 * 1024)
#define DATA_WORDS (DATA_BYTES / sizeof(uint64_t))
#define STRIDE_WORDS (CACHE_LINE_BYTES / sizeof(uint64_t))
#define STAGE_COUNT 32

typedef uint64_t (*stage_fn_t)(uint64_t, uint64_t, uint64_t);

static uint64_t data[DATA_WORDS] __attribute__((aligned(CACHE_LINE_BYTES)));
static volatile uint64_t sink;

static inline uint64_t rotl64(uint64_t value, unsigned int shift)
{
    return (value << shift) | (value >> (64U - shift));
}

static void __attribute__((noinline)) init_data(void)
{
    size_t i;

    for (i = 0; i < DATA_WORDS; ++i) {
        data[i] = 0x9e3779b97f4a7c15ULL ^ (uint64_t)(i * 17U);
    }
}

#define DEFINE_STAGE_FN(ID, ROT_A, ROT_B, XOR_A, ADD_A)                           \
    static uint64_t __attribute__((noinline)) stage##ID(                          \
        uint64_t value,                                                           \
        uint64_t history,                                                         \
        uint64_t token)                                                           \
    {                                                                             \
        uint64_t local = value ^ token ^ (XOR_A);                                 \
                                                                                  \
        if ((local & (1ULL << ((ID) & 7U))) == 0) {                               \
            local += (ADD_A);                                                     \
        } else {                                                                  \
            local ^= rotl64(history, (ROT_A));                                    \
        }                                                                         \
                                                                                  \
        if ((((history >> (((ID) % 11U) + 1U)) ^ token) & 0x10ULL) != 0) {       \
            local += rotl64(token, (ROT_B));                                      \
        } else {                                                                  \
            local ^= rotl64(token + history, (ROT_A));                            \
        }                                                                         \
                                                                                  \
        if (((token + (ADD_A)) & 0x100ULL) == 0) {                                \
            local ^= 0x0101010101010101ULL * (uint64_t)(((ID) & 7U) + 1U);        \
        } else {                                                                  \
            local += 0x0202020202020202ULL * (uint64_t)(((ID) & 3U) + 1U);        \
        }                                                                         \
                                                                                  \
        if (((history + token + (uint64_t)(ID)) & 0x400ULL) != 0) {              \
            local = rotl64(local ^ history, (ROT_B));                             \
        } else {                                                                  \
            local = rotl64(local + token, (ROT_A));                               \
        }                                                                         \
                                                                                  \
        switch ((unsigned int)((local >> (((ID) % 5U) + 2U)) & 0x3U)) {          \
        case 0:                                                                   \
            local += ((history & 0xffULL) + (ADD_A));                             \
            break;                                                                \
        case 1:                                                                   \
            local ^= ((token & 0xffULL) + (XOR_A));                               \
            break;                                                                \
        case 2:                                                                   \
            local += rotl64(history ^ token, ((ROT_A) % 13U) + 1U);               \
            break;                                                                \
        default:                                                                  \
            local ^= rotl64(local + token + (ADD_A), ((ROT_B) % 13U) + 1U);       \
            break;                                                                \
        }                                                                         \
                                                                                  \
        if (((local ^ history ^ token) & 0x800ULL) == 0) {                        \
            local += rotl64(local, ((ROT_A) % 17U) + 1U);                         \
        } else {                                                                  \
            local ^= rotl64(local, ((ROT_B) % 17U) + 1U);                         \
        }                                                                         \
                                                                                  \
        return local ^ ((XOR_A) + (ADD_A));                                       \
    }

DEFINE_STAGE_FN(0, 5U, 11U, 0x1111111111111111ULL, 0x0101010101010101ULL)
DEFINE_STAGE_FN(1, 7U, 13U, 0x2222222222222222ULL, 0x0202020202020202ULL)
DEFINE_STAGE_FN(2, 9U, 17U, 0x3333333333333333ULL, 0x0303030303030303ULL)
DEFINE_STAGE_FN(3, 11U, 19U, 0x4444444444444444ULL, 0x0404040404040404ULL)
DEFINE_STAGE_FN(4, 13U, 23U, 0x5555555555555555ULL, 0x0505050505050505ULL)
DEFINE_STAGE_FN(5, 15U, 27U, 0x6666666666666666ULL, 0x0606060606060606ULL)
DEFINE_STAGE_FN(6, 17U, 29U, 0x7777777777777777ULL, 0x0707070707070707ULL)
DEFINE_STAGE_FN(7, 19U, 31U, 0x8888888888888888ULL, 0x0808080808080808ULL)
DEFINE_STAGE_FN(8, 21U, 7U, 0x9999999999999999ULL, 0x0909090909090909ULL)
DEFINE_STAGE_FN(9, 23U, 9U, 0xaaaaaaaaaaaaaaaaULL, 0x0a0a0a0a0a0a0a0aULL)
DEFINE_STAGE_FN(10, 25U, 11U, 0xbbbbbbbbbbbbbbbbULL, 0x0b0b0b0b0b0b0b0bULL)
DEFINE_STAGE_FN(11, 27U, 13U, 0xccccccccccccccccULL, 0x0c0c0c0c0c0c0c0cULL)
DEFINE_STAGE_FN(12, 29U, 15U, 0xddddddddddddddddULL, 0x0d0d0d0d0d0d0d0dULL)
DEFINE_STAGE_FN(13, 31U, 17U, 0xeeeeeeeeeeeeeeeeULL, 0x0e0e0e0e0e0e0e0eULL)
DEFINE_STAGE_FN(14, 5U, 19U, 0xf0f0f0f0f0f0f0f0ULL, 0x0f0f0f0f0f0f0f0fULL)
DEFINE_STAGE_FN(15, 7U, 21U, 0x13579bdf2468ace0ULL, 0x1111111111111110ULL)
DEFINE_STAGE_FN(16, 9U, 23U, 0x2468ace013579bdfULL, 0x1212121212121212ULL)
DEFINE_STAGE_FN(17, 11U, 25U, 0x55aa55aa55aa55aaULL, 0x1313131313131313ULL)
DEFINE_STAGE_FN(18, 13U, 27U, 0xaa55aa55aa55aa55ULL, 0x1414141414141414ULL)
DEFINE_STAGE_FN(19, 15U, 29U, 0x0f1e2d3c4b5a6978ULL, 0x1515151515151515ULL)
DEFINE_STAGE_FN(20, 17U, 31U, 0x1021324354657687ULL, 0x1616161616161616ULL)
DEFINE_STAGE_FN(21, 19U, 5U, 0x89abcdef01234567ULL, 0x1717171717171717ULL)
DEFINE_STAGE_FN(22, 21U, 7U, 0x76543210fedcba98ULL, 0x1818181818181818ULL)
DEFINE_STAGE_FN(23, 23U, 9U, 0x3141592653589793ULL, 0x1919191919191919ULL)
DEFINE_STAGE_FN(24, 25U, 11U, 0x2718281828459045ULL, 0x1a1a1a1a1a1a1a1aULL)
DEFINE_STAGE_FN(25, 27U, 13U, 0xdeadbeefcafebabeULL, 0x1b1b1b1b1b1b1b1bULL)
DEFINE_STAGE_FN(26, 29U, 15U, 0xfeedface12345678ULL, 0x1c1c1c1c1c1c1c1cULL)
DEFINE_STAGE_FN(27, 31U, 17U, 0x0123456789abcdefULL, 0x1d1d1d1d1d1d1d1dULL)
DEFINE_STAGE_FN(28, 5U, 19U, 0xfedcba9876543210ULL, 0x1e1e1e1e1e1e1e1eULL)
DEFINE_STAGE_FN(29, 7U, 21U, 0x1122334455667788ULL, 0x1f1f1f1f1f1f1f1fULL)
DEFINE_STAGE_FN(30, 9U, 23U, 0x8877665544332211ULL, 0x2020202020202020ULL)
DEFINE_STAGE_FN(31, 11U, 25U, 0x7f4a7c159e3779b9ULL, 0x2121212121212121ULL)

static stage_fn_t stages[STAGE_COUNT] = {
    stage0,  stage1,  stage2,  stage3,  stage4,  stage5,  stage6,  stage7,
    stage8,  stage9,  stage10, stage11, stage12, stage13, stage14, stage15,
    stage16, stage17, stage18, stage19, stage20, stage21, stage22, stage23,
    stage24, stage25, stage26, stage27, stage28, stage29, stage30, stage31
};

int main(void)
{
    uint64_t history = 0x243f6a8885a308d3ULL;
    uint64_t phase = 0x13198a2e03707344ULL;
    uint32_t stage_cursor = 0;

    init_data();

    while (1) {
        uint64_t checksum = 0;
        size_t i;

        for (i = 0; i < DATA_WORDS; i += STRIDE_WORDS) {
            uint64_t value = data[i];
            uint64_t token = value ^ history ^ phase ^ (uint64_t)i;
            uint64_t local_history = history;
            unsigned int selector = stage_cursor & (STAGE_COUNT - 1U);

            if ((token & 0x1ULL) == 0) {
                value += token;
                local_history ^= 0x9e3779b97f4a7c15ULL;
            } else {
                value -= token;
                local_history += 0xbf58476d1ce4e5b9ULL;
            }

            if (((i / STRIDE_WORDS) & 0x7U) == 0U) {
                value ^= 0x0101010101010101ULL;
            } else {
                value += 0x0202020202020202ULL;
            }

            value = stages[selector](value, local_history, token);

            if (((local_history ^ phase ^ token) & 0x80ULL) != 0) {
                value ^= rotl64(local_history, 9U);
            } else {
                value += rotl64(phase, 7U);
            }

            data[i] = value;
            checksum ^= value;
            history = rotl64(local_history ^ value, 9U) + token + 0x94d049bb133111ebULL;
            phase = rotl64(phase + history + (uint64_t)i, 7U);
            stage_cursor = (stage_cursor + 1U) & (STAGE_COUNT - 1U);
        }

        sink = checksum ^ history ^ phase ^ (uint64_t)stage_cursor;
    }

    return 0;
}
