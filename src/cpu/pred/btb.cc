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

#include "cpu/pred/btb.hh"

#include "base/intmath.hh"
#include "base/trace.hh"
#include "debug/Fetch.hh"

namespace gem5
{

namespace branch_prediction
{

char
btbFillSourceTraceChar(BTBFillSource source)
{
    switch (source) {
      case BTBFillSource::None:
        return '-';
      case BTBFillSource::FetchDirect:
        return 'd';
      case BTBFillSource::FetchNondirect:
        return 'n';
      case BTBFillSource::PredecodeDirect:
        return 'p';
      case BTBFillSource::ResolveControl:
        return 'c';
      case BTBFillSource::Restore:
        return 'r';
    }

    return '?';
}

DefaultBTB::DefaultBTB(unsigned _numEntries,
                       unsigned _tagBits,
                       unsigned _instShiftAmt,
                       unsigned _numWays,
                       unsigned _num_threads)
    : numEntries(_numEntries),
      numWays(_numWays),
      numSets(_numEntries / _numWays),
      tagBits(_tagBits),
      instShiftAmt(_instShiftAmt),
      log2NumThreads(floorLog2(_num_threads))
{
    DPRINTF(Fetch, "BTB: Creating BTB object.\n");

    if (!isPowerOf2(numEntries)) {
        fatal("BTB entries is not a power of 2!");
    }
    if (!isPowerOf2(numWays)) {
        fatal("BTB ways is not a power of 2!");
    }
    if (numWays == 0 || numEntries % numWays != 0) {
        fatal("BTB ways must be a non-zero divisor of total BTB entries!");
    }
    if (!isPowerOf2(numSets)) {
        fatal("BTB sets is not a power of 2!");
    }

    btb.resize(numEntries);
    nextReplaceWay.assign(numSets, 0);

    for (unsigned i = 0; i < numEntries; ++i) {
        btb[i].valid = false;
    }

    idxMask = numSets - 1;
    tagMask = (1ULL << tagBits) - 1;
    tagShiftAmt = instShiftAmt + floorLog2(numSets);
}

void
DefaultBTB::reset()
{
    for (unsigned i = 0; i < numEntries; ++i) {
        btb[i].valid = false;
    }

    for (unsigned set = 0; set < numSets; ++set) {
        nextReplaceWay[set] = 0;
    }
}

inline unsigned
DefaultBTB::getIndex(Addr instPC, ThreadID tid) const
{
    return ((instPC >> instShiftAmt)
            ^ (tid << (tagShiftAmt - instShiftAmt - log2NumThreads)))
            & idxMask;
}

inline unsigned
DefaultBTB::getEntryIndex(unsigned set, unsigned way) const
{
    return set * numWays + way;
}

inline Addr
DefaultBTB::getTag(Addr instPC) const
{
    DPRINTF(Fetch, "instPC: %#x BTB Tag: %#x tagShitfAmt: %d tagMask: %#x\n",
            instPC, (instPC >> tagShiftAmt) & tagMask, tagShiftAmt, tagMask);
    return (instPC >> tagShiftAmt) & tagMask;
}

int
DefaultBTB::findWay(unsigned set, Addr inst_tag, ThreadID tid) const
{
    assert(set < numSets);

    for (unsigned way = 0; way < numWays; ++way) {
        const BTBEntry &entry = btb[getEntryIndex(set, way)];
        if (entry.valid && entry.tag == inst_tag && entry.tid == tid) {
            return way;
        }
    }

    return -1;
}

int
DefaultBTB::findWay(Addr instPC, ThreadID tid) const
{
    const unsigned set = getIndex(instPC, tid);
    const Addr inst_tag = getTag(instPC);
    return findWay(set, inst_tag, tid);
}

const DefaultBTB::BTBEntry *
DefaultBTB::findEntry(Addr instPC, ThreadID tid) const
{
    const unsigned set = getIndex(instPC, tid);
    const int way = findWay(set, getTag(instPC), tid);
    if (way < 0) {
        return nullptr;
    }
    return &btb[getEntryIndex(set, way)];
}

DefaultBTB::BTBEntry *
DefaultBTB::findEntry(Addr instPC, ThreadID tid)
{
    return const_cast<BTBEntry *>(
        static_cast<const DefaultBTB *>(this)->findEntry(instPC, tid));
}

unsigned
DefaultBTB::chooseWay(unsigned set)
{
    assert(set < numSets);

    for (unsigned way = 0; way < numWays; ++way) {
        const unsigned idx = getEntryIndex(set, way);
        if (!btb[idx].valid) {
            return way;
        }
    }

    const unsigned way = nextReplaceWay[set];
    nextReplaceWay[set] = (nextReplaceWay[set] + 1) % numWays;
    return way;
}

bool
DefaultBTB::type(Addr instPC, ThreadID tid)
{
    const BTBEntry *entry = findEntry(instPC, tid);
    return entry ? entry->uncond : false;
}

bool
DefaultBTB::valid(Addr instPC, ThreadID tid)
{
    const unsigned set = getIndex(instPC, tid);
    const Addr inst_tag = getTag(instPC);
    const int way = findWay(set, inst_tag, tid);
    const bool hit = way >= 0;

    return hit;
}

int
DefaultBTB::getBblIndex(Addr instPC, ThreadID tid)
{
    const unsigned set = getIndex(instPC, tid);
    const Addr inst_tag = getTag(instPC);

    assert(set < numSets);

    for (unsigned way = 0; way < numWays; ++way) {
        const unsigned idx = getEntryIndex(set, way);
        const BTBEntry &entry = btb[idx];
        if (entry.valid && entry.tag == inst_tag && entry.tid == tid) {
            if (instPC < entry.branch.instAddr() &&
                (instPC >> 6) == (entry.branch.instAddr() >> 6)) {
                DPRINTF(Fetch,
                        "Bgodala found btb_index:%d for instPC 0x%lx and BranchPC: 0x%lx\n",
                        idx, instPC, entry.branch.instAddr());
                return idx;
            }
        }
    }

    return -1;
}

StaticInstPtr
DefaultBTB::lookupBranchFromIndex(unsigned idx, ThreadID tid)
{
    assert(idx < numEntries);

    if (btb[idx].valid && btb[idx].tid == tid) {
        return btb[idx].staticBranchInst;
    }
    return 0;
}

TheISA::PCState
DefaultBTB::lookupBranchPCFromIndex(unsigned idx, ThreadID tid)
{
    assert(idx < numEntries);

    if (btb[idx].valid && btb[idx].tid == tid) {
        return btb[idx].branch;
    }
    return 0;
}

StaticInstPtr
DefaultBTB::lookupBranch(Addr instPC, ThreadID tid)
{
    const BTBEntry *entry = findEntry(instPC, tid);
    return entry ? entry->staticBranchInst : StaticInstPtr(0);
}

TheISA::PCState
DefaultBTB::lookupBranchPC(Addr instPC, ThreadID tid)
{
    const BTBEntry *entry = findEntry(instPC, tid);
    return entry ? entry->branch : TheISA::PCState(0);
}

uint64_t
DefaultBTB::lookupBblSize(Addr instPC, ThreadID tid)
{
    const BTBEntry *entry = findEntry(instPC, tid);
    return entry ? entry->bblSize : 0;
}

TheISA::PCState
DefaultBTB::lookup(Addr instPC, ThreadID tid)
{
    const BTBEntry *entry = findEntry(instPC, tid);
    return entry ? entry->target : TheISA::PCState(0);
}

TheISA::PCState
DefaultBTB::lookupFT(Addr instPC, ThreadID tid)
{
    const BTBEntry *entry = findEntry(instPC, tid);
    return entry ? entry->fallthrough : TheISA::PCState(0);
}

BTBFillSource
DefaultBTB::lookupSource(Addr instPC, ThreadID tid)
{
    const BTBEntry *entry = findEntry(instPC, tid);
    return entry ? entry->fillSource : BTBFillSource::None;
}

void
DefaultBTB::update(Addr instPC, const TheISA::PCState &target, ThreadID tid,
                   BTBFillSource source)
{
    const unsigned set = getIndex(instPC, tid);
    int way = findWay(set, getTag(instPC), tid);
    if (way < 0) {
        way = chooseWay(set);
    }
    const unsigned idx = getEntryIndex(set, way);

    assert(idx < numEntries);

    btb[idx].tid = tid;
    btb[idx].valid = true;
    btb[idx].target = target;
    btb[idx].tag = getTag(instPC);
    btb[idx].fillSource = source;
}

void
DefaultBTB::update(Addr instPC, const StaticInstPtr &staticBranchInst,
                   const TheISA::PCState &branch,
                   const uint64_t bblSize, const TheISA::PCState &target,
                   const TheISA::PCState &ft, bool uncond, ThreadID tid,
                   BTBFillSource source)
{
    const unsigned set = getIndex(instPC, tid);
    int way = findWay(set, getTag(instPC), tid);
    if (way < 0) {
        way = chooseWay(set);
    }
    const unsigned btb_idx = getEntryIndex(set, way);

    DPRINTF(Fetch,
            "BTB update btb_index: %d staticBrancInst 0x%lx target %s branchPC: %s\n",
            btb_idx, &*staticBranchInst, target, branch);

    assert(btb_idx < numEntries);

    btb[btb_idx].tid = tid;
    btb[btb_idx].valid = true;
    btb[btb_idx].staticBranchInst = staticBranchInst;
    btb[btb_idx].branch = branch;
    btb[btb_idx].bblSize = bblSize;
    btb[btb_idx].target = target;
    btb[btb_idx].fallthrough = ft;
    btb[btb_idx].tag = getTag(instPC);
    btb[btb_idx].uncond = uncond;
    btb[btb_idx].fillSource = source;
}

} // namespace branch_prediction
} // namespace gem5
