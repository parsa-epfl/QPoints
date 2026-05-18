/*
 * Copyright (c) 2004-2005 The Regents of The University of Michigan
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are
 * met: redistributions of source code must retain the above copyright
 * notice, this list of conditions and the following disclaimer;
 * redistributions in binary form must reproduce the above copyright
 * notice, this list of conditions and the following disclaimer in the
 * documentation and/or other materials provided with the distribution;
 * neither the name of the copyright holders nor the names of its
 * contributors may be used to endorse or promote products derived from
 * this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
 * A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 * OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 * SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
 * DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
 * THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

#ifndef __CPU_PRED_BTB_HH__
#define __CPU_PRED_BTB_HH__

#include <vector>

#include "arch/pcstate.hh"
#include "base/logging.hh"
#include "base/types.hh"
#include "cpu/base.hh"
#include "config/the_isa.hh"

namespace gem5
{

namespace branch_prediction
{

enum class BTBFillSource : uint8_t
{
    None = 0,
    FetchDirect,
    FetchNondirect,
    PredecodeDirect,
    ResolveControl,
    Restore,
};

char btbFillSourceTraceChar(BTBFillSource source);

class DefaultBTB
{
  private:
    struct BTBEntry
    {
        BTBEntry()
            : tag(0), staticBranchInst(0), branch(0), bblSize(0), target(0),
              fallthrough(0), uncond(false), valid(false),
              fillSource(BTBFillSource::None)
        {}

        /** The entry's tag. */
        Addr tag;

        /** The entry's branch. */
        StaticInstPtr staticBranchInst;
        TheISA::PCState branch;

        /** Size of the basic block */
        uint64_t bblSize;

        /** The entry's target. */
        TheISA::PCState target;

        /** The entry's fall-through. */
        TheISA::PCState fallthrough;

        bool uncond;

        /** The entry's thread id. */
        ThreadID tid;

        /** Whether or not the entry is valid. */
        bool valid;

        /** Last mechanism that populated this entry. */
        BTBFillSource fillSource;
    };

  public:
    /** Creates a BTB with the given number of entries, number of bits per
     *  tag, and instruction offset amount.
     *  @param numEntries Number of entries for the BTB.
     *  @param tagBits Number of bits for each tag in the BTB.
     *  @param instShiftAmt Offset amount for instructions to ignore alignment.
     *  @param numWays Number of ways per set.
     */
    DefaultBTB(unsigned numEntries, unsigned tagBits,
               unsigned instShiftAmt, unsigned numWays,
               unsigned numThreads);

    void reset();

    /** Looks up an address in the BTB. Must call valid() first on the address.
     *  @param inst_PC The address of the basic block to look up.
     *  @param tid The thread id.
     *  @return Returns the static branch inst.
     */
    int getBblIndex(Addr instPC, ThreadID tid);
    StaticInstPtr lookupBranchFromIndex(unsigned idx, ThreadID tid);
    TheISA::PCState lookupBranchPCFromIndex(unsigned idx, ThreadID tid);
    StaticInstPtr lookupBranch(Addr instPC, ThreadID tid);
    TheISA::PCState lookupBranchPC(Addr instPC, ThreadID tid);

    uint64_t lookupBblSize(Addr instPC, ThreadID tid);

    /** Looks up an address in the BTB. Must call valid() first on the address.
     *  @param inst_PC The address of the branch to look up.
     *  @param tid The thread id.
     *  @return Returns the target of the branch.
     */
    TheISA::PCState lookup(Addr instPC, ThreadID tid);

    /** Looks up an address in the BTB. Must call valid() first on the address.
     *  @param inst_PC The address of the basic block to look up.
     *  @param tid The thread id.
     *  @return Returns the fall-through of the branch.
     */
    TheISA::PCState lookupFT(Addr instPC, ThreadID tid);
    BTBFillSource lookupSource(Addr instPC, ThreadID tid);

    bool type(Addr instPC, ThreadID tid);

    /** Checks if a branch is in the BTB.
     *  @param inst_PC The address of the branch to look up.
     *  @param tid The thread id.
     *  @return Whether or not the branch exists in the BTB.
     */
    bool valid(Addr instPC, ThreadID tid);

    /** Updates the BTB with the target of a branch.
     *  @param inst_PC The address of the branch being updated.
     *  @param target_PC The target address of the branch.
     *  @param tid The thread id.
     */
    void update(Addr instPC, const TheISA::PCState &targetPC,
                ThreadID tid,
                BTBFillSource source = BTBFillSource::ResolveControl);

    // Nayana added
    void update(Addr instPC, const StaticInstPtr &staticBranchInst,
                const TheISA::PCState &branch,
                const uint64_t bblSize, const TheISA::PCState &target,
                const TheISA::PCState &ft, bool uncond, ThreadID tid,
                BTBFillSource source);

  private:
    /** Returns the set index into the BTB, based on the branch's PC.
     *  @param inst_PC The branch to look up.
     *  @return Returns the set index into the BTB.
     */
    inline unsigned getIndex(Addr instPC, ThreadID tid) const;

    /** Returns the flat index into the BTB for a set/way pair. */
    inline unsigned getEntryIndex(unsigned set, unsigned way) const;

    /** Returns the tag bits of a given address.
     *  @param inst_PC The branch's address.
     *  @return Returns the tag bits.
     */
    inline Addr getTag(Addr instPC) const;

    int findWay(Addr instPC, ThreadID tid) const;
    int findWay(unsigned set, Addr tag, ThreadID tid) const;
    unsigned chooseWay(unsigned set);
    const BTBEntry *findEntry(Addr instPC, ThreadID tid) const;
    BTBEntry *findEntry(Addr instPC, ThreadID tid);

    /** The actual BTB, flattened as contiguous sets of ways. */
    std::vector<BTBEntry> btb;

    /** Per-set round-robin replacement pointer. */
    std::vector<unsigned> nextReplaceWay;

    /** The total number of entries in the BTB. */
    unsigned numEntries;

    /** Ways per set. */
    unsigned numWays;

    /** Number of sets in the BTB. */
    unsigned numSets;

    /** The set index mask. */
    unsigned idxMask;

    /** The number of tag bits per entry. */
    unsigned tagBits;

    /** The tag mask. */
    Addr tagMask;

    /** Number of bits to shift PC when calculating index. */
    unsigned instShiftAmt;

    /** Number of bits to shift PC when calculating tag. */
    unsigned tagShiftAmt;

    /** Log2 NumThreads used for hashing threadid */
    unsigned log2NumThreads;
};

} // namespace branch_prediction
} // namespace gem5

#endif // __CPU_PRED_BTB_HH__
