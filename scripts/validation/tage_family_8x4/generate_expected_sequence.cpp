#include <array>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <string>

namespace {

constexpr uint8_t kTargetConditionalType = 0;
constexpr uint8_t kLoopConditionalType = 1;
constexpr uint8_t kUnconditionalType = 2;
constexpr uint8_t kNoFamily = 0xff;
constexpr uint8_t kNoBranch = 0xff;

constexpr std::size_t kFamilyCount = 4;
constexpr std::size_t kBranchesPerFamily = 8;
constexpr std::size_t kFamilyIterations = 64;

constexpr std::array<uint8_t, kFamilyCount> kInitialState = {0x5, 0x3, 0x6, 0x7};

struct FamilyLayout {
    uint64_t entry_pc;
    std::array<uint64_t, kBranchesPerFamily> conditional_pc;
    std::array<bool, kBranchesPerFamily> branch_on_one;
    std::array<uint64_t, kBranchesPerFamily> companion_unconditional_pc;
    uint64_t loop_eq_pc;
    uint64_t loop_ne_pc;
    // Families 0 and 2 use split loop-control sites after the final conditional,
    // while families 1 and 3 rejoin before a shared exit test.
    bool uses_split_loop_conditional;
};

constexpr uint64_t kOuterLoopPc = 0x1448;

constexpr std::array<FamilyLayout, kFamilyCount> kFamilyLayout = {{
    {
        0x694,
        {0x8a8, 0x6cc, 0x714, 0x75c, 0x7a4, 0x7ec, 0x834, 0x86c},
        {true, false, false, false, false, false, false, false},
        {0x8c8, 0xca4, 0xc84, 0xc64, 0xc44, 0xc24, 0xc04, 0x0},
        0x898,
        0x8f4,
        true,
    },
    {
        0x9fc,
        {0xbe4, 0xa38, 0xa74, 0xab0, 0xaec, 0xb28, 0xb64, 0xba0},
        {true, false, false, false, false, false, false, false},
        {0xbf4, 0xd14, 0xd04, 0xcf4, 0xce4, 0xcd4, 0xcc4, 0xcb4},
        0xbd4,
        0x0,
        false,
    },
    {
        0xe1c,
        {0x1000, 0xe58, 0xe94, 0xed0, 0xf0c, 0xf48, 0xf84, 0xfc0},
        {true, false, false, false, false, false, false, false},
        {0x1010, 0x13a0, 0x1390, 0x1380, 0x1370, 0x1360, 0x1350, 0x0},
        0xff0,
        0x103c,
        true,
    },
    {
        0x1148,
        {0x1330, 0x1184, 0x11c0, 0x11fc, 0x1238, 0x1274, 0x12b0, 0x12ec},
        {true, false, false, false, false, false, false, false},
        {0x1340, 0x1410, 0x1400, 0x13f0, 0x13e0, 0x13d0, 0x13c0, 0x13b0},
        0x1320,
        0x0,
        false,
    },
}};

uint8_t next_bit(uint8_t state)
{
    return static_cast<uint8_t>(((state >> 2) ^ state) & 0x1U);
}

uint8_t advance_state(uint8_t state, uint8_t bit)
{
    return static_cast<uint8_t>(((state << 1) | bit) & 0x7U);
}

bool emit_companion_unconditional(std::size_t branch, bool branch_taken)
{
    // The head tbnz branch emits its join branch on the not-taken path.
    // The later tbz branches emit their join branches on the taken path.
    return branch == 0 ? !branch_taken : branch_taken;
}

void usage(const char *argv0)
{
    std::cerr << "Usage: " << argv0
              << " <outer_iterations> <output.csv>\n";
}

} // namespace

int main(int argc, char **argv)
{
    if (argc != 3) {
        usage(argv[0]);
        return 1;
    }

    const uint64_t outer_iterations = std::strtoull(argv[1], nullptr, 10);
    const std::string output_path = argv[2];

    if (outer_iterations == 0) {
        std::cerr << "outer_iterations must be > 0\n";
        return 1;
    }

    std::ofstream out(output_path);
    if (!out) {
        std::cerr << "failed to open output file: " << output_path << "\n";
        return 1;
    }

    out << "sequence_index,outer_iteration,family,iteration_in_family,branch_index,pc,branch_type,actual_direction\n";

    std::array<uint8_t, kFamilyCount> family_state = kInitialState;
    uint64_t sequence_index = 0;

    for (uint64_t outer = 0; outer < outer_iterations; ++outer) {
        for (std::size_t family = 0; family < kFamilyCount; ++family) {
            const FamilyLayout &layout = kFamilyLayout[family];

            out << sequence_index++ << ','
                << outer << ','
                << family << ','
                << 0 << ','
                << static_cast<unsigned>(0xf0) << ",0x"
                << std::hex << layout.entry_pc << std::dec << ','
                << static_cast<unsigned>(kUnconditionalType) << ','
                << 1U << '\n';

            for (std::size_t iter = 0; iter < kFamilyIterations; ++iter) {
                uint8_t local_state = family_state[family];
                bool branch7_taken = false;

                for (std::size_t branch = 0; branch < kBranchesPerFamily; ++branch) {
                    const uint8_t bit = next_bit(local_state);
                    const bool taken = layout.branch_on_one[branch] ? (bit != 0U) : (bit == 0U);

                    out << sequence_index++ << ','
                        << outer << ','
                        << family << ','
                        << iter << ','
                        << branch << ",0x" << std::hex << layout.conditional_pc[branch] << std::dec << ','
                        << static_cast<unsigned>(kTargetConditionalType) << ','
                        << static_cast<unsigned>(taken) << '\n';

                    const uint64_t companion_pc = layout.companion_unconditional_pc[branch];
                    if (companion_pc != 0 && emit_companion_unconditional(branch, taken)) {
                        out << sequence_index++ << ','
                            << outer << ','
                            << family << ','
                            << iter << ','
                            << static_cast<unsigned>(0x80U + branch) << ",0x"
                            << std::hex << companion_pc << std::dec << ','
                            << static_cast<unsigned>(kUnconditionalType) << ','
                            << 1U << '\n';
                    }

                    if (branch + 1U == kBranchesPerFamily) {
                        branch7_taken = taken;
                    }
                    local_state = advance_state(local_state, bit);
                }

                family_state[family] = local_state;

                const bool continue_loop = iter + 1U < kFamilyIterations;

                if (layout.uses_split_loop_conditional) {
                    const bool use_loop_ne = branch7_taken;
                    const uint64_t loop_pc = use_loop_ne ? layout.loop_ne_pc : layout.loop_eq_pc;
                    const bool loop_taken = use_loop_ne ? continue_loop : !continue_loop;
                    out << sequence_index++ << ','
                        << outer << ','
                        << family << ','
                        << iter << ','
                        << static_cast<unsigned>(kBranchesPerFamily) << ",0x"
                        << std::hex << loop_pc << std::dec << ','
                        << static_cast<unsigned>(kLoopConditionalType) << ','
                        << static_cast<unsigned>(loop_taken) << '\n';
                } else {
                    out << sequence_index++ << ','
                        << outer << ','
                        << family << ','
                        << iter << ','
                        << static_cast<unsigned>(kBranchesPerFamily) << ",0x"
                        << std::hex << layout.loop_eq_pc << std::dec << ','
                        << static_cast<unsigned>(kLoopConditionalType) << ','
                        << static_cast<unsigned>(!continue_loop) << '\n';
                }
            }
        }

        out << sequence_index++ << ','
            << outer << ','
            << static_cast<unsigned>(kNoFamily) << ','
            << 0 << ','
            << static_cast<unsigned>(kNoBranch) << ",0x" << std::hex << kOuterLoopPc << std::dec << ','
            << static_cast<unsigned>(kUnconditionalType) << ','
            << 1 << '\n';
    }

    std::cerr << "Generated " << sequence_index
              << " branch events for " << outer_iterations
              << " outer iterations into " << output_path << "\n";
    return 0;
}
