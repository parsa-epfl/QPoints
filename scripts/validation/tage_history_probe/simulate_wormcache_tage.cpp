#include <array>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <string>
#include <vector>

#include "../common/wormcache_tage_model.hpp"

namespace {

using validation::tage_model::BimodalBaseline;
using validation::tage_model::kNumHistoryTables;
using validation::tage_model::TAGEPrediction;
using validation::tage_model::WormCacheStyleTAGE;

enum class BranchType : uint8_t {
    Conditional = 0,
    Unconditional = 1,
};

struct SequenceEntry {
    uint64_t sequence_index = 0;
    uint64_t iteration = 0;
    uint64_t pc = 0;
    BranchType type = BranchType::Conditional;
    bool taken = false;
};

bool parseEntry(const std::string &line, SequenceEntry &entry)
{
    if (line.empty() || line.rfind("sequence_index", 0) == 0) {
        return false;
    }

    std::stringstream ss(line);
    std::array<std::string, 5> fields = {};
    for (std::size_t i = 0; i < fields.size(); ++i) {
        if (!std::getline(ss, fields[i], ',')) {
            return false;
        }
    }

    entry.sequence_index = std::strtoull(fields[0].c_str(), nullptr, 10);
    entry.iteration = std::strtoull(fields[1].c_str(), nullptr, 10);
    entry.pc = std::strtoull(fields[2].c_str(), nullptr, 0);
    entry.type = static_cast<BranchType>(std::strtoul(fields[3].c_str(), nullptr, 10));
    entry.taken = std::strtoul(fields[4].c_str(), nullptr, 10) != 0;
    return true;
}

std::vector<uint64_t> checkpoints(uint64_t max_count)
{
    std::vector<uint64_t> values;
    for (uint64_t value = 10; value <= max_count; value *= 10) {
        values.push_back(value);
        if (value > std::numeric_limits<uint64_t>::max() / 10) {
            break;
        }
    }
    return values;
}

void usage(const char *argv0)
{
    std::cerr << "Usage: " << argv0 << " <sequence.csv> <hot_pc_hex>\n";
}

} // namespace

int main(int argc, char **argv)
{
    if (argc != 3) {
        usage(argv[0]);
        return 1;
    }

    const std::string input_path = argv[1];
    const uint64_t hot_pc = std::strtoull(argv[2], nullptr, 0);

    std::ifstream in(input_path);
    if (!in) {
        std::cerr << "failed to open sequence file: " << input_path << "\n";
        return 1;
    }

    WormCacheStyleTAGE tage;
    BimodalBaseline bimodal;

    uint64_t total_branches = 0;
    uint64_t conditional_branches = 0;
    uint64_t tage_cond_correct = 0;
    uint64_t bimodal_cond_correct = 0;

    uint64_t hot_count = 0;
    uint64_t tage_hot_correct = 0;
    uint64_t bimodal_hot_correct = 0;
    std::array<uint64_t, kNumHistoryTables> hot_tagged_provider = {};
    uint64_t hot_bimodal_provider = 0;

    const auto hot_checkpoints = checkpoints(1'000'000);
    std::size_t next_checkpoint = 0;

    std::string line;
    while (std::getline(in, line)) {
        SequenceEntry entry;
        if (!parseEntry(line, entry)) {
            continue;
        }

        ++total_branches;

        if (entry.type == BranchType::Conditional) {
            ++conditional_branches;
            const TAGEPrediction tage_pred = tage.predict(entry.pc);
            const bool bimodal_pred = bimodal.predict(entry.pc);
            const bool tage_correct = tage_pred.result == entry.taken;
            const bool bimodal_correct = bimodal_pred == entry.taken;

            tage_cond_correct += static_cast<uint64_t>(tage_correct);
            bimodal_cond_correct += static_cast<uint64_t>(bimodal_correct);

            if (entry.pc == hot_pc) {
                ++hot_count;
                tage_hot_correct += static_cast<uint64_t>(tage_correct);
                bimodal_hot_correct += static_cast<uint64_t>(bimodal_correct);

                if (tage_pred.bank < kNumHistoryTables) {
                    hot_tagged_provider[tage_pred.bank] += 1;
                } else {
                    hot_bimodal_provider += 1;
                }

                while (next_checkpoint < hot_checkpoints.size() &&
                       hot_count == hot_checkpoints[next_checkpoint]) {
                    const double tage_acc =
                        static_cast<double>(tage_hot_correct) /
                        static_cast<double>(hot_count);
                    const double bimodal_acc =
                        static_cast<double>(bimodal_hot_correct) /
                        static_cast<double>(hot_count);
                    std::cout << "checkpoint hot_count=" << hot_count
                              << " tage_hot_accuracy=" << std::fixed
                              << std::setprecision(6) << tage_acc
                              << " bimodal_hot_accuracy=" << bimodal_acc << "\n";
                    ++next_checkpoint;
                }
            }

            tage.train(entry.pc, entry.taken);
            bimodal.train(entry.pc, entry.taken);
        } else {
            tage.updateHistory(entry.pc, entry.taken);
        }
    }

    const double tage_cond_acc =
        conditional_branches == 0
            ? 0.0
            : static_cast<double>(tage_cond_correct) /
                  static_cast<double>(conditional_branches);
    const double bimodal_cond_acc =
        conditional_branches == 0
            ? 0.0
            : static_cast<double>(bimodal_cond_correct) /
                  static_cast<double>(conditional_branches);
    const double tage_hot_acc =
        hot_count == 0 ? 0.0
                       : static_cast<double>(tage_hot_correct) /
                             static_cast<double>(hot_count);
    const double bimodal_hot_acc =
        hot_count == 0 ? 0.0
                       : static_cast<double>(bimodal_hot_correct) /
                             static_cast<double>(hot_count);

    std::cout << "total_branches=" << total_branches << "\n";
    std::cout << "conditional_branches=" << conditional_branches << "\n";
    std::cout << "tage_conditional_accuracy=" << std::fixed << std::setprecision(6)
              << tage_cond_acc << "\n";
    std::cout << "bimodal_conditional_accuracy=" << bimodal_cond_acc << "\n";
    std::cout << "hot_pc=0x" << std::hex << hot_pc << std::dec << "\n";
    std::cout << "hot_branch_count=" << hot_count << "\n";
    std::cout << "tage_hot_accuracy=" << tage_hot_acc << "\n";
    std::cout << "bimodal_hot_accuracy=" << bimodal_hot_acc << "\n";
    std::cout << "hot_provider_bimodal=" << hot_bimodal_provider << "\n";
    for (std::size_t bank = 0; bank < kNumHistoryTables; ++bank) {
        std::cout << "hot_provider_tagged_bank_" << bank
                  << "=" << hot_tagged_provider[bank] << "\n";
    }

    return 0;
}
