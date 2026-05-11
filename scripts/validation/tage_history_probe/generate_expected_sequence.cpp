#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <string>

namespace {

// These are the branch PCs observed in the current AArch64 lowering of
// tage_history_probe.c, built with the companion Makefile flags.
constexpr uint64_t kHotConditionalPc = 0x65c;
constexpr uint64_t kLoopBackPc = 0x688;
constexpr uint8_t kConditionalType = 0;
constexpr uint8_t kUnconditionalType = 1;
constexpr uint8_t kInitialState = 0x5;

uint8_t next_bit(uint8_t state)
{
    return static_cast<uint8_t>(((state >> 2) ^ state) & 0x1U);
}

void usage(const char *argv0)
{
    std::cerr << "Usage: " << argv0
              << " <iterations> <output.csv>\n";
}

} // namespace

int main(int argc, char **argv)
{
    if (argc != 3) {
        usage(argv[0]);
        return 1;
    }

    const uint64_t iterations = std::strtoull(argv[1], nullptr, 10);
    const std::string output_path = argv[2];

    if (iterations == 0) {
        std::cerr << "iterations must be > 0\n";
        return 1;
    }

    std::ofstream out(output_path);
    if (!out) {
        std::cerr << "failed to open output file: " << output_path << "\n";
        return 1;
    }

    out << "sequence_index,iteration,pc,branch_type,actual_direction\n";

    uint8_t state = kInitialState;
    uint64_t sequence_index = 0;

    for (uint64_t iter = 0; iter < iterations; ++iter) {
        const uint8_t bit = next_bit(state);

        out << sequence_index++ << ','
            << iter << ",0x" << std::hex << kHotConditionalPc << std::dec << ','
            << static_cast<unsigned>(kConditionalType) << ','
            << static_cast<unsigned>(bit) << '\n';

        out << sequence_index++ << ','
            << iter << ",0x" << std::hex << kLoopBackPc << std::dec << ','
            << static_cast<unsigned>(kUnconditionalType) << ','
            << 1 << '\n';

        state = static_cast<uint8_t>(((state << 1) | bit) & 0x7U);
    }

    std::cerr << "Generated " << sequence_index
              << " branch events for " << iterations
              << " loop iterations into " << output_path << "\n";
    return 0;
}
