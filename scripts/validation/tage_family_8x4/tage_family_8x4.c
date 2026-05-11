#include <stdint.h>

static volatile uint64_t sink;

enum {
    FAMILY_COUNT = 4,
    BRANCHES_PER_FAMILY = 8,
    FAMILY_ITERS = 64,
};

static const uint64_t kTakenAdd[BRANCHES_PER_FAMILY] = {
    0x9e3779b97f4a7c15ULL,
    0xc2b2ae3d27d4eb4fULL,
    0x165667b19e3779f9ULL,
    0x85ebca77c2b2ae63ULL,
    0x27d4eb2f165667c5ULL,
    0x94d049bb133111ebULL,
    0xbf58476d1ce4e5b9ULL,
    0x6c8e9cf570932bd5ULL,
};

static const uint64_t kNotTakenXor[BRANCHES_PER_FAMILY] = {
    0xd6e8feb86659fd93ULL,
    0xa4093822299f31d0ULL,
    0x13198a2e03707344ULL,
    0x243f6a8885a308d3ULL,
    0x082efa98ec4e6c89ULL,
    0x452821e638d01377ULL,
    0xbe5466cf34e90c6cULL,
    0xc0acf169b5f18a8cULL,
};

static const unsigned int kTakenRot[BRANCHES_PER_FAMILY] = {5U, 9U, 13U, 17U, 21U, 27U, 31U, 37U};
static const unsigned int kNotTakenRot[BRANCHES_PER_FAMILY] = {7U, 11U, 19U, 23U, 29U, 33U, 39U, 43U};

static inline uint64_t rotl64(uint64_t value, unsigned int shift)
{
    return (value << shift) | (value >> (64U - shift));
}

static inline uint8_t next_bit(uint8_t state)
{
    return (uint8_t)(((state >> 2) ^ state) & 0x1U);
}

static inline uint8_t advance_state(uint8_t state, uint8_t bit)
{
    return (uint8_t)(((state << 1) | bit) & 0x7U);
}

#define BRANCH_STEP(FAMILY, SLOT, LOCAL, ACC)                                              \
    do {                                                                                    \
        unsigned int bit_##FAMILY##_##SLOT = next_bit((LOCAL));                             \
        if (bit_##FAMILY##_##SLOT != 0U) {                                                  \
            (ACC) += kTakenAdd[(SLOT)] ^ ((uint64_t)(FAMILY) << ((SLOT) + 1U));            \
            (ACC) = rotl64(                                                                 \
                (ACC) ^ ((uint64_t)(LOCAL) + ((uint64_t)(FAMILY) << 8U)),                  \
                kTakenRot[(SLOT)]);                                                         \
        } else {                                                                            \
            (ACC) ^= kNotTakenXor[(SLOT)] + ((uint64_t)(FAMILY) << 12U);                   \
            (ACC) = rotl64(                                                                 \
                (ACC) + ((uint64_t)(LOCAL) << ((SLOT) & 3U)),                              \
                kNotTakenRot[(SLOT)]);                                                      \
        }                                                                                   \
        (ACC) ^= 0x0101010101010101ULL *                                                    \
                 (uint64_t)(bit_##FAMILY##_##SLOT + 1U + (FAMILY) + (SLOT));               \
        (LOCAL) = advance_state((LOCAL), (uint8_t)bit_##FAMILY##_##SLOT);                  \
    } while (0)

#define RUN_FAMILY(FAMILY, STATE, ACC)                                                      \
    do {                                                                                    \
        uint32_t remaining_##FAMILY = FAMILY_ITERS;                                         \
        do {                                                                                \
            uint8_t local_##FAMILY = (STATE);                                               \
            BRANCH_STEP(FAMILY, 0, local_##FAMILY, (ACC));                                  \
            BRANCH_STEP(FAMILY, 1, local_##FAMILY, (ACC));                                  \
            BRANCH_STEP(FAMILY, 2, local_##FAMILY, (ACC));                                  \
            BRANCH_STEP(FAMILY, 3, local_##FAMILY, (ACC));                                  \
            BRANCH_STEP(FAMILY, 4, local_##FAMILY, (ACC));                                  \
            BRANCH_STEP(FAMILY, 5, local_##FAMILY, (ACC));                                  \
            BRANCH_STEP(FAMILY, 6, local_##FAMILY, (ACC));                                  \
            BRANCH_STEP(FAMILY, 7, local_##FAMILY, (ACC));                                  \
            (STATE) = local_##FAMILY;                                                       \
            --remaining_##FAMILY;                                                           \
        } while (remaining_##FAMILY != 0U);                                                 \
    } while (0)

int main(void)
{
    uint64_t acc = 0x243f6a8885a308d3ULL;
    uint8_t state0 = 0x5U;
    uint8_t state1 = 0x3U;
    uint8_t state2 = 0x6U;
    uint8_t state3 = 0x7U;

    while (1) {
        RUN_FAMILY(0, state0, acc);
        RUN_FAMILY(1, state1, acc);
        RUN_FAMILY(2, state2, acc);
        RUN_FAMILY(3, state3, acc);

        acc ^= 0x9e3779b97f4a7c15ULL;
        acc = rotl64(acc + (uint64_t)(state0 ^ state1 ^ state2 ^ state3), 17U);
        sink = acc ^ (uint64_t)(state0 | (state1 << 3) | (state2 << 6) | (state3 << 9));
    }

    return 0;
}
