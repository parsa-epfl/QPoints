#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>

namespace validation::tage_model {

constexpr std::size_t kCounterBits = 3;
constexpr std::size_t kLogBimodalEntries = 13;
constexpr std::size_t kNumHistoryTables = 7;
constexpr std::size_t kLogGlobalTableEntries = kLogBimodalEntries - 4;
constexpr std::size_t kTagBits = 12;
constexpr std::size_t kMaxHistoryBits = 131;
constexpr std::array<std::size_t, kNumHistoryTables> kHistoryLengths = {
    130, 76, 44, 25, 15, 9, 5};

struct FoldedHistory {
    uint32_t comp = 0;
    uint32_t c_length = 0;
    uint32_t o_length = 0;
    uint32_t out_point = 0;

    void init(uint32_t original_length, uint32_t compressed_length)
    {
        comp = 0;
        o_length = original_length;
        c_length = compressed_length;
        out_point = o_length % c_length;
    }

    void update(const std::array<bool, kMaxHistoryBits> &history)
    {
        comp = (comp << 1) | static_cast<uint32_t>(history[0]);
        comp ^= static_cast<uint32_t>(history[o_length]) << out_point;
        comp ^= comp >> c_length;
        comp &= (1U << c_length) - 1U;
    }
};

struct TAGEBiModalEntry {
    int8_t hyst = 1;
    int8_t pred = 0;
};

struct TAGEGlobalTableEntry {
    int8_t ctr = 0;
    uint16_t tag = 0;
    int8_t ubit = 0;
};

struct TAGEPrediction {
    bool result = false;
    std::size_t bank = kNumHistoryTables;
    bool alternate_prediction = false;
    std::size_t alternate_bank = kNumHistoryTables;
    std::array<std::size_t, kNumHistoryTables> gi = {};
    std::size_t bi = 0;
};

class WormCacheStyleTAGE {
  public:
    WormCacheStyleTAGE()
    {
        std::array<std::size_t, kNumHistoryTables> histories = {};
        histories[0] = kMaxHistoryBits - 1;
        histories[kNumHistoryTables - 1] = 5;
        for (std::size_t i = 1; i < kNumHistoryTables - 1; ++i) {
            const double base = static_cast<double>(kMaxHistoryBits - 1) / 5.0;
            const double exp =
                static_cast<double>(i) / static_cast<double>(kNumHistoryTables - 1);
            histories[kNumHistoryTables - 1 - i] =
                static_cast<std::size_t>(std::llround(5.0 * std::pow(base, exp)));
        }

        for (std::size_t idx = 0; idx < kNumHistoryTables; ++idx) {
            ch_i[idx].init(static_cast<uint32_t>(histories[idx]), kLogGlobalTableEntries);
            ch_t[0][idx].init(
                static_cast<uint32_t>(histories[idx]),
                static_cast<uint32_t>(
                    kTagBits - ((idx + (kNumHistoryTables & 1U)) / 2U)));
            ch_t[1][idx].init(
                static_cast<uint32_t>(histories[idx]),
                static_cast<uint32_t>(
                    kTagBits - ((idx + (kNumHistoryTables & 1U)) / 2U) - 1U));
        }
    }

    TAGEPrediction predict(uint64_t pc) const
    {
        return isConditionalTaken(pc);
    }

    void updateHistory(uint64_t pc, bool taken)
    {
        std::rotate(ghist.rbegin(), ghist.rbegin() + 1, ghist.rend());
        ghist[0] = taken;

        path_history = (path_history << 1) | static_cast<int32_t>((pc >> 2) & 1ULL);
        path_history &= (1 << 16) - 1;

        for (std::size_t idx = 0; idx < kNumHistoryTables; ++idx) {
            ch_i[idx].update(ghist);
            ch_t[0][idx].update(ghist);
            ch_t[1][idx].update(ghist);
        }
    }

    bool train(uint64_t pc, bool taken)
    {
        const TAGEPrediction prediction = isConditionalTaken(pc);
        bool allocation = prediction.result != taken && prediction.bank > 0;

        if (prediction.bank < kNumHistoryTables) {
            const auto &entry = gtable[prediction.bank][prediction.gi[prediction.bank]];
            const bool local_taken = entry.ctr >= 0;
            const bool pseudo_new_alloc =
                (std::abs(entry.ctr * 2 + 1) == 1) && (entry.ubit == 0);

            if (pseudo_new_alloc && local_taken == taken) {
                allocation = false;
            }
        }

        if (allocation) {
            int8_t min_ubit = 3;
            for (std::size_t idx = 0; idx < prediction.bank; ++idx) {
                min_ubit = std::min(
                    min_ubit, gtable[idx][prediction.gi[idx]].ubit);
            }

            if (min_ubit > 0) {
                for (std::size_t idx = 0; idx < prediction.bank; ++idx) {
                    gtable[idx][prediction.gi[idx]].ubit -= 1;
                }
            } else {
                int32_t y = getRandom() & ((1 << (prediction.bank - 1)) - 1);
                std::size_t x = prediction.bank - 1;
                while ((y & 1) != 0) {
                    x -= 1;
                    y >>= 1;
                }

                for (std::size_t idx = 0; idx <= x; ++idx) {
                    const std::size_t bank = x - idx;
                    auto &entry = gtable[bank][prediction.gi[bank]];
                    if (entry.ubit == min_ubit) {
                        entry.tag = computeTag(pc >> 2, bank);
                        entry.ctr = taken ? 0 : -1;
                        entry.ubit = 0;
                        break;
                    }
                }
            }
        }

        tick += 1;
        if ((tick & ((1 << 18) - 1)) == 0) {
            int32_t mask = (tick >> 18) & 1;
            if (mask == 0) {
                mask = 2;
            }
            for (std::size_t idx = 0; idx < kNumHistoryTables; ++idx) {
                for (std::size_t way = 0; way < (1U << kLogGlobalTableEntries); ++way) {
                    gtable[idx][way].ubit &= static_cast<int8_t>(mask);
                }
            }
        }

        if (prediction.bank < kNumHistoryTables) {
            auto &entry = gtable[prediction.bank][prediction.gi[prediction.bank]];
            entry.ctr = updateCounter(entry.ctr, taken, kCounterBits);
        } else {
            auto &entry = btable[prediction.bi];
            updateBimodalEntry(entry, prediction.result, taken);
        }

        if (prediction.result != prediction.alternate_prediction &&
            prediction.bank < kNumHistoryTables) {
            auto &entry = gtable[prediction.bank][prediction.gi[prediction.bank]];
            if (prediction.result == taken) {
                if (entry.ubit < 3) {
                    entry.ubit += 1;
                }
            } else if (entry.ubit > 0) {
                entry.ubit -= 1;
            }
        }

        updateHistory(pc, taken);
        return prediction.result == taken;
    }

  private:
    int32_t tick = 0;
    int32_t path_history = 0;
    std::array<bool, kMaxHistoryBits> ghist = {};
    std::array<FoldedHistory, kNumHistoryTables> ch_i = {};
    std::array<std::array<FoldedHistory, kNumHistoryTables>, 2> ch_t = {};
    std::array<TAGEBiModalEntry, 1 << kLogBimodalEntries> btable = {};
    std::array<std::array<TAGEGlobalTableEntry, 1 << kLogGlobalTableEntries>,
               kNumHistoryTables>
        gtable = {};
    int32_t seed = 0;

    static int8_t updateCounter(int8_t cnt, bool taken, std::size_t nbits)
    {
        const int8_t max = (1 << (nbits - 1)) - 1;
        const int8_t min = -max - 1;
        if (taken) {
            return cnt < max ? cnt + 1 : cnt;
        }
        return cnt > min ? cnt - 1 : cnt;
    }

    static void updateBimodalEntry(TAGEBiModalEntry &entry, bool predicted, bool taken)
    {
        if (predicted == taken) {
            if (taken) {
                if (entry.pred != 0) {
                    entry.hyst = 1;
                }
            } else if (entry.pred == 0) {
                entry.hyst = 0;
            }
        } else {
            int8_t inter = entry.pred * 2 + entry.hyst;
            if (taken) {
                if (inter < 3) {
                    inter += 1;
                }
            } else if (inter > 0) {
                inter -= 1;
            }
            entry.pred = inter >> 1;
            entry.hyst = inter & 1;
        }
    }

    std::size_t bimodalIndex(uint64_t shifted_pc) const
    {
        return static_cast<std::size_t>(shifted_pc & ((1ULL << kLogBimodalEntries) - 1));
    }

    std::size_t computeIndex(uint64_t shifted_pc, std::size_t bank) const
    {
        auto mixPath = [bank](uint32_t path_hist, std::size_t size) -> std::size_t {
            std::size_t a = static_cast<std::size_t>(path_hist) & ((1U << size) - 1U);
            const std::size_t a1 = a & ((1U << kLogGlobalTableEntries) - 1U);
            std::size_t a2 = a >> kLogGlobalTableEntries;
            a2 = ((a2 << bank) & ((1U << kLogGlobalTableEntries) - 1U)) +
                 (a2 >> (kLogGlobalTableEntries - bank));
            a = a1 ^ a2;
            return ((a << bank) & ((1U << kLogGlobalTableEntries) - 1U)) +
                   (a >> (kLogGlobalTableEntries - bank));
        };

        const uint64_t index_without_path =
            shifted_pc ^ (shifted_pc >> (kLogGlobalTableEntries - kNumHistoryTables + bank + 1)) ^
            static_cast<uint64_t>(ch_i[bank].comp);

        const uint64_t index =
            kHistoryLengths[bank] >= 16
                ? (index_without_path ^
                   static_cast<uint64_t>(mixPath(static_cast<uint32_t>(path_history), 16)))
                : (index_without_path ^
                   static_cast<uint64_t>(
                       mixPath(static_cast<uint32_t>(path_history), kHistoryLengths[bank])));

        return static_cast<std::size_t>(index & ((1U << kLogGlobalTableEntries) - 1U));
    }

    uint16_t computeTag(uint64_t shifted_pc, std::size_t bank) const
    {
        const uint64_t tag =
            shifted_pc ^ static_cast<uint64_t>(ch_t[0][bank].comp) ^
            static_cast<uint64_t>(ch_t[1][bank].comp << 1);
        const uint64_t mask =
            (1ULL << (kTagBits - ((bank + (kNumHistoryTables & 1U)) / 2U))) - 1ULL;
        return static_cast<uint16_t>(tag & mask);
    }

    TAGEPrediction isConditionalTaken(uint64_t pc) const
    {
        const uint64_t shifted_pc = pc >> 2;
        const std::size_t bi = bimodalIndex(shifted_pc);
        std::array<std::size_t, kNumHistoryTables> gi = {};
        for (std::size_t idx = 0; idx < kNumHistoryTables; ++idx) {
            gi[idx] = computeIndex(shifted_pc, idx);
        }

        std::size_t provider_bank = kNumHistoryTables;
        std::size_t alternate_bank = kNumHistoryTables;

        for (std::size_t idx = 0; idx < kNumHistoryTables; ++idx) {
            if (gtable[idx][gi[idx]].tag == computeTag(shifted_pc, idx)) {
                provider_bank = idx;
                break;
            }
        }

        for (std::size_t idx = provider_bank + 1; idx < kNumHistoryTables; ++idx) {
            if (gtable[idx][gi[idx]].tag == computeTag(shifted_pc, idx)) {
                alternate_bank = idx;
                break;
            }
        }

        if (provider_bank < kNumHistoryTables) {
            const bool alternate_prediction =
                alternate_bank < kNumHistoryTables
                    ? (gtable[alternate_bank][gi[alternate_bank]].ctr >= 0)
                    : (btable[bi].pred > 0);
            return {gtable[provider_bank][gi[provider_bank]].ctr >= 0,
                    provider_bank,
                    alternate_prediction,
                    alternate_bank,
                    gi,
                    bi};
        }

        const bool alternate_prediction = btable[bi].pred > 0;
        return {alternate_prediction,
                provider_bank,
                alternate_prediction,
                alternate_bank,
                gi,
                bi};
    }

    int32_t getRandom()
    {
        seed = ((1 << (2 * kNumHistoryTables)) + 1) * seed + 0xf3f531;
        seed &= (1 << (2 * kNumHistoryTables)) - 1;
        return seed;
    }
};

class BimodalBaseline {
  public:
    bool predict(uint64_t pc) const
    {
        return table[bimodalIndex(pc >> 2)].pred > 0;
    }

    void train(uint64_t pc, bool taken)
    {
        auto &entry = table[bimodalIndex(pc >> 2)];
        updateEntry(entry, predict(pc), taken);
    }

  private:
    std::array<TAGEBiModalEntry, 1 << kLogBimodalEntries> table = {};

    static void updateEntry(TAGEBiModalEntry &entry, bool predicted, bool taken)
    {
        if (predicted == taken) {
            if (taken) {
                if (entry.pred != 0) {
                    entry.hyst = 1;
                }
            } else if (entry.pred == 0) {
                entry.hyst = 0;
            }
        } else {
            int8_t inter = entry.pred * 2 + entry.hyst;
            if (taken) {
                if (inter < 3) {
                    inter += 1;
                }
            } else if (inter > 0) {
                inter -= 1;
            }
            entry.pred = inter >> 1;
            entry.hyst = inter & 1;
        }
    }

    static std::size_t bimodalIndex(uint64_t shifted_pc)
    {
        return static_cast<std::size_t>(shifted_pc & ((1ULL << kLogBimodalEntries) - 1));
    }
};

} // namespace validation::tage_model
