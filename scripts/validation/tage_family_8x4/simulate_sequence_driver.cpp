#include <array>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
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
    TargetConditional = 0,
    LoopConditional = 1,
    Unconditional = 2,
};

struct SequenceEntry {
    uint64_t sequence_index = 0;
    uint64_t outer_iteration = 0;
    uint64_t family = 0;
    uint64_t iteration_in_family = 0;
    uint64_t branch_index = 0;
    uint64_t pc = 0;
    BranchType type = BranchType::TargetConditional;
    bool taken = false;
};

struct PerPcStats {
    uint64_t count = 0;
    uint64_t tage_correct = 0;
    uint64_t bimodal_correct = 0;
    std::array<uint64_t, kNumHistoryTables> tagged_provider = {};
    uint64_t bimodal_provider = 0;
};

bool parseEntry(const std::string &line, SequenceEntry &entry)
{
    if (line.empty() || line.rfind("sequence_index", 0) == 0) {
        return false;
    }

    std::stringstream ss(line);
    std::array<std::string, 8> fields = {};
    for (std::size_t i = 0; i < fields.size(); ++i) {
        if (!std::getline(ss, fields[i], ',')) {
            return false;
        }
    }

    entry.sequence_index = std::strtoull(fields[0].c_str(), nullptr, 10);
    entry.outer_iteration = std::strtoull(fields[1].c_str(), nullptr, 10);
    entry.family = std::strtoull(fields[2].c_str(), nullptr, 10);
    entry.iteration_in_family = std::strtoull(fields[3].c_str(), nullptr, 10);
    entry.branch_index = std::strtoull(fields[4].c_str(), nullptr, 10);
    entry.pc = std::strtoull(fields[5].c_str(), nullptr, 0);
    entry.type = static_cast<BranchType>(std::strtoul(fields[6].c_str(), nullptr, 10));
    entry.taken = std::strtoul(fields[7].c_str(), nullptr, 10) != 0;
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
    std::cerr << "Usage: " << argv0 << " <sequence.csv>\n";
}

} // namespace

int main(int argc, char **argv)
{
    if (argc != 2) {
        usage(argv[0]);
        return 1;
    }

    const std::string input_path = argv[1];
    std::ifstream in(input_path);
    if (!in) {
        std::cerr << "failed to open sequence file: " << input_path << "\n";
        return 1;
    }

    WormCacheStyleTAGE tage;
    BimodalBaseline bimodal;

    uint64_t total_branches = 0;
    uint64_t target_conditional_branches = 0;
    uint64_t loop_conditional_branches = 0;
    uint64_t unconditional_branches = 0;

    uint64_t tage_target_correct = 0;
    uint64_t bimodal_target_correct = 0;
    uint64_t tage_loop_correct = 0;
    uint64_t bimodal_loop_correct = 0;

    std::array<uint64_t, kNumHistoryTables> target_tagged_provider = {};
    uint64_t target_bimodal_provider = 0;
    std::map<uint64_t, PerPcStats> per_pc_stats;

    const auto target_checkpoints = checkpoints(1'000'000);
    std::size_t next_checkpoint = 0;

    std::string line;
    while (std::getline(in, line)) {
        SequenceEntry entry;
        if (!parseEntry(line, entry)) {
            continue;
        }

        ++total_branches;

        if (entry.type == BranchType::Unconditional) {
            ++unconditional_branches;
            tage.updateHistory(entry.pc, entry.taken);
            continue;
        }

        const TAGEPrediction tage_pred = tage.predict(entry.pc);
        const bool bimodal_pred = bimodal.predict(entry.pc);
        const bool tage_correct = tage_pred.result == entry.taken;
        const bool bimodal_correct = bimodal_pred == entry.taken;

        if (entry.type == BranchType::TargetConditional) {
            ++target_conditional_branches;
            tage_target_correct += static_cast<uint64_t>(tage_correct);
            bimodal_target_correct += static_cast<uint64_t>(bimodal_correct);

            if (tage_pred.bank < kNumHistoryTables) {
                target_tagged_provider[tage_pred.bank] += 1;
            } else {
                target_bimodal_provider += 1;
            }

            auto &stats = per_pc_stats[entry.pc];
            stats.count += 1;
            stats.tage_correct += static_cast<uint64_t>(tage_correct);
            stats.bimodal_correct += static_cast<uint64_t>(bimodal_correct);
            if (tage_pred.bank < kNumHistoryTables) {
                stats.tagged_provider[tage_pred.bank] += 1;
            } else {
                stats.bimodal_provider += 1;
            }

            while (next_checkpoint < target_checkpoints.size() &&
                   target_conditional_branches == target_checkpoints[next_checkpoint]) {
                const double tage_acc =
                    static_cast<double>(tage_target_correct) /
                    static_cast<double>(target_conditional_branches);
                const double bimodal_acc =
                    static_cast<double>(bimodal_target_correct) /
                    static_cast<double>(target_conditional_branches);
                std::cout << "checkpoint target_count=" << target_conditional_branches
                          << " tage_target_accuracy=" << std::fixed
                          << std::setprecision(6) << tage_acc
                          << " bimodal_target_accuracy=" << bimodal_acc << "\n";
                ++next_checkpoint;
            }
        } else {
            ++loop_conditional_branches;
            tage_loop_correct += static_cast<uint64_t>(tage_correct);
            bimodal_loop_correct += static_cast<uint64_t>(bimodal_correct);
        }

        tage.train(entry.pc, entry.taken);
        bimodal.train(entry.pc, entry.taken);
    }

    const double tage_target_acc =
        target_conditional_branches == 0
            ? 0.0
            : static_cast<double>(tage_target_correct) /
                  static_cast<double>(target_conditional_branches);
    const double bimodal_target_acc =
        target_conditional_branches == 0
            ? 0.0
            : static_cast<double>(bimodal_target_correct) /
                  static_cast<double>(target_conditional_branches);
    const double tage_loop_acc =
        loop_conditional_branches == 0
            ? 0.0
            : static_cast<double>(tage_loop_correct) /
                  static_cast<double>(loop_conditional_branches);
    const double bimodal_loop_acc =
        loop_conditional_branches == 0
            ? 0.0
            : static_cast<double>(bimodal_loop_correct) /
                  static_cast<double>(loop_conditional_branches);

    std::cout << "total_branches=" << total_branches << "\n";
    std::cout << "target_conditional_branches=" << target_conditional_branches << "\n";
    std::cout << "loop_conditional_branches=" << loop_conditional_branches << "\n";
    std::cout << "unconditional_branches=" << unconditional_branches << "\n";
    std::cout << "unique_target_pcs=" << per_pc_stats.size() << "\n";
    std::cout << "tage_target_accuracy=" << std::fixed << std::setprecision(6)
              << tage_target_acc << "\n";
    std::cout << "bimodal_target_accuracy=" << bimodal_target_acc << "\n";
    std::cout << "tage_loop_accuracy=" << tage_loop_acc << "\n";
    std::cout << "bimodal_loop_accuracy=" << bimodal_loop_acc << "\n";
    std::cout << "target_provider_bimodal=" << target_bimodal_provider << "\n";
    for (std::size_t bank = 0; bank < kNumHistoryTables; ++bank) {
        std::cout << "target_provider_tagged_bank_" << bank
                  << "=" << target_tagged_provider[bank] << "\n";
    }

    for (const auto &[pc, stats] : per_pc_stats) {
        const double tage_acc =
            stats.count == 0 ? 0.0
                             : static_cast<double>(stats.tage_correct) /
                                   static_cast<double>(stats.count);
        const double bimodal_acc =
            stats.count == 0 ? 0.0
                             : static_cast<double>(stats.bimodal_correct) /
                                   static_cast<double>(stats.count);
        std::cout << "pc_summary pc=0x" << std::hex << pc << std::dec
                  << " count=" << stats.count
                  << " tage_accuracy=" << std::fixed << std::setprecision(6) << tage_acc
                  << " bimodal_accuracy=" << bimodal_acc
                  << " provider_bimodal=" << stats.bimodal_provider;
        for (std::size_t bank = 0; bank < kNumHistoryTables; ++bank) {
            std::cout << " provider_tagged_bank_" << bank
                      << "=" << stats.tagged_provider[bank];
        }
        std::cout << "\n";
    }

    return 0;
}
